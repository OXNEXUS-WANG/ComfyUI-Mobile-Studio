# -*- coding: utf-8 -*-
"""一键体检报告打包测试。"""
import io
import json
import unittest
import zipfile

from _common import APP  # noqa: F401
import health_report


class HealthReportTests(unittest.TestCase):
    def _data(self):
        return {
            "generated": 1700000000,
            "app": {"version": "1.1.0", "edition": "commercial",
                    "pid": 123, "started": 1699990000,
                    "python": "3.13.0", "platform": "Windows 11"},
            "health": {"score": 92, "label": "健康"},
            "diagnostics": {
                "summary": {"ok": 2, "info": 1, "warn": 1, "error": 0},
                "checks": [
                    {"id": "comfy", "level": "ok", "title": "ComfyUI 连接",
                     "detail": "正常", "hint": ""},
                    {"id": "disk", "level": "warn", "title": "磁盘空间",
                     "detail": "<script>alert(1)</script>", "hint": "清理旧图"},
                ],
                "version": "0.40.0",
            },
            "snapshot": {"cpu_percent": 10, "cpu_count": 16,
                         "ram_percent": 40, "gpu_name": "RTX 5060",
                         "queue_size": 0, "running_count": 0,
                         "comfy_ready": True, "disk_free_gb": 50},
            "storage": {"total_images": 2, "total_mb": 2.0, "free_gb": 50},
            "cleanup": {"settings": {"enabled": False}},
            "license": {"commercial": True, "valid": True,
                        "customer": "客户A", "expires": 0,
                        "machine_code": "ABCD-EF01-2345-6789-ABCD-EF01"},
            "models": {"categories": [
                {"key": "checkpoints", "label": "底模", "bytes": 1048576,
                 "files": [{"name": "a.safetensors"}]}
            ]},
            "workers": [], "jobs": [], "alerts": [],
            "counts": {"users": 1, "guests": 0},
            "config": {"monitor": {"alerts_enabled": True}},
            "logs": {"activity": ['{"action":"login"}'],
                     "security": ['{"action":"login_ok"}']},
        }

    def test_zip_entries_and_escaping(self):
        raw = health_report.build_zip(self._data())
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = set(zf.namelist())
            self.assertTrue({"report.html", "report.json", "summary.txt",
                             "logs/activity.log", "logs/security.log"}
                            <= names)
            html_text = zf.read("report.html").decode("utf-8")
            self.assertIn("体检报告", html_text)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html_text)
            self.assertNotIn("<script>alert(1)</script>", html_text)
            payload = json.loads(zf.read("report.json").decode("utf-8"))
            self.assertEqual(payload["license"]["customer"], "客户A")
            summary = zf.read("summary.txt").decode("utf-8")
            self.assertIn("磁盘空间", summary)

    def test_no_secret_fields_added(self):
        data = self._data()
        raw = health_report.build_zip(data)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            payload = zf.read("report.json").decode("utf-8")
        for secret in ("pw_hash", "api_key", "worker_secret", "MGS1."):
            self.assertNotIn(secret, payload)


if __name__ == "__main__":
    unittest.main()
