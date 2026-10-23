# -*- coding: utf-8 -*-
"""安装器/启动器的环境冲突处理静态回归测试。"""
import unittest

from _common import APP, ROOT


class InstallerConflictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = ROOT
        cls.ps = (base / "installer" / "install.ps1").read_text(encoding="utf-8")
        cls.dl = (base / "installer" / "download_models.py").read_text(
            encoding="utf-8")
        cls.boot = (base / "installer" / "bootstrap.py").read_text(
            encoding="utf-8")
        cls.start = (APP / "start_service.py").read_text(
            encoding="utf-8")
        cls.web = (APP / "web_server.py").read_text(
            encoding="utf-8")
        cls.bat = (APP / "一键启动.bat").read_text(encoding="utf-8")

    def test_port_and_process_conflicts_are_detected(self):
        for name in ("Get-PortOwner", "Resolve-PortConflicts",
                     "Resolve-TargetProcesses", "Test-OwnProcess",
                     "Stop-OwnProcess"):
            self.assertIn(name, self.ps)
        self.assertIn("8188, 8800", self.ps)
        self.assertIn("Test-OwnProcess $owner", self.ps)

    def test_failure_shows_problem_dialog_and_writes_report(self):
        for text in ("Show-ProblemDialog", "Write-ProblemReport",
                     "install_problem.txt", "Get-ProblemAdvice",
                     "Show-ProblemDialog $err"):
            self.assertIn(text, self.ps)
        self.assertIn("MB_TOPMOST", self.start)

    def test_directory_and_python_env_are_adapted(self):
        for name in ("Resolve-DirectoryConflict", "New-AltInstallDir",
                     "Test-WritableDir", "Clear-PythonEnv"):
            self.assertIn(name, self.ps)
        for var in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE"):
            self.assertIn(var, self.ps)
        self.assertIn("SkipModels = $true", self.ps)
        self.assertIn('set "PYTHONHOME="', self.bat)
        self.assertIn("PYTHONNOUSERSITE", self.start)

    def test_installer_markers_do_not_block_retry(self):
        # 安装器自己写的免责声明/报告/写探针不能把“空目录”误判成非空。
        for text in ("Get-InstallDirUserItems", "disclaimer_accepted.json",
                     "install_report.txt", ".mgs_write_*.tmp"):
            self.assertIn(text, self.ps)
        self.assertEqual(
            self.ps.count("Get-InstallDirUserItems $InstallDir"), 2)

    def test_local_comfy_zip_and_old_portable_upgrade(self):
        # 国内镜像的便携包可能较旧：允许用 -ComfyZip 本地包，并在低于
        # 最低兼容线时自动更新源码，避免装完缺节点。
        for text in ("[string]$ComfyZip", "ComfyZip 指定的文件不存在",
                     "$ComfyMin = [string]$Lock.comfyui.compatible_min",
                     "[version]$ver -lt [version]$ComfyMin",
                     "Update-ComfyUI $true"):
            self.assertIn(text, self.ps)

    def test_existing_nodes_are_backed_up_not_deleted(self):
        self.assertIn("Backup-ExistingNode", self.ps)
        self.assertIn("Backup-ExistingNode $dest $name", self.ps)
        self.assertIn("_node_trash", self.ps)

    def test_mismatched_models_are_backed_up(self):
        self.assertIn("backup_mismatched", self.dl)
        self.assertIn(".bak-", self.dl)
        self.assertIn("文件可能正被 ComfyUI 占用", self.dl)

    def test_certificate_is_renewed_when_invalid(self):
        self.assertIn("_cert_ok", self.boot)
        self.assertIn("_backup_file", self.boot)
        self.assertIn("旧证书已备份", self.boot)

    def test_single_instance_lock_exists(self):
        for text in ("acquire_instance_lock", "release_instance_lock",
                     "instance.lock", "O_CREAT | os.O_EXCL"):
            self.assertIn(text, self.web)
        self.assertIn("atexit.register(release_instance_lock)", self.web)

    def test_launcher_distinguishes_our_ports_from_foreign_services(self):
        for name in ("check_port_conflicts", "web_is_ours",
                     "comfy_is_comfy", "port_owner", "owner_is_ours",
                     "show_message"):
            self.assertIn(name, self.start)
        self.assertIn("端口 8800 被其他程序占用", self.start)
        self.assertIn("端口 8188 被其他程序占用", self.start)


if __name__ == "__main__":
    unittest.main()
