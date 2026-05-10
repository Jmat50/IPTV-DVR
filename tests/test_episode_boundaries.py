from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = REPO_ROOT / "gui"
if str(GUI_DIR) not in sys.path:
    sys.path.insert(0, str(GUI_DIR))

import episode_boundaries  # noqa: E402


class EpisodeBoundaryTests(unittest.TestCase):
    def test_short_file_returns_single_block(self) -> None:
        with mock.patch.object(episode_boundaries, "_probe_duration_seconds", return_value=600.0):
            blocks = episode_boundaries.detect_episode_blocks(
                Path("C:/video.ts"),
                min_gap_seconds=90.0,
                min_black_seconds=2.0,
                min_silence_seconds=1.5,
            )
        self.assertEqual(blocks, [(0.0, 600.0)])

    def test_detects_boundaries_when_black_and_silence_align(self) -> None:
        sample_out = "\n".join(
            [
                "[blackdetect @ 0x0] black_start:1798.0 black_end:1802.5 black_duration:4.5",
                "[silencedetect @ 0x0] silence_start:1799.5",
                "[silencedetect @ 0x0] silence_end:1802.0 | silence_duration:2.5",
                "[blackdetect @ 0x0] black_start:3598.0 black_end:3602.0 black_duration:4.0",
                "[silencedetect @ 0x0] silence_start:3599.0",
                "[silencedetect @ 0x0] silence_end:3602.3 | silence_duration:3.3",
            ],
        )
        with mock.patch.object(episode_boundaries, "_probe_duration_seconds", return_value=5400.0):
            with mock.patch.object(episode_boundaries, "_run_signal_scan", return_value=sample_out):
                blocks = episode_boundaries.detect_episode_blocks(
                    Path("C:/video.ts"),
                    min_gap_seconds=600.0,
                    min_black_seconds=2.0,
                    min_silence_seconds=1.0,
                )
        self.assertEqual(len(blocks), 3)
        self.assertAlmostEqual(blocks[0][0], 0.0)
        self.assertGreater(blocks[0][1], 1700.0)
        self.assertAlmostEqual(blocks[-1][1], 5400.0)


if __name__ == "__main__":
    unittest.main()
