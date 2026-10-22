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


if __name__ == "__main__":
    unittest.main()
