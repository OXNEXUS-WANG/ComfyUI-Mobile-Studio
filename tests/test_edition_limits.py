# -*- coding: utf-8 -*-
import json
import os
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import app_core
import edition_policy
import lan_share
import license_guard


class EditionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_edition_file = license_guard.EDITION_FILE
        license_guard.EDITION_FILE = os.path.join(self.td.name, "EDITION")

    def tearDown(self):
        license_guard.EDITION_FILE = self.old_edition_file
        self.td.cleanup()

    def _set_edition(self, value):
        with open(license_guard.EDITION_FILE, "w", encoding="ascii") as fh:
            fh.write(value)

    def test_share_and_commercial_limits_differ(self):
        self._set_edition("share")
        share = edition_policy.policy()
        self.assertEqual(share["max_accounts"], 5)
        self.assertEqual(share["max_workers"], 2)
        self._set_edition("commercial")
        commercial = edition_policy.policy()
        self.assertEqual(commercial["max_accounts"], 50)
        self.assertEqual(commercial["max_workers"], 20)
        self.assertGreater(commercial["max_accounts"], share["max_accounts"])
        self.assertGreater(commercial["max_workers"], share["max_workers"])

    def test_account_quota_and_creation_limit(self):
        self._set_edition("share")
        old_users = app_core.USERS
        old_file = app_core.USERS_FILE
        old_hash = app_core.hash_password
        app_core.USERS = {}
        app_core.USERS_FILE = os.path.join(self.td.name, "users.json")
        app_core.hash_password = lambda pw: ("salt", "hash")
        old_policy = edition_policy.policy
        edition_policy.policy = lambda: {
            "edition": "share", "label": "分享版", "label_en": "Share",
            "max_accounts": 2, "max_workers": 2}
        try:
            app_core.create_user("admin", "pw123456", role="admin")
            app_core.create_user("user1", "pw123456")
            self.assertTrue(app_core.account_quota()["reached"])
            with self.assertRaises(ValueError):
                app_core.create_user("user2", "pw123456")
            # 停用一个账号后释放名额
            uid = app_core.find_user("user1")["id"]
            app_core.update_user(uid, {"enabled": False})
            self.assertFalse(app_core.account_quota()["reached"])
            app_core.create_user("user2", "pw123456")
            self.assertEqual(app_core.account_quota()["used"], 2)
        finally:
            app_core.USERS = old_users
            app_core.USERS_FILE = old_file
            app_core.hash_password = old_hash
            edition_policy.policy = old_policy


class WorkerQuotaTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_workers = lan_share.WORKERS
        self.old_file = lan_share.WORKERS_FILE
        self.old_policy = edition_policy.policy
        lan_share.WORKERS = {}
        lan_share.WORKERS_FILE = Path(self.td.name) / "workers.json"
        edition_policy.policy = lambda: {
            "edition": "share", "label": "分享版", "label_en": "Share",
            "max_accounts": 5, "max_workers": 2}

    def tearDown(self):
        lan_share.WORKERS = self.old_workers
        lan_share.WORKERS_FILE = self.old_file
        edition_policy.policy = self.old_policy
        self.td.cleanup()

    def _worker(self, wid, status):
        return {"id": wid, "name": wid, "status": status,
                "approved": status == "approved", "secret_hash": "x",
                "created": 0, "last_seen": 0}

    def test_worker_slots_count_pending_and_approved(self):
        lan_share.WORKERS = {
            "w1": self._worker("w1", "approved"),
            "w2": self._worker("w2", "pending"),
            "w3": self._worker("w3", "rejected"),
        }
        q = lan_share.worker_quota()
        self.assertEqual(q["used"], 2)
        self.assertTrue(q["reached"])

    def test_approval_blocked_at_limit(self):
        lan_share.WORKERS = {
            "w1": self._worker("w1", "approved"),
            "w2": self._worker("w2", "approved"),
            "w3": self._worker("w3", "pending"),
        }
        worker, err = lan_share.update_worker("w3", {"status": "approved"})
        self.assertIsNone(worker)
        self.assertIn("最多", err)

    def test_removing_worker_frees_slot(self):
        lan_share.WORKERS = {
            "w1": self._worker("w1", "approved"),
            "w2": self._worker("w2", "approved"),
        }
        self.assertTrue(lan_share.worker_quota()["reached"])
        self.assertTrue(lan_share.remove_worker("w2"))
        self.assertFalse(lan_share.worker_quota()["reached"])

    def test_approving_pending_worker_is_allowed_within_slots(self):
        lan_share.WORKERS = {
            "w1": self._worker("w1", "pending"),
            "w2": self._worker("w2", "pending"),
        }
        worker, err = lan_share.update_worker("w1", {"status": "approved"})
        self.assertEqual(err, "")
        self.assertEqual(worker.get("status"), "approved")
        self.assertTrue(lan_share.worker_quota()["reached"])

    def test_join_is_rejected_when_slots_are_full(self):
        old_codes = lan_share.JOIN_CODES
        lan_share.JOIN_CODES = {}
        try:
            lan_share.WORKERS = {
                "w1": self._worker("w1", "approved"),
                "w2": self._worker("w2", "pending"),
            }
            code = "ABCD2345"
            lan_share.JOIN_CODES[lan_share._code_hash(code)] = {
                "created": 0, "expires": lan_share._now() + 600,
                "created_by": "admin", "used_by": "", "used_at": 0,
            }
            worker, secret, err = lan_share.redeem_join_code(
                code, "192.168.137.50", "test", {}, "1.0")
            self.assertIsNone(worker)
            self.assertEqual(secret, "")
            self.assertIn("最多", err)
        finally:
            lan_share.JOIN_CODES = old_codes


if __name__ == "__main__":
    unittest.main()
