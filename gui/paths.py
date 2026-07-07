"""Paths for dev (repo) and PyInstaller frozen exe (next to iptv-dvr.exe)."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    # Frozen: e.g. gui\iptv-gui.exe — config.json and logs/ sit beside the exe.
    if is_frozen() and getattr(sys, "executable", None):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def ffmpeg_exe() -> Path:
    root = project_root()
    if is_frozen():
        candidates = [root / "ffmpeg" / "ffmpeg.exe"]
    else:
        candidates = [root / "gui" / "ffmpeg" / "ffmpeg.exe"]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def ffprobe_exe() -> Path:
    return ffmpeg_exe().with_name("ffprobe.exe")


def config_file() -> Path:
    return project_root() / "config.json"


def log_dir() -> Path:
    d = project_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tools_dir() -> Path:
    d = project_root() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ccextractor_exe() -> Path:
    root = project_root()
    if is_frozen():
        candidates = [root / "tools" / "ccextractor" / "ccextractor.exe"]
    else:
        candidates = [
            root / "gui" / "tools" / "ccextractor" / "ccextractor.exe",
            root / "tools" / "ccextractor" / "ccextractor.exe",
        ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def comskip_dir() -> Path:
    root = project_root()
    if is_frozen():
        return root / "tools" / "comskip"
    return root / "gui" / "tools" / "comskip"


def comskip_exe() -> Path:
    root = project_root()
    if is_frozen():
        candidates = [root / "tools" / "comskip" / "comskip.exe"]
    else:
        candidates = [
            root / "gui" / "tools" / "comskip" / "comskip.exe",
            root / "tools" / "comskip" / "comskip.exe",
        ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def comskip_ini() -> Path:
    bundled = comskip_dir() / "comskip.ini"
    if bundled.is_file():
        return bundled
    return comskip_exe().with_name("comskip.ini")


def comskip_work_dir() -> Path:
    d = log_dir() / "comskip_work"
    d.mkdir(parents=True, exist_ok=True)
    return d
