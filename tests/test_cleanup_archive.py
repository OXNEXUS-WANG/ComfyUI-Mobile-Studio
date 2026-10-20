# -*- coding: utf-8 -*-
"""磁盘清理与图库 ZIP 打包测试。"""
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from _common import APP  # noqa: F401
import app_core
import disk_cleanup


def _touch(path, mtime):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * 32)
    os.utime(path, (mtime, mtime))


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.old = {
            "DELIVER_DIR": app_core.DELIVER_DIR,
            "THUMB_DIR": app_core.THUMB_DIR,
            "OUTPUT_DIR": app_core.OUTPUT_DIR,
            "SETTINGS_FILE": disk_cleanup.SETTINGS_FILE,
        }
        app_core.DELIVER_DIR = str(self.root / "generated")
        app_core.THUMB_DIR = str(self.root / "generated" / ".thumbs")
        app_core.OUTPUT_DIR = str(self.root / "output")
        disk_cleanup.SETTINGS_FILE = str(self.root / "cleanup.json")
        with disk_cleanup._LOCK:
            disk_cleanup._CACHE.update({"mtime": 0.0, "settings": None})
        now = time.time()
        self.now = now
        self.old_file = self.root / "generated" / "u_a" / "m" / "old.png"
        self.new_file = self.root / "generated" / "u_a" / "m" / "new.png"
        self.fav_file = self.root / "generated" / "u_a" / "m" / "fav.png"
        _touch(str(self.old_file), now - 40 * 86400)
        _touch(str(self.new_file), now - 1 * 86400)
        _touch(str(self.fav_file), now - 40 * 86400)
        with open(self.root / "generated" / "u_a" / ".favorites.json",
                  "w", encoding="utf-8") as fh:
            json.dump(["u_a/m/fav.png"], fh)

    def tearDown(self):
        for key, value in self.old.items():
            setattr(app_core if key != "SETTINGS_FILE" else disk_cleanup,
                    key, value)
        with disk_cleanup._LOCK:
            disk_cleanup._CACHE.update({"mtime": 0.0, "settings": None})
        self.td.cleanup()

    def test_default_is_off_and_clamped(self):
        cfg = disk_cleanup.load(force=True)
        self.assertFalse(cfg["enabled"])
        cfg = disk_cleanup.save({"target_free_gb": 5, "min_free_gb": 20,
                                 "retention_days": 0})
        self.assertGreaterEqual(cfg["target_free_gb"], cfg["min_free_gb"])
        self.assertEqual(cfg["retention_days"], 1)

    def test_candidates_skip_favorites_and_new_files(self):
        rows = disk_cleanup.gallery_candidates(
            str(self.root / "generated"), 30, 100, True, self.now)
        names = [x["rel"] for x in rows]
        self.assertIn("u_a/m/old.png", names)
        self.assertNotIn("u_a/m/fav.png", names)
        self.assertNotIn("u_a/m/new.png", names)

    def test_manual_cleanup_deletes_only_old(self):
        disk_cleanup.save({"enabled": True, "retention_days": 30,
                           "min_free_gb": 10, "target_free_gb": 100,
                           "max_files_per_run": 100,
                           "include_videos": True,
                           "include_comfy_output": False})
        result = app_core.run_disk_cleanup(
            "manual", free_bytes=5 * 1073741824)
        self.assertEqual(result.get("deleted_images"), 1)
        self.assertTrue(self.new_file.exists())
        self.assertTrue(self.fav_file.exists())
        self.assertFalse(self.old_file.exists())


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.old = {
            "DELIVER_DIR": app_core.DELIVER_DIR,
            "ARCHIVE_DIR": app_core.ARCHIVE_DIR,
        }
        app_core.DELIVER_DIR = str(self.root / "generated")
        app_core.ARCHIVE_DIR = str(self.root / "generated" / ".archives")
        self.a = self.root / "generated" / "u_a" / "m" / "a.png"
        self.b = self.root / "generated" / "u_a" / "m" / "b.png"
        _touch(str(self.a), time.time())
        _touch(str(self.b), time.time())

    def tearDown(self):
        for key, value in self.old.items():
            setattr(app_core, key, value)
        self.td.cleanup()

    def test_zip_and_owner_permissions(self):
        info, err = app_core.make_archive(
            ["u_a/m/a.png", "u_a/m/b.png"],
            {"id": "u_a", "role": "user", "enabled": True})
        self.assertEqual(err, "")
        self.assertEqual(info["count"], 2)
        path, name = app_core.archive_download(
            info["token"], {"id": "u_a", "role": "user"})
        self.assertTrue(path and os.path.isfile(path))
        with zipfile.ZipFile(path) as zf:
            self.assertEqual(sorted(zf.namelist()),
                             ["u_a/m/a.png", "u_a/m/b.png"])
        path, _ = app_core.archive_download(
            info["token"], {"id": "u_b", "role": "user"})
        self.assertIsNone(path)
        path, _ = app_core.archive_download(
            info["token"], {"id": "admin", "role": "admin"})
        self.assertTrue(path)

    def test_archive_rejects_foreign_file(self):
        info, err = app_core.make_archive(
            ["u_a/m/a.png"], {"id": "u_b", "role": "user"})
        self.assertIsNone(info)
        self.assertIn("没有可打包", err)


if __name__ == "__main__":
    unittest.main()
