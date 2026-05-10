"""Run FFmpeg stream-copy capture (same flags as Go iptvrecord)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

from duration_parse import parse_duration
from paths import ffmpeg_exe

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
        user32.SetWindowTextW(hwnd, f"{base} [PROTECTED - DO NOT CLOSE]")

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
            "Close disabled during active recording",
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
