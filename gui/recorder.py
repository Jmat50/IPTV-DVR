"""Run FFmpeg stream-copy capture (same flags as Go iptvrecord)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from duration_parse import parse_duration
from paths import ffmpeg_exe, ffprobe_exe

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


def _any_caption_sidecar(output_path: Path) -> bool:
    for ext in (".vtt", ".srt", ".ass"):
        if _sidecar_has_content(output_path.with_suffix(ext)):
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
    if _sidecar_has_content(ts_path.with_suffix(".srt")):
        return True
    argv, cwd = build_extract_embedded_608_argv(ts_path)
    code = run_ffmpeg(argv, log_file=log_file, cwd=cwd)
    if code != 0:
        return False
    return _sidecar_has_content(ts_path.with_suffix(".srt"))


def maybe_post_extract_captions(
    output_path: Path,
    *,
    download_captions: bool,
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
