# -*- coding: utf-8 -*-
"""LoRA 训练档案、命令、TOML、日志解析和元数据清理测试。"""
import json
import os
import struct
import tempfile
import unittest

from _common import ROOT

import training_profiles as tp

try:
    import numpy as np
    from safetensors.numpy import save_file as save_np
    HAS_SAFETENSORS = True
except Exception:
    HAS_SAFETENSORS = False


class TrainingProfileTests(unittest.TestCase):
    def test_params_are_clamped_and_preset_defaults_applied(self):
        p = tp.normalize_params("anima", {
            "resolution": 9999, "network_dim": 999,
            "learning_rate": 99, "max_steps": 999999,
            "blocks_to_swap": 999, "total_blocks": 28,
        })
        self.assertLessEqual(p["resolution"], 1024)
        self.assertLessEqual(p["network_dim"], 128)
        self.assertLessEqual(p["learning_rate"], 1e-2)
        self.assertLessEqual(p["max_steps"], 3000)
        self.assertLessEqual(p["blocks_to_swap"], 26)
        self.assertGreaterEqual(p["blocks_to_swap"], 0)

    def test_recipe_commands(self):
        with tempfile.TemporaryDirectory() as root:
            project = {
                "id": "t_abcdef123456", "profile": "anima",
                "base_model": tp.ANIMA_MODEL,
                "output_name": "lora_anima_t_abcdef123456",
                "params": tp.normalize_params("anima", {
                    "max_steps": 100, "resolution": 512,
                    "network_dim": 8, "network_alpha": 4,
                }),
            }
            cmd = tp.build_train_command(
                root, os.path.join(root, "training_launcher.py"), project,
                "C:/data.toml", "C:/out")
            joined = " ".join(cmd)
            self.assertIn("anima_train_network.py", joined)
            self.assertIn("--network_module=networks.lora_anima", joined)
            self.assertIn("--block_swap_h2d_only", joined)
            self.assertIn("--qwen_image_vae_2d", joined)
            self.assertIn("--cache_text_encoder_outputs_to_disk", joined)
            self.assertIn("--blocks_to_swap=22", joined)
            self.assertNotIn("shuffle_caption", joined)

            project["profile"] = "sdxl"
            project["base_model"] = "Illustrious-XL-v2.0.safetensors"
            project["params"] = tp.normalize_params("sdxl", {
                "max_steps": 100, "resolution": 512})
            cmd2 = tp.build_train_command(
                root, os.path.join(root, "training_launcher.py"), project,
                "C:/data.toml", "C:/out")
            joined2 = " ".join(cmd2)
            self.assertIn("sdxl_train_network.py", joined2)
            self.assertIn("--sdpa", joined2)
            self.assertNotIn("--blocks_to_swap", joined2)

    def test_dataset_toml_has_no_cache_incompatible_options(self):
        text = tp.dataset_toml({
            "params": {"resolution": 768, "num_repeats": 4,
                       "shuffle_caption": True, "caption_dropout": 0.2,
                       "keep_tokens": 2},
        }, "C:/tmp/dataset")
        self.assertIn("resolution = 768", text)
        self.assertIn("num_repeats = 4", text)
        self.assertNotIn("shuffle_caption", text)
        self.assertNotIn("caption_dropout_rate", text)
        self.assertNotIn("keep_tokens", text)

    def test_log_progress_parser(self):
        text = (
            "epoch 1/2\n"
            "steps:  25%|## | 10/40 [00:20<01:00, 2.00s/it, avr_loss=0.123]\n"
            "saving checkpoint: /tmp/lora-step10.safetensors\n")
        st = tp.parse_log_tail(text)
        self.assertEqual(st["step"], 10)
        self.assertEqual(st["total_steps"], 40)
        self.assertEqual(st["epoch"], 1)
        self.assertEqual(st["loss"], 0.123)
        self.assertEqual(st["percent"], 25.0)
        self.assertIn("lora-step10.safetensors", st["checkpoints"])

    def test_error_classification(self):
        msg, hint = tp.classify_error(
            "RuntimeError: CUDA out of memory")
        self.assertIn("显存", msg)
        self.assertIn("512", hint)
        msg2, _ = tp.classify_error("OpenBLAS error: allocation failed")
        self.assertIn("内存", msg2)

    @unittest.skipUnless(HAS_SAFETENSORS, "safetensors/numpy not available")
    def test_metadata_is_stripped_without_touching_tensors(self):
        with tempfile.TemporaryDirectory() as root:
            src = os.path.join(root, "src.safetensors")
            dst = os.path.join(root, "dst.safetensors")
            save_np({"x": np.zeros((2, 3), dtype=np.float32)},
                    src, metadata={"note": "secret", "ss_tag_frequency": "{}"})
            n = tp.strip_metadata(src, dst)
            self.assertEqual(n, 1)
            with open(dst, "rb") as fh:
                length = struct.unpack("<Q", fh.read(8))[0]
                header = json.loads(fh.read(length))
            self.assertNotIn("__metadata__", header)
            self.assertIn("x", header)

    def test_estimate_seconds_scales_with_steps(self):
        a = tp.estimate_seconds("anima", 100, 512, 10)
        b = tp.estimate_seconds("anima", 1000, 512, 10)
        self.assertGreater(b, a)


if __name__ == "__main__":
    unittest.main()
