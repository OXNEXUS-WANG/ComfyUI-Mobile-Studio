# -*- coding: utf-8 -*-
"""ComfyUI 适配层、能力检查和模板/目录数据测试。"""
import json
import unittest
from unittest import mock

from _common import APP, ROOT  # noqa: F401

import app_core
import comfy_client
import model_profiles
import workflow_templates


class ComfyClientTests(unittest.TestCase):
    def test_ws_target_uses_configured_url(self):
        client = comfy_client.ComfyClient("http://192.168.1.50:9000")
        target = client.ws_target("tester")
        self.assertEqual(target["host"], "192.168.1.50")
        self.assertEqual(target["port"], 9000)
        self.assertEqual(target["netloc"], "192.168.1.50:9000")
        self.assertEqual(target["path"], "/ws?clientId=tester")

    def test_capabilities_reports_missing_core_nodes(self):
        client = comfy_client.ComfyClient("http://127.0.0.1:1")
        with mock.patch.object(client, "object_info",
                               return_value={"KSampler": {}}), \
             mock.patch.object(client, "comfyui_version",
                               return_value="0.40.0"):
            report = client.capabilities(required=("KSampler", "SaveImage"))
        self.assertTrue(report["online"])
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing"], ["SaveImage"])

    def test_ensure_nodes_raises_only_when_online(self):
        client = comfy_client.ComfyClient("http://127.0.0.1:1")
        with mock.patch.object(client, "capabilities",
                               return_value={"online": True,
                                             "missing": ["KSampler"]}):
            with self.assertRaises(comfy_client.ComfyCapabilityError):
                client.ensure_nodes(("KSampler",), context="出图")
        with mock.patch.object(client, "capabilities",
                               return_value={"online": False,
                                             "missing": []}):
            self.assertTrue(client.ensure_nodes(("KSampler",)))

    def test_request_json_handles_empty_response(self):
        client = comfy_client.ComfyClient("http://127.0.0.1:1")
        response = mock.MagicMock()
        response.read.return_value = b""
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with mock.patch("comfy_client.urllib.request.urlopen",
                        return_value=response):
            self.assertEqual(client.free(), {})


class WorkflowTemplateTests(unittest.TestCase):
    def test_templates_fill_types_and_do_not_leak_placeholders(self):
        nodes = workflow_templates.build(
            "sdxl_base", ckpt="x.safetensors", width=832, height=1216,
            count=1, negative="bad", seed=7, steps=20, cfg=6.0,
            sampler="euler", scheduler="normal")
        self.assertEqual(nodes["4"]["inputs"]["ckpt_name"], "x.safetensors")
        self.assertEqual(nodes["5"]["inputs"]["width"], 832)
        self.assertIsInstance(nodes["3"]["inputs"]["steps"], int)
        raw = json.dumps(nodes)
        self.assertNotIn("{{", raw)

    def test_all_expected_templates_exist(self):
        self.assertEqual(
            set(workflow_templates.names()),
            {"sdxl_base", "anima_base", "video_t2v", "video_i2v",
             "upscale_base"})


class ModelCatalogTests(unittest.TestCase):
    def test_catalog_has_profiles_and_presets(self):
        self.assertIn("anima", model_profiles.PROFILES)
        self.assertIn("unknown", model_profiles.SIZE_PRESETS)
        self.assertEqual(
            model_profiles.detect_family("anima-aesthetic-v1.1.safetensors"),
            "anima")
        self.assertEqual(len(app_core.CKPT_PRESETS), 6)
        self.assertEqual(
            app_core.CKPT_PRESETS[
                "anima-aesthetic-v1.1.safetensors"]["steps"], 30)

    def test_version_range(self):
        self.assertTrue(app_core.comfy_version_compatible(
            "0.40.0", "0.40.0", "0.43.0"))
        self.assertTrue(app_core.comfy_version_compatible(
            "0.42.9", "0.40.0", "0.43.0"))
        self.assertFalse(app_core.comfy_version_compatible(
            "0.39.9", "0.40.0", "0.43.0"))
        self.assertFalse(app_core.comfy_version_compatible(
            "0.43.0", "0.40.0", "0.43.0"))
        self.assertIsNone(app_core.comfy_version_compatible(
            "", "0.40.0", "0.43.0"))


if __name__ == "__main__":
    unittest.main()
