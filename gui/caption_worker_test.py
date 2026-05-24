"""Tests for SRT validation and finalize."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from caption_worker import atomic_finalize_partial, validate_srt_file


class CaptionWorkerTests(unittest.TestCase):
    def test_validate_and_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            partial = Path(td) / "a.srt.partial"
            final = Path(td) / "a.srt"
            partial.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
            self.assertTrue(validate_srt_file(partial))
            self.assertTrue(atomic_finalize_partial(partial, final))
            self.assertTrue(final.is_file())
            self.assertFalse(partial.exists())

    def test_reject_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.srt.partial"
            p.write_text("", encoding="utf-8")
            self.assertFalse(validate_srt_file(p))


if __name__ == "__main__":
    unittest.main()
