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

    def test_share_build_excludes_commercial_launcher(self):
        # 商用分支重命名入口时要移除一次，分享分支也必须移除一次。
        self.assertEqual(
            self.build.count('Remove-Staged "安装_商业版.bat"'), 2)
        share = self.build.split('} else {', 1)[1]
        self.assertIn('Remove-Staged "安装_商业版.bat"', share)

    def test_packages_do_not_ship_dev_manual(self):
        # 旧版 docs/使用说明.md 含开发者本机路径，不能进客户包；
        # 安装时用 MANUAL.md 生成根目录的使用说明。
        self.assertIn('Remove-Staged "docs\\使用说明.md"', self.build)
        self.assertIn('Copy-Item $manual (Join-Path $InstallDir "使用说明.md")',
                      self.install)

    def test_release_build_excludes_runtime_prompt_data(self):
        # 提示词历史在浏览器 localStorage；服务端运行数据必须永远不进发布包。
        for name in ("users.json", "sessions.json", "usage.json",
                     "team_prompts.json", "jobs_state.json",
                     "jobs_resume.json", "hardware.json",
                     "supervisor.lock", "local_llm.json", "monitor.json"):
            self.assertIn('"%s"' % name, self.build)
        for name in ("generated", "web_uploads", "logs"):
            self.assertIn('"%s"' % name, self.build)

    def test_package_readme_keeps_title_after_image_trim(self):
        # 发布包会去掉 docs/media 首屏图，但 README 不能因此从空行开始。
        self.assertIn("$pkgHeader", self.build)
        self.assertIn('"# CometInk 彗墨 · ComfyUI 手机出图"', self.build)

    def test_shipped_files_have_no_developer_paths(self):
        files = [
            "installer/install.ps1", "README.md", "MANUAL.md",
            "INSTALL.en.md", "安装说明.txt", "worker/deploy_node.py",
            "tools/offline_bundle.py", "docs/备份与恢复.md",
            "docs/手机HTTPS访问.md",
        ]
        for rel in files:
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("D:\\AI", text, rel)
            self.assertNotIn("C:\\Users\\", text, rel)
        self.assertIn("D:\\CometInk", self.install)

    def test_commercial_build_excludes_maintainer_files(self):
        for text in ('Remove-Staged "build_release.ps1"',
                     'Remove-Staged ".gitignore"',
                     'Remove-Staged ".gitattributes"',
                     'Remove-Staged "tools\\make_cometink_icon.py"'):
            self.assertIn(text, self.build)

    def test_installer_uses_cometink_shortcut_and_icon(self):
        self.assertIn('"CometInk Studio.lnk"', self.install)
        self.assertIn('"cometink.ico"', self.install)
        self.assertNotIn('$shortcutName = "Nexus Studio.lnk"', self.install)
        # 只保留迁移时删除旧品牌快捷方式的引用。
        self.assertIn('$legacy = Join-Path $desktop "Nexus Studio.lnk"', self.install)
        self.assertIn('"CometInk 8800"', self.install)
        self.assertIn('$AppVersion = "1.3.21"', self.install)
        self.assertIn('$DisclaimerVersion = "1.2"', self.install)

    def test_offline_bundle_carries_pwa_icons(self):
        self.assertIn("cometink-icon-", self.bundle)
        self.assertIn('".ico"', self.bundle)

    def test_version_and_disclaimer_are_updated(self):
        self.assertEqual(self.version, "1.3.21")
        self.assertIn("CometInk 彗墨", self.disclaimer)
        self.assertIn("免责声明版本：1.2", self.disclaimer)


if __name__ == "__main__":
    unittest.main()
