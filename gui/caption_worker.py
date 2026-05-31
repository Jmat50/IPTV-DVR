"""CCExtractor sidecar worker for live caption extraction during recording."""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from pathlib import Path

from paths import ccextractor_exe

# Idle timeout (seconds) for CCExtractor tail-follow mode (--stream <secs>).
# When the recording file stops growing for this long, CCExtractor exits.
# See caption_mode.ccextractor_live_supported() for 0.96.x CLI compatibility checks.
LIVE_STREAM_IDLE_SECONDS = "15"

_TIMESTAMP_RE = re.compile(
    r"^\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}",
    re.MULTILINE,
)


def srt_sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(".srt")


def srt_partial_path(output_path: Path) -> Path:
    return output_path.with_suffix(".srt.partial")


def build_ccextractor_live_argv(recording_path: Path, partial_path: Path) -> list[str]:
    """Argv for tail-follow extraction on a growing MPEG-TS recording."""
    exe = ccextractor_exe()
    return [
        str(exe),
        "-1",
        "--input",
        "ts",
        "--stream",
        LIVE_STREAM_IDLE_SECONDS,
        "--out",
        "srt",
        "-o",
        str(partial_path),
        str(recording_path),
    ]


def build_ccextractor_argv(recording_path: Path, partial_path: Path) -> list[str]:
    return build_ccextractor_live_argv(recording_path, partial_path)


def build_ccextractor_post_argv(recording_path: Path, out_path: Path) -> list[str]:
    """Post-record extraction: CEA-608 only (-1).

    GSN/HLS MPEG-TS often triggers a Rust panic in the default CEA-708 path
    (service_decoder) on long files; FFmpeg subcc and CCExtractor -1 both use 608.
    """
    exe = ccextractor_exe()
    return [
        str(exe),
        "-1",
        "--out=srt",
        "-o",
        str(out_path),
        str(recording_path),
    ]


def validate_srt_file(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 4:
            return False
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if "-->" not in text:
        return False
    return bool(_TIMESTAMP_RE.search(text))


def atomic_finalize_partial(partial: Path, final: Path) -> bool:
    if not validate_srt_file(partial):
        return False
    final.parent.mkdir(parents=True, exist_ok=True)
    partial.replace(final)
    return validate_srt_file(final)


class LiveCaptionWorker:
    """Run CCExtractor in stream mode against a growing recording file."""

    def __init__(
        self,
        recording_path: Path,
        *,
        log_file: Path | None = None,
        start_timeout_s: float = 120.0,
        poll_interval_s: float = 0.5,
    ) -> None:
        self.recording_path = recording_path
        self.log_file = log_file
        self.start_timeout_s = start_timeout_s
        self.poll_interval_s = poll_interval_s
        self.partial_path = srt_partial_path(recording_path)
        self.final_path = srt_sidecar_path(recording_path)
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._log_fp = None

    def _log(self, msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line)
        else:
            print(line, end="", file=sys.stderr)

    def _drain_output(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            if self._log_fp:
                self._log_fp.write(line)
                self._log_fp.flush()

    def start(self) -> bool:
        if not ccextractor_exe().is_file():
            self._log(
                f"captions: CCExtractor not found at {ccextractor_exe()} "
                "(run scripts\\download_ccextractor.ps1)",
            )
            return False
        try:
            if self.partial_path.is_file():
                self.partial_path.unlink()
        except OSError:
            pass
        argv = build_ccextractor_argv(self.recording_path, self.partial_path)
        self._log(f"captions: starting live worker: {' '.join(argv)}")
        try:
            if self.log_file:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                self._log_fp = open(self.log_file, "a", encoding="utf-8")
                self._log_fp.write(f"\n---\n$ {' '.join(argv)}\n")
                self._log_fp.flush()
            self._proc = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as e:
            self._log(f"captions: failed to start CCExtractor: {e}")
            return False
        self._reader = threading.Thread(target=self._drain_output, daemon=True)
        self._reader.start()
        return True

    def stop_and_finalize(self, *, grace_s: float = 15.0) -> bool:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if self._reader is not None:
            self._reader.join(timeout=2.0)
        if self._log_fp:
            self._log_fp.close()
            self._log_fp = None
        self._proc = None
        if atomic_finalize_partial(self.partial_path, self.final_path):
            self._log(f"captions: live worker wrote {self.final_path}")
            return True
        try:
            if self.partial_path.is_file():
                self.partial_path.unlink()
        except OSError:
            pass
        self._log("captions: live worker produced no valid SRT")
        return False
