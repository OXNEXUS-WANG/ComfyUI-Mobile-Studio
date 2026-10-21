# -*- coding: utf-8 -*-
"""离线 U 盘打包与迁移测试。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import offline_bundle


def _write(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


class OfflineBundleTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.src = self.root / "install"
        self.bundle = self.root / "bundle"
        self.target = self.root / "target"
        _write(self.src / "app" / "app_core.py", b"app")
        _write(self.src / "app" / "webapp_templates" / "page.html", b"<html>")
        _write(self.src / "app" / "training_manager.py", b"trainer-code")
        _write(self.src / "app" / "users.json", b'{"admin":"secret"}')
        _write(self.src / "app" / "trainings.json", b'{"projects":{}}')
        _write(self.src / "app" / "training_settings.json", b"{}")
        _write(self.src / "app" / "loras.json", b"{}")
        _write(self.src / "app" / "trainer" / "pysite" / "x.py", b"dep")
        _write(self.src / "app" / "trainings" / "u" / "t" /
               "dataset" / "a.txt", b"caption")
        _write(self.src / "worker" / "worker_agent.py", b"worker")
        _write(self.src / "一键启动.bat", b"@echo off")
        _write(self.src / "EDITION", b"share")
        _write(self.src / "users.json", b'{"admin":"secret"}')
        _write(self.src / "ComfyUI" / "models" / "checkpoints" /
               "m.safetensors", b"model")
        _write(self.src / "ComfyUI" / "main.py", b"main")
        _write(self.src / "ComfyUI" / "output" / "x.png", b"output")
        _write(self.src / "ComfyUI" / "input" / "y.png", b"input")
        _write(self.src / "ComfyUI" / "user" / "settings.json", b"{}")
        _write(self.src / "ComfyUI" / "custom_nodes" / "demo" / "node.py",
               b"node")
        _write(self.src / "python_embeded" / "python.exe", b"python")

    def tearDown(self):
        self.td.cleanup()

    def test_models_bundle_and_migrate(self):
        manifest = offline_bundle.create_bundle(
            str(self.src), str(self.bundle), include_models=True,
            include_runtime=False)
        self.assertTrue(manifest["include_models"])
        self.assertFalse(manifest["include_runtime"])
        for name in ("bundle_manifest.json", "一键迁移到新机器.bat",
                     "migrate_offline.py", "offline_bundle.py"):
            self.assertTrue((self.bundle / name).is_file(), name)
        payload = self.bundle / "payload"
        self.assertTrue((payload / "app_core.py").is_file())
        self.assertTrue((payload / "training_manager.py").is_file())
        self.assertFalse((payload / "users.json").exists())
        self.assertFalse((payload / "trainings.json").exists())
        self.assertFalse((payload / "training_settings.json").exists())
        self.assertFalse((payload / "loras.json").exists())
        self.assertFalse((payload / "trainer").exists())
        self.assertFalse((payload / "trainings").exists())
        self.assertTrue((payload / "ComfyUI" / "models" / "checkpoints" /
                         "m.safetensors").is_file())
        self.assertTrue((payload / "ComfyUI" / "custom_nodes" / "demo" /
                         "node.py").is_file())
        self.assertFalse((payload / "users.json").exists())
        self.assertFalse((payload / "ComfyUI" / "output").exists())
        self.assertFalse((payload / "python_embeded").exists())

        (self.target / "ComfyUI" / "models").mkdir(parents=True)
        _write(self.target / "app_core.py", b"old")
        result = offline_bundle.migrate_bundle(
            str(self.bundle), str(self.target))
        self.assertGreater(result["files"], 0)
        self.assertEqual((self.target / "app_core.py").read_bytes(), b"app")
        self.assertTrue((self.target / "ComfyUI" / "models" / "checkpoints" /
                         "m.safetensors").is_file())
        self.assertTrue((self.target / "ComfyUI" / "custom_nodes" / "demo" /
                         "node.py").is_file())
        self.assertFalse((self.target / "users.json").exists())

    def test_runtime_bundle_and_protected_skips(self):
        manifest = offline_bundle.create_bundle(
            str(self.src), str(self.bundle), include_models=True,
            include_runtime=True)
        self.assertTrue(manifest["include_runtime"])
        payload = self.bundle / "payload"
        self.assertTrue((payload / "ComfyUI" / "main.py").is_file())
        self.assertTrue((payload / "python_embeded" / "python.exe").is_file())
        self.assertFalse((payload / "ComfyUI" / "output").exists())
        self.assertFalse((payload / "ComfyUI" / "user").exists())
        # 即使有人往包里塞了运行期文件，迁移也必须跳过
        _write(payload / "users.json", b"secret")
        _write(payload / "trainings.json", b'{"projects":{}}')
        _write(payload / "generated" / "a.png", b"image")
        _write(payload / "trainer" / "pysite" / "x.py", b"dep")
        _write(payload / "trainings" / "u" / "t" / "a.txt", b"caption")
        _write(payload / "ComfyUI" / "output" / "z.png", b"output")
        result = offline_bundle.migrate_bundle(
            str(self.bundle), str(self.target))
        self.assertTrue(result["runtime"])
        self.assertFalse((self.target / "users.json").exists())
        self.assertFalse((self.target / "trainings.json").exists())
        self.assertFalse((self.target / "generated").exists())
        self.assertFalse((self.target / "trainer").exists())
        self.assertFalse((self.target / "trainings").exists())
        self.assertFalse((self.target / "ComfyUI" / "output").exists())
        self.assertTrue((self.target / "python_embeded" / "python.exe").is_file())

    def test_models_only_requires_comfy(self):
        offline_bundle.create_bundle(
            str(self.src), str(self.bundle), include_models=True,
            include_runtime=False)
        with self.assertRaises(ValueError):
            offline_bundle.migrate_bundle(str(self.bundle), str(self.target))

    def test_models_already_downloaded(self):
        payload_models = self.bundle / "payload" / "ComfyUI" / "models" / \
            "checkpoints"
        _write(payload_models / "downloaded.safetensors", b"downloaded")
        manifest = offline_bundle.create_bundle(
            str(self.src), str(self.bundle), include_models=True,
            include_runtime=False, models_already=True)
        self.assertTrue((payload_models / "downloaded.safetensors").is_file())
        self.assertTrue((self.bundle / "payload" / "app_core.py").is_file())
        self.assertEqual(manifest["source_edition"], "share")

    def test_bundle_inside_source_rejected(self):
        with self.assertRaises(ValueError):
            offline_bundle.create_bundle(
                str(self.src), str(self.src / "usb"),
                include_models=True, include_runtime=False)


if __name__ == "__main__":
    unittest.main()
