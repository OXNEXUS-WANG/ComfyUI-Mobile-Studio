# -*- coding: utf-8 -*-
"""监控中心单元测试：告警、健康分、worker 遥测、趋势与 Prometheus 文本。"""
import tempfile
import time
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import monitor_center


class MonitorCenterTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old = {
            "ALERTS_FILE": monitor_center.ALERTS_FILE,
            "TRENDS_FILE": monitor_center.TRENDS_FILE,
            "SETTINGS_FILE": monitor_center.SETTINGS_FILE,
        }
        monitor_center.ALERTS_FILE = str(Path(self.td.name) / "alerts.json")
        monitor_center.TRENDS_FILE = str(Path(self.td.name) / "trends.json")
        monitor_center.SETTINGS_FILE = str(Path(self.td.name) / "monitor.json")
        with monitor_center._LOCK:
            monitor_center._ALERTS.clear()
            monitor_center._HISTORY.clear()
            monitor_center._ALERT_SEEN.update({"loaded": False,
                                               "last_save": 0.0})
        with monitor_center._TELEMETRY_LOCK:
            monitor_center._TELEMETRY.clear()
        with monitor_center._TRENDS_LOCK:
            monitor_center._TRENDS = None
            monitor_center._NOTED_JOBS.clear()

    def tearDown(self):
        for key, value in self.old.items():
            setattr(monitor_center, key, value)
        with monitor_center._LOCK:
            monitor_center._ALERTS.clear()
            monitor_center._HISTORY.clear()
            monitor_center._ALERT_SEEN.update({"loaded": False,
                                               "last_save": 0.0})
        with monitor_center._TELEMETRY_LOCK:
            monitor_center._TELEMETRY.clear()
        with monitor_center._TRENDS_LOCK:
            monitor_center._TRENDS = None
            monitor_center._NOTED_JOBS.clear()
        self.td.cleanup()

    def test_alert_raise_ack_and_health(self):
        snap = {
            "now": time.time(), "queue_size": 25, "running_count": 0,
            "comfy_ready": True, "workers": [], "jobs": [],
            "job_count_10m": 10, "error_count_10m": 5,
            "disk_free_gb": 5, "cert_days": 10,
        }
        alerts = monitor_center.evaluate(snap)
        keys = {a["key"] for a in alerts}
        self.assertIn("queue_backlog", keys)
        self.assertIn("error_rate", keys)
        self.assertIn("disk_low", keys)
        self.assertIn("cert_expiry", keys)
        health = monitor_center.health(snap)
        self.assertLess(health["score"], 100)
        self.assertTrue(monitor_center.ack_alert(alerts[0]["id"]))
        self.assertTrue(any(a.get("ack") for a in monitor_center.active_alerts()))

    def test_worker_series(self):
        monitor_center.note_worker("w_1", {"gpu_util": 50, "temp_c": 60})
        monitor_center.note_worker("w_1", {"gpu_util": 80, "temp_c": 70})
        series = monitor_center.worker_series("w_1")
        self.assertEqual(len(series), 2)
        self.assertEqual(series[-1]["gpu_util"], 80)
        self.assertIn("w_1", monitor_center.all_worker_series())

    def test_trends_and_metrics(self):
        monitor_center.note_job({
            "job_id": "j1", "status": "done", "finished_at": time.time(),
            "elapsed": 12.5, "images": ["a.png"],
        })
        monitor_center.note_job({
            "job_id": "j1", "status": "done", "finished_at": time.time(),
            "elapsed": 12.5, "images": ["a.png"],
        })
        data = monitor_center.trends(24)
        self.assertEqual(len(data["hours"]), 24)
        self.assertEqual(data["hours"][-1]["jobs"], 1)
        text = monitor_center.metrics_text({
            "running_count": 2, "queue_size": 3, "workers_online": 1,
            "workers_total": 2, "gpu_util": 40, "vram_used_mb": 1024,
            "error_count_10m": 0, "gallery_images": 5,
            "disk_free_gb": 20,
        }, [{"severity": "warn"}])
        self.assertIn("mgs_up 1", text)
        self.assertIn('mgs_alerts{severity="warn"} 1', text)
        self.assertNotIn("mgs_alerts{severity=\"warn\"} 0", text)


if __name__ == "__main__":
    unittest.main()
