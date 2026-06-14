"""Tests for post-record TS scan/repair gating."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from recorder import maybe_post_scan_repair


class PostScanRepairTests(unittest.TestCase):
    def test_disabled_skips_repair(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "sample.ts"
            ts.write_bytes(b"\x47" + b"\x00" * 128)
            self.assertFalse(maybe_post_scan_repair(ts, enabled=False))

    @patch("recorder.try_repair_ts_file", return_value=True)
    @patch("recorder.should_repair_ts_file", return_value=True)
    def test_enabled_runs_repair_when_needed(
        self,
        _mock_should: object,
        mock_repair: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "sample.ts"
            ts.write_bytes(b"\x47" + b"\x00" * 128)
            self.assertTrue(maybe_post_scan_repair(ts, enabled=True))
            mock_repair.assert_called_once()

    @patch("recorder.try_repair_ts_file")
    @patch("recorder.should_repair_ts_file", return_value=False)
    def test_enabled_skips_when_scan_clean(
        self,
        _mock_should: object,
        mock_repair: object,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "sample.ts"
            ts.write_bytes(b"\x47" + b"\x00" * 128)
            self.assertFalse(maybe_post_scan_repair(ts, enabled=True))
            mock_repair.assert_not_called()


if __name__ == "__main__":
    unittest.main()
