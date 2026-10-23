# -*- coding: utf-8 -*-
"""完整使用手册回归：内容、版本和发布包收录。"""
import unittest

from _common import ROOT


class ManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manual_path = ROOT / "MANUAL.md"
        cls.manual = cls.manual_path.read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.install = (ROOT / "installer" / "install.ps1").read_text(
            encoding="utf-8")
        cls.bundle = (ROOT / "tools" / "offline_bundle.py").read_text(
            encoding="utf-8")

    def test_manual_exists_and_has_core_sections(self):
        self.assertTrue(self.manual_path.is_file())
        for text in (
            "# CometInk 彗墨 · 使用手册",
            "## 1. 这是什么",
            "## 5. 安装与第一次启动",
            "## 7. 出图：从提示词到成品",
            "## 9. 任务、队列与算力节点",
            "## 10. 多账号、权限与配额",
            "## 11. LoRA 训练",
            "## 13. 3D 接口星图",
            "## 16. 安全设计",
            "## 18. 常见问题排查",
            "## 19. 已知限制",
        ):
            self.assertIn(text, self.manual)

    def test_manual_matches_current_version_and_brand(self):
        self.assertIn("v1.3.10", self.manual)
        self.assertIn("CometInk", self.manual)
        self.assertNotIn("Nexus", self.manual)
        self.assertIn("[MANUAL.md](MANUAL.md)", self.readme)

    def test_manual_is_shipped(self):
        self.assertIn('"MANUAL.md"', self.install)
        self.assertIn('"MANUAL.md"', self.bundle)


if __name__ == "__main__":
    unittest.main()
