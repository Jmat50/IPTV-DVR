"""Tests for caption finalize and reprocess helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caption_finalize import reprocess_captions


class CaptionFinalizeTests(unittest.TestCase):
    @patch("caption_finalize.maybe_post_extract_captions")
    @patch("caption_finalize.validate_srt_file", return_value=True)
    def test_reprocess_skips_repair_and_replaces_sidecar(
        self,
        _mock_validate: object,
        mock_post: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "sample.ts"
            srt = ts.with_suffix(".srt")
            ts.write_bytes(b"\x47" + b"\x00" * 128)
            srt.write_text("old\n", encoding="utf-8")

            ok = reprocess_captions(ts, "post_only", post_processor="ccextractor")

            self.assertTrue(ok)
            self.assertFalse(srt.is_file())
            mock_post.assert_called_once()
            self.assertEqual(mock_post.call_args.kwargs["post_processor"], "ccextractor")


if __name__ == "__main__":
    unittest.main()
