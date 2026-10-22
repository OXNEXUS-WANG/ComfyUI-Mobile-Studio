# -*- coding: utf-8 -*-
"""CometInk 彗墨品牌、图标和发布包命名回归测试。"""
import hashlib
import unittest

from PIL import Image

from _common import APP, ROOT  # noqa: F401
import app_core


class CometInkBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        cls.login = (APP / "webapp_templates" / "login.html").read_text(
            encoding="utf-8")
        cls.license = (APP / "webapp_templates" / "license.html").read_text(
            encoding="utf-8")
        cls.core = (APP / "app_core.py").read_text(encoding="utf-8")
        cls.i18n = (APP / "i18n.js").read_text(encoding="utf-8")
        cls.star = (APP / "宇宙接口图.html").read_text(encoding="utf-8")
        cls.build = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        cls.install = (ROOT / "installer" / "install.ps1").read_text(
            encoding="utf-8")
        cls.bundle = (ROOT / "tools" / "offline_bundle.py").read_text(
            encoding="utf-8")
        cls.disclaimer = (ROOT / "DISCLAIMER.md").read_text(encoding="utf-8")
        cls.version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

    def test_icon_assets_are_valid(self):
        for size in (1024, 512, 192, 180):
            p = APP / ("cometink-icon-%d.png" % size)
            self.assertTrue(p.is_file(), p)
            with Image.open(p) as im:
                self.assertEqual(im.size, (size, size))
                self.assertEqual(im.mode, "RGBA")
        ico = APP / "cometink.ico"
        self.assertTrue(ico.is_file())
        with Image.open(ico) as im:
            sizes = set(im.ico.sizes())
        for size in ((16, 16), (32, 32), (48, 48), (256, 256)):
            self.assertIn(size, sizes)
        # 旧的快捷方式图标也换成同一套品牌。
        self.assertEqual(
            hashlib.sha256((APP / "cometink.ico").read_bytes()).hexdigest(),
            hashlib.sha256((APP / "comfyui.ico").read_bytes()).hexdigest())

    def test_pages_manifest_and_app_icon_use_cometink(self):
        self.assertIn('"name": "CometInk"', self.core)
        self.assertIn('"short_name": "CometInk"', self.core)
        self.assertIn("<title>CometInk 彗墨</title>", self.page)
        self.assertIn("<h1>CometInk", self.page)
        self.assertIn("data-no-i18n>彗墨</em>", self.page)
        self.assertIn('rel="icon" type="image/png" href="/icon-192.png"',
                      self.page)
        self.assertIn("<title>需要登录 · CometInk</title>", self.login)
        self.assertIn("<h1>CometInk", self.login)
        self.assertIn("<title>CometInk 彗墨 · 商用版激活</title>", self.license)
        p = app_core.app_icon(192)
        self.assertTrue(p and p.endswith("cometink-icon-192.png"), p)

    def test_i18n_and_star_map_use_cometink(self):
        self.assertIn("'手机出图': 'CometInk'", self.i18n)
        self.assertIn("'彗墨': 'CometInk'", self.i18n)
        self.assertNotIn("Sign in · Nexus", self.i18n)
        self.assertIn("<title>COMETINK · 接口星图</title>", self.star)
        self.assertIn("COMETINK CORE", self.star)
        # 旧 localStorage 键保留，升级后不丢星球位置/贴图。
        self.assertIn("nexusPosV1", self.star)

    def test_release_package_is_named_cometink(self):
        self.assertIn('"CometInk-v" + $Version', self.build)
        self.assertNotIn('"Nexus-v" + $Version', self.build)

    def test_installer_uses_cometink_shortcut_and_icon(self):
        self.assertIn('"CometInk Studio.lnk"', self.install)
        self.assertIn('"cometink.ico"', self.install)
        self.assertNotIn('$shortcutName = "Nexus Studio.lnk"', self.install)
        # 只保留迁移时删除旧品牌快捷方式的引用。
        self.assertIn('$legacy = Join-Path $desktop "Nexus Studio.lnk"', self.install)
        self.assertIn('"CometInk 8800"', self.install)
        self.assertIn('$AppVersion = "1.3.6"', self.install)
        self.assertIn('$DisclaimerVersion = "1.2"', self.install)

    def test_offline_bundle_carries_pwa_icons(self):
        self.assertIn("cometink-icon-", self.bundle)
        self.assertIn('".ico"', self.bundle)

    def test_version_and_disclaimer_are_updated(self):
        self.assertEqual(self.version, "1.3.6")
        self.assertIn("CometInk 彗墨", self.disclaimer)
        self.assertIn("免责声明版本：1.2", self.disclaimer)


if __name__ == "__main__":
    unittest.main()
