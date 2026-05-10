from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = REPO_ROOT / "gui"
if str(GUI_DIR) not in sys.path:
    sys.path.insert(0, str(GUI_DIR))

from span_fusion import FusedSpan, fuse_commercial_spans  # noqa: E402


class SpanFusionTests(unittest.TestCase):
    def test_fusion_with_weighted_overlap(self) -> None:
        fused = fuse_commercial_spans(
            detector_spans={
                "myth": [(100.0, 150.0)],
                "legacy": [(120.0, 170.0)],
            },
            detector_weights={
                "myth": 1.0,
                "legacy": 1.0,
            },
            duration_seconds=300.0,
            confidence_threshold=0.50,
        )
        self.assertTrue(fused)
        self.assertLessEqual(fused[0].start, 100.0)
        self.assertGreaterEqual(fused[-1].end, 170.0)

    def test_threshold_above_one_rejects_all(self) -> None:
        fused = fuse_commercial_spans(
            detector_spans={
                "myth": [(100.0, 130.0)],
                "ffmpeg_signals": [(100.0, 130.0)],
            },
            detector_weights={
                "myth": 0.2,
                "ffmpeg_signals": 1.0,
            },
            duration_seconds=300.0,
            confidence_threshold=1.01,
        )
        self.assertEqual(fused, [])

    def test_merge_touching_spans(self) -> None:
        fused = fuse_commercial_spans(
            detector_spans={
                "myth": [(10.0, 20.0), (20.1, 30.0)],
            },
            detector_weights={"myth": 1.0},
            duration_seconds=100.0,
            confidence_threshold=0.1,
        )
        self.assertEqual(len(fused), 1)
        self.assertAlmostEqual(fused[0].start, 10.0)
        self.assertAlmostEqual(fused[0].end, 30.0)


if __name__ == "__main__":
    unittest.main()
