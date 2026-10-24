# -*- coding: utf-8 -*-
"""网页服务主动拉起 ComfyUI + 首屏状态接口的回归测试。"""
import os
import unittest
from unittest import mock

from _common import APP
import start_service


class ComfyAutostartTests(unittest.TestCase):
    def setUp(self):
        start_service._COMFY_STATUS_CACHE.update({"t": 0.0, "data": None})
        start_service._COMFY_LAST_ERROR["msg"] = ""

    def test_status_distinguishes_alive_starting_and_missing(self):
        with mock.patch.object(start_service, "http_ok", return_value=True), \
             mock.patch.object(start_service, "port_open", return_value=True), \
             mock.patch.object(start_service, "proc_running", return_value=True):
            st = start_service.comfy_status(force=True)
            self.assertTrue(st["alive"])
            self.assertFalse(st["starting"])
        with mock.patch.object(start_service, "http_ok", return_value=False), \
             mock.patch.object(start_service, "port_open", return_value=True), \
             mock.patch.object(start_service, "proc_running", return_value=True):
            st = start_service.comfy_status(force=True)
            self.assertFalse(st["alive"])
            self.assertTrue(st["starting"])

    def test_start_skips_existing_and_starts_when_missing(self):
        with mock.patch.object(start_service, "http_ok", return_value=False), \
             mock.patch.object(start_service, "port_open", return_value=False), \
             mock.patch.object(start_service, "proc_running", return_value=False), \
             mock.patch.object(start_service.os.path, "isfile", return_value=True), \
             mock.patch.object(start_service, "_start_comfy") as spawn:
            child = mock.Mock(pid=1234)
            spawn.return_value = child
            res = start_service.start_comfy_local()
            self.assertTrue(res["started"])
            spawn.assert_called_once()

            spawn.reset_mock()
            with mock.patch.object(start_service, "proc_running",
                                   return_value=True):
                start_service._COMFY_STATUS_CACHE.update(
                    {"t": 0.0, "data": None})
                res = start_service.start_comfy_local()
                self.assertFalse(res["started"])
                spawn.assert_not_called()

    def test_autostart_can_be_disabled(self):
        old = os.environ.get("MGS_NO_COMFY_AUTOSTART")
        os.environ["MGS_NO_COMFY_AUTOSTART"] = "1"
        try:
            self.assertEqual(start_service.autostart_comfy(0),
                             {"skipped": True})
        finally:
            if old is None:
                os.environ.pop("MGS_NO_COMFY_AUTOSTART", None)
            else:
                os.environ["MGS_NO_COMFY_AUTOSTART"] = old

    def test_page_has_comfy_status_banner(self):
        page = (APP / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        web = (APP / "web_server.py").read_text(encoding="utf-8")
        for text in ('id="comfyBanner"', 'id="comfyStartBtn"',
                     "pollComfyStatus", "/api/comfy/status",
                     "/api/comfy/start", "一键启动"):
            self.assertIn(text, page)
        for text in ('"/api/comfy/status"', '"/api/comfy/start"',
                     "_comfy_autostart_worker"):
            self.assertIn(text, web)


if __name__ == "__main__":
    unittest.main()
