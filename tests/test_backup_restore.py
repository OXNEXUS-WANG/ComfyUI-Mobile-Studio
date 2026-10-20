# -*- coding: utf-8 -*-
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from _common import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import backup  # noqa: E402
import restore  # noqa: E402


class BackupRestoreTests(unittest.TestCase):
    def _make_root(self, base):
        root = Path(base) / "root"
        (root / "generated" / "admin" / "m").mkdir(parents=True)
        (root / "users.json").write_text('{"users":{}}', encoding="utf-8")
        (root / "workers.json").write_text('{"version":1}', encoding="utf-8")
        (root / "generated" / "admin" / "m" / "a.png").write_bytes(b"PNG")
        (root / "generated" / "admin" / "m" / "a.png.json").write_text(
            '{"prompt":"x"}', encoding="utf-8")
        (root / "generated" / ".favorites.json").write_text(
            '["admin/m/a.png"]', encoding="utf-8")
        return root

    def test_backup_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._make_root(td)
            zpath = Path(td) / "b.zip"
            backup.build(root, zpath, include_images=True)
            with zipfile.ZipFile(zpath) as zf:
                names = set(zf.namelist())
                self.assertIn("users.json", names)
                self.assertIn("generated/admin/m/a.png", names)
                manifest = json.loads(zf.read("backup_manifest.json"))
                self.assertEqual(manifest["format"],
                                 "comfyui-mobile-studio-backup")
            dest = Path(td) / "restored"
            dest.mkdir()
            (dest / "users.json").write_text('{"users":{"old":1}}',
                                             encoding="utf-8")
            old = restore.service_running
            restore.service_running = lambda: False
            try:
                rc = restore.restore(zpath, dest, yes=True)
            finally:
                restore.service_running = old
            self.assertEqual(rc, 0)
            self.assertEqual((dest / "users.json").read_text(encoding="utf-8"),
                             '{"users":{}}')
            self.assertEqual((dest / "generated/admin/m/a.png").read_bytes(),
                             b"PNG")
            self.assertTrue(list((dest / "_backups").glob("pre-restore-*.zip")))

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            zpath = Path(td) / "evil.zip"
            with zipfile.ZipFile(zpath, "w") as zf:
                zf.writestr("backup_manifest.json", json.dumps({
                    "format": "comfyui-mobile-studio-backup",
                    "files": [{"path": "../evil.txt", "size": 1}],
                }))
                zf.writestr("../evil.txt", "x")
            with zipfile.ZipFile(zpath) as zf:
                with self.assertRaises(ValueError):
                    restore.validate_zip(zf)


if __name__ == "__main__":
    unittest.main()
