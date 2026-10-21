# -*- coding: utf-8 -*-
"""高危确认、查看器返回键和涂抹蒙版的静态回归测试。"""
import unittest

from _common import ROOT


class UISafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (ROOT / "app" / "webapp_templates" / "page.html").read_text(
            encoding="utf-8")

    def test_confirm_modal_requires_ack_when_requested(self):
        for text in ("id=\"confirmPop\"", "id=\"cfAck\"", "id=\"cfOk\"",
                     "function uiConfirm", "function cfTryOk",
                     "请先勾选上面的确认项", "ackWrap.classList.contains"):
            self.assertIn(text, self.page)
        self.assertGreaterEqual(self.page.count("uiConfirm({"), 14)

    def test_dangerous_actions_use_custom_confirmation(self):
        for snippet in ("title: uiT(\"删除这张图片\"",
                        "title: uiT(\"删除选中图片\"",
                        "title: adminT(\"彻底删除模型\"",
                        "title: plgT(\"高风险插件\"",
                        "title: uiT(\"删除团队\""):
            self.assertIn(snippet, self.page)

    def test_viewer_and_mask_have_large_back_buttons(self):
        for text in ("id=\"vwBack\"", "id=\"mkBack\"",
                     "document.getElementById(\"vwBack\").onclick = closeViewer",
                     "document.getElementById(\"mkBack\").onclick",
                     "closeMask(true)"):
            self.assertIn(text, self.page)
        self.assertIn("min-height: 44px", self.page)
        self.assertIn("min-height: 52px", self.page)

    def test_mask_is_translucent_and_exports_native_size(self):
        self.assertIn("cv.width = nw", self.page)
        self.assertIn("cv.height = nh", self.page)
        self.assertIn("background: rgba(0,0,0,.45)", self.page)
        self.assertIn("mctx.fillStyle = \"#000\"", self.page)
        self.assertIn("mctx.drawImage(src, 0, 0)", self.page)
        self.assertNotIn("mkCtx.fillStyle = \"#000\"", self.page)
        self.assertIn("原图加载失败", self.page)

    def test_touch_controls_disable_double_tap_zoom(self):
        self.assertIn("touch-action: manipulation", self.page)
        self.assertIn("touch-action: none", self.page)
        self.assertIn("env(safe-area-inset-top)", self.page)


if __name__ == "__main__":
    unittest.main()
