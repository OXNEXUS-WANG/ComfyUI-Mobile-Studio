# -*- coding: utf-8 -*-
import json
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import app_core


class UsersBackupTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.old_file = app_core.USERS_FILE
        self.old_access = app_core.ACCESS_FILE
        self.old_users = app_core.USERS
        app_core.USERS_FILE = str(self.root / "users.json")
        app_core.ACCESS_FILE = str(self.root / "missing_access.json")
        app_core.USERS = {}

    def tearDown(self):
        app_core.USERS_FILE = self.old_file
        app_core.ACCESS_FILE = self.old_access
        app_core.USERS = self.old_users
        self.td.cleanup()

    def test_corrupt_users_recovers_from_backup(self):
        app_core.USERS = {
            "admin": {"id": "admin", "username": "admin",
                      "role": "admin", "enabled": True,
                      "salt": "00" * 16, "pw_hash": "00" * 32},
        }
        self.assertTrue(app_core._save_users_locked())
        self.assertTrue(app_core._save_users_locked())
        self.assertTrue(Path(app_core.USERS_FILE + ".bak").is_file())

        Path(app_core.USERS_FILE).write_text("{broken json", encoding="utf-8")
        app_core.USERS = {}
        app_core.ensure_users()
        self.assertIn("admin", app_core.USERS)
        self.assertEqual(app_core.USERS["admin"]["role"], "admin")

    def test_backup_not_written_from_corrupt_primary(self):
        Path(app_core.USERS_FILE).write_text("{broken json", encoding="utf-8")
        app_core.USERS = {"admin": {"id": "admin", "username": "admin",
                                    "role": "admin", "enabled": True}}
        app_core._save_users_locked()
        self.assertFalse(Path(app_core.USERS_FILE + ".bak").is_file())
        data = json.loads(Path(app_core.USERS_FILE).read_text(encoding="utf-8"))
        self.assertIn("admin", data["users"])


if __name__ == "__main__":
    unittest.main()
