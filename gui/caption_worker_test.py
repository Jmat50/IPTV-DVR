"""Tests for SRT validation and finalize."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from caption_worker import (
    atomic_finalize_partial,
    build_ccextractor_argv,
    build_ccextractor_post_argv,
    validate_srt_file,
)


class CaptionWorkerTests(unittest.TestCase):
    def test_build_argv_stream_mode(self) -> None:
        recording = Path(r"C:\tmp\show.ts")
        partial = Path(r"C:\tmp\show.srt.partial")
        argv = build_ccextractor_argv(recording, partial)
        self.assertIn("-1", argv)
        self.assertIn("--input", argv)
        self.assertIn("ts", argv)
        self.assertIn("--stream", argv)
        self.assertIn("15", argv)
        self.assertIn("--out", argv)
        self.assertIn("srt", argv)
        self.assertEqual(argv[-1], str(recording))

    def test_build_post_argv(self) -> None:
        recording = Path(r"C:\tmp\show.ts")
        final = Path(r"C:\tmp\show.srt")
        argv = build_ccextractor_post_argv(recording, final)
        self.assertIn("-1", argv)
        self.assertIn("--out=srt", argv)
        self.assertEqual(argv[-2], str(final))
        self.assertEqual(argv[-1], str(recording))

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
