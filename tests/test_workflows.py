# -*- coding: utf-8 -*-
import unittest

from _common import APP  # noqa: F401
import app_core
import comfy_workflows


class WorkflowTests(unittest.TestCase):
    def test_pony_prefix_is_concatenated(self):
        wf = comfy_workflows.build_workflow(
            "1girl", "", 832, 1216, 25, 6.0, 1, False,
            ckpt="x.safetensors", prefix="score_9, score_8_up, ")
        nodes = wf["prompt"]
        self.assertEqual(nodes["54"]["class_type"], "CLIPTextEncode")
        self.assertEqual(nodes["54"]["inputs"]["text"], "score_9, score_8_up, ")
        self.assertEqual(nodes["55"]["class_type"], "ConditioningConcat")

    def test_pony_prefix_helper(self):
        name = "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"
        self.assertEqual(app_core.pony_prefix_for(name, "1girl"),
                         app_core.PONY_PREFIX)
        self.assertEqual(
            app_core.pony_prefix_for(name, "score_9, 1girl"), "")

    def test_no_prefix_keeps_prompt_direct(self):
        wf = comfy_workflows.build_workflow(
            "1girl", "", 832, 1216, 25, 6.0, 1, False,
            ckpt="x.safetensors")
        self.assertNotIn("54", wf["prompt"])
        self.assertEqual(wf["prompt"]["6"]["inputs"]["text"], "1girl")

    def test_fit_size_snaps_and_respects_limits(self):
        self.assertEqual(app_core.fit_size(832, 1216, 512, 1536, 1500000),
                         (832, 1216))
        self.assertEqual(app_core.fit_size(1001, 999, 512, 1536, 1500000),
                         (1008, 992))
        w, h = app_core.fit_size(1536, 1536, 512, 1536, 1500000)
        self.assertLessEqual(w * h, 1500000)
        w, h = app_core.fit_size(2048, 2048, 256, 960, 480000)
        self.assertLessEqual(max(w, h), 960)
        self.assertLessEqual(w * h, 480000)
        self.assertEqual(w % 16, 0)
        self.assertEqual(h % 16, 0)

    def test_video_size_defaults_are_16_aligned(self):
        for size in app_core.VIDEO_SIZES:
            w, h = (int(x) for x in size.split("x"))
            self.assertEqual(w % 16, 0, size)
            self.assertEqual(h % 16, 0, size)
            self.assertLessEqual(w * h, app_core.VIDEO_MAX_PIXELS, size)
            self.assertLessEqual(max(w, h), app_core.VIDEO_MAX_SIDE, size)


if __name__ == "__main__":
    unittest.main()
