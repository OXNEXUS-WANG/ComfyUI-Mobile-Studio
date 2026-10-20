# -*- coding: utf-8 -*-
import os
import tempfile
import time
import unittest

from _common import APP  # noqa: F401
import queue_control


class QueueControlTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_file = queue_control.SETTINGS_FILE
        self.old_cache = dict(queue_control._CACHE)
        queue_control.SETTINGS_FILE = os.path.join(
            self.td.name, "queue_control.json")
        queue_control._CACHE.update({"mtime": 0.0, "data": None})

    def tearDown(self):
        queue_control.SETTINGS_FILE = self.old_file
        queue_control._CACHE.update(self.old_cache)
        self.td.cleanup()

    def test_defaults_and_pause(self):
        data = queue_control.load()
        self.assertFalse(data["paused"])
        self.assertEqual(data["max_wait_seconds"], 0)
        queue_control.set_paused(True, "维护", by="admin")
        self.assertTrue(queue_control.dispatch_blocked())
        self.assertTrue(queue_control.load()["paused"])
        queue_control.set_paused(False)
        self.assertFalse(queue_control.dispatch_blocked())

    def test_user_pause_and_boost(self):
        queue_control.set_user_paused("u_1", True, "测试", by="admin")
        self.assertTrue(queue_control.user_paused("u_1"))
        self.assertFalse(queue_control.user_paused("u_2"))
        queue_control.set_priority("u_1", 30)
        self.assertEqual(queue_control.user_boost("u_1"), 30)
        queue_control.set_priority("u_1", 0)
        self.assertEqual(queue_control.user_boost("u_1"), 0)
        queue_control.set_user_paused("u_1", False)
        self.assertFalse(queue_control.user_paused("u_1"))

    def test_maintenance_window(self):
        queue_control.set_maintenance(True, "00:00", "23:59", [])
        self.assertTrue(queue_control.maintenance_active(
            time.struct_time((2026, 10, 20, 12, 0, 0, 1, 293, 0))))
        queue_control.set_maintenance(True, "02:00", "04:00", [])
        self.assertFalse(queue_control.maintenance_active(
            time.struct_time((2026, 10, 20, 12, 0, 0, 1, 293, 0))))
        self.assertTrue(queue_control.maintenance_active(
            time.struct_time((2026, 10, 20, 3, 0, 0, 1, 293, 0))))

    def test_overnight_window(self):
        queue_control.set_maintenance(True, "23:00", "02:00", [])
        self.assertTrue(queue_control.maintenance_active(
            time.struct_time((2026, 10, 20, 23, 30, 0, 1, 293, 0))))
        self.assertTrue(queue_control.maintenance_active(
            time.struct_time((2026, 10, 20, 1, 30, 0, 1, 293, 0))))
        self.assertFalse(queue_control.maintenance_active(
            time.struct_time((2026, 10, 20, 12, 0, 0, 1, 293, 0))))

    def test_max_wait_clamped(self):
        queue_control.set_max_wait(-5)
        self.assertEqual(queue_control.load()["max_wait_seconds"], 0)
        queue_control.set_max_wait(999999999)
        self.assertEqual(queue_control.load()["max_wait_seconds"],
                         7 * 24 * 3600)


if __name__ == "__main__":
    unittest.main()
