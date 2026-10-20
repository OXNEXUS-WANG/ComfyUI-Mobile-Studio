# -*- coding: utf-8 -*-
import os
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401
import workflow_manager


class WorkflowManagerTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.old_dir = workflow_manager.WORKFLOW_DIR
        workflow_manager.WORKFLOW_DIR = str(Path(self.td.name) / "workflows")

    def tearDown(self):
        workflow_manager.WORKFLOW_DIR = self.old_dir
        self.td.cleanup()

    def _object_info(self):
        return {"CheckpointLoaderSimple": {}, "KSampler": {}}

    def _models(self):
        return {"categories": [{"files": [
            {"name": "good.safetensors"},
            {"name": "vae.pt"},
        ]}]}

    def _ui(self):
        return {
            "nodes": [
                {"id": 1, "type": "CheckpointLoaderSimple",
                 "widgets_values": ["good.safetensors"]},
                {"id": 2, "type": "KSampler", "widgets_values": []},
                {"id": 3, "type": "MissingNode", "widgets_values": []},
                {"id": 4, "type": "Note", "widgets_values": ["note"]},
            ],
            "links": [[1, 1, 0, 2, 0, "MODEL"]],
        }

    def test_ui_check_missing_node_and_model(self):
        data = self._ui()
        health = workflow_manager.check_workflow(
            data, self._object_info(), self._models())
        self.assertEqual(health["format"], "ui")
        self.assertEqual(health["node_count"], 4)
        self.assertIn("MissingNode", health["missing_nodes"])
        self.assertIn("good.safetensors", health["required_models"])
        self.assertEqual(health["missing_models"], [])
        self.assertEqual(health["level"], "warn")

    def test_missing_model(self):
        data = self._ui()
        data["nodes"][0]["widgets_values"] = ["missing.safetensors"]
        health = workflow_manager.check_workflow(
            data, self._object_info(), self._models())
        self.assertIn("missing.safetensors", health["missing_models"])

    def test_api_format_and_import_list_delete(self):
        data = {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "good.safetensors"}},
            "2": {"class_type": "KSampler",
                  "inputs": {"model": ["1", 0]}},
        }
        info = workflow_manager.import_content(
            data, name="api flow", filename="api.json", by="admin",
            object_info=self._object_info(), model_payload=self._models())
        self.assertEqual(info["format"], "api")
        self.assertEqual(info["health"]["level"], "ok")
        rows = workflow_manager.list_workflows()
        self.assertEqual(len(rows), 1)
        wid = rows[0]["id"]
        checked = workflow_manager.check_saved(
            wid, self._object_info(), self._models())
        self.assertEqual(checked["id"], wid)
        workflow_manager.delete_workflow(wid)
        self.assertEqual(workflow_manager.list_workflows(), [])

    def test_invalid_json_and_format(self):
        with self.assertRaises(ValueError):
            workflow_manager.parse_workflow("{bad json")
        with self.assertRaises(ValueError):
            workflow_manager.check_workflow({"foo": "bar"})

    def test_cycle_detection(self):
        data = {
            "nodes": [{"id": 1, "type": "KSampler"},
                      {"id": 2, "type": "KSampler"}],
            "links": [[1, 1, 0, 2, 0, "X"], [2, 2, 0, 1, 0, "X"]],
        }
        health = workflow_manager.check_workflow(
            data, self._object_info(), self._models())
        self.assertTrue(health["cycles"])

    def test_broken_link(self):
        data = {
            "nodes": [{"id": 1, "type": "KSampler"}],
            "links": [[1, 99, 0, 1, 0, "X"]],
        }
        health = workflow_manager.check_workflow(
            data, self._object_info(), self._models())
        self.assertTrue(health["broken_links"])


if __name__ == "__main__":
    unittest.main()
