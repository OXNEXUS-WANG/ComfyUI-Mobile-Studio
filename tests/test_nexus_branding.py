# -*- coding: utf-8 -*-
"""Nexus 品牌、图标和发布包命名回归测试。"""
import hashlib
import unittest

from PIL import Image

from _common import APP, ROOT  # noqa: F401
import app_core


class NexusBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "app" / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        cls.login = (ROOT / "app" / "webapp_templates" / "login.html").read_text(
            encoding="utf-8")
        cls.license = (ROOT / "app" / "webapp_templates" / "license.html").read_text(
            encoding="utf-8")
        cls.core = (ROOT / "app" / "app_core.py").read_text(encoding="utf-8")
        cls.build = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        cls.install = (ROOT / "installer" / "install.ps1").read_text(
            encoding="utf-8")
        cls.bundle = (ROOT / "tools" / "offline_bundle.py").read_text(
            encoding="utf-8")

    def test_icon_assets_are_valid(self):
        for size in (1024, 512, 192, 180):
            p = ROOT / "app" / ("nexus-icon-%d.png" % size)
            self.assertTrue(p.is_file(), p)
            with Image.open(p) as im:
                self.assertEqual(im.size, (size, size))
                self.assertEqual(im.mode, "RGBA")
        ico = ROOT / "app" / "nexus.ico"
        self.assertTrue(ico.is_file())
        with Image.open(ico) as im:
            sizes = set(im.ico.sizes())
        for size in ((16, 16), (32, 32), (48, 48), (256, 256)):
            self.assertIn(size, sizes)
        # 旧的快捷方式图标也换成同一套品牌。
        self.assertEqual(
            hashlib.sha256((ROOT / "app" / "nexus.ico").read_bytes()).hexdigest(),
            hashlib.sha256((ROOT / "app" / "comfyui.ico").read_bytes()).hexdigest())

    def test_pages_manifest_and_app_icon_use_nexus(self):
        self.assertIn('"name": "Nexus"', self.core)
        self.assertIn('"short_name": "Nexus"', self.core)
        self.assertIn("<title>Nexus</title>", self.page)
        self.assertIn("<h1>Nexus", self.page)
        self.assertIn('rel="icon" type="image/png" href="/icon-192.png"',
                      self.page)
        self.assertIn("<title>需要登录 · Nexus</title>", self.login)
        self.assertIn("<h1>Nexus</h1>", self.login)
        self.assertIn("<title>Nexus · 商用版激活</title>", self.license)
        p = app_core.app_icon(192)
        self.assertTrue(p and p.endswith("nexus-icon-192.png"), p)

    def test_release_package_is_named_nexus(self):
        self.assertIn('"Nexus-v" + $Version', self.build)
        self.assertNotIn('"ComfyUI-Mobile-Studio-v" + $Version', self.build)

    def test_installer_uses_nexus_shortcut_and_icon(self):
        self.assertIn('"Nexus Studio.lnk"', self.install)
        self.assertIn('"nexus.ico"', self.install)
        self.assertNotIn('"手机出图.lnk"', self.install)
        self.assertIn('"Nexus 8800"', self.install)

    def test_offline_bundle_carries_pwa_icons(self):
        self.assertIn("nexus-icon-", self.bundle)
        self.assertIn('".ico"', self.bundle)


if __name__ == "__main__":
    unittest.main()
