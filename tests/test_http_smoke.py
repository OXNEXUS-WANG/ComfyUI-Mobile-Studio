# -*- coding: utf-8 -*-
"""在线冒烟测试。需要设置 MGS_TEST_PASSWORD 才运行，避免把密码写进仓库。"""
import json
import os
import ssl
import unittest
import urllib.error
import urllib.request

BASE = os.environ.get("MGS_TEST_URL", "https://127.0.0.1:8800").rstrip("/")
USER = os.environ.get("MGS_TEST_USER", "admin")
PASSWORD = os.environ.get("MGS_TEST_PASSWORD", "")
CTX = ssl._create_unverified_context()


def call(path, data=None, cookie="", method=None):
    body = None
    headers = {"Accept": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(BASE + path, data=body, headers=headers,
                                 method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=20) as resp:
            raw = resp.read()
            return resp.status, raw, resp.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Set-Cookie", "")


@unittest.skipUnless(PASSWORD, "set MGS_TEST_PASSWORD to run live HTTP tests")
class HttpSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        status, raw, set_cookie = call(
            "/api/login", {"username": USER, "password": PASSWORD})
        if status != 200:
            raise unittest.SkipTest("login failed: HTTP %s" % status)
        cls.cookie = set_cookie.split(";", 1)[0]

    def test_page_and_models(self):
        status, raw, _ = call("/", cookie=self.cookie)
        self.assertEqual(status, 200)
        self.assertGreater(len(raw), 10000)
        status, raw, _ = call("/api/models", cookie=self.cookie)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertTrue(data.get("models"))
        for m in data["models"]:
            self.assertIn("family", m)
            self.assertIn("label_en", m)
            self.assertIn("warnings", m)
        self.assertIn("translation", data)
        self.assertIn("argos_ready", data["translation"])

    def test_new_admin_and_preference_endpoints(self):
        status, raw, _ = call("/api/preferences", cookie=self.cookie)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertIn(data.get("translation_mode"), ("argos", "local"))
        self.assertIn("translation", data)

        status, raw, _ = call("/api/admin/translation", cookie=self.cookie)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertIn("config", data)
        self.assertNotIn("api_key", data["config"])

        status, raw, _ = call("/api/admin/system", cookie=self.cookie)
        self.assertEqual(status, 200)
        data = json.loads(raw)
        self.assertIn("snapshots", data)
        self.assertIn("users.json", data.get("restore_scope") or [])

    def test_gallery_is_private_without_cookie(self):
        status, _, _ = call("/api/gallery")
        self.assertEqual(status, 401)

    def test_wrong_password(self):
        status, _, _ = call("/api/login",
                            {"username": USER, "password": "definitely-wrong"})
        self.assertEqual(status, 401)

    def test_password_change_validation(self):
        status, _, _ = call("/api/password",
                            {"old_password": "wrong", "new_password": "abcdefgh"},
                            cookie=self.cookie)
        self.assertEqual(status, 403)
        status, _, _ = call("/api/password",
                            {"old_password": PASSWORD, "new_password": "short"},
                            cookie=self.cookie)
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
