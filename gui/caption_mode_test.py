"""Tests for caption mode resolution."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from caption_mode import (
    migrate_caption_mode,
    normalize_caption_mode,
    resolve_caption_mode,
    use_live_ccextractor,
)


class CaptionModeTests(unittest.TestCase):
    def test_migrate_legacy(self) -> None:
        self.assertEqual(migrate_caption_mode(caption_mode=None, download_captions=True), "auto")
        self.assertEqual(migrate_caption_mode(caption_mode="post_only", download_captions=False), "post_only")

    def test_normalize(self) -> None:
        self.assertEqual(normalize_caption_mode("LIVE"), "live_ccextractor")

    @patch("caption_mode.ccextractor_live_supported", return_value=True)
    @patch("caption_mode.ccextractor_available", return_value=True)
    def test_auto_ts_live(self, _mock_available: object, _mock_live: object) -> None:
        self.assertEqual(resolve_caption_mode("auto", Path("x.ts")), "live_ccextractor")
        self.assertTrue(use_live_ccextractor("auto", Path("x.ts")))

    @patch("caption_mode.ccextractor_live_supported", return_value=False)
    @patch("caption_mode.ccextractor_available", return_value=True)
    def test_auto_without_live_support(self, _mock_available: object, _mock_live: object) -> None:
        self.assertEqual(resolve_caption_mode("auto", Path("x.ts")), "post_only")


if __name__ == "__main__":
    unittest.main()
