# -*- coding: utf-8 -*-
"""训练页、接口和英文文案的静态回归测试。"""
import unittest

from _common import ROOT


class TrainingUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "app" / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")
        cls.js = (ROOT / "app" / "webapp_templates" / "training.js").read_text(
            encoding="utf-8")
        cls.i18n = (ROOT / "app" / "i18n.js").read_text(encoding="utf-8")
        cls.server = (ROOT / "app" / "web_server.py").read_text(
            encoding="utf-8")

    def test_training_tab_and_modals_exist(self):
        for text in ("id=\"trainTab\"", "id=\"view-train\"",
                     "id=\"trainNewPop\"", "id=\"trainDetailPop\"",
                     "id=\"trainGalleryPop\"", "training.js?v=",
                     "id=\"trainAdminContent\""):
            self.assertIn(text, self.page)
        self.assertIn("#trainNewPop.on", self.page)

    def test_training_page_uses_safe_controls(self):
        for text in ("uiConfirm", "upload_chunk", "data-no-i18n",
                     "reasonText", "trainRenderAdmin", "loadTraining"):
            self.assertIn(text, self.js)
        self.assertIn("async function uploadFiles", self.js)
        self.assertIn("async function openGallery", self.js)
        self.assertIn("settings", self.js)

    def test_api_routes_are_wired(self):
        for text in ("/api/training", "/api/admin/training",
                     "/api/training/upload_chunk",
                     "/api/training/preview/", "training_manager"):
            self.assertIn(text, self.server)

    def test_english_training_strings_exist(self):
        for text in ("'LoRA 训练': 'LoRA training'",
                     "'新建训练': 'New training'",
                     "'训练队列': 'Training queue'",
                     "'提交审核': 'Submit for review'"):
            self.assertIn(text, self.i18n)

    def test_anima_lora_support(self):
        profiles = (ROOT / "app" / "model_profiles.py").read_text(
            encoding="utf-8")
        workflows = (ROOT / "app" / "comfy_workflows.py").read_text(
            encoding="utf-8")
        self.assertIn('"supports_lora": True', profiles)
        self.assertIn("loras=None", workflows)
        self.assertIn("LoraLoaderModelOnly", workflows)


if __name__ == "__main__":
    unittest.main()
