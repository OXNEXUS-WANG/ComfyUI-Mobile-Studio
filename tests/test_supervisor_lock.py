# -*- coding: utf-8 -*-
"""--watch 守护进程单实例锁：不允许两个 watcher 互相抢着重启。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import APP
import start_service


class SupervisorLockTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.lock = str(Path(self.td.name) / "supervisor.lock")
        self.old = start_service.SUPERVISOR_LOCK
        start_service.SUPERVISOR_LOCK = self.lock

    def tearDown(self):
        start_service.SUPERVISOR_LOCK = self.old
        self.td.cleanup()

    def test_second_live_watcher_is_rejected(self):
        Path(self.lock).write_text(json.dumps({"pid": 999999}),
                                   encoding="utf-8")
        with mock.patch.object(start_service, "_watcher_pid_alive",
                               return_value=True):
            self.assertFalse(start_service.acquire_supervisor_lock())
        self.assertTrue(Path(self.lock).is_file())

    def test_stale_lock_is_replaced(self):
        Path(self.lock).write_text(json.dumps({"pid": 999999}),
                                   encoding="utf-8")
        with mock.patch.object(start_service, "_watcher_pid_alive",
                               return_value=False):
            self.assertTrue(start_service.acquire_supervisor_lock())
        data = json.loads(Path(self.lock).read_text(encoding="utf-8"))
        self.assertEqual(int(data["pid"]), __import__("os").getpid())
        start_service.release_supervisor_lock()
        self.assertFalse(Path(self.lock).exists())

    def test_watch_is_gated_by_lock(self):
        src = (APP / "start_service.py").read_text(encoding="utf-8")
        self.assertIn("watch = \"--watch\" in sys.argv", src)
        self.assertIn("acquire_supervisor_lock()", src)
        self.assertIn("if watch:", src)


if __name__ == "__main__":
    unittest.main()
