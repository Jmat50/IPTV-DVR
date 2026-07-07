import unittest
from pathlib import Path
import tempfile

from comskip_merge import (
    CommercialBreak,
    EpisodeSegment,
    merge_commercial_breaks,
    normalize_breaks,
    parse_comskip_edl,
    write_merged_edl,
    write_merged_txt,
)


class ComskipMergeTest(unittest.TestCase):
    def test_parse_edl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample.edl"
            p.write_text("10.00\t40.00\t3\n120.5\t180.0\t3\n", encoding="utf-8")
            breaks = parse_comskip_edl(p)
            self.assertEqual(len(breaks), 2)
            self.assertAlmostEqual(breaks[0].start_sec, 10.0)
            self.assertAlmostEqual(breaks[1].end_sec, 180.0)

    def test_merge_offsets(self) -> None:
        seg = EpisodeSegment(index=2, start_sec=3600.0, end_sec=7200.0)
        with tempfile.TemporaryDirectory() as td:
            edl = Path(td) / "seg.edl"
            edl.write_text("10.00\t40.00\t3\n", encoding="utf-8")
            merged = merge_commercial_breaks([(seg, edl, None)], total_sec=8000.0)
            self.assertEqual(len(merged), 1)
            self.assertAlmostEqual(merged[0].start_sec, 3610.0)
            self.assertEqual(merged[0].episode_index, 2)

    def test_normalize_overlap(self) -> None:
        breaks = [
            CommercialBreak(10.0, 50.0),
            CommercialBreak(40.0, 70.0),
        ]
        out = normalize_breaks(breaks, total_sec=100.0)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0].start_sec, 10.0)
        self.assertAlmostEqual(out[0].end_sec, 70.0)

    def test_write_merged_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            edl = Path(td) / "out.edl"
            txt = Path(td) / "out.txt"
            breaks = [CommercialBreak(1.0, 2.0)]
            write_merged_edl(edl, breaks)
            write_merged_txt(txt, breaks, fps=30.0, total_sec=60.0)
            self.assertIn("1.00", edl.read_text(encoding="utf-8"))
            self.assertIn("FRAMES AT", txt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
