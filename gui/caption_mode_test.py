"""Tests for caption mode resolution."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.assertEqual(migrate_caption_mode(caption_mode=None, download_captions=True), "auto")
        self.assertEqual(migrate_caption_mode(caption_mode="post_only", download_captions=False), "post_only")

    def test_normalize(self) -> None:
        self.assertEqual(normalize_caption_mode("LIVE"), "live_ccextractor")
        self.assertEqual(normalize_caption_post_processor("CC"), "ccextractor")

    @patch("caption_mode.ccextractor_live_supported", return_value=True)
    @patch("caption_mode.ccextractor_available", return_value=True)
    def test_auto_ts_live(self, _mock_available: object, _mock_live: object) -> None:
        self.assertEqual(resolve_caption_mode("auto", Path("x.ts")), "live_ccextractor")
        self.assertTrue(use_live_ccextractor("auto", Path("x.ts")))

    @patch("caption_mode.ccextractor_live_supported", return_value=False)
    @patch("caption_mode.ccextractor_available", return_value=True)
    def test_auto_without_live_support(self, _mock_available: object, _mock_live: object) -> None:
        self.assertEqual(resolve_caption_mode("auto", Path("x.ts")), "post_only")
        resolved, reason = resolve_caption_mode_with_reason("auto", Path("x.ts"))
        self.assertEqual(resolved, "post_only")
        self.assertIn("unavailable", reason.lower())

    @patch("caption_mode.ccextractor_live_supported", return_value=False)
    @patch("caption_mode.ccextractor_live_support_reason", return_value="CCExtractor 0.96.x CLI regression")
    @patch("caption_mode.ccextractor_available", return_value=True)
    def test_auto_reports_regression_reason(
        self,
        _mock_available: object,
        _mock_reason: object,
        _mock_live: object,
    ) -> None:
        _resolved, reason = resolve_caption_mode_with_reason("auto", Path("x.ts"))
        self.assertEqual(_resolved, "post_only")
        self.assertIn("regression", reason)

    def test_post_processor_mode_gate(self) -> None:
        self.assertTrue(caption_mode_allows_post_processor("auto"))
        self.assertTrue(caption_mode_allows_post_processor("post_only"))
        self.assertFalse(caption_mode_allows_post_processor("off"))
        self.assertFalse(caption_mode_allows_post_processor("live_ccextractor"))
        self.assertEqual(resolve_post_processor_for_mode("auto", "ccextractor"), "ccextractor")
        self.assertEqual(resolve_post_processor_for_mode("off", "ccextractor"), "ffmpeg")


if __name__ == "__main__":
    unittest.main()
