# -*- coding: utf-8 -*-
"""模型管理：路径导入、分块上传、回收站与安全文件名。"""
import os
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import model_manager


class ModelManagerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.old = {
            "MODELS_ROOT": model_manager.MODELS_ROOT,
            "TRASH_DIR": model_manager.TRASH_DIR,
            "UPLOAD_DIR": model_manager.UPLOAD_DIR,
        }
        model_manager.MODELS_ROOT = str(self.root / "models")
        model_manager.TRASH_DIR = str(self.root / "trash")
        model_manager.UPLOAD_DIR = str(self.root / "uploads")

    def tearDown(self):
        for key, value in self.old.items():
            setattr(model_manager, key, value)
        self.td.cleanup()

    def test_safe_filename(self):
        self.assertEqual(model_manager.safe_filename("../../a.safetensors"),
                         "a.safetensors")
        self.assertEqual(model_manager.safe_filename("a:b?.safetensors"),
                         "b_.safetensors")
        self.assertEqual(model_manager.safe_filename(""), "")

    def test_import_delete_restore_purge(self):
        src = self.root / "download" / "my_model.safetensors"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"abc" * 100)
        info = model_manager.import_path(
            "checkpoints", str(src), move=False)
        self.assertEqual(info["name"], "my_model.safetensors")
        self.assertTrue(src.exists())
        dest = self.root / "models" / "checkpoints" / info["name"]
        self.assertTrue(dest.exists())

        meta = model_manager.remove_model("checkpoints", info["name"])
        self.assertFalse(dest.exists())
        self.assertTrue(any(x["id"] == meta["id"]
                            for x in model_manager.trash_entries()))
        model_manager.restore_model(meta["id"])
        self.assertTrue(dest.exists())
        meta = model_manager.remove_model("checkpoints", info["name"])
        model_manager.purge_model(meta["id"])
        self.assertEqual(model_manager.trash_entries(), [])

    def test_import_move_and_rejects_traversal(self):
        src = self.root / "download" / "m.ckpt"
        src.parent.mkdir(parents=True)
        src.write_bytes(b"x")
        model_manager.import_path("checkpoints", str(src), move=True)
        self.assertFalse(src.exists())
        with self.assertRaises(ValueError):
            model_manager.remove_model("checkpoints", "../m.ckpt")

    def test_chunked_upload(self):
        data = b"0123456789abcdef" * 1000
        start = model_manager.upload_start(
            "loras", "new_lora.safetensors", len(data))
        uid = start["upload_id"]
        offset = 0
        for step in (5000, 10000, len(data)):
            part = data[offset:step]
            res = model_manager.upload_chunk(uid, offset, part)
            self.assertEqual(res["received"], step)
            offset = step
        info = model_manager.upload_finish(uid)
        path = self.root / "models" / "loras" / info["name"]
        self.assertEqual(path.read_bytes(), data)
        with self.assertRaises(ValueError):
            model_manager.upload_start(
                "loras", "new_lora.safetensors", len(data))

    def test_rejects_wrong_category_and_extension(self):
        with self.assertRaises(ValueError):
            model_manager.import_path("bad", "C:/nope.safetensors")
        src = self.root / "x.txt"
        src.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            model_manager.import_path("checkpoints", str(src))


if __name__ == "__main__":
    unittest.main()
