"""Run FFmpeg stream-copy capture (same flags as Go iptvrecord)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from duration_parse import parse_duration
from paths import ffmpeg_exe


def build_ffmpeg_argv(
    *,
    stream_url: str,
    output_path: Path,
    duration_text: str,
    user_agent: str = "",
    referer: str = "",
) -> list[str]:
    sec = parse_duration(duration_text)
    ff = ffmpeg_exe()
    if not ff.is_file():
        raise FileNotFoundError(
            f"embedded FFmpeg not found at {ff}. Run scripts\\download_ffmpeg.ps1 from the repo root.",
        )
    args: list[str] = [
        str(ff),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_at_eof",
        "1",
        "-reconnect_delay_max",
        "5",
    ]
    if user_agent:
        args += ["-user_agent", user_agent]
    if referer:
        args += ["-headers", f"Referer: {referer}\r\n"]
    args += [
        "-i",
        stream_url,
        "-c",
        "copy",
        "-t",
        str(sec),
        "-y",
        str(output_path),
    ]
    return args


def run_ffmpeg(argv: list[str], *, log_file: Path | None = None) -> int:
    """Run ffmpeg; stream stdout/stderr to log_file if set. Returns process return code."""
    log_fp = None
    try:
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(log_file, "a", encoding="utf-8")
            log_fp.write(f"\n---\n$ {' '.join(argv)}\n")
            log_fp.flush()
        p = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        assert p.stdout is not None
        for line in p.stdout:
            if log_fp:
                log_fp.write(line)
                log_fp.flush()
        return int(p.wait())
    finally:
        if log_fp:
            log_fp.close()
