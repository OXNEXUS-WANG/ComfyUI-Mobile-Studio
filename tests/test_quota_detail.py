# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch

from _common import APP  # noqa: F401
import app_core

USER = {"id": "u_test", "username": "tester", "role": "user", "limits": {}}


class QuotaDetailTests(unittest.TestCase):
    def test_step_limit_has_structured_quota(self):
        lim = {"max_steps": 10}
        with patch.object(app_core, "is_admin", return_value=False), \
             patch.object(app_core, "user_limits", return_value=lim):
            msg, quota = app_core.check_user_limits_detail(
                USER, "x.safetensors", steps=20)
        self.assertIn("步数超过上限", msg)
        self.assertEqual(quota["kind"], "max_steps")
        self.assertEqual(quota["used"], 20)
        self.assertEqual(quota["limit"], 10)

    def test_daily_image_quota(self):
        lim = {"daily_images": 3}
        usage = {"today": 3, "images": 3, "bytes": 0, "active": 0,
                 "running": 0, "gpu_seconds_today": 0,
                 "gpu_seconds_month": 0}
        with patch.object(app_core, "is_admin", return_value=False), \
             patch.object(app_core, "user_limits", return_value=lim), \
             patch.object(app_core, "user_usage", return_value=usage):
            msg, quota = app_core.check_user_limits_detail(
                USER, "x.safetensors", count=1)
        self.assertIn("出图额度", msg)
        self.assertEqual(quota["kind"], "daily_images")
        self.assertEqual(quota["used"], 3)
        self.assertEqual(quota["limit"], 3)
        self.assertEqual(quota["reset"], "daily")

    def test_traffic_quota_detail(self):
        lim = {"daily_traffic_mb": 10}
        snap = {"traffic_today": 11 * 1048576, "traffic_month": 0}
        with patch.object(app_core, "is_admin", return_value=False), \
             patch.object(app_core, "user_limits", return_value=lim), \
             patch.object(app_core, "usage_snapshot", return_value=snap):
            msg, quota = app_core.traffic_quota_detail(USER)
        self.assertIn("流量额度", msg)
        self.assertEqual(quota["kind"], "daily_traffic_mb")
        self.assertEqual(quota["limit"], 10)
        self.assertEqual(quota["reset"], "daily")

    def test_admin_is_never_limited(self):
        with patch.object(app_core, "is_admin", return_value=True):
            msg, quota = app_core.check_user_limits_detail(
                {"id": "admin"}, "x", steps=999)
        self.assertIsNone(msg)
        self.assertIsNone(quota)


if __name__ == "__main__":
    unittest.main()
