"""Tests for ComskipSettings and ini materialization."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from comskip_ini_build import apply_ini_overrides, materialize_comskip_ini
from comskip_settings import (
    DEFAULT_DETECT_METHOD,
    ComskipSettings,
    bits_from_detect_method,
    comskip_settings_from_dict,
    comskip_settings_to_dict,
    detect_method_from_bits,
)


class ComskipSettingsTest(unittest.TestCase):
    def test_default_detect_method(self) -> None:
        s = ComskipSettings()
        self.assertEqual(s.detect_method(), DEFAULT_DETECT_METHOD)
        self.assertEqual(s.detect_method(), 43)

    def test_bits_roundtrip(self) -> None:
        bits = bits_from_detect_method(111)
        method = detect_method_from_bits(
            black=bits["detect_black_frame"],
            logo=bits["detect_logo"],
            scene=bits["detect_scene_change"],
            fuzzy=bits["detect_fuzzy"],
            cc=bits["detect_closed_captions"],
            ar=bits["detect_aspect_ratio"],
            silence=bits["detect_silence"],
            cutscenes=bits["detect_cutscenes"],
        )
        self.assertEqual(method, 111)

    def test_from_dict_defaults(self) -> None:
        s = comskip_settings_from_dict(None)
        self.assertEqual(s.detect_method(), 43)
        self.assertTrue(s.connect_blocks_with_logo)

    def test_from_dict_detect_method_shortcut(self) -> None:
        s = comskip_settings_from_dict({"detect_method": 111})
        self.assertTrue(s.detect_scene_change)
        self.assertTrue(s.detect_silence)
        self.assertEqual(s.detect_method(), 111)

    def test_to_dict_includes_detect_method(self) -> None:
        d = comskip_settings_to_dict(ComskipSettings(detect_silence=True))
        self.assertEqual(d["detect_method"], 43 | 64)

    def test_ini_overrides_values(self) -> None:
        s = ComskipSettings(subtitles=True, min_commercialbreak=15, connect_blocks_with_logo=False)
        o = s.ini_overrides()
        self.assertEqual(o["subtitles"], "1")
        self.assertEqual(o["min_commercialbreak"], "15")
        self.assertEqual(o["connect_blocks_with_logo"], "0")


class ComskipIniBuildTest(unittest.TestCase):
    def test_apply_replaces_first_key(self) -> None:
        tpl = "detect_method=43\t\t;comment\nsubtitles=0\nother=1\n"
        out = apply_ini_overrides(tpl, {"detect_method": "111", "subtitles": "1"})
        self.assertIn("detect_method=111", out)
        self.assertIn("subtitles=1", out)
        self.assertNotIn("detect_method=43", out)

    def test_apply_appends_missing(self) -> None:
        tpl = "detect_method=43\n"
        out = apply_ini_overrides(tpl, {"subtitles": "1"})
        self.assertIn("subtitles=1", out)
        self.assertIn("Per-job overrides", out)

    def test_materialize_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tpl = Path(td) / "template.ini"
            tpl.write_text("detect_method=43\nsubtitles=0\n", encoding="utf-8")
            dest = Path(td) / "out" / "comskip.ini"
            s = ComskipSettings(subtitles=True, detect_silence=True)
            materialize_comskip_ini(s, dest, template_path=tpl)
            text = dest.read_text(encoding="utf-8")
            self.assertIn(f"detect_method={s.detect_method()}", text)
            self.assertIn("subtitles=1", text)


if __name__ == "__main__":
    unittest.main()
