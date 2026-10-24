# -*- coding: utf-8 -*-
"""按显存分档的生成上限测试（不依赖本机 nvidia-smi）。"""
import sys
import unittest

from _common import ROOT

sys.path.insert(0, str(ROOT / "worker"))
import worker_agent  # noqa: E402

import hardware_profile  # noqa: E402


class HardwareProfileTests(unittest.TestCase):
    def test_tiers_scale_with_vram(self):
        expect = {
            "low": (1024, 800000, 2),
            "8gb": (1536, 1500000, 4),
            "12gb": (2048, 2500000, 6),
            "16gb": (2560, 4000000, 8),
            "24gb": (3072, 6000000, 8),
        }
        for tier, (side, pixels, count) in expect.items():
            data = hardware_profile.limits(tier)
            self.assertEqual(data["max_side"], side, tier)
            self.assertEqual(data["max_pixels"], pixels, tier)
            self.assertEqual(data["max_count"], count, tier)

    def test_model_caps_never_exceed_hardware(self):
        caps = {"max_side": 4096, "max_pixels": 8_000_000}
        low = hardware_profile.cap_model_caps(caps, "low")
        self.assertEqual(low, {"max_side": 1024, "max_pixels": 800000})
        high = hardware_profile.cap_model_caps(caps, "16gb")
        self.assertEqual(high, {"max_side": 2560, "max_pixels": 4000000})

    def test_size_list_is_filtered_per_tier(self):
        sizes = ["832x1216", "1536x1536", "512x512"]
        self.assertEqual(
            hardware_profile.fit_sizes(sizes, "8gb"),
            ["832x1216", "512x512"])
        self.assertEqual(
            hardware_profile.fit_sizes(sizes, "low"), ["512x512"])

    def test_worker_caps_follow_vram(self):
        self.assertEqual(worker_agent.caps_for_vram(4000), (800_000, 2))
        self.assertEqual(worker_agent.caps_for_vram(8151), (1_500_000, 4))
        self.assertEqual(worker_agent.caps_for_vram(12288), (2_500_000, 6))
        self.assertEqual(worker_agent.caps_for_vram(24576), (6_000_000, 8))

    def test_video_seconds_follow_tier(self):
        self.assertEqual(hardware_profile.limits("low")["video_max_seconds"],
                         2.0)
        self.assertEqual(hardware_profile.limits("8gb")["video_max_seconds"],
                         3.0)
        self.assertEqual(hardware_profile.limits("24gb")["video_max_seconds"],
                         6.0)


if __name__ == "__main__":
    unittest.main()
