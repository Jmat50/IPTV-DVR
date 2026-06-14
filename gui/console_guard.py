"""Windows console accidental-close guard for long-lived child processes."""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

CREATE_NEW_CONSOLE = 0x00000010


@dataclass(frozen=True)
class ConsoleGuard:
    tool_label: str
    menu_text: str


GUARD_FFMPEG = ConsoleGuard(
    "FFmpeg",
    "Close disabled while FFmpeg is recording",
)
GUARD_CCEXTRACTOR = ConsoleGuard(
    "CCExtractor",
    "Close disabled while CCExtractor is extracting captions",
)


def create_new_console_flag() -> int | None:
    if sys.platform != "win32":
        return None
    return CREATE_NEW_CONSOLE


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


def _warn_console_is_protected(hwnd: int, guard: ConsoleGuard) -> None:
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, len(title))
    base = title.value.strip() or guard.tool_label
    protected_tag = f"[{guard.tool_label} - PROTECTED - do not close]"
    if protected_tag.lower() not in base.lower():
        user32.SetWindowTextW(hwnd, f"{base} {protected_tag}")

    menu = user32.GetSystemMenu(hwnd, False)
    if menu:
        mf_string = 0x0000
        mf_separator = 0x0800
        mf_disabled = 0x0002
        user32.AppendMenuW(menu, mf_separator, 0, None)
        user32.AppendMenuW(
            menu,
            mf_string | mf_disabled,
            0,
            guard.menu_text,
        )
        user32.DrawMenuBar(hwnd)


def _arm_console_close_guard(pid: int, guard: ConsoleGuard) -> None:
    if sys.platform != "win32":
        return

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        hwnd = _find_console_window_for_pid(pid)
        if hwnd is not None:
            _disable_console_close(hwnd)
            _warn_console_is_protected(hwnd, guard)
            return
        time.sleep(0.10)


def start_console_close_guard(pid: int, guard: ConsoleGuard) -> None:
    if sys.platform != "win32":
        return
    threading.Thread(
        target=_arm_console_close_guard,
        args=(pid, guard),
        daemon=True,
    ).start()
