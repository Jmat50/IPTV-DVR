import unittest
from pathlib import Path
import tempfile

from comskip_chapters import write_chapters_ffmeta
from comskip_merge import CommercialBreak, EpisodeSegment


class ComskipChaptersTest(unittest.TestCase):
    def test_ffmeta_structure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rec.chapters.ffmeta"
            write_chapters_ffmeta(
                path,
                title="rec",
                episodes=[EpisodeSegment(1, 0.0, 120.0)],
                commercials=[CommercialBreak(10.0, 20.0, episode_index=1)],
                total_sec=120.0,
            )
            text = path.read_text(encoding="utf-8")
            self.assertIn(";FFMETADATA1", text)
            self.assertIn("title=Episode 1", text)
            self.assertIn("Commercial (Ep 1)", text)
            self.assertIn("TIMEBASE=1/1000", text)


if __name__ == "__main__":
    unittest.main()
