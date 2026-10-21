# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from _common import APP  # noqa: F401
import node_manager


class NodeManagerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.old_nodes = node_manager.CUSTOM_NODES_DIR
        self.old_trash = node_manager.TRASH_DIR
        self.old_uploads = node_manager.UPLOAD_DIR
        node_manager.CUSTOM_NODES_DIR = str(self.root / "custom_nodes")
        node_manager.TRASH_DIR = str(self.root / "_node_trash")
        node_manager.UPLOAD_DIR = str(self.root / "_node_uploads")
        os.makedirs(node_manager.CUSTOM_NODES_DIR, exist_ok=True)

    def tearDown(self):
        node_manager.CUSTOM_NODES_DIR = self.old_nodes
        node_manager.TRASH_DIR = self.old_trash
        node_manager.UPLOAD_DIR = self.old_uploads
        self.td.cleanup()

    def _make_node(self, name="my-node", init=True):
        path = Path(node_manager.CUSTOM_NODES_DIR) / name
        path.mkdir(parents=True, exist_ok=True)
        if init:
            (path / "__init__.py").write_text(
                "NODE_CLASS_MAPPINGS = {}\n", encoding="utf-8")
        (path / "requirements.txt").write_text(
            "definitely_missing_pkg_xyz>=1.0\n", encoding="utf-8")
        return path

    def test_invalid_node_name_is_not_scanned(self):
        info = node_manager.check_node("..")
        self.assertFalse(info.get("exists"))
        info = node_manager.check_node("")
        self.assertFalse(info.get("exists"))

    def test_check_missing_requirement(self):
        self._make_node()
        info = node_manager.check_node("my-node")
        self.assertTrue(info["has_init"])
        self.assertTrue(info["has_mapping"])
        self.assertEqual(info["level"], "warn")
        self.assertIn("definitely_missing_pkg_xyz",
                      info["missing_requirements"])

    def test_import_directory_and_remove(self):
        src = self.root / "source-node"
        src.mkdir()
        (src / "__init__.py").write_text(
            "NODE_CLASS_MAPPINGS = {}\n", encoding="utf-8")
        info = node_manager.import_path(str(src), name="imported")
        self.assertEqual(info["name"], "imported")
        self.assertTrue(os.path.isfile(os.path.join(
            node_manager.CUSTOM_NODES_DIR, "imported", "__init__.py")))
        dest = node_manager.remove_node("imported")
        self.assertTrue(os.path.isdir(dest))
        self.assertFalse(os.path.isdir(os.path.join(
            node_manager.CUSTOM_NODES_DIR, "imported")))

    def test_import_zip(self):
        zip_path = self.root / "node.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("pack/__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
            zf.writestr("pack/README.md", "hello\n")
        info = node_manager.import_zip_file(str(zip_path), name="zipnode")
        self.assertEqual(info["level"], "ok")
        self.assertTrue(os.path.isfile(os.path.join(
            node_manager.CUSTOM_NODES_DIR, "zipnode", "__init__.py")))

    def test_zip_traversal_rejected(self):
        zip_path = self.root / "bad.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../evil.py", "print(1)\n")
        with self.assertRaises(ValueError):
            node_manager.import_zip_file(str(zip_path))

    def test_zip_binary_rejected(self):
        zip_path = self.root / "bad2.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("pack/__init__.py", "")
            zf.writestr("pack/evil.exe", b"MZ")
        with self.assertRaises(ValueError):
            node_manager.import_zip_file(str(zip_path))

    def test_zip_allows_metadata_and_audio(self):
        zip_path = self.root / "assets.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("pack/__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
            zf.writestr("pack/.gitignore", "__pycache__/\n")
            zf.writestr("pack/LICENSE", "MIT\n")
            zf.writestr("pack/assets/notify.mp3", b"ID3")
        info = node_manager.import_zip_file(str(zip_path), name="assets-node")
        self.assertEqual(info["level"], "ok")
        self.assertEqual(info["binary_files"], [])

    def test_check_flags_dangerous_binary(self):
        path = self._make_node("risky-node")
        (path / "evil.dll").write_bytes(b"MZ")
        info = node_manager.check_node("risky-node")
        self.assertEqual(info["level"], "warn")
        self.assertIn("evil.dll", info["binary_files"])

    def test_directory_without_init_rejected(self):
        src = self.root / "empty-node"
        src.mkdir()
        (src / "README.md").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            node_manager.import_path(str(src))

    def test_chunk_upload(self):
        zip_path = self.root / "chunk.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("pack/__init__.py", "NODE_CLASS_MAPPINGS = {}\n")
        data = zip_path.read_bytes()
        start = node_manager.upload_start("chunk.zip", len(data))
        uid = start["upload_id"]
        half = len(data) // 2
        node_manager.upload_chunk(uid, 0, data[:half])
        node_manager.upload_chunk(uid, half, data[half:])
        info = node_manager.upload_finish(uid)
        self.assertEqual(info["name"], "chunk")
        self.assertTrue(os.path.isdir(os.path.join(
            node_manager.CUSTOM_NODES_DIR, "chunk")))

    def test_check_all_summary(self):
        self._make_node("n1")
        self._make_node("n2")
        result = node_manager.check_all()
        self.assertEqual(result["summary"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
