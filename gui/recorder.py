"""Run FFmpeg stream-copy capture (same flags as Go iptvrecord)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from caption_mode import CaptionPostProcessor
from caption_worker import build_ccextractor_post_argv, validate_srt_file
from duration_parse import parse_duration
from paths import ccextractor_exe, ffmpeg_exe, ffprobe_exe

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes


def _find_console_window_for_pid(pid: int) -> int | None:
    if sys.platform != "win32":
        return None

    user32 = ctypes.windll.user32
    found: int | None = None

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd: int, _lparam: int) -> bool:
        nonlocal found
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value != pid:
            return True
        class_name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value == "ConsoleWindowClass":
            found = int(hwnd)
            return False
        return True

    user32.EnumWindows(_enum_proc, 0)
    return found


def _disable_console_close(hwnd: int) -> None:
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    sc_close = 0xF060
    mf_bycommand = 0x0000
    menu = user32.GetSystemMenu(hwnd, False)
    if menu:
        user32.DeleteMenu(menu, sc_close, mf_bycommand)
        user32.DrawMenuBar(hwnd)


def _warn_console_is_protected(hwnd: int) -> None:
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, len(title))
    base = title.value.strip() or "FFmpeg"
    if "[protected]" not in base.lower():
        user32.SetWindowTextW(hwnd, f"{base} [FFmpeg - PROTECTED - do not close]")

    menu = user32.GetSystemMenu(hwnd, False)
    if menu:
        mf_string = 0x0000
        mf_separator = 0x0800
        mf_bypostion = 0x0400
        mf_disabled = 0x0002
        user32.AppendMenuW(menu, mf_separator, 0, None)
        user32.AppendMenuW(
            menu,
            mf_string | mf_disabled,
            0,
            "Close disabled while FFmpeg is recording",
        )
        user32.DrawMenuBar(hwnd)


def _arm_ffmpeg_console_close_guard(pid: int) -> None:
    if sys.platform != "win32":
        return

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        hwnd = _find_console_window_for_pid(pid)
        if hwnd is not None:
            _disable_console_close(hwnd)
            _warn_console_is_protected(hwnd)
            return
        time.sleep(0.10)


def _start_ffmpeg_console_close_guard(pid: int) -> None:
    if sys.platform != "win32":
        return
    threading.Thread(target=_arm_ffmpeg_console_close_guard, args=(pid,), daemon=True).start()


def caption_sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(".vtt")


def _sidecar_has_content(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _caption_sidecar_paths(output_path: Path) -> list[Path]:
    return [
        output_path.with_suffix(".vtt"),
        output_path.with_suffix(".ass"),
        output_path.with_suffix(".srt"),
        Path(str(output_path) + ".srt"),
    ]


def _any_caption_sidecar(output_path: Path) -> bool:
    for p in _caption_sidecar_paths(output_path):
        if _sidecar_has_content(p):
            return True
    return False


def probe_url_has_subtitles(
    stream_url: str,
    *,
    user_agent: str = "",
    referer: str = "",
) -> bool:
    """Return True when the live input exposes a subtitle stream for dual-output capture."""
    fp = ffprobe_exe()
    if not fp.is_file():
        return False
    cmd = [str(fp), "-v", "error"]
    if user_agent:
        cmd += ["-user_agent", user_agent]
    if referer:
        cmd += ["-headers", f"Referer: {referer}\r\n"]
    cmd += [
        "-select_streams",
        "s",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        stream_url,
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        return False
    return bool((p.stdout or "").strip())


def build_ffmpeg_argv(
    *,
    stream_url: str,
    output_path: Path,
    duration_text: str,
    user_agent: str = "",
    referer: str = "",
    download_captions: bool = False,
    dual_output_vtt: bool | None = None,
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
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-t",
        str(sec),
        "-y",
        str(output_path),
    ]
    use_vtt = dual_output_vtt if dual_output_vtt is not None else download_captions
    if use_vtt and probe_url_has_subtitles(
        stream_url,
        user_agent=user_agent,
        referer=referer,
    ):
        args += [
            "-map",
            "0:s:0?",
            "-c",
            "copy",
            "-t",
            str(sec),
            "-y",
            str(caption_sidecar_path(output_path)),
        ]
    return args


def _caption_ext_for_codec(codec: str) -> str:
    c = codec.lower()
    if c == "webvtt":
        return ".vtt"
    if c == "subrip":
        return ".srt"
    if c == "ass":
        return ".ass"
    if c:
        return ".srt"
    return ".vtt"


def probe_subtitle_codec(media_path: Path) -> str:
    fp = ffprobe_exe()
    if not fp.is_file():
        return ""
    p = subprocess.run(
        [
            str(fp),
            "-v",
            "error",
            "-select_streams",
            "s:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        return ""
    return (p.stdout or "").strip()


def build_extract_captions_argv(ts_path: Path, codec: str) -> list[str]:
    ff = ffmpeg_exe()
    ext = _caption_ext_for_codec(codec)
    out_path = ts_path.with_suffix(ext)
    return [
        str(ff),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(ts_path),
        "-map",
        "0:s:0?",
        "-c",
        "copy",
        "-y",
        str(out_path),
    ]


def try_extract_captions_from_ts(ts_path: Path, *, log_file: Path | None = None) -> bool:
    codec = probe_subtitle_codec(ts_path)
    if not codec:
        return False
    argv = build_extract_captions_argv(ts_path, codec)
    code = run_ffmpeg(argv, log_file=log_file)
    if code != 0:
        return False
    out_path = Path(argv[-1])
    return _sidecar_has_content(out_path)


def _movie_basename_for_lavfi(name: str) -> str:
    return name.replace("'", r"\'")


def build_extract_embedded_608_argv(ts_path: Path) -> tuple[list[str], Path]:
    """Extract CEA-608 from H.264 in a .ts to .srt (lavfi movie basename; run with cwd=parent)."""
    ff = ffmpeg_exe()
    base = ts_path.name
    out_name = ts_path.with_suffix(".srt").name
    lavfi = f"movie='{_movie_basename_for_lavfi(base)}'[out+subcc]"
    argv = [
        str(ff),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "lavfi",
        "-i",
        lavfi,
        "-map",
        "s",
        "-c:s",
        "srt",
        "-y",
        out_name,
    ]
    return argv, ts_path.parent


def try_extract_embedded_608_from_ts(ts_path: Path, *, log_file: Path | None = None) -> bool:
    if ts_path.suffix.lower() != ".ts":
        return False
    final_path = ts_path.with_suffix(".srt")
    if _sidecar_has_content(final_path):
        return True
    argv, cwd = build_extract_embedded_608_argv(ts_path)
    code = run_ffmpeg(argv, log_file=log_file, cwd=cwd)
    if code != 0:
        return False
    return _sidecar_has_content(final_path)


def run_tool(
    argv: list[str],
    *,
    log_file: Path | None = None,
    cwd: Path | None = None,
) -> int:
    log_fp = None
    try:
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(log_file, "a", encoding="utf-8")
            log_fp.write(f"\n---\n$ {' '.join(argv)}\n")
            log_fp.flush()
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
        )
        body = f"{p.stdout or ''}{p.stderr or ''}"
        if log_fp and body:
            log_fp.write(body)
            log_fp.flush()
        return int(p.returncode)
    finally:
        if log_fp:
            log_fp.close()


def try_extract_ccextractor_post(ts_path: Path, *, log_file: Path | None = None) -> bool:
    if ts_path.suffix.lower() != ".ts":
        return False
    exe = ccextractor_exe()
    if not exe.is_file():
        msg = f"captions: post ccextractor unavailable at {exe}\n"
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(msg)
        else:
            print(msg, end="", file=sys.stderr)
        return False
    final_path = ts_path.with_suffix(".srt")
    if _sidecar_has_content(final_path):
        return True
    code = run_tool(
        build_ccextractor_post_argv(ts_path, final_path),
        log_file=log_file,
    )
    if code != 0:
        try:
            if final_path.is_file():
                final_path.unlink()
        except OSError:
            pass
        return False
    return validate_srt_file(final_path)


def maybe_post_extract_captions(
    output_path: Path,
    *,
    download_captions: bool,
    post_processor: CaptionPostProcessor = "ffmpeg",
    log_file: Path | None = None,
) -> None:
    if not download_captions:
        return
    if _any_caption_sidecar(output_path):
        return
    if output_path.suffix.lower() != ".ts":
        return
    if not output_path.is_file():
        return
    if post_processor == "ccextractor":
        if try_extract_ccextractor_post(output_path, log_file=log_file):
            return
    else:
        if try_extract_captions_from_ts(output_path, log_file=log_file):
            return
        if try_extract_embedded_608_from_ts(output_path, log_file=log_file):
            return
    msg = "captions: none found in stream or recording\n"
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(msg)
    else:
        print(msg, end="", file=sys.stderr)


def run_ffmpeg(argv: list[str], *, log_file: Path | None = None, cwd: Path | None = None) -> int:
    """Run ffmpeg; stream stdout/stderr to log_file if set. Returns process return code.

    On Windows, accidental-close safeguards apply only to this FFmpeg child's console HWND
    (identified by FFmpeg's PID); the Tk GUI and other windows are not modified.
    """
    log_fp = None
    try:
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fp = open(log_file, "a", encoding="utf-8")
            log_fp.write(f"\n---\n$ {' '.join(argv)}\n")
            log_fp.flush()
        popen_kw: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "text": True,
            "bufsize": 1,
        }
        if cwd is not None:
            popen_kw["cwd"] = str(cwd)
        p = subprocess.Popen(argv, **popen_kw)
        _start_ffmpeg_console_close_guard(p.pid)
        assert p.stdout is not None
        for line in p.stdout:
            if log_fp:
                log_fp.write(line)
                log_fp.flush()
        return int(p.wait())
    finally:
        if log_fp:
            log_fp.close()


def is_manual_stop_exit(code: int) -> bool:
    """Return True when ffmpeg exited due to user console close / Ctrl+C on Windows."""
    if sys.platform != "win32":
        return code == 130
    # Windows STATUS_CONTROL_C_EXIT can surface as signed or unsigned.
    return code in (130, -1073741510, 3221225786)


def build_repair_ts_argv(ts_path: Path, repaired_path: Path, *, use_setts: bool) -> list[str]:
    ff = ffmpeg_exe()
    rate = probe_video_frame_rate(ts_path)
    return [
        str(ff),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "+genpts+discardcorrupt",
        "-err_detect",
        "ignore_err",
        "-avoid_negative_ts",
        "make_zero",
        "-i",
        str(ts_path),
        "-map",
        "0",
        "-c",
        "copy",
        *(
            [
                "-bsf:v",
                f"setts=pts=N/({rate}*TB):dts=N/({rate}*TB)",
            ]
            if use_setts and rate
            else []
        ),
        "-y",
        str(repaired_path),
    ]


def probe_video_frame_rate(media_path: Path) -> str:
    fp = ffprobe_exe()
    if not fp.is_file():
        return ""
    p = subprocess.run(
        [
            str(fp),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=avg_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if p.returncode != 0:
        return ""
    for raw in (p.stdout or "").splitlines():
        rate = raw.strip()
        if not rate or rate == "0/0":
            continue
        # Keep ffmpeg rational form (e.g. 30000/1001) for setts expression.
        return rate
    return ""


# Skip TS repair when A/V durations already diverge (e.g. after a setts remux).
_MAX_REPAIR_AV_DELTA_S = 5.0


def probe_stream_duration(media_path: Path, stream: str) -> float | None:
    """Return stream duration in seconds, or None when unavailable."""
    fp = ffprobe_exe()
    if not fp.is_file():
        return None
    p = subprocess.run(
        [
            str(fp),
            "-v",
            "error",
            "-select_streams",
            stream,
            "-show_entries",
            "stream=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if p.returncode != 0:
        return None
    for raw in (p.stdout or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        try:
            return float(text)
        except ValueError:
            continue
    return None


def probe_av_duration_delta(media_path: Path) -> float | None:
    """Return video duration minus audio duration in seconds."""
    video = probe_stream_duration(media_path, "v:0")
    audio = probe_stream_duration(media_path, "a:0")
    if video is None or audio is None:
        return None
    return video - audio


def should_repair_ts_file(ts_path: Path, *, partial_recording: bool = False) -> bool:
    """Return True only for partial/corrupt TS that may benefit from remux repair."""
    if ts_path.suffix.lower() != ".ts":
        return False
    if not ts_path.is_file():
        return False
    try:
        if ts_path.stat().st_size <= 0:
            return False
    except OSError:
        return False

    delta = probe_av_duration_delta(ts_path)
    if delta is not None and abs(delta) > _MAX_REPAIR_AV_DELTA_S:
        return False

    if not partial_recording and _validate_repaired_ts(ts_path):
        return False

    return True


def try_repair_ts_file(
    ts_path: Path,
    *,
    log_file: Path | None = None,
    partial_recording: bool = False,
) -> bool:
    """Best-effort remux to normalize partially-ended TS recordings for strict players."""
    if not should_repair_ts_file(ts_path, partial_recording=partial_recording):
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("captions: TS repair skipped (complete or already skewed recording)\n")
        return False

    repaired = ts_path.with_name(ts_path.name + ".repair.tmp.ts")
    try:
        if repaired.is_file():
            repaired.unlink()
    except OSError:
        pass

    # Some streams regress with forced setts while others need it.
    # Try setts first, then a pure remux fallback if validation fails.
    for use_setts in (True, False):
        code = run_ffmpeg(build_repair_ts_argv(ts_path, repaired, use_setts=use_setts), log_file=log_file)
        if code != 0:
            try:
                if repaired.is_file():
                    repaired.unlink()
            except OSError:
                pass
            continue
        try:
            if not repaired.is_file() or repaired.stat().st_size <= 0:
                if repaired.is_file():
                    repaired.unlink()
                continue
        except OSError:
            continue
        try:
            repaired.replace(ts_path)
        except OSError:
            try:
                if repaired.is_file():
                    repaired.unlink()
            except OSError:
                pass
            continue
        if _validate_repaired_ts(ts_path, log_file=log_file):
            return True
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                mode = "setts" if use_setts else "plain-remux"
                f.write(f"captions: TS repair validation failed after {mode}, trying fallback\n")
    return False


def _validate_repaired_ts(ts_path: Path, *, log_file: Path | None = None) -> bool:
    ff = ffmpeg_exe()
    cmd = [
        str(ff),
        "-hide_banner",
        "-v",
        "warning",
        "-i",
        str(ts_path),
        "-map",
        "0",
        "-t",
        "20",
        "-f",
        "null",
        "-",
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = f"{p.stdout or ''}{p.stderr or ''}".lower()
    bad = (
        "non-monoton" in out
        or "invalid dts" in out
        or "error while decoding" in out
        or "packet corrupt" in out
    )
    if log_file and out.strip():
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(out)
    return p.returncode == 0 and not bad


def probe_audio_bitrate(media_path: Path) -> int | None:
    fp = ffprobe_exe()
    if not fp.is_file():
        return None
    p = subprocess.run(
        [
            str(fp),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=bit_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if p.returncode != 0:
        return None
    for raw in (p.stdout or "").splitlines():
        text = raw.strip()
        if not text:
            continue
        try:
            return int(text)
        except ValueError:
            continue
    return None


def build_resync_audio_to_video_argv(
    ts_path: Path,
    out_path: Path,
    *,
    atempo: float,
    audio_bitrate: int | None = None,
) -> list[str]:
    """Stretch or compress audio to match the video timeline; video is stream-copied."""
    ff = ffmpeg_exe()
    br = audio_bitrate or probe_audio_bitrate(ts_path) or 192_000
    br_k = max(64, int(round(br / 1000)))
    return [
        str(ff),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-i",
        str(ts_path),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-map",
        "0:a:0",
        "-filter:a",
        f"atempo={atempo:.6f}",
        "-c:a",
        "aac",
        "-b:a",
        f"{br_k}k",
        "-y",
        str(out_path),
    ]


def try_resync_audio_to_video(ts_path: Path, *, log_file: Path | None = None) -> bool:
    """Re-time audio to the video clock when A/V durations diverge (e.g. after setts repair)."""
    if ts_path.suffix.lower() != ".ts":
        return False
    if not ts_path.is_file():
        return False

    video = probe_stream_duration(ts_path, "v:0")
    audio = probe_stream_duration(ts_path, "a:0")
    if video is None or audio is None or video <= 0 or audio <= 0:
        return False

    delta = video - audio
    if abs(delta) < 0.5:
        return False

    # Slow audio when video is longer; speed up when audio is longer.
    atempo = audio / video
    if not 0.5 <= atempo <= 2.0:
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(
                    f"captions: audio resync skipped (atempo {atempo:.4f} outside 0.5..2.0)\n"
                )
        return False

    resynced = ts_path.with_name(ts_path.name + ".resync.tmp.ts")
    try:
        if resynced.is_file():
            resynced.unlink()
    except OSError:
        pass

    argv = build_resync_audio_to_video_argv(ts_path, resynced, atempo=atempo)
    code = run_ffmpeg(argv, log_file=log_file)
    if code != 0:
        try:
            if resynced.is_file():
                resynced.unlink()
        except OSError:
            pass
        return False

    try:
        if not resynced.is_file() or resynced.stat().st_size <= 0:
            return False
    except OSError:
        return False

    new_delta = probe_av_duration_delta(resynced)
    if new_delta is None or abs(new_delta) > 2.0:
        try:
            resynced.unlink()
        except OSError:
            pass
        if log_file:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"captions: audio resync rejected (remaining delta {new_delta})\n")
        return False

    try:
        resynced.replace(ts_path)
    except OSError:
        try:
            if resynced.is_file():
                resynced.unlink()
        except OSError:
            pass
        return False

    if log_file:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(
                f"captions: audio resync applied (atempo={atempo:.6f}, "
                f"delta {delta:+.2f}s -> {new_delta:+.2f}s)\n"
            )
    return True
