# -*- coding: utf-8 -*-
import copy
import os
import tempfile
import time
import unittest
from collections import deque

from _common import APP  # noqa: F401
import app_core
import queue_control


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.old_sched = copy.deepcopy(app_core.SCHEDULER)
        self.old_jobs = dict(app_core.JOBS)
        self.old_refresh = app_core._sched_refresh_slots_locked
        self.old_persist = app_core.persist_jobs
        self.old_is_admin = app_core.is_admin
        self.old_get_user = app_core.get_user
        self.td = tempfile.TemporaryDirectory()
        self.old_qfile = queue_control.SETTINGS_FILE
        self.old_qcache = dict(queue_control._CACHE)
        queue_control.SETTINGS_FILE = os.path.join(
            self.td.name, "queue_control.json")
        queue_control._CACHE.update({"mtime": 0.0, "data": None})
        app_core._sched_refresh_slots_locked = lambda *a, **k: None
        app_core.persist_jobs = lambda *a, **k: None
        app_core.is_admin = lambda user: True
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
        with app_core.SCHED_LOCK:
            app_core.SCHEDULER.clear()
            app_core.SCHEDULER.update({
                "slots": {
                    "local": {"id": "local", "kind": "local", "name": "本机",
                              "active": "", "available": False, "last_used": 0,
                              "policy": {}},
                    "r1": {"id": "r1", "kind": "remote", "name": "节点1",
                           "active": "", "available": True, "last_used": 0,
                           "policy": {"id": "r1", "accepting": True,
                                      "trusted": True, "allowed_users": [],
                                      "models": {}, "caps": {}}},
                    "r2": {"id": "r2", "kind": "remote", "name": "节点2",
                           "active": "", "available": True, "last_used": 0,
                           "policy": {"id": "r2", "accepting": True,
                                      "trusted": True, "allowed_users": [],
                                      "models": {}, "caps": {}}},
                },
                "queues": {}, "last_served": {}, "serve_seq": 0,
                "events": {}, "seq": 0, "active": "",
            })
            for i, uid in enumerate(("u_a", "u_b", "u_c"), 1):
                app_core.JOBS["j%d" % i] = {
                    "status": "queued", "user_id": uid, "kind": "gen",
                    "remote_ok": True, "model": "x", "requirements": [],
                    "count": 1, "pixels": 100,
                }
                app_core.SCHEDULER["queues"][uid] = deque(["j%d" % i])

    def tearDown(self):
        app_core._sched_refresh_slots_locked = self.old_refresh
        app_core.persist_jobs = self.old_persist
        app_core.is_admin = self.old_is_admin
        app_core.get_user = self.old_get_user
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
            app_core.JOBS.update(self.old_jobs)
        with app_core.SCHED_LOCK:
            app_core.SCHEDULER.clear()
            app_core.SCHEDULER.update(self.old_sched)
        queue_control.SETTINGS_FILE = self.old_qfile
        queue_control._CACHE.update(self.old_qcache)
        self.td.cleanup()

    def test_two_remote_slots_and_fair_queue(self):
        with app_core.SCHED_LOCK:
            for jid in ("j1", "j2", "j3"):
                app_core.SCHEDULER["seq"] += 1
                app_core.JOBS[jid]["queue_seq"] = app_core.SCHEDULER["seq"]
            app_core._sched_dispatch_locked(local_ok=False)
            running = [j for j, job in app_core.JOBS.items()
                       if job.get("status") == "running"]
            self.assertEqual(len(running), 2)
            # 两个不同账号先各占一个槽，第三个继续排队
            self.assertEqual(app_core.JOBS["j3"]["status"], "queued")
            first = running[0]
            app_core.scheduler_release(first)
            self.assertEqual(app_core.JOBS["j3"]["status"], "running")

    def test_local_slot_is_strictly_single(self):
        with app_core.SCHED_LOCK:
            app_core.SCHEDULER["slots"] = {
                "local": {
                    "id": "local", "kind": "local", "name": "本机",
                    "active": "", "available": True, "last_used": 0,
                    "policy": {},
                },
            }
            app_core.SCHEDULER["queues"].clear()
            app_core.SCHEDULER["served_cost"] = {}
            for i, jid in enumerate(("j1", "j2", "j3"), 1):
                app_core.JOBS[jid]["remote_ok"] = False
                app_core.SCHEDULER["seq"] += 1
                app_core.JOBS[jid]["queue_seq"] = app_core.SCHEDULER["seq"]
                app_core.SCHEDULER["queues"].setdefault(
                    app_core.JOBS[jid]["user_id"], deque()).append(jid)
            app_core._sched_dispatch_locked(local_ok=True)
            running = [j for j, job in app_core.JOBS.items()
                       if job.get("status") == "running"]
            self.assertEqual(len(running), 1)
            self.assertEqual(app_core.SCHEDULER["slots"]["local"]["active"],
                             running[0])

    def test_same_worker_gets_only_one_job(self):
        with app_core.SCHED_LOCK:
            app_core.SCHEDULER["slots"].pop("r2", None)
            app_core.SCHEDULER["seq"] = 2
            app_core.SCHEDULER["queues"]["u_a"] = deque(["j1"])
            app_core.SCHEDULER["queues"]["u_b"] = deque(["j2"])
            app_core._sched_dispatch_locked(local_ok=False)
            running = [j for j, job in app_core.JOBS.items()
                       if job.get("status") == "running"]
            self.assertEqual(len(running), 1)
            self.assertEqual(app_core.SCHEDULER["slots"]["r1"]["active"], running[0])
            self.assertEqual(app_core.JOBS["j2"]["status"], "queued")

    def test_single_account_cap(self):
        app_core.is_admin = lambda user: False
        app_core.get_user = lambda uid: {"id": uid, "role": "user"}
        with app_core.SCHED_LOCK:
            app_core.JOBS["j1"]["user_id"] = "u_a"
            app_core.JOBS["j2"]["user_id"] = "u_a"
            app_core.JOBS["j3"]["user_id"] = "u_a"
            app_core.SCHEDULER["queues"].clear()
            app_core.SCHEDULER["queues"]["u_a"] = deque(["j1", "j2", "j3"])
            for sid in ("r1", "r2"):
                app_core.SCHEDULER["slots"][sid]["policy"]["allowed_users"] = ["u_a"]
            app_core.SCHEDULER["seq"] = 3
            app_core._sched_dispatch_locked(local_ok=False)
            # max_concurrent 默认 1：只放行一个，其余排队
            running = [j for j, job in app_core.JOBS.items()
                       if job.get("status") == "running"]
            self.assertEqual(len(running), 1)


    def _one_slot(self):
        with app_core.SCHED_LOCK:
            app_core.SCHEDULER["slots"].pop("r2", None)
            app_core.SCHEDULER["slots"]["r1"]["available"] = True
            app_core.SCHEDULER["queues"].clear()
            app_core.SCHEDULER["served_cost"] = {}
            for jid in ("j1", "j2", "j3"):
                app_core.SCHEDULER["seq"] += 1
                app_core.JOBS[jid]["queue_seq"] = app_core.SCHEDULER["seq"]
            app_core.SCHEDULER["queues"]["u_a"] = deque(["j1", "j3"])
            app_core.SCHEDULER["queues"]["u_b"] = deque(["j2"])

    def test_weighted_cost_fairness(self):
        self._one_slot()
        app_core.JOBS["j1"]["eta"] = 180
        app_core.JOBS["j2"]["eta"] = 30
        app_core.JOBS["j3"]["eta"] = 180
        with app_core.SCHED_LOCK:
            app_core._sched_dispatch_locked(local_ok=False)
        self.assertEqual(app_core.JOBS["j1"]["status"], "running")
        app_core.scheduler_release("j1")
        # u_a 已消耗 180 秒，先轮到只消耗 30 秒的 u_b
        self.assertEqual(app_core.JOBS["j2"]["status"], "running")
        app_core.scheduler_release("j2")
        self.assertEqual(app_core.JOBS["j3"]["status"], "running")

    def test_priority_boost(self):
        self._one_slot()
        with app_core.SCHED_LOCK:
            app_core.JOBS["j1"]["priority"] = 0
            app_core.JOBS["j2"]["priority"] = 10
            app_core._sched_dispatch_locked(local_ok=False)
        # 交互任务 j2 虽然提交更晚，仍排在挂机任务 j1 前面
        self.assertEqual(app_core.JOBS["j2"]["status"], "running")
        self.assertEqual(app_core.JOBS["j1"]["status"], "queued")

    def test_queue_estimate_fields(self):
        self._one_slot()
        app_core.JOBS["j1"]["eta"] = 60
        app_core.JOBS["j2"]["eta"] = 30
        info1 = app_core.scheduler_job_info("j1")
        info2 = app_core.scheduler_job_info("j2")
        self.assertEqual(info1["queue_position"], 1)
        self.assertEqual(info1["queue_state"], "queued")
        self.assertAlmostEqual(info1["queue_eta"], 0, delta=2)
        self.assertGreaterEqual(info1["queue_finish_in"], 55)
        self.assertEqual(info2["queue_position"], 2)
        self.assertGreaterEqual(info2["queue_eta"], 55)
        self.assertGreaterEqual(info2["queue_finish_in"], 85)
        self.assertIn("queue_eta_min", info2)
        self.assertIn("queue_eta_max", info2)

    def test_queue_state_paused(self):
        self._one_slot()
        queue_control.set_paused(True, "测试")
        info = app_core.scheduler_job_info("j1")
        self.assertEqual(info["queue_state"], "paused")
        queue_control.set_paused(False)

    def test_queue_max_wait_expires(self):
        self._one_slot()
        app_core.JOBS["j1"]["queued_at"] = time.time() - 10
        queue_control.set_max_wait(1)
        old = (app_core.persist_jobs, app_core.activity, app_core.audit,
               app_core.cleanup_stage, app_core.scheduler_kick,
               app_core.monitor_center.note_job)
        app_core.persist_jobs = lambda *a, **k: None
        app_core.activity = lambda *a, **k: None
        app_core.audit = lambda *a, **k: None
        app_core.cleanup_stage = lambda *a, **k: None
        app_core.scheduler_kick = lambda *a, **k: None
        app_core.monitor_center.note_job = lambda *a, **k: None
        try:
            app_core.queue_watchdog_tick()
        finally:
            (app_core.persist_jobs, app_core.activity, app_core.audit,
             app_core.cleanup_stage, app_core.scheduler_kick,
             app_core.monitor_center.note_job) = old
        self.assertEqual(app_core.JOBS["j1"]["status"], "error")
        self.assertIn("排队超时", app_core.JOBS["j1"]["error"])
        self.assertNotIn("j1", list(app_core.SCHEDULER["queues"].get("u_a") or ()))

    def test_paused_user_is_skipped(self):
        self._one_slot()
        queue_control.set_user_paused("u_a", True, "测试", by="admin")
        with app_core.SCHED_LOCK:
            app_core._sched_dispatch_locked(local_ok=False)
        self.assertEqual(app_core.JOBS["j2"]["status"], "running")
        self.assertEqual(app_core.JOBS["j1"]["status"], "queued")


if __name__ == "__main__":
    unittest.main()
