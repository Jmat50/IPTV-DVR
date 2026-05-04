"""Paths for dev (repo) and PyInstaller frozen exe (next to iptv-recorder.exe)."""

from __future__ import annotations

import sys
from shutil import which
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
    return project_root() / "tools"


def _tool_path_candidates(*parts: str) -> list[Path]:
    root = project_root()
    candidates = [root / "tools" / Path(*parts)]
    parent = root.parent
    candidates.append(parent / "tools" / Path(*parts))
    return candidates


def comskip_exe() -> Path:
    return _tool_path_candidates("comskip", "comskip.exe")[0]


def comskip_ini() -> Path:
    return _tool_path_candidates("comskip", "comskip.ini")[0]


def commercial_cleaner_exe() -> Path:
    return _tool_path_candidates("commercialcleaner", "CommercialCleaner.exe")[0]


def resolve_comskip_exe() -> Path | None:
    for p in _tool_path_candidates("comskip", "comskip.exe"):
        if p.is_file():
            return p
    on_path = which("comskip")
    return Path(on_path) if on_path else None


def resolve_commercial_cleaner_exe() -> Path | None:
    for p in _tool_path_candidates("commercialcleaner", "CommercialCleaner.exe"):
        if p.is_file():
            return p
    on_path = which("CommercialCleaner")
    return Path(on_path) if on_path else None
