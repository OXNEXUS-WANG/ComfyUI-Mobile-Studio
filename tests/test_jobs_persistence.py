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
        self.old_resume = app_core.JOBS_RESUME_FILE
        self.old_load = app_core.runtime_settings.load
        self.td = tempfile.TemporaryDirectory()
        app_core.JOBS_STATE_FILE = str(Path(self.td.name) / "jobs_state.json")
        app_core.JOBS_RESUME_FILE = str(Path(self.td.name) / "jobs_resume.json")
        app_core.JOBS_STATE_META.update({"last_write": 0.0, "loaded": False})
        app_core.RECOVERY_PENDING.clear()
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()

    def tearDown(self):
        app_core.JOBS_STATE_FILE = self.old_file
        app_core.JOBS_RESUME_FILE = self.old_resume
        app_core.runtime_settings.load = self.old_load
        app_core.JOBS_STATE_META.update({"last_write": 0.0, "loaded": False})
        app_core.RECOVERY_PENDING.clear()
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

    def _seed_resume(self, jid):
        app_core.save_job_resume(jid, {
            "created": time.time(), "prompt": "p", "negative": "",
            "width": 512, "height": 512, "steps": 8, "cfg": 1.0,
            "seed": 1, "count": 1, "ckpt": "x.safetensors", "kind": "gen",
            "user_id": "admin",
        })

    def test_queued_job_with_resume_is_requeued(self):
        now = time.time()
        self._seed_resume("q1")
        with app_core.JOBS_LOCK:
            app_core.JOBS["q1"] = {
                "status": "queued", "queued_at": now, "user_id": "admin",
                "kind": "gen", "model": "x.safetensors",
            }
        app_core.persist_jobs(force=True)
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
        app_core.JOBS_STATE_META["loaded"] = False
        app_core.load_jobs_state()
        with app_core.JOBS_LOCK:
            job = dict(app_core.JOBS["q1"])
        self.assertEqual(job["status"], "queued")
        self.assertTrue(job["recovered"])
        self.assertEqual(job["recovery_attempts"], 1)
        self.assertIn("q1", app_core.RECOVERY_PENDING)

    def test_running_without_prompt_can_retry(self):
        now = time.time()
        self._seed_resume("r1")
        with app_core.JOBS_LOCK:
            app_core.JOBS["r1"] = {
                "status": "running", "started": now, "user_id": "admin",
                "kind": "gen", "model": "x.safetensors",
            }
        app_core.persist_jobs(force=True)
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
        app_core.JOBS_STATE_META["loaded"] = False
        app_core.load_jobs_state()
        with app_core.JOBS_LOCK:
            job = dict(app_core.JOBS["r1"])
        self.assertEqual(job["status"], "queued")
        self.assertIn("r1", app_core.RECOVERY_PENDING)

    def test_running_with_prompt_is_not_duplicated(self):
        now = time.time()
        self._seed_resume("r2")
        with app_core.JOBS_LOCK:
            app_core.JOBS["r2"] = {
                "status": "running", "started": now, "user_id": "admin",
                "kind": "gen", "model": "x.safetensors",
                "comfy_prompt_id": "pid-1",
            }
        app_core.persist_jobs(force=True)
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
        app_core.JOBS_STATE_META["loaded"] = False
        app_core.load_jobs_state()
        with app_core.JOBS_LOCK:
            job = dict(app_core.JOBS["r2"])
        self.assertEqual(job["status"], "error")
        self.assertIn("避免重复", job["error"])
        self.assertNotIn("r2", app_core.RECOVERY_PENDING)

    def test_resume_file_can_be_dropped(self):
        self._seed_resume("x1")
        self.assertIn("x1", app_core.load_job_resume_map())
        app_core.drop_job_resume("x1")
        self.assertNotIn("x1", app_core.load_job_resume_map())


if __name__ == "__main__":
    unittest.main()
