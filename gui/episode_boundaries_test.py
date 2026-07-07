import unittest

from episode_boundaries import parse_blackdetect_output, parse_silencedetect_output


class EpisodeBoundariesTest(unittest.TestCase):
    def test_parse_blackdetect(self) -> None:
        text = (
            "[blackdetect @ 0x1] black_start:100.0 black_end:103.0 black_duration:3.0\n"
            "[blackdetect @ 0x1] black_start:200.0 black_end:201.0 black_duration:1.0\n"
        )
        gaps = parse_blackdetect_output(text)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0].time_sec, 101.5)

    def test_parse_silencedetect(self) -> None:
        text = (
            "[silencedetect @ 0x1] silence_start: 50.0\n"
            "[silencedetect @ 0x1] silence_end: 52.5 | silence_duration: 2.5\n"
        )
        gaps = parse_silencedetect_output(text)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0].time_sec, 51.25)


if __name__ == "__main__":
    unittest.main()
