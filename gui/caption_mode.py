"""Caption mode resolution and migration from legacy download_captions."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from caption_worker import build_ccextractor_live_argv
from paths import ccextractor_exe

CaptionMode = Literal["off", "post_only", "live_ccextractor", "auto"]
CaptionPostProcessor = Literal["ffmpeg", "ccextractor"]
CAPTION_MODES: tuple[CaptionMode, ...] = ("off", "post_only", "live_ccextractor", "auto")
CAPTION_POST_PROCESSORS: tuple[CaptionPostProcessor, ...] = ("ffmpeg", "ccextractor")

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
_POST_PROCESSOR_ALIASES: dict[str, CaptionPostProcessor] = {
    "": "ffmpeg",
    "ffmpeg": "ffmpeg",
    "cc": "ccextractor",
    "ccextractor": "ccextractor",
}

_LIVE_SUPPORT_CACHE: bool | None = None
_LIVE_SUPPORT_REASON: str = ""


def normalize_caption_mode(raw: str | None) -> CaptionMode:
    key = (raw or "").strip().lower()
    return _MODE_ALIASES.get(key, "off")


def normalize_caption_post_processor(raw: str | None) -> CaptionPostProcessor:
    key = (raw or "").strip().lower()
    return _POST_PROCESSOR_ALIASES.get(key, "ffmpeg")


def caption_mode_allows_post_processor(mode: CaptionMode) -> bool:
    return mode in ("auto", "post_only")


def resolve_post_processor_for_mode(
    mode: CaptionMode,
    requested: str | None,
) -> CaptionPostProcessor:
    if not caption_mode_allows_post_processor(mode):
        return "ffmpeg"
    return normalize_caption_post_processor(requested)


def ccextractor_available() -> bool:
    return ccextractor_exe().is_file()


def _set_live_support_cache(value: bool, reason: str) -> bool:
    global _LIVE_SUPPORT_CACHE, _LIVE_SUPPORT_REASON
    _LIVE_SUPPORT_CACHE = value
    _LIVE_SUPPORT_REASON = reason
    return value


def ccextractor_live_support_reason() -> str:
    if _LIVE_SUPPORT_CACHE is None:
        _ = ccextractor_live_supported()
    return _LIVE_SUPPORT_REASON


def _probe_ts_bytes() -> bytes:
    """Minimal bytes so the probe file exists; CCExtractor validates CLI before read."""
    return b"\x47"  # MPEG-TS sync byte


def ccextractor_live_supported() -> bool:
    if _LIVE_SUPPORT_CACHE is not None:
        return _LIVE_SUPPORT_CACHE
    exe = ccextractor_exe()
    if not exe.is_file():
        return _set_live_support_cache(False, f"CCExtractor not found at {exe}")
    with tempfile.TemporaryDirectory() as td:
        probe = Path(td) / "probe.ts"
        probe.write_bytes(_probe_ts_bytes())
        partial = Path(td) / "probe.srt.partial"
        cmd = build_ccextractor_live_argv(probe, partial)
        try:
            p = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                cwd=str(exe.parent),
            )
            out = f"{p.stdout}\n{p.stderr}".lower()
        except subprocess.TimeoutExpired:
            # Command accepted and waited for stream updates.
            return _set_live_support_cache(True, "live probe timed out while waiting for stream data")
        if p.returncode == 0:
            return _set_live_support_cache(True, "live probe exited cleanly")
        if "only supports one input file" in out:
            return _set_live_support_cache(
                False,
                "CCExtractor 0.96.x CLI regression: --stream <secs> rejects any input file "
                "(inverted validation in rust parser; live tail mode never starts)",
            )
        if "a value is required for '--stream <stream>'" in out:
            return _set_live_support_cache(False, "live stream mode parsing failed (--stream value)")
        short = " ".join(line.strip() for line in out.splitlines() if line.strip())[:220]
        return _set_live_support_cache(
            False,
            short or f"live probe failed with exit code {p.returncode}",
        )


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
        return "post_only"
    return "off"


def captions_enabled(mode: CaptionMode) -> bool:
    return mode != "off"


def resolve_caption_mode_with_reason(mode: CaptionMode, output_path: Path) -> tuple[CaptionMode, str]:
    if mode == "auto":
        return "post_only", "auto uses post-record extraction"
    if mode == "live_ccextractor":
        if output_path.suffix.lower() != ".ts":
            return "post_only", "live_ccextractor requires .ts output"
        if not ccextractor_available():
            return "post_only", f"CCExtractor not found at {ccextractor_exe()}"
        if not ccextractor_live_supported():
            reason = ccextractor_live_support_reason()
            return "post_only", f"CCExtractor live mode unavailable: {reason}"
        return "live_ccextractor", "live CCExtractor enabled"
    return mode, "captions mode unchanged"


def resolve_caption_mode(mode: CaptionMode, output_path: Path) -> CaptionMode:
    resolved, _ = resolve_caption_mode_with_reason(mode, output_path)
    return resolved


def use_live_ccextractor(mode: CaptionMode, output_path: Path) -> bool:
    return resolve_caption_mode(mode, output_path) == "live_ccextractor"


def use_post_extract(mode: CaptionMode) -> bool:
    resolved = mode if mode != "auto" else "post_only"
    return resolved in ("post_only", "live_ccextractor")
