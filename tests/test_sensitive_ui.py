# -*- coding: utf-8 -*-
"""敏感词过滤 UI / API 静态接线测试。"""
import unittest
from pathlib import Path

from _common import APP  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


class SensitiveUITests(unittest.TestCase):
    def test_page_has_filter_controls(self):
        text = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        for marker in ("adminSensitiveMode", "adminSensitiveWords",
                       "adminSensitiveSave", "adminSensitiveTest",
                       "adminSensitivePrompt"):
            self.assertIn('id="%s"' % marker, text)
        self.assertIn("function adminSaveSensitive", text)
        self.assertIn("sensitive_warning", text)

    def test_server_has_admin_endpoint(self):
        text = (APP / "web_server.py").read_text(encoding="utf-8")
        self.assertIn('"/api/admin/sensitive"', text)
        self.assertIn("sensitive_filter.check", text)
        self.assertIn("sensitive_prompt", text)

    def test_i18n_has_filter_labels(self):
        text = (APP / "i18n.js").read_text(encoding="utf-8")
        self.assertIn("'提示词过滤': 'Prompt filter'", text)
        self.assertIn("'直接拦截': 'Block'", text)
        self.assertIn("'仅提醒': 'Warn only'", text)


if __name__ == "__main__":
    unittest.main()
