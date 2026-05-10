from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
GUI_DIR = REPO_ROOT / "gui"
if str(GUI_DIR) not in sys.path:
    sys.path.insert(0, str(GUI_DIR))

import postprocess  # noqa: E402


class PostprocessUnitTests(unittest.TestCase):
    def test_parse_mythcommflag_marks(self) -> None:
        sample = "\n".join(
            [
                "commercialBreakListFor: C:/video.ts",
                "totalframecount: 53346",
                "framenum: 17468 marktype: 4",
                "framenum: 21592 marktype: 5",
                "framenum: 25263 marktype: 4",
                "framenum: 29842 marktype: 5",
                "",
            ],
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "mythcommflag.txt"
            p.write_text(sample, encoding="utf-8")
            total_frames, marks = postprocess._parse_mythcommflag_marks(p)
        self.assertEqual(total_frames, 53346)
        self.assertEqual(marks, [(17468, 4), (21592, 5), (25263, 4), (29842, 5)])

    def test_commercial_spans_closes_open_tail(self) -> None:
        spans = postprocess._commercial_spans_from_marks(
            [(100, 4), (200, 5), (400, 4)],
            fallback_total_frames=1000,
        )
        self.assertEqual(spans, [(100, 200), (400, 1000)])

    def test_seconds_spans_and_invert_ranges(self) -> None:
        commercials = postprocess._seconds_spans_from_frames(
            [(300, 600), (900, 1200)],
            fps=30.0,
            duration_seconds=60.0,
        )
        self.assertEqual(commercials, [(10.0, 20.0), (30.0, 40.0)])
        keep = postprocess._invert_intervals(60.0, commercials)
        self.assertEqual(keep, [(0.0, 10.0), (20.0, 30.0), (40.0, 60.0)])

    def test_invert_intervals_merges_touching_ranges(self) -> None:
        keep = postprocess._invert_intervals(
            100.0,
            [(10.0, 20.0), (20.03, 30.0), (80.0, 90.0)],
        )
        self.assertEqual(keep, [(0.0, 10.0), (30.0, 80.0), (90.0, 100.0)])

    def test_build_concat_filter(self) -> None:
        keep_ranges = [(0.0, 15.0), (20.0, 30.0)]
        with_audio = postprocess._build_concat_filter(keep_ranges, with_audio=True)
        self.assertIn("concat=n=2:v=1:a=1[vout][aout]", with_audio)
        self.assertIn("[0:a:0]atrim=start=0.000000:end=15.000000", with_audio)

        no_audio = postprocess._build_concat_filter(keep_ranges, with_audio=False)
        self.assertIn("concat=n=2:v=1:a=0[vout]", no_audio)
        self.assertNotIn("atrim", no_audio)

    def test_run_postprocessing_skips_cut_when_no_commercials(self) -> None:
        class Settings:
            def __init__(self) -> None:
                self.strategy = "myth_only"
                self.episode_aware = False
                self.min_keep_segment_seconds = 0.0

        class Job:
            remove_commercials_after_complete = True
            commercial_settings = Settings()

        recorded = Path("C:/video.ts")
        with mock.patch.object(postprocess, "_probe_duration_seconds", return_value=120.0):
            with mock.patch.object(postprocess, "detect_commercials_with_mythcommflag", return_value=[]):
                with mock.patch.object(postprocess, "cut_commercials_with_ffmpeg") as cut_mock:
                    result = postprocess.run_postprocessing(
                        Job(),
                        recorded_path=recorded,
                        log_file=Path("C:/tmp/job.log"),
                    )
        self.assertTrue(result.success)
        self.assertEqual(result.output_path, recorded)
        cut_mock.assert_not_called()

    def test_run_postprocessing_applies_cut_when_commercials_exist(self) -> None:
        class Settings:
            def __init__(self) -> None:
                self.strategy = "myth_only"
                self.episode_aware = False
                self.min_keep_segment_seconds = 0.0

        class Job:
            remove_commercials_after_complete = True
            commercial_settings = Settings()

        recorded = Path("C:/video.ts")
        cleaned = Path("C:/video_clean.mkv")
        with mock.patch.object(postprocess, "_probe_duration_seconds", return_value=120.0):
            with mock.patch.object(postprocess, "detect_commercials_with_mythcommflag", return_value=[(5.0, 10.0)]):
                with mock.patch.object(postprocess, "cut_commercials_with_ffmpeg", return_value=cleaned) as cut_mock:
                    result = postprocess.run_postprocessing(
                        Job(),
                        recorded_path=recorded,
                        log_file=Path("C:/tmp/job.log"),
                    )
        self.assertTrue(result.success)
        self.assertEqual(result.output_path, cleaned)
        cut_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
