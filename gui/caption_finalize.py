"""Unified caption finalize: live worker result, post-extract fallback."""

from __future__ import annotations

from pathlib import Path

from caption_mode import (
    CaptionMode,
    CaptionPostProcessor,
    captions_enabled,
    resolve_caption_mode,
)
from caption_worker import validate_srt_file
from recorder import (
    _any_caption_sidecar,
    _caption_sidecar_paths,
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


def reprocess_captions(
    output_path: Path,
    mode: CaptionMode = "post_only",
    *,
    post_processor: CaptionPostProcessor = "ccextractor",
    log_file: Path | None = None,
    replace_existing: bool = True,
) -> bool:
    """Re-run post-record caption extraction without modifying the TS file."""
    if not captions_enabled(mode):
        return False
    if output_path.suffix.lower() != ".ts" or not output_path.is_file():
        return False

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"captions: reprocess start (no TS repair): {output_path}\n")

    if replace_existing:
        for sidecar in _caption_sidecar_paths(output_path):
            try:
                if sidecar.is_file():
                    sidecar.unlink()
            except OSError:
                pass

    maybe_post_extract_captions(
        output_path,
        download_captions=True,
        post_processor=post_processor,
        log_file=log_file,
    )
    srt = output_path.with_suffix(".srt")
    return validate_srt_file(srt)
