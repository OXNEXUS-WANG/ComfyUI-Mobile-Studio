# -*- coding: utf-8 -*-
import json
import struct
import tempfile
import unittest
from pathlib import Path

from _common import APP  # noqa: F401  (sets sys.path)
import model_profiles


def fake_safetensors(path, keys, meta=None):
    header = {"__metadata__": meta or {}}
    for k in keys:
        header[k] = {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]}
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(struct.pack("<Q", len(raw)))
        fh.write(raw)
    return str(path)


class ModelProfileTests(unittest.TestCase):
    def test_filename_families_do_not_confuse_anima(self):
        self.assertEqual(
            model_profiles.detect_family("anima-aesthetic-v1.1.safetensors"),
            "anima")
        self.assertEqual(
            model_profiles.detect_family("animagine-xl-4.0.safetensors"),
            "sdxl_anime")
        self.assertEqual(
            model_profiles.detect_family("animaPencilXL_v500.safetensors"),
            "sdxl_anime")
        p = model_profiles.profile_for("animagine-xl-4.0.safetensors")
        self.assertEqual(p["label_en"], "Anime · Animagine XL")

    def test_tensor_signatures(self):
        with tempfile.TemporaryDirectory() as td:
            flux = fake_safetensors(
                Path(td) / "f.safetensors",
                ["model.diffusion_model.double_blocks.0.x",
                 "model.diffusion_model.single_blocks.0.x"])
            anima = fake_safetensors(
                Path(td) / "a.safetensors",
                ["model.diffusion_model.x_embedder.weight",
                 "model.diffusion_model.blocks.0.adaln_modulation_cross_attn.1.weight"])
            sdxl = fake_safetensors(
                Path(td) / "s.safetensors",
                ["conditioner.embedders.1.model.x",
                 "model.diffusion_model.input_blocks.0.0.weight"])
            sd15 = fake_safetensors(
                Path(td) / "o.safetensors",
                ["cond_stage_model.transformer.text_model.embeddings.token_embedding.weight",
                 "model.diffusion_model.input_blocks.0.0.weight"])
            self.assertEqual(model_profiles.detect_family("f", flux), "flux")
            self.assertEqual(model_profiles.detect_family("a", anima), "anima")
            self.assertEqual(model_profiles.detect_family("s", sdxl), "sdxl_photo")
            self.assertEqual(model_profiles.detect_family("o", sd15), "sd15")

    def test_turbo_and_lightning(self):
        turbo = model_profiles.profile_for("sdxl-turbo.safetensors")
        self.assertEqual((turbo["steps"], turbo["cfg"]), (4, 1.0))
        self.assertFalse(turbo["supports_negative"])
        lightning = model_profiles.profile_for("sdxl_lightning_8step.safetensors")
        self.assertEqual((lightning["steps"], lightning["cfg"]), (6, 2.0))

    def test_known_preset_is_preserved(self):
        p = model_profiles.profile_for(
            "RealVisXL_V5.0_Lightning_fp16.safetensors",
            known={"label": "写实 · RealVis Lightning", "steps": 8, "cfg": 2.0,
                   "kind": "photo", "family": "sdxl_photo"})
        self.assertEqual(p["steps"], 8)
        self.assertEqual(p["family"], "sdxl_photo")

    def test_lora_family_detection(self):
        with tempfile.TemporaryDirectory() as td:
            sdxl = fake_safetensors(
                Path(td) / "sdxl.safetensors",
                ["lora_unet_down_blocks_0_resnets_0_conv1.lora_up.weight"])
            sd15 = fake_safetensors(
                Path(td) / "sd15.safetensors",
                ["lora_unet_input_blocks_4_1_transformer_blocks_0_attn2.lora_up.weight"])
            anima = fake_safetensors(
                Path(td) / "anima.safetensors",
                ["diffusion_model.blocks.0.adaln_modulation_cross_attn.1.lora_A.weight"])
            flux = fake_safetensors(
                Path(td) / "flux.safetensors",
                ["diffusion_model.double_blocks.0.img_attn.lora_A.weight"])
            self.assertEqual(model_profiles.detect_lora_family("x", sdxl), "sdxl")
            self.assertEqual(model_profiles.detect_lora_family("x", sd15), "sd15")
            self.assertEqual(model_profiles.detect_lora_family("x", anima), "anima")
            self.assertEqual(model_profiles.detect_lora_family("x", flux), "flux")
            self.assertFalse(model_profiles.lora_compatible("sd15_anime", "sdxl"))
            self.assertFalse(model_profiles.lora_compatible("anima", "sdxl"))
            self.assertTrue(model_profiles.lora_compatible("sdxl_anime", "sdxl"))
            self.assertTrue(model_profiles.lora_compatible("anima", "unknown"))


if __name__ == "__main__":
    unittest.main()
