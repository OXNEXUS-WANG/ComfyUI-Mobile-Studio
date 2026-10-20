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


if __name__ == "__main__":
    unittest.main()
