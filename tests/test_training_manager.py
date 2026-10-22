# -*- coding: utf-8 -*-
"""训练项目、审核、数据集、配额与 LoRA 归属测试。"""
import os
import tempfile
import unittest
from io import BytesIO

from PIL import Image

import training_manager as tm
import training_profiles as tp

USER = {"id": "u_test", "username": "tester", "name": "Tester",
        "role": "user", "enabled": True}
ADMIN = {"id": "admin", "username": "admin", "name": "Admin",
         "role": "admin", "enabled": True}


def make_png(path, color=(180, 120, 200)):
    im = Image.new("RGB", (320, 320), color)
    im.save(path, "PNG")


class TrainingManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "ComfyUI", "models", "loras"))
        self.m = tm.TrainingManager(self.root)
        self.m.settings["enabled"] = True
        self.m.settings["max_steps"] = 3000
        self.m.settings["max_dataset_images"] = 100
        self.png = os.path.join(self.root, "sample.png")
        make_png(self.png)

    def tearDown(self):
        self.tmp.cleanup()

    def create_project(self):
        p = self.m.create_project(USER, {
            "name": "Test LoRA", "profile": "anima", "trigger": "mychar",
            "params": {"resolution": 512, "max_steps": 100,
                       "network_dim": 8, "network_alpha": 4,
                       "num_repeats": 1, "epochs": 1},
        })
        for i in range(5):
            self.m.add_gallery_image(p["id"], USER, self.png,
                                     "anime portrait %d" % i)
        return p

    def test_create_upload_submit_and_admin_approval(self):
        p = self.create_project()
        self.assertEqual(p["status"], "draft")
        self.assertEqual(self.m.project_dataset_stats(p)[0], 5)
        err, quota = self.m.submit_project(
            p["id"], USER, limits={"max_dataset_images": 50,
                                   "max_train_steps": 2000},
            usage={})
        self.assertIsNone(err)
        self.assertEqual(self.m._project(p["id"])["status"], "pending")
        with self.assertRaises(PermissionError):
            self.m.approve_project(p["id"], USER)
        self.m.approve_project(p["id"], ADMIN, {"max_minutes": 30})
        self.assertEqual(self.m._project(p["id"])["status"], "approved")
        self.assertEqual(self.m.summary(admin=True)["queue"], 1)

    def test_empty_primary_does_not_resurrect_stale_backup(self):
        import json
        with open(os.path.join(self.root, "trainings.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": 1, "projects": {}}, fh)
        with open(os.path.join(self.root, "trainings.json.bak"), "w",
                  encoding="utf-8") as fh:
            json.dump({"version": 1, "projects": {
                "t_old": {"id": "t_old", "name": "deleted"}}}, fh)
        fresh = tm.TrainingManager(self.root)
        self.assertEqual(fresh.projects, {})

    def test_disabled_training_profile_and_model_are_rejected(self):
        self.m.settings["allowed_profiles"] = ["anima"]
        with self.assertRaises(ValueError):
            self.m.create_project(USER, {
                "name": "Blocked SDXL", "profile": "sdxl",
                "base_model": "Illustrious-XL-v2.0.safetensors",
                "trigger": "x", "params": {"max_steps": 100,
                                          "resolution": 512}})
        self.m.settings["allowed_profiles"] = ["anima", "sdxl"]
        self.m.settings["allowed_sdxl_models"] = ["Illustrious-XL-v2.0.safetensors"]
        with self.assertRaises(ValueError):
            self.m.create_project(USER, {
                "name": "Blocked model", "profile": "sdxl",
                "base_model": "Juggernaut-XI-byRunDiffusion.safetensors",
                "trigger": "x", "params": {"max_steps": 100,
                                          "resolution": 512}})
        p = self.m.create_project(USER, {
            "name": "Allowed", "profile": "sdxl",
            "base_model": "Illustrious-XL-v2.0.safetensors",
            "trigger": "x", "params": {"max_steps": 100,
                                      "resolution": 512}})
        self.m.settings["allowed_sdxl_models"] = ["Other.safetensors"]
        with self.assertRaises(ValueError):
            self.m.submit_project(p["id"], USER, limits=None, usage={})

    def test_sdxl_hardware_requirement_blocks_submit(self):
        p = self.m.create_project(USER, {
            "name": "SDXL Test", "profile": "sdxl",
            "base_model": "Illustrious-XL-v2.0.safetensors",
            "trigger": "sx", "params": {"max_steps": 100,
                                        "resolution": 512}})
        for _ in range(5):
            self.m.add_gallery_image(p["id"], USER, self.png, "test")
        orig_gpu, orig_ram = self.m._gpu_info, self.m._ram_total_mb
        try:
            self.m._gpu_info = lambda: {"vram_total": 8188.0,
                                        "vram_free": 7000.0}
            self.m._ram_total_mb = lambda: 16000.0
            msg = self.m._hardware_error(p)
            self.assertIn("显存", msg)
            with self.assertRaises(ValueError):
                self.m.submit_project(p["id"], USER, limits=None, usage={})

            self.m._gpu_info = lambda: {"vram_total": 12288.0,
                                        "vram_free": 11000.0}
            self.m._ram_total_mb = lambda: 32000.0
            self.assertEqual(self.m._hardware_error(p), "")
            err, _ = self.m.submit_project(p["id"], USER, limits=None, usage={})
            self.assertIsNone(err)
            self.assertEqual(self.m._project(p["id"])["status"], "pending")
        finally:
            self.m._gpu_info, self.m._ram_total_mb = orig_gpu, orig_ram

    def test_chunk_upload_and_caption_edit(self):
        p = self.m.create_project(USER, {
            "name": "Chunk LoRA", "profile": "anima", "trigger": "chunk",
            "params": {"max_steps": 100, "resolution": 512}})
        data = open(self.png, "rb").read()
        st = self.m.upload_start(p["id"], USER, "a.png", len(data),
                                 limits={"max_image_mb": 25})
        self.m.upload_chunk(USER, st["upload_id"], 0, data[:100])
        self.m.upload_chunk(USER, st["upload_id"], 100, data[100:])
        item = self.m.upload_finish(USER, st["upload_id"], "caption here")
        self.assertEqual(item["caption"], "caption here")
        self.m.set_caption(p["id"], USER, item["id"], "new caption")
        payload = self.m.dataset_payload(p["id"], USER)
        self.assertEqual(payload["images"][0]["caption"], "new caption")
        with open(os.path.join(self.m._dataset_dir(p),
                               "img_%s.txt" % item["id"]), encoding="utf-8") as fh:
            self.assertIn("chunk", fh.read())

    def test_quota_rejects_too_many_steps_and_bad_image(self):
        p = self.m.create_project(USER, {
            "name": "Quota", "profile": "anima", "trigger": "q",
            "params": {"max_steps": 2500, "resolution": 1024}})
        for _ in range(5):
            self.m.add_gallery_image(p["id"], USER, self.png, "")
        err, quota = self.m.submit_project(
            p["id"], USER, limits={"max_train_steps": 1000,
                                   "max_train_resolution": 768}, usage={})
        self.assertIn("步数", err)
        self.assertEqual(quota["kind"], "max_train_steps")

    def test_retry_and_delete(self):
        p = self.create_project()
        self.m._project(p["id"])["status"] = "error"
        self.m._project(p["id"])["error"] = "boom"
        self.m.retry_project(p["id"], USER)
        self.assertEqual(self.m._project(p["id"])["status"], "draft")
        self.m.delete_project(p["id"], USER)
        self.assertIsNone(self.m._project(p["id"]))

    def test_lora_visibility(self):
        ldir = os.path.join(self.root, "ComfyUI", "models", "loras")
        name = "lora_anima_t_abcdef123456.safetensors"
        open(os.path.join(ldir, name), "wb").close()
        self.m.loras[name] = {
            "owner_id": "u_test", "project_id": "t_abcdef123456",
            "family": "anima", "public": False,
        }
        self.m.save_loras()
        self.assertEqual([x["name"] for x in self.m.list_visible_loras(USER)],
                         [name])
        self.assertEqual(
            self.m.list_visible_loras({"id": "u_other", "role": "user",
                                       "enabled": True}), [])
        self.assertEqual(
            [x["name"] for x in self.m.list_visible_loras(ADMIN)], [name])
        self.m.share_lora(name, True, ADMIN)
        self.assertTrue(self.m.lora_allowed(
            {"id": "u_other", "role": "user", "enabled": True}, name))

    def test_summary_hides_other_users_name(self):
        p = self.create_project()
        self.m.active_tid = p["id"]
        p["status"] = "running"
        s = self.m.summary(admin=False, user={"id": "u_other"})
        self.assertEqual(s["active"]["name"], "LoRA 训练")
        s2 = self.m.summary(admin=True)
        self.assertEqual(s2["active"]["name"], "Test LoRA")

    def test_trainer_status_and_health_shape(self):
        st = self.m.trainer_status()
        self.assertIn("installed", st)
        self.assertIn("ready", st)
        self.assertIn("install", st)


if __name__ == "__main__":
    unittest.main()
