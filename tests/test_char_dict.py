# -*- coding: utf-8 -*-
"""角色/作品词典与自动识别开关回归测试。"""
import unittest

from _common import APP
import prompt_engine


class CharacterDictionaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        cls.server = (APP / "web_server.py").read_text(encoding="utf-8")
        cls.core = (APP / "app_core.py").read_text(encoding="utf-8")

    def test_dictionary_is_expanded(self):
        self.assertGreaterEqual(len(prompt_engine.CHAR_ALIASES), 6900)
        self.assertGreaterEqual(len(prompt_engine.CHAR_SERIES), 3900)
        for zh, tag in (
            ("枫原万叶", "kaedehara_kazuha"),
            ("灶门炭治郎", "kamado_tanjirou"),
            ("费伦", "fern_(sousou_no_frieren)"),
            ("阿米娅", "amiya_(arknights)"),
            ("今汐", "jinhsi_(wuthering_waves)"),
            ("碧蓝航线", "azur_lane"),
            ("鸣潮", "wuthering_waves"),
        ):
            target = (prompt_engine.CHAR_SERIES if zh in ("碧蓝航线", "鸣潮")
                      else prompt_engine.CHAR_ALIASES)
            self.assertEqual(target.get(zh), tag)

    def test_compound_aliases_are_split(self):
        # 「蔚蓝档案、碧蓝档案、蓝色档案」这类合并写法必须能单独命中。
        self.assertEqual(prompt_engine.CHAR_SERIES.get("碧蓝档案"),
                         "blue_archive")
        self.assertEqual(prompt_engine.CHAR_SERIES.get("蓝色档案"),
                         "blue_archive")

    def test_extract_replaces_character_and_series(self):
        text, tags = prompt_engine.extract_char_tags("蔚蓝档案的白子站在海边")
        self.assertNotIn("白子", text)
        self.assertIn("shiroko_(blue_archive)", tags)
        self.assertIn("blue_archive", tags)

    def test_ui_switch_and_server_flag_exist(self):
        for text in ('id="charDict"', "角色/作品自动识别",
                     "char_dict: charDictOn", "mg_char_dict"):
            self.assertIn(text, self.page)
        self.assertIn('data.get("char_dict")', self.server)
        self.assertIn("params.get(\"char_dict\", True)", self.core)


if __name__ == "__main__":
    unittest.main()
