import tempfile
import unittest
from pathlib import Path

from comskip_worker import (
    comskip_run_ok,
    comskip_sidecar_edl,
    publish_edl_beside_recording,
)


class ComskipWorkerTest(unittest.TestCase):
    def test_exit_codes(self) -> None:
        self.assertTrue(comskip_run_ok(0, edl_ok=False, txt_ok=False))
        self.assertTrue(comskip_run_ok(1, edl_ok=True, txt_ok=False))
        self.assertTrue(comskip_run_ok(1, edl_ok=False, txt_ok=True))
        self.assertFalse(comskip_run_ok(1, edl_ok=False, txt_ok=False))
        self.assertFalse(comskip_run_ok(2, edl_ok=True, txt_ok=True))

    def test_edl_beside_recording(self) -> None:
        rec = Path(r"C:\Videos\show.ts")
        self.assertEqual(comskip_sidecar_edl(rec), Path(r"C:\Videos\show.edl"))

    def test_publish_edl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            work.mkdir()
            rec = root / "out" / "show.ts"
            rec.parent.mkdir()
            work_edl = work / "show.edl"
            work_edl.write_text("1.00\t2.00\t3\n", encoding="utf-8")
            published = publish_edl_beside_recording(work_edl, rec)
            self.assertEqual(published, root / "out" / "show.edl")
            self.assertTrue(published.is_file())
            self.assertEqual(published.read_text(encoding="utf-8"), "1.00\t2.00\t3\n")
            self.assertTrue(work_edl.is_file())


if __name__ == "__main__":
    unittest.main()
