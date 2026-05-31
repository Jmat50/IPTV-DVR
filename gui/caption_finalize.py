"""Unified caption finalize: live worker result, post-extract fallback."""

from __future__ import annotations

from pathlib import Path

from caption_mode import (
    CaptionMode,
    CaptionPostProcessor,
    captions_enabled,
    resolve_caption_mode,
)
from recorder import (
    _any_caption_sidecar,
    maybe_post_extract_captions,
    probe_url_has_subtitles,
)


def should_dual_output_vtt(
    mode: CaptionMode,
    *,
    stream_url: str,
    user_agent: str = "",
    referer: str = "",
) -> bool:
    if not captions_enabled(mode):
        return False
    return probe_url_has_subtitles(stream_url, user_agent=user_agent, referer=referer)


def finalize_captions(
    output_path: Path,
    mode: CaptionMode,
    *,
    post_processor: CaptionPostProcessor = "ffmpeg",
    log_file: Path | None = None,
    live_ok: bool = False,
) -> None:
    """Post-process captions after recording; respects existing sidecars."""
    if not captions_enabled(mode):
        return
    if _any_caption_sidecar(output_path):
        return
    if live_ok:
        return
    resolved = resolve_caption_mode(mode, output_path)
    if resolved in ("post_only", "live_ccextractor"):
        maybe_post_extract_captions(
            output_path,
            download_captions=True,
            post_processor=post_processor,
            log_file=log_file,
        )
