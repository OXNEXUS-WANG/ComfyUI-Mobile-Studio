# -*- coding: utf-8 -*-
"""安装器在中文 Windows PowerShell 5.1 下的编码与首装提示回归测试。"""
import unittest

from _common import ROOT


class InstallerEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = (ROOT / "installer" / "install.ps1")
        cls.text = cls.ps.read_text(encoding="utf-8-sig")

    def test_powershell_scripts_have_utf8_bom(self):
        # Windows PowerShell 5.1 在 ACP=936 时把无 BOM 的 UTF-8 当 GB2312
        # 解析，中文字符串会直接破坏语法，首装第一步就失败。
        for rel in ("installer/install.ps1", "build_release.ps1"):
            data = (ROOT / rel).read_bytes()
            self.assertEqual(data[:3], b"\xef\xbb\xbf", rel)

    def test_firewall_and_modelscope_first_install_hints(self):
        # 手机访问必须放行 8800；普通用户双击修复脚本即可触发 UAC。
        self.assertIn("Start-Process -FilePath '%~f0' -Verb RunAs", self.text)
        self.assertIn("手机访问必须放行 TCP 8800", self.text)
        self.assertIn("手机访问还需要放行防火墙 TCP 8800", self.text)
        # 模型优先 ModelScope；DryRun 不再因为 hf-mirror 不可用而误报。
        self.assertIn('$MsModel = "https://modelscope.cn/models"', self.text)
        self.assertIn("ModelScope，优先", self.text)
        self.assertIn("ModelScope 已可用", self.text)
        self.assertIn('$src = "ModelScope"', self.text)


if __name__ == "__main__":
    unittest.main()
