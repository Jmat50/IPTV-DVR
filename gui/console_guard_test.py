"""Tests for shared console guard profiles."""

from __future__ import annotations

import unittest

from console_guard import GUARD_CCEXTRACTOR, GUARD_FFMPEG, create_new_console_flag


class ConsoleGuardTests(unittest.TestCase):
    def test_guard_profiles(self) -> None:
        self.assertEqual(GUARD_FFMPEG.tool_label, "FFmpeg")
        self.assertIn("FFmpeg", GUARD_FFMPEG.menu_text)
        self.assertEqual(GUARD_CCEXTRACTOR.tool_label, "CCExtractor")
        self.assertIn("CCExtractor", GUARD_CCEXTRACTOR.menu_text)

    def test_create_new_console_flag_is_platform_specific(self) -> None:
        flag = create_new_console_flag()
        if __import__("sys").platform == "win32":
            self.assertEqual(flag, 0x00000010)
        else:
            self.assertIsNone(flag)


if __name__ == "__main__":
    unittest.main()
