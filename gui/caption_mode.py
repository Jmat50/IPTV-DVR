"""Caption mode resolution and migration from legacy download_captions."""

from __future__ import annotations

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


def normalize_caption_mode(raw: str | None) -> CaptionMode:
    key = (raw or "").strip().lower()
    return _MODE_ALIASES.get(key, "off")


def ccextractor_available() -> bool:
    return ccextractor_exe().is_file()


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
        if output_path.suffix.lower() == ".ts" and ccextractor_available():
            return "live_ccextractor"
        return "post_only"
    if mode == "live_ccextractor":
        if output_path.suffix.lower() != ".ts":
            return "post_only"
        if not ccextractor_available():
            return "post_only"
    return mode


def use_live_ccextractor(mode: CaptionMode, output_path: Path) -> bool:
    return resolve_caption_mode(mode, output_path) == "live_ccextractor"


def use_post_extract(mode: CaptionMode) -> bool:
    resolved = mode if mode != "auto" else "post_only"
    return resolved in ("post_only", "live_ccextractor")
