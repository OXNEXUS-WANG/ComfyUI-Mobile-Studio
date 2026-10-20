# -*- coding: utf-8 -*-
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from _common import APP  # noqa: F401
import worker_bundle


class WorkerBundleTests(unittest.TestCase):
    def test_bundle_has_profile_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ComfyUI" / "models" / "checkpoints").mkdir(parents=True)
            (root / "ComfyUI" / "models" / "checkpoints" / "a.safetensors").write_bytes(b"12345")
            (root / "ComfyUI" / "custom_nodes" / "MyNode").mkdir(parents=True)
            (root / "worker").mkdir()
            for name in ("worker_agent.py", "deploy_node.py"):
                (root / "worker" / name).write_text("# test\n", encoding="utf-8")
            (root / "installer").mkdir()
            (root / "installer" / "versions.lock.json").write_text(
                '{"schema":1}', encoding="utf-8")
            data, profile = worker_bundle.build_bundle(
                str(root), "https://192.168.137.1:8800")
            self.assertEqual(len(profile["models"]), 1)
            self.assertEqual(profile["models"][0]["size"], 5)
            self.assertEqual(profile["custom_nodes"], ["MyNode"])
            z = zipfile.ZipFile(io.BytesIO(data))
            names = z.namelist()
            self.assertIn("node_profile.json", names)
            self.assertIn("deploy_node.py", names)
            self.assertIn("versions.lock.json", names)
            self.assertNotIn("worker_agent.json", names)
            self.assertNotIn("key.pem", names)
            saved = json.loads(z.read("node_profile.json"))
            self.assertEqual(saved["central_url"], "https://192.168.137.1:8800")


if __name__ == "__main__":
    unittest.main()
