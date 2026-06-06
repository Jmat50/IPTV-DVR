"""Tests for caption mode resolution."""

from __future__ import annotations

import unittest
from pathlib import Path

from caption_mode import (
    caption_mode_allows_post_processor,
    migrate_caption_mode,
    normalize_caption_mode,
    normalize_caption_post_processor,
    resolve_post_processor_for_mode,
    resolve_caption_mode,
    resolve_caption_mode_with_reason,
    use_live_ccextractor,
)


class CaptionModeTests(unittest.TestCase):
    def test_migrate_legacy(self) -> None:
        self.assertEqual(migrate_caption_mode(caption_mode=None, download_captions=True), "post_only")
        self.assertEqual(migrate_caption_mode(caption_mode="post_only", download_captions=False), "post_only")

    def test_normalize(self) -> None:
        self.assertEqual(normalize_caption_mode("LIVE"), "live_ccextractor")
        self.assertEqual(normalize_caption_post_processor("CC"), "ccextractor")

    def test_auto_uses_post_only(self) -> None:
        self.assertEqual(resolve_caption_mode("auto", Path("x.ts")), "post_only")
        self.assertFalse(use_live_ccextractor("auto", Path("x.ts")))
        resolved, reason = resolve_caption_mode_with_reason("auto", Path("x.mp4"))
        self.assertEqual(resolved, "post_only")
        self.assertIn("post-record", reason.lower())

    def test_post_processor_mode_gate(self) -> None:
        self.assertTrue(caption_mode_allows_post_processor("auto"))
        self.assertTrue(caption_mode_allows_post_processor("post_only"))
        self.assertFalse(caption_mode_allows_post_processor("off"))
        self.assertFalse(caption_mode_allows_post_processor("live_ccextractor"))
        self.assertEqual(resolve_post_processor_for_mode("auto", "ccextractor"), "ccextractor")
        self.assertEqual(resolve_post_processor_for_mode("off", "ccextractor"), "ffmpeg")


if __name__ == "__main__":
    unittest.main()
