# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
import zipfile

from _common import APP  # noqa: F401
import app_core
import node_manager
import plugin_manager


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    with open(path, "rb") as fh:
        return fh.read()


class PluginManagerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = self.td.name
        self.custom = os.path.join(root, "custom_nodes")
        os.makedirs(self.custom)
        self._old = {
            "PLUGIN_DIR": plugin_manager.PLUGIN_DIR,
            "PACK_DIR": plugin_manager.PACK_DIR,
            "QUARANTINE_DIR": plugin_manager.QUARANTINE_DIR,
            "BACKUP_DIR": plugin_manager.BACKUP_DIR,
            "DISABLED_DIR": plugin_manager.DISABLED_DIR,
            "REGISTRY_PATH": plugin_manager.REGISTRY_PATH,
            "CUSTOM_NODES_DIR": plugin_manager.CUSTOM_NODES_DIR,
            "NM_CUSTOM": node_manager.CUSTOM_NODES_DIR,
            "NM_UPLOAD": node_manager.UPLOAD_DIR,
            "NM_TRASH": node_manager.TRASH_DIR,
        }
        plugin_manager.PLUGIN_DIR = os.path.join(root, "plugins")
        plugin_manager.PACK_DIR = os.path.join(plugin_manager.PLUGIN_DIR, "packs")
        plugin_manager.QUARANTINE_DIR = os.path.join(
            plugin_manager.PLUGIN_DIR, "quarantine")
        plugin_manager.BACKUP_DIR = os.path.join(
            plugin_manager.PLUGIN_DIR, "backups")
        plugin_manager.DISABLED_DIR = os.path.join(
            plugin_manager.PLUGIN_DIR, "disabled")
        plugin_manager.REGISTRY_PATH = os.path.join(
            plugin_manager.PLUGIN_DIR, "registry.json")
        plugin_manager.CUSTOM_NODES_DIR = self.custom
        node_manager.CUSTOM_NODES_DIR = self.custom
        node_manager.UPLOAD_DIR = os.path.join(root, "_uploads")
        node_manager.TRASH_DIR = os.path.join(root, "_trash")
        plugin_manager.ensure_plugins()

    def tearDown(self):
        plugin_manager.PLUGIN_DIR = self._old["PLUGIN_DIR"]
        plugin_manager.PACK_DIR = self._old["PACK_DIR"]
        plugin_manager.QUARANTINE_DIR = self._old["QUARANTINE_DIR"]
        plugin_manager.BACKUP_DIR = self._old["BACKUP_DIR"]
        plugin_manager.DISABLED_DIR = self._old["DISABLED_DIR"]
        plugin_manager.REGISTRY_PATH = self._old["REGISTRY_PATH"]
        plugin_manager.CUSTOM_NODES_DIR = self._old["CUSTOM_NODES_DIR"]
        node_manager.CUSTOM_NODES_DIR = self._old["NM_CUSTOM"]
        node_manager.UPLOAD_DIR = self._old["NM_UPLOAD"]
        node_manager.TRASH_DIR = self._old["NM_TRASH"]
        self.td.cleanup()

    def test_safe_pack_import_and_style_merge(self):
        pack = plugin_manager.import_pack("admin", {
            "schema": 1,
            "name": "国漫风",
            "styles": [{"name": "淡彩", "suffix": "国漫淡彩，低饱和度"}],
            "prompts": [{"name": "雨夜", "text": "雨夜的青石巷"}],
            "presets": [{"name": "快速", "size": "512x512", "steps": 8}],
        })
        self.assertEqual(pack["name"], "国漫风")
        self.assertEqual(pack["presets"][0]["steps"], 8)
        self.assertEqual(plugin_manager.styles_for_user("admin"),
                         {"淡彩": "国漫淡彩，低饱和度"})
        plugin_manager.set_pack_enabled("admin", pack["id"], False)
        self.assertEqual(plugin_manager.styles_for_user("admin"), {})
        plugin_manager.delete_pack("admin", pack["id"])
        self.assertEqual(plugin_manager.list_user_packs("admin"), [])

    def test_pack_rejects_empty_and_bad_schema(self):
        with self.assertRaises(ValueError):
            plugin_manager.import_pack("admin", {"name": "空包"})
        with self.assertRaises(ValueError):
            plugin_manager.import_pack("admin", {
                "schema": 9, "name": "旧包",
                "styles": [{"name": "x", "suffix": "y"}]})

    def test_submit_quarantine_then_approve_disable_rollback(self):
        zpath = os.path.join(self.td.name, "demo.zip")
        blob = make_zip(zpath, {
            "demo/__init__.py": "NODE_CLASS_MAPPINGS = {}\n",
            "demo/requirements.txt": "",
        })
        sub = plugin_manager.submit_node("u_1", "demo.zip", blob)
        self.assertEqual(sub["status"], "pending")
        self.assertFalse(os.path.isdir(os.path.join(self.custom, "demo")))
        node = plugin_manager.approve_submission(
            sub["id"], {"id": "admin"}, force=True, replace=True)
        self.assertEqual(node["status"], "active")
        self.assertTrue(os.path.isdir(os.path.join(self.custom, "demo")))

        # 覆盖安装一次，产生可回滚备份
        zpath2 = os.path.join(self.td.name, "demo2.zip")
        blob2 = make_zip(zpath2, {
            "demo/__init__.py": "NODE_CLASS_MAPPINGS = {'Demo': object}\n",
        })
        sub2 = plugin_manager.submit_node("u_1", "demo2.zip", blob2)
        node2 = plugin_manager.approve_submission(
            sub2["id"], {"id": "admin"}, replace=True)
        self.assertGreaterEqual(node2["backup_count"], 1)
        plugin_manager.disable_node("demo", {"id": "admin"})
        self.assertFalse(os.path.isdir(os.path.join(self.custom, "demo")))
        plugin_manager.enable_node("demo", {"id": "admin"})
        self.assertTrue(os.path.isdir(os.path.join(self.custom, "demo")))
        plugin_manager.rollback_node("demo", {"id": "admin"})
        with open(os.path.join(self.custom, "demo", "__init__.py"),
                  encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "NODE_CLASS_MAPPINGS = {}")
        plugin_manager.remove_managed_node("demo", {"id": "admin"})
        self.assertFalse(os.path.isdir(os.path.join(self.custom, "demo")))

    def test_high_risk_requires_force(self):
        zpath = os.path.join(self.td.name, "danger.zip")
        blob = make_zip(zpath, {
            "danger/__init__.py":
                "import subprocess\nNODE_CLASS_MAPPINGS = {}\n",
        })
        sub = plugin_manager.submit_node("u_1", "danger.zip", blob)
        self.assertEqual(sub["risk_level"], "high")
        with self.assertRaises(ValueError):
            plugin_manager.approve_submission(sub["id"], {"id": "admin"})
        plugin_manager.reject_submission(sub["id"], {"id": "admin"}, "不要")
        self.assertEqual(
            plugin_manager.list_user_submissions("u_1")[0]["status"], "rejected")

    def test_non_node_zip_rejected(self):
        zpath = os.path.join(self.td.name, "plain.zip")
        blob = make_zip(zpath, {"readme.txt": "hello"})
        with self.assertRaises(ValueError):
            plugin_manager.submit_node("u_1", "plain.zip", blob)

    def test_submit_rejects_oversized_unpack(self):
        zpath = os.path.join(self.td.name, "big.zip")
        blob = make_zip(zpath, {
            "big/__init__.py": "NODE_CLASS_MAPPINGS = {}\n",
            "big/data.txt": "x" * 200,
        })
        old = plugin_manager.MAX_SUBMIT_EXTRACT_BYTES
        plugin_manager.MAX_SUBMIT_EXTRACT_BYTES = 20
        try:
            with self.assertRaises(ValueError):
                plugin_manager.submit_node("u_1", "big.zip", blob)
        finally:
            plugin_manager.MAX_SUBMIT_EXTRACT_BYTES = old

    def test_baseline_is_captured(self):
        # setUp 时 custom_nodes 为空；新建一个预装节点后重建注册表
        os.makedirs(os.path.join(self.custom, "preinstalled"))
        os.remove(plugin_manager.REGISTRY_PATH)
        plugin_manager.ensure_plugins()
        with open(plugin_manager.REGISTRY_PATH, encoding="utf-8") as fh:
            reg = json.load(fh)
        self.assertIn("preinstalled", reg["baseline"])

    def test_plugin_feature_defaults(self):
        # 提交只进隔离区，默认允许；真正安装仍需管理员审批。
        self.assertTrue(app_core.DEFAULT_FEATURES["plugin_pack"])
        self.assertTrue(app_core.DEFAULT_FEATURES["plugin_submit"])


if __name__ == "__main__":
    unittest.main()
