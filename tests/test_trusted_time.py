# -*- coding: utf-8 -*-
import json
import tempfile
import time
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import trusted_time


class TrustedTimeTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old = {
            "STATE_FILE": trusted_time.STATE_FILE,
            "KEY_FILE": trusted_time.KEY_FILE,
            "LOG_DIR": trusted_time.LOG_DIR,
        }
        trusted_time.STATE_FILE = str(Path(self.td.name) / "time_state.json")
        trusted_time.KEY_FILE = str(Path(self.td.name) / "trusted_time.key")
        trusted_time.LOG_DIR = str(Path(self.td.name) / "logs")
        self._reset()

    def tearDown(self):
        self._reset()
        trusted_time.STATE_FILE = self.old["STATE_FILE"]
        trusted_time.KEY_FILE = self.old["KEY_FILE"]
        trusted_time.LOG_DIR = self.old["LOG_DIR"]
        self.td.cleanup()

    def _reset(self):
        trusted_time._STARTED = False
        trusted_time._LAST_PERSIST = 0.0
        trusted_time._BASE.update({
            "ready": False, "trusted": 0.0, "mono": 0.0, "source": "wall",
            "last_sync": 0.0, "last_seen": 0.0, "rollback_count": 0,
            "last_rollback": 0.0, "error": "",
        })

    def test_initializes_and_persists_state(self):
        before = time.time()
        trusted_time.ensure_started(start_sync=False)
        value = trusted_time.now()
        self.assertGreaterEqual(value, before - 2)
        self.assertTrue(trusted_time.status()["ready"])
        self.assertTrue(Path(trusted_time.STATE_FILE).is_file())
        self.assertTrue(Path(trusted_time.KEY_FILE).is_file())

    def test_tampered_state_is_ignored(self):
        trusted_time.ensure_started(start_sync=False)
        path = Path(trusted_time.STATE_FILE)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["payload"]["last_seen"] = time.time() + 86400
        path.write_text(json.dumps(data), encoding="utf-8")
        self._reset()
        trusted_time.ensure_started(start_sync=False)
        # 被篡改的状态不生效，仍以本机时间/单调时钟为准。
        self.assertLess(trusted_time.now(), time.time() + 3600)

    def test_rollback_is_detected_and_floored(self):
        trusted_time.ensure_started(start_sync=False)
        future = time.time() + 3600
        payload = {
            "version": 1, "last_seen": future,
            "last_mono": time.monotonic(),
            "source": "wall", "last_sync": future,
            "rollback_count": 0, "last_rollback": 0.0,
            "updated": future,
        }
        data = {"payload": payload, "hmac": trusted_time._sign(payload)}
        Path(trusted_time.STATE_FILE).write_text(
            json.dumps(data), encoding="utf-8")
        self._reset()
        trusted_time.ensure_started(start_sync=False)
        st = trusted_time.status()
        self.assertEqual(st["source"], "rollback")
        self.assertGreaterEqual(st["rollback_count"], 1)
        self.assertGreaterEqual(st["trusted"], future - 5)

    def test_not_initialized_falls_back_to_wall_clock(self):
        self.assertAlmostEqual(trusted_time.now(), time.time(), delta=2)


if __name__ == "__main__":
    unittest.main()
