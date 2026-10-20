# -*- coding: utf-8 -*-
"""商用版机器码 / 授权码校验测试（临时密钥对，不依赖维护者私钥）。"""
import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import license_guard


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class LicenseTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.key = Ed25519PrivateKey.generate()
        pub = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.old = {
            "EDITION_FILE": license_guard.EDITION_FILE,
            "LICENSE_FILE": license_guard.LICENSE_FILE,
            "PUBLIC_KEY_B64": license_guard.PUBLIC_KEY_B64,
        }
        license_guard.EDITION_FILE = str(self.root / "EDITION")
        license_guard.LICENSE_FILE = str(self.root / "license.json")
        license_guard.PUBLIC_KEY_B64 = base64.b64encode(pub).decode()
        Path(license_guard.EDITION_FILE).write_text("commercial",
                                                    encoding="utf-8")
        license_guard._CACHE.update(key=None, status=None)

    def tearDown(self):
        for key, value in self.old.items():
            setattr(license_guard, key, value)
        license_guard._CACHE.update(key=None, status=None)
        self.td.cleanup()

    def _code(self, machine=None, days=365, edition="commercial"):
        now = int(time.time())
        payload = {
            "v": 1, "edition": edition,
            "machine": machine or license_guard.normalize_machine(
                license_guard.machine_code()),
            "customer": "测试客户",
            "issued": now,
            "expires": 0 if days == 0 else now + days * 86400,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
        sig = self.key.sign(raw)
        return "MGS1." + _b64e(raw) + "." + _b64e(sig)

    def test_machine_code_format(self):
        code = license_guard.machine_code()
        self.assertRegex(code, r"^[0-9A-F]{4}(-[0-9A-F]{4}){5}$")

    def test_activate_and_status(self):
        status = license_guard.activate(self._code())
        self.assertTrue(status["valid"])
        self.assertEqual(status["customer"], "测试客户")
        self.assertIsNotNone(status["days_left"])
        self.assertTrue(os.path.isfile(license_guard.LICENSE_FILE))
        self.assertTrue(license_guard.status(force=True)["valid"])
        self.assertFalse(license_guard.license_required())

    def test_wrong_machine_rejected(self):
        with self.assertRaises(ValueError):
            license_guard.activate(self._code(machine="0" * 24))
        self.assertFalse(os.path.exists(license_guard.LICENSE_FILE))

    def test_expired_and_tampered_rejected(self):
        with self.assertRaises(ValueError):
            license_guard.activate(self._code(days=-1))
        good = self._code()
        with self.assertRaises(ValueError):
            license_guard.activate(good[:-4] + "AAAA")

    def test_share_edition_needs_no_activation(self):
        Path(license_guard.EDITION_FILE).write_text("share",
                                                    encoding="utf-8")
        license_guard._CACHE.update(key=None, status=None)
        status = license_guard.status(force=True)
        self.assertFalse(status["commercial"])
        self.assertTrue(status["valid"])
        with self.assertRaises(ValueError):
            license_guard.activate(self._code())


if __name__ == "__main__":
    unittest.main()
