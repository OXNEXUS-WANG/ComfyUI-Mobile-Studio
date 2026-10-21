# -*- coding: utf-8 -*-
import unittest

from _common import APP  # noqa: F401
import input_guard


class InputGuardTests(unittest.TestCase):
    def test_removes_invisible_and_control_chars(self):
        raw = "  樱花​‮下的⁠少女\x00  "
        text, info = input_guard.clean_text(raw, 2000)
        self.assertEqual(text, "樱花下的少女")
        self.assertEqual(info["removed"], 4)
        self.assertFalse(info["truncated"])

    def test_keeps_chinese_and_emoji(self):
        text, info = input_guard.clean_text("银发少女 🌸👩‍👩‍👧", 2000)
        self.assertEqual(text, "银发少女 🌸👩‍👩‍👧")
        self.assertEqual(info["removed"], 0)

    def test_truncates_to_limit(self):
        text, info = input_guard.clean_text("中" * 2100, 2000)
        self.assertEqual(len(text), 2000)
        self.assertTrue(info["truncated"])
        self.assertEqual(info["limit"], 2000)

    def test_empty_after_cleaning(self):
        text, info = input_guard.clean_text("​\x00‮", 2000)
        self.assertEqual(text, "")
        self.assertEqual(info["removed"], 3)

    def test_notice_text(self):
        _text, info = input_guard.clean_text("a​" + "b" * 2100, 2000)
        notice = input_guard.notice_text(info)
        self.assertIn("不可见字符", notice)
        self.assertIn("截断", notice)


if __name__ == "__main__":
    unittest.main()
