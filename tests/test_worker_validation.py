# -*- coding: utf-8 -*-
"""节点机准入校验：节点、ComfyUI 版本、模型大小。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from _common import APP, ROOT  # noqa: F401

sys.path.insert(0, str(ROOT / "worker"))
import worker_agent

import app_core
import lan_share
import web_server


def _policy(**overrides):
    data = {
        "id": "w1", "accepting": True, "owner_id": "admin",
        "trusted": True, "allowed_users": (),
        "models": {"checkpoints": ["model.safetensors"]},
        "model_sizes": {"checkpoints": {"model.safetensors": 12345}},
        "nodes": ["KSampler", "SaveImage"],
        "comfy_version": "0.40.0",
        "caps": {"max_pixels": 2000000, "max_count": 4},
    }
    data.update(overrides)
    return data


def _job(**overrides):
    data = {
        "remote_ok": True, "kind": "gen", "user_id": "admin",
        "requirements": [{"folder": "checkpoints",
                          "name": "model.safetensors", "size": 12345}],
        "required_nodes": ["KSampler", "SaveImage"],
        "pixels": 512 * 512, "count": 1, "exclude_workers": [],
    }
    data.update(overrides)
    return data


class WorkerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.user_patch = mock.patch.object(
            app_core, "get_user",
            return_value={"id": "admin", "role": "admin"})
        self.user_patch.start()

    def tearDown(self):
        self.user_patch.stop()

    def test_good_worker_is_accepted(self):
        self.assertTrue(app_core._worker_policy_can_run(_policy(), _job()))

    def test_missing_node_rejects_worker(self):
        job = _job(required_nodes=["KSampler", "MissingNode"])
        self.assertFalse(app_core._worker_policy_can_run(_policy(), job))

    def test_model_size_mismatch_rejects_worker(self):
        policy = _policy(model_sizes={
            "checkpoints": {"model.safetensors": 99999}})
        self.assertFalse(app_core._worker_policy_can_run(policy, _job()))

    def test_unknown_size_falls_back_to_name(self):
        policy = _policy(model_sizes={})
        self.assertTrue(app_core._worker_policy_can_run(policy, _job()))

    def test_comfy_version_out_of_range_rejects_worker(self):
        self.assertFalse(app_core._worker_policy_can_run(
            _policy(comfy_version="0.39.9"), _job()))
        self.assertFalse(app_core._worker_policy_can_run(
            _policy(comfy_version="0.43.0"), _job()))
        self.assertTrue(app_core._worker_policy_can_run(
            _policy(comfy_version=""), _job()))


class WorkerModelTests(unittest.TestCase):
    def test_admin_payload_marks_incompatible_version(self):
        payload = {"workers": [
            {"inventory": {"comfy_version": "0.39.9"}},
            {"inventory": {"comfy_version": "0.40.0"}},
            {"inventory": {}},
        ]}
        web_server._annotate_worker_compat(payload)
        self.assertFalse(payload["workers"][0]["comfy_compatible"])
        self.assertTrue(payload["workers"][1]["comfy_compatible"])
        self.assertIsNone(payload["workers"][2]["comfy_compatible"])

    def test_worker_reports_model_sizes(self):
        with tempfile.TemporaryDirectory() as td:
            comfy = Path(td) / "ComfyUI"
            ckpt = comfy / "models" / "checkpoints" / "model.safetensors"
            ckpt.parent.mkdir(parents=True)
            ckpt.write_bytes(b"x" * 37)
            sizes = worker_agent.model_sizes(
                str(comfy), {"checkpoints": ["model.safetensors"]})
            self.assertEqual(sizes["checkpoints"]["model.safetensors"], 37)

    def test_lan_share_worker_has_models_checks_size(self):
        worker = {"inventory": {
            "models": {"checkpoints": ["model.safetensors"]},
            "model_sizes": {"checkpoints": {"model.safetensors": 10}},
        }}
        req = [{"folder": "checkpoints", "name": "model.safetensors",
                "size": 10}]
        self.assertTrue(lan_share.worker_has_models(worker, req))
        req[0]["size"] = 11
        self.assertFalse(lan_share.worker_has_models(worker, req))

    def test_lan_share_worker_can_take_checks_nodes(self):
        worker = {"status": "approved", "comfy_ready": True,
                  "last_seen": time.time(), "inventory": {
            "models": {"checkpoints": ["model.safetensors"]},
            "model_sizes": {"checkpoints": {"model.safetensors": 10}},
            "nodes": ["KSampler"],
            "capabilities": {"max_pixels": 2000000, "max_count": 4},
        }}
        user = {"id": "admin", "role": "admin"}
        self.assertTrue(lan_share.worker_can_take(
            worker, user, [{"folder": "checkpoints",
                            "name": "model.safetensors", "size": 10}],
            512 * 512, 1, ["KSampler"]))
        self.assertFalse(lan_share.worker_can_take(
            worker, user, [{"folder": "checkpoints",
                            "name": "model.safetensors", "size": 10}],
            512 * 512, 1, ["MissingNode"]))


if __name__ == "__main__":
    unittest.main()
