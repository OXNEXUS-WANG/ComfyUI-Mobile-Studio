# -*- coding: utf-8 -*-
import os
import unittest

from _common import APP  # noqa: F401
import app_core


class ProxyAuthTests(unittest.TestCase):
    def setUp(self):
        self.old_enabled = os.environ.get("MGS_TRUSTED_PROXY")
        self.old_header = os.environ.get("MGS_PROXY_HEADER")
        self.old_find = app_core.find_user
        self.old_active = app_core.user_is_active
        app_core.find_user = lambda name: (
            {"id": "u1", "username": name, "enabled": True}
            if name == "alice" else None)
        app_core.user_is_active = lambda user: bool(user)

    def tearDown(self):
        if self.old_enabled is None:
            os.environ.pop("MGS_TRUSTED_PROXY", None)
        else:
            os.environ["MGS_TRUSTED_PROXY"] = self.old_enabled
        if self.old_header is None:
            os.environ.pop("MGS_PROXY_HEADER", None)
        else:
            os.environ["MGS_PROXY_HEADER"] = self.old_header
        app_core.find_user = self.old_find
        app_core.user_is_active = self.old_active

    def test_disabled_by_default(self):
        os.environ.pop("MGS_TRUSTED_PROXY", None)
        self.assertFalse(app_core.proxy_auth_enabled())
        self.assertIsNone(app_core.proxy_auth_user("alice", "127.0.0.1"))

    def test_only_loopback_and_known_user(self):
        os.environ["MGS_TRUSTED_PROXY"] = "1"
        self.assertTrue(app_core.proxy_auth_enabled())
        self.assertEqual(
            app_core.proxy_auth_user("alice", "127.0.0.1")["username"],
            "alice")
        self.assertIsNone(app_core.proxy_auth_user("alice", "192.168.137.23"))
        self.assertIsNone(app_core.proxy_auth_user("bob", "127.0.0.1"))

    def test_custom_header_name(self):
        os.environ["MGS_TRUSTED_PROXY"] = "true"
        os.environ["MGS_PROXY_HEADER"] = "X-Auth-User"
        self.assertEqual(app_core.proxy_auth_header(), "X-Auth-User")


if __name__ == "__main__":
    unittest.main()
