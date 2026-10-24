# -*- coding: utf-8 -*-
"""新增模型下载包与推荐参数回归测试。"""
import json
import unittest

from _common import ROOT
import model_profiles


class ModelPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (ROOT / "installer" / "models_manifest.json").read_text(
                encoding="utf-8"))
        cls.catalog = model_profiles.catalog().get("checkpoint_presets") or {}

    def test_new_packs_are_downloadable_and_pinned(self):
        expected = {
            "lightning": "SDXL-Lightning-4step.safetensors",
            "sdxl_base": "SDXL-Base-1.0.safetensors",
            "juggernaut_v9": "Juggernaut-XL-v9.safetensors",
            "animagine31": "Animagine-XL-3.1.safetensors",
        }
        packs = self.manifest["packs"]
        for key, dest in expected.items():
            self.assertIn(key, packs)
            f = packs[key]["files"][0]
            self.assertEqual(f["dest"], "ComfyUI/models/checkpoints/" + dest)
            self.assertEqual(len(f.get("sha256") or ""), 64, dest)
            self.assertTrue(f.get("modelscope_repo"), dest)
            self.assertTrue(f.get("modelscope_revision"), dest)

    def test_new_pack_presets(self):
        checks = {
            "SDXL-Lightning-4step.safetensors": (4, 1.0),
            "SDXL-Base-1.0.safetensors": (25, 7.0),
            "Juggernaut-XL-v9.safetensors": (30, 5.0),
            "Animagine-XL-3.1.safetensors": (28, 7.0),
        }
        for name, (steps, cfg) in checks.items():
            self.assertIn(name, self.catalog)
            p = model_profiles.profile_for(name, known=self.catalog[name])
            self.assertEqual(p["steps"], steps, name)
            self.assertEqual(p["cfg"], cfg, name)
            self.assertTrue(p.get("supported"), name)


if __name__ == "__main__":
    unittest.main()
