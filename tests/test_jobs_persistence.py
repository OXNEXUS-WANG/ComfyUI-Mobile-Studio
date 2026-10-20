# -*- coding: utf-8 -*-
import json
import tempfile
import time
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import app_core


class JobsPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.old_file = app_core.JOBS_STATE_FILE
        self.td = tempfile.TemporaryDirectory()
        app_core.JOBS_STATE_FILE = str(Path(self.td.name) / "jobs_state.json")
        app_core.JOBS_STATE_META.update({"last_write": 0.0, "loaded": False})
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()

    def tearDown(self):
        app_core.JOBS_STATE_FILE = self.old_file
        app_core.JOBS_STATE_META.update({"last_write": 0.0, "loaded": False})
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
        self.td.cleanup()

    def test_round_trip_hides_prompt_and_recovers_interrupted(self):
        now = time.time()
        with app_core.JOBS_LOCK:
            app_core.JOBS.update({
                "queued1": {
                    "status": "queued", "queued_at": now, "user_id": "admin",
                    "kind": "gen", "model": "x.safetensors",
                    "prompt": "SECRET PROMPT", "input_refs": {"image": "a.png"},
                },
                "run1": {
                    "status": "running", "started": now, "user_id": "admin",
                    "kind": "gen", "model": "x.safetensors",
                    "prompt": "SECRET PROMPT",
                },
                "done1": {
                    "status": "done", "started": now - 10, "elapsed": 9,
                    "user_id": "admin", "kind": "gen",
                    "model": "x.safetensors",
                    "image": "admin/x/a.png", "images": ["admin/x/a.png"],
                    "prompt": "SECRET PROMPT",
                },
            })
        app_core.persist_jobs(force=True)
        raw = Path(app_core.JOBS_STATE_FILE).read_text(encoding="utf-8")
        self.assertNotIn("SECRET PROMPT", raw)
        self.assertNotIn("input_refs", raw)
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
        app_core.JOBS_STATE_META["loaded"] = False
        app_core.load_jobs_state()
        with app_core.JOBS_LOCK:
            jobs = {k: dict(v) for k, v in app_core.JOBS.items()}
        self.assertEqual(jobs["done1"]["status"], "done")
        self.assertEqual(jobs["done1"]["images"], ["admin/x/a.png"])
        for jid in ("queued1", "run1"):
            self.assertEqual(jobs[jid]["status"], "error")
            self.assertIn("服务重启", jobs[jid]["error"])
            self.assertTrue(jobs[jid]["recovered"])

    def test_corrupt_file_is_ignored(self):
        Path(app_core.JOBS_STATE_FILE).write_text("{not json", encoding="utf-8")
        app_core.JOBS_STATE_META["loaded"] = False
        app_core.load_jobs_state()  # 不应抛异常
        with app_core.JOBS_LOCK:
            self.assertEqual(app_core.JOBS, {})


if __name__ == "__main__":
    unittest.main()
