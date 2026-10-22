# -*- coding: utf-8 -*-
"""越权防护回归测试：团队成员、队列快照、LoRA 删除、改密会话。"""
import copy
import unittest
from collections import deque

from _common import APP, ROOT  # noqa: F401
import app_core


class AuthzHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.web = (APP / "web_server.py").read_text(encoding="utf-8")
        cls.page = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        cls.training = (APP / "training_manager.py").read_text(
            encoding="utf-8")

    def test_team_membership_is_admin_only(self):
        # 普通团队所有者不能把任意账号拉进团队，否则会直接共享对方图库。
        self.assertIn('if action in ("add_member", "remove_member",', self.web)
        self.assertIn("只有管理员可以添加、移除或修改团队成员", self.web)
        self.assertIn("memberManager", self.page)
        self.assertIn("团队成员由管理员添加或移除", self.page)

    def test_normal_user_cannot_delete_lora_with_admin_bypass(self):
        self.assertIn(
            "self.delete_lora(out_name, user, admin=admin)", self.training)
        self.assertNotIn(
            "self.delete_lora(out_name, user, admin=True)", self.training)

    def test_password_change_revokes_other_sessions(self):
        self.assertIn("drop_other_sessions(user.get(\"id\"), sid)", self.web)
        self.assertIn("revoked_sessions", self.web)

    def test_frames_are_blocked(self):
        self.assertIn('send_header("X-Frame-Options", "DENY")', self.web)

    def test_scheduler_snapshot_hides_other_users_jobs(self):
        old_sched = copy.deepcopy(app_core.SCHEDULER)
        old_jobs = dict(app_core.JOBS)
        old_is_admin = app_core.is_admin
        try:
            app_core.is_admin = lambda user: False
            with app_core.SCHED_LOCK:
                app_core.SCHEDULER.clear()
                app_core.SCHEDULER.update({
                    "slots": {},
                    "queues": {"u_a": deque(["j1"]),
                               "u_b": deque(["j2"])},
                    "last_served": {}, "serve_seq": 0,
                    "events": {}, "seq": 2, "active": "",
                })
                app_core.JOBS.clear()
                app_core.JOBS["j1"] = {
                    "status": "queued", "user_id": "u_a", "kind": "gen",
                    "model": "a.safetensors", "count": 1,
                }
                app_core.JOBS["j2"] = {
                    "status": "queued", "user_id": "u_b", "kind": "gen",
                    "model": "b.safetensors", "count": 1,
                }
            snap = app_core.scheduler_snapshot(
                {"id": "u_a", "role": "user", "enabled": True})
            ids = {x.get("job_id") for x in
                   (snap.get("waiting") or []) +
                   (snap.get("running") or [])}
            self.assertIn("j1", ids)
            self.assertNotIn("j2", ids)
            self.assertEqual(snap.get("active"), None)
        finally:
            app_core.is_admin = old_is_admin
            with app_core.SCHED_LOCK:
                app_core.SCHEDULER.clear()
                app_core.SCHEDULER.update(old_sched)
            with app_core.JOBS_LOCK:
                app_core.JOBS.clear()
                app_core.JOBS.update(old_jobs)


if __name__ == "__main__":
    unittest.main()
