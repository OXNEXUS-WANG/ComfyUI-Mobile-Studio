# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_file = runtime_settings.SETTINGS_FILE
        runtime_settings.SETTINGS_FILE = str(
            Path(self.td.name) / "supervisor.json")

    def tearDown(self):
        runtime_settings.SETTINGS_FILE = self.old_file
        self.td.cleanup()

    def test_defaults_and_clamps(self):
        data = runtime_settings.load()
        self.assertTrue(data["enabled"])
        self.assertTrue(data["auto_restart_comfy"])
        self.assertEqual(data["max_restarts_per_hour"], 6)

        saved = runtime_settings.save({
            "enabled": False,
            "max_restarts_per_hour": 999,
            "check_seconds": 1,
        })
        self.assertFalse(saved["enabled"])
        self.assertEqual(saved["max_restarts_per_hour"], 100)
        self.assertEqual(saved["check_seconds"], 2)
        self.assertEqual(runtime_settings.load()["enabled"], False)

    def test_corrupt_file_falls_back(self):
        Path(runtime_settings.SETTINGS_FILE).write_text("{oops", encoding="utf-8")
        self.assertTrue(runtime_settings.load()["enabled"])


if __name__ == "__main__":
    unittest.main()
