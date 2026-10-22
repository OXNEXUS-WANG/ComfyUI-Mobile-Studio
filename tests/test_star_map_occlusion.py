# -*- coding: utf-8 -*-
"""星图连线遮挡的静态回归：前端画布和绘制入口不能被误删。"""
import unittest

from _common import APP


class StarMapOcclusionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (APP / "宇宙接口图.html").read_text(encoding="utf-8")

    def test_front_canvas_exists_above_planets(self):
        self.assertIn('id="linkFront"', self.html)
        self.assertIn("#linkFront{", self.html)
        self.assertIn("z-index:3400", self.html)
        self.assertIn("pointer-events:none", self.html)

    def test_front_draw_is_called_and_uses_depth(self):
        self.assertIn("function drawLinkOcclusion", self.html)
        self.assertIn("drawLinkOcclusion(now)", self.html)
        self.assertIn("n._sr", self.html)
        self.assertIn("n._zc", self.html)
        self.assertIn("z < pl.z - 1", self.html)

    def test_svg_links_stay_under_planets(self):
        # 原有 SVG 连线仍在星球下层；上层只补“正面”片段。
        self.assertIn('<svg id="links">', self.html)
        self.assertIn('<div id="planets"></div>', self.html)
        self.assertIn('<canvas id="linkFront"></canvas>', self.html)

    def test_bottom_hud_does_not_overlap_in_english(self):
        # 英文图例更长：HUD 用 grid 把提示放到图例上方，
        # 控件按实际 HUD 高度抬升；窄屏 guide 换行并让开按钮。
        self.assertIn('grid-template-areas:"hint hint" "legend stats"',
                      self.html)
        self.assertIn("grid-area:hint", self.html)
        self.assertIn("bottom:calc(var(--hud-h, 58px) + 10px)", self.html)
        self.assertNotIn("position:absolute;left:50%;bottom:40px", self.html)
        self.assertIn("flex-wrap:wrap;justify-content:flex-end", self.html)
        self.assertIn("bottom:calc(100px + 40px)", self.html)
        self.assertIn("@media (max-width:300px)", self.html)
        self.assertIn(".ctl{padding:5px 6px;font-size:9px", self.html)
        self.assertIn("function syncHudHeight()", self.html)
        self.assertIn("addEventListener('mg-lang'", self.html)

    def test_link_front_canvas_reapplies_dpr_after_resize(self):
        # 设置 canvas.width/height 会把 2D 上下文重置成 identity；
        # 如果只在 dpr 变化时 setTransform，窗口缩放后前置连线会错位。
        start = self.html.index("function resizeLinkFront")
        end = self.html.index("function renderStars", start)
        block = self.html[start:end]
        self.assertIn("lfctx.setTransform(dpr, 0, 0, dpr, 0, 0);", block)
        self.assertNotIn("if(lfDpr !== dpr)", block)


if __name__ == "__main__":
    unittest.main()
