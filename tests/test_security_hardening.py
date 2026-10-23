# -*- coding: utf-8 -*-
"""安全加固回归：Origin 校验、登录锁定、上传解码、会话、磁盘阈值。"""
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import APP  # noqa: F401
import app_core
import disk_cleanup
import web_server


class OriginTests(unittest.TestCase):
    def test_same_origin_accepts_host_and_referer(self):
        host = "192.168.137.1:8800"
        self.assertTrue(web_server.same_origin(
            "https://192.168.137.1:8800", "", host))
        self.assertTrue(web_server.same_origin(
            "", "https://192.168.137.1:8800/index", host))
        # 非浏览器客户端（curl/worker）没有这两个头，放行
        self.assertTrue(web_server.same_origin("", "", host))

    def test_same_origin_rejects_cross_site_and_null(self):
        host = "127.0.0.1:8800"
        self.assertFalse(web_server.same_origin(
            "https://evil.example", "", host))
        self.assertFalse(web_server.same_origin(
            "null", "", host))
        self.assertFalse(web_server.same_origin(
            "https://127.0.0.1:9999", "", host))
        self.assertFalse(web_server.same_origin(
            "", "javascript:alert(1)", host))


class LoginLockTests(unittest.TestCase):
    def setUp(self):
        self.old_fails = dict(app_core.LOGIN_FAILS)
        self.old_ip = dict(app_core.LOGIN_IP_FAILS)
        with app_core.LOGIN_FAILS_LOCK:
            app_core.LOGIN_FAILS.clear()
            app_core.LOGIN_IP_FAILS.clear()

    def tearDown(self):
        with app_core.LOGIN_FAILS_LOCK:
            app_core.LOGIN_FAILS.clear()
            app_core.LOGIN_FAILS.update(self.old_fails)
            app_core.LOGIN_IP_FAILS.clear()
            app_core.LOGIN_IP_FAILS.update(self.old_ip)

    def test_account_and_ip_are_locked_together(self):
        ip = "10.0.0.1"
        with mock.patch("app_core.time.time", return_value=1000.0):
            for _ in range(5):
                app_core.note_login_failure("alice", ip)
            self.assertGreaterEqual(
                app_core.login_wait_seconds("alice", ip), 590)
            # 同一个 IP 的另一个账号不能被连坐
            self.assertEqual(app_core.login_wait_seconds("bob", ip), 0)
            self.assertEqual(app_core.login_locked_users().get("alice"), 600)
            self.assertEqual(app_core.unlock_login(username="alice"), 1)
            self.assertEqual(app_core.login_wait_seconds("alice", ip), 0)

    def test_ip_spray_only_gets_short_throttle(self):
        ip = "10.0.0.2"
        with mock.patch("app_core.time.time", return_value=1000.0):
            for i in range(20):
                app_core.note_login_failure("u%d" % i, ip)
            # IP 级 60 秒限流，不是 10 分钟硬锁
            self.assertEqual(app_core.login_wait_seconds("new", ip), 60)
            self.assertEqual(app_core.unlock_login(ip=ip), 20)


class UploadDecodeTests(unittest.TestCase):
    def test_small_png_decodes(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (16, 16), (20, 40, 80)).save(buf, format="PNG")
        im, fmt, w, h = web_server.decode_upload_image(buf.getvalue())
        try:
            self.assertEqual((fmt, w, h), ("PNG", 16, 16))
            self.assertEqual(im.size, (16, 16))
        finally:
            im.close()

    def test_oversized_image_is_rejected_before_load(self):
        from PIL import Image
        buf = io.BytesIO()
        # 7000×6000 = 4200 万像素，超过 4000 万上限
        Image.new("1", (7000, 6000)).save(buf, format="PNG")
        with self.assertRaises(ValueError):
            web_server.decode_upload_image(buf.getvalue())

    def test_non_image_is_rejected(self):
        with self.assertRaises(ValueError):
            web_server.decode_upload_image(b"not an image")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_file = app_core.SESSION_FILE
        app_core.SESSION_FILE = str(Path(self.td.name) / "sessions.json")
        self.old_sessions = dict(app_core.SESSIONS)
        with app_core.SESSIONS_LOCK:
            app_core.SESSIONS.clear()
        self.uid = next(iter(app_core.USERS))

    def tearDown(self):
        app_core.SESSION_FILE = self.old_file
        with app_core.SESSIONS_LOCK:
            app_core.SESSIONS.clear()
            app_core.SESSIONS.update(self.old_sessions)
        self.td.cleanup()

    def test_logout_and_revoke_are_immediate(self):
        tok1 = app_core.new_session(self.uid)
        tok2 = app_core.new_session(self.uid)
        self.assertTrue(app_core.session_valid(tok1))
        app_core.drop_session(tok1)
        self.assertFalse(app_core.session_valid(tok1))
        self.assertTrue(app_core.session_valid(tok2))

        sid2 = app_core.session_sid(tok2)
        tok3 = app_core.new_session(self.uid)
        self.assertTrue(app_core.session_valid(tok3))
        app_core.drop_other_sessions(self.uid, sid2)
        self.assertTrue(app_core.session_valid(tok2))
        self.assertFalse(app_core.session_valid(tok3))

    def test_admin_can_revoke_one_session(self):
        tok = app_core.new_session(self.uid)
        sid = app_core.session_sid(tok)
        self.assertEqual(app_core.drop_session_sid(
            self.uid, sid, admin=True), 1)
        self.assertFalse(app_core.session_valid(tok))


class DiskThresholdTests(unittest.TestCase):
    def test_critical_is_clamped_below_warn(self):
        cfg = disk_cleanup._clean({
            "warn_free_gb": 5,
            "critical_free_gb": 8,
            "min_free_gb": 1,
        })
        self.assertEqual(cfg["warn_free_gb"], 5)
        self.assertEqual(cfg["critical_free_gb"], 5)
        self.assertGreaterEqual(cfg["min_free_gb"], 5)

    def test_disk_guard_message(self):
        old_load = disk_cleanup.load
        old_usage = app_core.shutil.disk_usage
        try:
            disk_cleanup.load = lambda *a, **k: {"critical_free_gb": 2}
            app_core.shutil.disk_usage = lambda path: mock.Mock(
                free=1024 ** 3, total=10 * 1024 ** 3)
            self.assertIn("磁盘剩余空间不足",
                          app_core.disk_guard_message())
        finally:
            disk_cleanup.load = old_load
            app_core.shutil.disk_usage = old_usage


class PageWiringTests(unittest.TestCase):
    def test_admin_payload_has_login_lock_field(self):
        rows = app_core.admin_users_payload()
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("login_locked", row)

    def test_admin_ui_has_unlock_and_guard_fields(self):
        page = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        for token in ("data-admin-unlock", "data-admin-kick",
                      "adminSupGpu", "adminSupTtl",
                      "adminCleanupWarn", "adminCleanupCritical"):
            self.assertIn(token, page)


if __name__ == "__main__":
    unittest.main()
