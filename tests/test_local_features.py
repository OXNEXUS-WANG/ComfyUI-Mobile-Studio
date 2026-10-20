# -*- coding: utf-8 -*-
"""本地翻译模型、游客账号和系统还原点的单元测试。"""
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _common import APP  # noqa: F401
import app_core
import local_llm
import system_state


class _MockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        if self.path.endswith("/api/chat"):
            out = {"message": {"content": "silver hair, red eyes, 1girl"}}
        else:
            out = {"choices": [{"message": {
                "content": "a girl with silver hair and red eyes"}}]}
        raw = json.dumps(out).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


class LocalLlmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def test_ollama_and_openai_translate(self):
        base = "http://127.0.0.1:%d" % self.port
        for provider in ("ollama", "openai"):
            cfg = dict(local_llm.DEFAULT_CONFIG)
            cfg.update({"enabled": True, "provider": provider,
                        "base_url": base, "model": "tiny"})
            out, err = local_llm.translate("一个银发红眼的女孩", cfg)
            self.assertEqual(err, "")
            self.assertIn("silver", out)

    def test_public_address_is_rejected(self):
        with self.assertRaises(ValueError):
            local_llm.validate({
                "enabled": True, "provider": "ollama",
                "base_url": "http://8.8.8.8:11434", "model": "tiny",
            })

    def test_non_chinese_returns_unchanged(self):
        out, err = local_llm.translate("1girl, silver hair",
                                       {"enabled": False})
        self.assertEqual((out, err), ("1girl, silver hair", ""))

    def test_config_round_trip_and_secret_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            old = local_llm.CONFIG_FILE
            local_llm.CONFIG_FILE = str(Path(td) / "local_llm.json")
            try:
                cfg = local_llm.save({
                    "enabled": True, "provider": "ollama",
                    "base_url": "http://127.0.0.1:%d" % self.port,
                    "model": "tiny", "api_key": "secret",
                })
                self.assertEqual(cfg["model"], "tiny")
                public = local_llm.public_config(local_llm.load(force=True))
                self.assertTrue(public["api_key_set"])
                self.assertNotIn("api_key", public)
                self.assertNotIn("secret", json.dumps(public))
            finally:
                local_llm.CONFIG_FILE = old
                local_llm.load(force=True)


class GuestTests(unittest.TestCase):
    def test_guest_expiry_and_public_fields(self):
        now = time.time()
        user = {"id": "u_g", "username": "guest_x", "guest": True,
                "enabled": True, "expires_at": now - 1,
                "limits": app_core.guest_limits()}
        self.assertTrue(app_core.user_expired(user, now))
        self.assertFalse(app_core.user_is_active(user, now))
        pub = app_core.public_user(user)
        self.assertTrue(pub["expired"])
        self.assertEqual(pub["guest"], True)
        self.assertNotIn("pw_hash", pub)

    def test_guest_default_limits(self):
        limits = app_core.guest_limits()
        self.assertFalse(limits["features"]["video"])
        self.assertFalse(limits["features"]["upscale"])
        self.assertFalse(limits["features"]["auto"])
        self.assertTrue(limits["features"]["txt2img"])
        self.assertEqual(limits["max_concurrent"], 1)

    def test_create_and_expire_guest(self):
        old_users = app_core.USERS
        old_file = app_core.USERS_FILE
        old_drop = app_core.drop_user_sessions
        old_presence = app_core.drop_presence
        old_stop = app_core.stop_user_jobs
        old_pause = app_core.lan_share.pause_owned_workers
        td = tempfile.TemporaryDirectory()
        try:
            app_core.USERS_FILE = str(Path(td.name) / "users.json")
            app_core.USERS = {}
            app_core.drop_user_sessions = lambda uid: None
            app_core.drop_presence = lambda uid: None
            app_core.stop_user_jobs = lambda uid, reason="": 0
            app_core.lan_share.pause_owned_workers = lambda uid, by="": None
            admin = app_core.create_user("admin2", "password1",
                                         role="admin")
            app_core.USERS[admin["id"]] = admin
            res = app_core.create_guest(admin, 1)
            self.assertTrue(res["password"])
            guest = app_core.find_user(res["user"]["username"])
            self.assertTrue(guest.get("guest"))
            self.assertTrue(guest.get("expires_at") > time.time())
            guest["expires_at"] = time.time() - 1
            expired = app_core.expire_guests()
            self.assertTrue(any(x[0] == guest["id"] for x in expired))
            self.assertFalse(app_core.get_user(guest["id"])["enabled"])
        finally:
            app_core.USERS = old_users
            app_core.USERS_FILE = old_file
            app_core.drop_user_sessions = old_drop
            app_core.drop_presence = old_presence
            app_core.stop_user_jobs = old_stop
            app_core.lan_share.pause_owned_workers = old_pause
            td.cleanup()


class SystemResetTests(unittest.TestCase):
    def test_reset_keeps_admin_and_drops_guests(self):
        old = {
            "ROOT": app_core.ROOT,
            "USERS": app_core.USERS,
            "USERS_FILE": app_core.USERS_FILE,
            "USAGE": app_core.USAGE,
            "USAGE_FILE": app_core.USAGE_FILE,
            "JOBS": app_core.JOBS,
            "JOBS_STATE_FILE": app_core.JOBS_STATE_FILE,
            "reset_workers": app_core.lan_share.reset_workers,
            "scheduler_kick": app_core.scheduler_kick,
            "local_save": app_core.local_llm.save,
            "stop_all": app_core.stop_all_jobs,
        }
        td = tempfile.TemporaryDirectory()
        try:
            root = Path(td.name)
            app_core.ROOT = str(root)
            app_core.USERS_FILE = str(root / "users.json")
            app_core.USAGE_FILE = str(root / "usage.json")
            app_core.JOBS_STATE_FILE = str(root / "jobs_state.json")
            app_core.USERS = {}
            app_core.USAGE = {"version": 1, "users": {}}
            with app_core.JOBS_LOCK:
                app_core.JOBS.clear()
            admin = app_core.create_user("resetadmin", "password1",
                                         role="admin")
            guest = app_core.create_user("guest1", "password2",
                                         role="user")
            guest["guest"] = True
            guest["expires_at"] = time.time() + 3600
            app_core.USERS[guest["id"]] = guest
            app_core.lan_share.reset_workers = lambda: {}
            app_core.scheduler_kick = lambda: None
            app_core.local_llm.save = lambda patch: {}
            app_core.stop_all_jobs = lambda reason="": 0
            app_core.system_reset(app_core.get_user(admin["id"]))
            self.assertEqual(set(app_core.USERS.keys()), {admin["id"]})
            self.assertFalse(app_core.USERS[admin["id"]].get("guest"))
            self.assertFalse(app_core.USERS[admin["id"]].get("expires_at"))
            self.assertTrue(list((root / "_restore_points").glob("snap-*.zip")))
        finally:
            app_core.ROOT = old["ROOT"]
            app_core.USERS = old["USERS"]
            app_core.USERS_FILE = old["USERS_FILE"]
            app_core.USAGE = old["USAGE"]
            app_core.USAGE_FILE = old["USAGE_FILE"]
            app_core.JOBS = old["JOBS"]
            app_core.JOBS_STATE_FILE = old["JOBS_STATE_FILE"]
            app_core.lan_share.reset_workers = old["reset_workers"]
            app_core.scheduler_kick = old["scheduler_kick"]
            app_core.local_llm.save = old["local_save"]
            app_core.stop_all_jobs = old["stop_all"]
            td.cleanup()


class SnapshotTests(unittest.TestCase):
    def test_snapshot_restore_and_safety_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "users.json").write_text('{"users":{"a":1}}',
                                             encoding="utf-8")
            (root / "usage.json").write_text('{"users":{}}',
                                             encoding="utf-8")
            snap = system_state.create_snapshot(str(root), "test")
            self.assertTrue((root / "_restore_points" / snap["name"]).is_file())
            (root / "users.json").write_text('{"users":{"b":2}}',
                                             encoding="utf-8")
            res = system_state.restore_snapshot(str(root), snap["name"])
            self.assertIn("users.json", res["restored"])
            self.assertEqual((root / "users.json").read_text(encoding="utf-8"),
                             '{"users":{"a":1}}')
            safety = Path(res["safety"]["name"])
            self.assertTrue((root / "_restore_points" / safety).is_file())
            self.assertTrue(system_state.list_snapshots(str(root)))

    def test_bad_snapshot_name_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                system_state.restore_snapshot(td, "../users.json")


class TimelineTests(unittest.TestCase):
    def setUp(self):
        with app_core.JOBS_LOCK:
            self.old_jobs = dict(app_core.JOBS)
            app_core.JOBS.clear()
            app_core.JOBS["j_test"] = {
                "status": "done", "kind": "gen", "mode": "txt",
                "model": "D:/models/m.safetensors",
                "queued_at": 1000.0, "dispatched_at": 1002.0,
                "started": 1002.0, "submitted_at": 1003.0,
                "first_progress_at": 1005.0, "finished_at": 1020.0,
                "saved_at": 1021.0, "elapsed": 18.0,
                "worker_name": "", "worker_kind": "local", "attempt": 1,
                "retry_count": 0, "images": ["a.png"],
                "user_id": "u_owner", "username": "owner",
            }

    def tearDown(self):
        with app_core.JOBS_LOCK:
            app_core.JOBS.clear()
            app_core.JOBS.update(self.old_jobs)

    def test_timeline_stages_and_permissions(self):
        admin = {"id": "admin", "role": "admin", "enabled": True}
        owner = {"id": "u_owner", "role": "user", "enabled": True}
        other = {"id": "u_other", "role": "user", "enabled": True}
        data = app_core.job_timeline("j_test", admin)
        self.assertIsNotNone(data)
        self.assertEqual([s["key"] for s in data["stages"]],
                         ["queue", "dispatch", "sample", "save"])
        self.assertEqual(data["model"], "m.safetensors")
        self.assertIsNotNone(app_core.job_timeline("j_test", owner))
        self.assertIsNone(app_core.job_timeline("j_test", other))
        self.assertIsNone(app_core.job_timeline("missing", admin))

    def test_running_job_has_no_save_stage(self):
        with app_core.JOBS_LOCK:
            app_core.JOBS["j_test"].update({
                "status": "running", "finished_at": 0, "saved_at": 0,
                "images": []})
        data = app_core.job_timeline(
            "j_test", {"id": "admin", "role": "admin", "enabled": True})
        self.assertEqual([s["key"] for s in data["stages"]],
                         ["queue", "dispatch", "sample"])


if __name__ == "__main__":
    unittest.main()
