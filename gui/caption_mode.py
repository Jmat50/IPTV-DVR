"""Caption mode resolution and migration from legacy download_captions."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from paths import ccextractor_exe

CaptionMode = Literal["off", "post_only", "live_ccextractor", "auto"]
CAPTION_MODES: tuple[CaptionMode, ...] = ("off", "post_only", "live_ccextractor", "auto")

_MODE_ALIASES: dict[str, CaptionMode] = {
    "": "off",
    "off": "off",
    "none": "off",
    "post": "post_only",
    "post_only": "post_only",
    "live": "live_ccextractor",
    "live_ccextractor": "live_ccextractor",
    "ccextractor": "live_ccextractor",
    "auto": "auto",
}

_LIVE_SUPPORT_CACHE: bool | None = None


def normalize_caption_mode(raw: str | None) -> CaptionMode:
    key = (raw or "").strip().lower()
    return _MODE_ALIASES.get(key, "off")


def ccextractor_available() -> bool:
    return ccextractor_exe().is_file()


def ccextractor_live_supported() -> bool:
    global _LIVE_SUPPORT_CACHE
    if _LIVE_SUPPORT_CACHE is not None:
        return _LIVE_SUPPORT_CACHE
    exe = ccextractor_exe()
    if not exe.is_file():
        _LIVE_SUPPORT_CACHE = False
        return False
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "probe.ts"
        probe.write_bytes(b"\x00")
        partial = Path(td) / "probe.srt.partial"
        cmd = [
            str(exe),
            "--stream",
            "15",
            "-out=srt",
            str(probe),
            "-o",
            str(partial),
        ]
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
            )
            out = f"{p.stdout}\n{p.stderr}".lower()
        except subprocess.TimeoutExpired:
            # Command accepted and waited for stream updates.
            _LIVE_SUPPORT_CACHE = True
            return True
        _LIVE_SUPPORT_CACHE = "only supports one input file" not in out
        return _LIVE_SUPPORT_CACHE


def migrate_caption_mode(
    *,
    caption_mode: str | None,
    download_captions: bool,
) -> CaptionMode:
    if caption_mode:
        mode = normalize_caption_mode(caption_mode)
        if mode != "off" or caption_mode.strip().lower() in _MODE_ALIASES:
            return mode
    if download_captions:
        return "auto"
    return "off"


def captions_enabled(mode: CaptionMode) -> bool:
    return mode != "off"


def resolve_caption_mode(mode: CaptionMode, output_path: Path) -> CaptionMode:
    if mode == "auto":
        if (
            output_path.suffix.lower() == ".ts"
            and ccextractor_available()
            and ccextractor_live_supported()
        ):
            return "live_ccextractor"
        return "post_only"
    if mode == "live_ccextractor":
        if output_path.suffix.lower() != ".ts":
            return "post_only"
        if not ccextractor_available() or not ccextractor_live_supported():
            return "post_only"
    return mode


def use_live_ccextractor(mode: CaptionMode, output_path: Path) -> bool:
    return resolve_caption_mode(mode, output_path) == "live_ccextractor"


def use_post_extract(mode: CaptionMode) -> bool:
    resolved = mode if mode != "auto" else "post_only"
    return resolved in ("post_only", "live_ccextractor")
