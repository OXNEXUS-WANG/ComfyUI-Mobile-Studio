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

    def test_guard_defaults_and_clamps(self):
        cfg = runtime_settings.guard_config()
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["gpu_pct"], 88)
        self.assertEqual(cfg["cpu_pct"], 70)
        self.assertEqual(cfg["presence_ttl"], 75)

        runtime_settings.save({
            "guard_enabled": False,
            "guard_gpu_pct": 120,
            "guard_cpu_pct": 1,
            "guard_proc_pct": 9999,
            "guard_enter_seconds": 0,
            "guard_recover_seconds": 99,
            "guard_cooldown_seconds": -5,
            "guard_presence_ttl": 9999,
        })
        cfg = runtime_settings.guard_config()
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["gpu_pct"], 100)
        self.assertEqual(cfg["cpu_pct"], 30)
        self.assertEqual(cfg["proc_pct"], 500)
        self.assertEqual(cfg["enter_seconds"], 2)
        self.assertEqual(cfg["recover_seconds"], 30)
        self.assertEqual(cfg["cooldown_seconds"], 0)
        self.assertEqual(cfg["presence_ttl"], 600)

    def test_corrupt_file_falls_back(self):
        Path(runtime_settings.SETTINGS_FILE).write_text("{oops", encoding="utf-8")
        self.assertTrue(runtime_settings.load()["enabled"])


if __name__ == "__main__":
    unittest.main()
