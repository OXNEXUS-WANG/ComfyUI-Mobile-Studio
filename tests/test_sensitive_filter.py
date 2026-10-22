# -*- coding: utf-8 -*-
"""提示词敏感词过滤：归一化、范围、模式和持久化。"""
import os
import tempfile
import unittest

from _common import APP  # noqa: F401

import sensitive_filter as sf


class SensitiveFilterTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old = sf.SETTINGS_FILE
        sf.SETTINGS_FILE = os.path.join(self.td.name, "sensitive_filter.json")
        sf._RULES.update(key=None, rules=[])

    def tearDown(self):
        sf.SETTINGS_FILE = self.old
        sf._RULES.update(key=None, rules=[])
        self.td.cleanup()

    def _save(self, **kw):
        data = {"mode": "block", "scope": {"prompt": True,
                                           "negative": True,
                                           "caption": False},
                "words": []}
        data.update(kw)
        return sf.save(data)

    def test_default_is_off(self):
        data = sf.load()
        self.assertEqual(data["mode"], "off")
        self.assertEqual(data["words"], [])
        self.assertFalse(sf.check("blood")["hit"])

    def test_chinese_english_and_normalization(self):
        self._save(words=["敏感词", "blood"])
        for text in ("这是敏感词", "ＢＬＯＯＤ", "blo​od",
                     "b l o o d", "blood!"):
            self.assertTrue(sf.check(text)["hit"], text)
        self.assertFalse(sf.check("classic")["hit"])
        self.assertFalse(sf.check("bloody")["hit"])

    def test_scope_negative_and_caption(self):
        self._save(words=["badword"], scope={"prompt": True,
                                             "negative": False,
                                             "caption": False})
        self.assertFalse(sf.check("ok", "badword")["hit"])
        self.assertFalse(sf.check_caption("badword")["hit"])
        self._save(words=["badword"], scope={"prompt": False,
                                             "negative": True,
                                             "caption": True})
        self.assertFalse(sf.check("badword", "")["hit"])
        self.assertTrue(sf.check("ok", "badword")["hit"])
        self.assertTrue(sf.check_caption("badword")["hit"])

    def test_warn_and_block_modes(self):
        self._save(mode="warn", words=["badword"])
        result = sf.check("badword")
        self.assertTrue(result["hit"])
        self.assertEqual(result["mode"], "warn")
        self._save(mode="block", words=["badword"])
        self.assertEqual(sf.check("badword")["mode"], "block")

    def test_words_are_cleaned_and_deduped(self):
        data = self._save(words="bad\nbad\n aaaa\n" + "x" * 100)
        self.assertEqual(data["words"], ["bad", "aaaa", "x" * sf.MAX_WORD_LEN])
        self.assertEqual(len({sf.normalize_text(x) for x in data["words"]}), 3)

    def test_public_settings_hides_words(self):
        self._save(words=["secret-word"])
        public = sf.public_settings(admin=False)
        self.assertNotIn("words", public)
        self.assertEqual(public["count"], 1)
        admin = sf.public_settings(admin=True)
        self.assertEqual(admin["words"], ["secret-word"])

    def test_test_text_returns_ids_but_check_does_not(self):
        self._save(words=["badword", "敏感词"])
        test = sf.test_text("badword 和敏感词")
        self.assertTrue(test["hit"])
        self.assertEqual(test["ids"], ["w1", "w2"])
        self.assertEqual(test["terms"], ["badword", "敏感词"])
        check = sf.check("badword 和敏感词")
        self.assertNotIn("terms", check)
        self.assertNotIn("badword", str(check))


if __name__ == "__main__":
    unittest.main()
