# -*- coding: utf-8 -*-
"""英文界面文件选择框不再显示浏览器中文“选择文件”。"""
import unittest
from pathlib import Path

from _common import APP  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


class FilePickerI18nTests(unittest.TestCase):
    def test_license_page_uses_custom_file_picker(self):
        text = (APP / "webapp_templates" / "license.html").read_text(
            encoding="utf-8")
        self.assertIn('id="fileLabel"', text)
        self.assertIn('id="fileName"', text)
        self.assertIn("chooseFile: '选择授权文件'", text)
        self.assertIn("chooseFile: 'Choose license file'", text)
        self.assertIn('.file{display:none}', text)

    def test_main_page_hides_native_file_inputs(self):
        text = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        self.assertIn("function initFilePickers()", text)
        self.assertIn("native-file-hidden", text)
        self.assertIn("file-pick-btn", text)
        self.assertIn("btn.textContent = \"选择文件\"", text)

    def test_i18n_has_file_picker_keys(self):
        text = (APP / "i18n.js").read_text(encoding="utf-8")
        self.assertIn("'选择文件': 'Choose file'", text)
        self.assertIn("'未选择文件': 'No file selected'", text)


if __name__ == "__main__":
    unittest.main()
