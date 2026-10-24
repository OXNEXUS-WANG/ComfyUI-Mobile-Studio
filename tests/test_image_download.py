# -*- coding: utf-8 -*-
"""电脑端图库“下载 / 保存”必须触发附件下载，而不是只打开新标签页。"""
import unittest

from _common import APP


class ImageDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = (APP / "web_server.py").read_text(encoding="utf-8")
        cls.page = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        cls.i18n = (APP / "i18n.js").read_text(encoding="utf-8")

    def test_img_route_supports_attachment_download(self):
        self.assertIn('query.get("download")', self.web)
        self.assertIn("download_name=os.path.basename(fp)", self.web)

    def test_desktop_save_button_triggers_download(self):
        self.assertIn("?download=1", self.page)
        self.assertIn("function saveUrl", self.page)
        self.assertIn("await saveUrl", self.page)
        self.assertIn("a.download = name", self.page)
        self.assertIn("图片另存为", self.page)
        self.assertIn("下载 / 保存", self.page)
        self.assertIn("'下载 / 保存': 'Download / Save'", self.i18n)


if __name__ == "__main__":
    unittest.main()
