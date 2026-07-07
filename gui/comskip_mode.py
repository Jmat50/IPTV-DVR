"""Comskip availability and output compatibility helpers."""

from __future__ import annotations

from pathlib import Path

from paths import comskip_exe, comskip_ini


def comskip_available() -> bool:
    return comskip_exe().is_file() and comskip_ini().is_file()


def comskip_supported_output(path: Path) -> bool:
    return path.suffix.lower() == ".ts"
