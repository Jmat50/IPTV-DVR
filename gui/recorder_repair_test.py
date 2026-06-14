"""Tests for post-record TS scan/repair gating and guarded CCExtractor runs."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from console_guard import GUARD_CCEXTRACTOR
from recorder import maybe_post_scan_repair, run_tool


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


class GuardedToolTests(unittest.TestCase):
    @patch("recorder.subprocess.Popen")
    @patch("recorder.start_console_close_guard")
    def test_run_tool_uses_guard_when_requested(
        self,
        mock_guard: object,
        mock_popen: object,
    ) -> None:
        proc = mock_popen.return_value
        proc.stdout = iter(["done\n"])
        proc.wait.return_value = 0
        code = run_tool(
            ["ccextractor.exe", "-1", "input.ts"],
            console_guard=GUARD_CCEXTRACTOR,
        )
        self.assertEqual(code, 0)
        mock_guard.assert_called_once_with(proc.pid, GUARD_CCEXTRACTOR)
        mock_popen.assert_called_once()
        if sys.platform == "win32":
            self.assertEqual(mock_popen.call_args.kwargs.get("creationflags"), 0x00000010)


if __name__ == "__main__":
    unittest.main()
