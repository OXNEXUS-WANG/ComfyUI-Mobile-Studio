# -*- coding: utf-8 -*-
"""首次安装免责声明：静态回归测试。"""
import unittest

from _common import ROOT


class InstallerDisclaimerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ps = (ROOT / "installer" / "install.ps1").read_text(
            encoding="utf-8")
        cls.disclaimer = (ROOT / "DISCLAIMER.md").read_text(encoding="utf-8")
        cls.build = (ROOT / "build_release.ps1").read_text(encoding="utf-8")
        gitignore_path = ROOT / ".gitignore"
        cls.gitignore = (gitignore_path.read_text(encoding="utf-8")
                         if gitignore_path.is_file() else "")
        cls.offline = (ROOT / "tools" / "offline_bundle.py").read_text(
            encoding="utf-8")

    def test_prominent_dialog_and_required_checkbox_exist(self):
        for text in (
            "function Show-Disclaimer",
            "function Confirm-Disclaimer",
            "function Write-DisclaimerMarker",
            "New-Object System.Windows.Forms.Form",
            "New-Object System.Windows.Forms.RichTextBox",
            "New-Object System.Windows.Forms.CheckBox",
            "我已阅读并理解上述免责声明",
            "同意并继续",
            "退出安装",
            "$accept.Enabled = $false",
            "$script:DlgAccept.Enabled = [bool]$script:DlgAgree.Checked",
            "[System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea",
            "[System.Windows.Forms.AutoScaleMode]::None",
            "($ch - 270)",
            "($ch - 64)",
        ):
            self.assertIn(text, self.ps)

    def test_disclaimer_is_gated_before_any_install_action(self):
        gate = self.ps.index("Confirm-Disclaimer $InstallDir")
        # 停止旧服务、建目录、下载、写账号都必须在同意之后。
        for later in (
            "Resolve-TargetProcesses",
            'Step "3" "准备目录"',
            "Copy-AppFiles",
            "Set-AdminPassword",
        ):
            self.assertGreater(self.ps.index(later, gate), gate)

    def test_unattended_install_must_explicitly_accept(self):
        self.assertIn("[switch]$AcceptDisclaimer", self.ps)
        self.assertIn("if ($AcceptDisclaimer)", self.ps)
        self.assertIn("-AcceptDisclaimer", self.ps)
        self.assertIn("首次安装需要阅读并同意免责声明", self.ps)
        self.assertIn("无人值守安装请显式添加 -AcceptDisclaimer", self.ps)
        # -Yes / -NoDialog 只能关闭交互，不能代替同意。
        self.assertIn("if (-not $script:Dialogs)", self.ps)

    def test_acceptance_marker_is_recorded_but_never_published(self):
        self.assertIn("disclaimer_accepted.json", self.ps)
        self.assertIn('Write-DisclaimerMarker $Dir "interactive"', self.ps)
        self.assertIn('Write-DisclaimerMarker $Dir "command_line"', self.ps)
        # 安装完成后也把完整文本复制到安装目录，便于随时查阅。
        self.assertIn('"VERSION", "VERSION_LOCK.md", "DISCLAIMER.md"', self.ps)
        self.assertIn("disclaimer_accepted.json", self.build)
        if self.gitignore:
            self.assertIn("disclaimer_accepted.json", self.gitignore)
        self.assertIn("disclaimer_accepted.json", self.offline)
        self.assertIn('"DISCLAIMER.md"', self.offline)

    def test_disclaimer_text_covers_key_legal_topics(self):
        for text in (
            "按“现状”",
            "合法合规使用",
            "生成内容与责任",
            "模型、LoRA、插件与第三方组件",
            "训练数据与 LoRA",
            "商用授权范围",
            "网络边界与公网暴露风险",
            "数据、隐私与备份",
            "责任限制",
            "English summary",
        ):
            self.assertIn(text, self.disclaimer)

    def test_public_internet_exposure_clause_is_explicit(self):
        for text in (
            "仅为本机、家庭或办公室局域网",
            "端口映射",
            "内网穿透",
            "反向代理",
            "云服务器",
            "公网 IPv6",
            "0.0.0.0",
            "无论因何种原因",
            "由部署者、运营者和使用者自行承担全部责任",
            "法律允许的最大范围内",
        ):
            self.assertIn(text, self.disclaimer)
        self.assertIn('$DisclaimerVersion = "1.2"', self.ps)
        # 接受记录不应包含密码或授权码。
        marker_fn = self.ps.split(
            "function Write-DisclaimerMarker")[1].split(
            "function Confirm-Disclaimer")[0].lower()
        self.assertNotIn("password", marker_fn)
        self.assertNotIn("license", marker_fn)


if __name__ == "__main__":
    unittest.main()
