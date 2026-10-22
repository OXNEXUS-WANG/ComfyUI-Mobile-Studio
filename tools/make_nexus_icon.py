# -*- coding: utf-8 -*-
"""生成 Nexus 品牌图标：深色圆角底 + 斜体描线 N + 霓虹渐变。

输出（app/ 目录）：
  nexus-icon-1024.png
  nexus-icon-512.png
  nexus-icon-192.png
  nexus-icon-180.png
  nexus.ico
"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app")
S = 2048


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _vertical_gradient(size, stops):
    """stops: [(position 0..1, (r,g,b)), ...]。"""
    w = 8
    im = Image.new("RGB", (w, size))
    px = im.load()
    for y in range(size):
        t = y / float(max(1, size - 1))
        lo = stops[0]
        hi = stops[-1]
        for i in range(len(stops) - 1):
            if stops[i][0] <= t <= stops[i + 1][0]:
                lo, hi = stops[i], stops[i + 1]
                break
        span = max(1e-6, hi[0] - lo[0])
        c = _lerp(lo[1], hi[1], (t - lo[0]) / span)
        for x in range(w):
            px[x, y] = c
    return im.resize((size, size), Image.BICUBIC)


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def _line_mask(points, width):
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    d.line(points, fill=255, width=width, joint="curve")
    r = width // 2
    for x, y in (points[0], points[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=255)
    return m


def _four_point_star(draw, cx, cy, r, color):
    pts = [(cx, cy - r), (cx + r * 0.20, cy - r * 0.20),
           (cx + r, cy), (cx + r * 0.20, cy + r * 0.20),
           (cx, cy + r), (cx - r * 0.20, cy + r * 0.20),
           (cx - r, cy), (cx - r * 0.20, cy - r * 0.20)]
    draw.polygon(pts, fill=color)


def build():
    # 深空蓝黑底
    bg = _vertical_gradient(S, [
        (0.0, (7, 12, 25)),
        (0.45, (10, 20, 40)),
        (0.72, (8, 14, 29)),
        (1.0, (5, 8, 16)),
    ]).convert("RGBA")

    # 左上柔光 + 右下冷光
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([int(-0.25 * S), int(-0.30 * S), int(0.55 * S), int(0.48 * S)],
               fill=(40, 150, 255, 70))
    gd.ellipse([int(0.55 * S), int(0.55 * S), int(1.20 * S), int(1.20 * S)],
               fill=(120, 70, 255, 46))
    glow = glow.filter(ImageFilter.GaussianBlur(int(S * 0.13)))
    bg = Image.alpha_composite(bg, glow)

    # 低对比科技斜线
    grid = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(grid)
    step = int(S * 0.075)
    for x in range(-S, S * 2, step):
        dr.line([(x, 0), (x + S, S)], fill=(120, 210, 255, 10), width=2)
    for x in range(-S, S * 2, step * 2):
        dr.line([(x, S), (x + S, 0)], fill=(150, 120, 255, 7), width=1)
    bg = Image.alpha_composite(bg, grid)

    # 斜体 N 的骨架：左竖、对角线、右竖
    pts = [
        (int(0.215 * S), int(0.780 * S)),   # 左下
        (int(0.325 * S), int(0.220 * S)),   # 左上
        (int(0.635 * S), int(0.780 * S)),   # 右下
        (int(0.745 * S), int(0.220 * S)),   # 右上
    ]

    # 外发光
    outer_w = int(S * 0.185)
    outer = _line_mask(pts, outer_w)
    halo = outer.filter(ImageFilter.GaussianBlur(int(S * 0.045)))
    halo_img = Image.new("RGBA", (S, S), (54, 190, 255, 0))
    halo_img.putalpha(halo.point(lambda v: int(v * 0.42)))
    bg = Image.alpha_composite(bg, halo_img)

    # 深色描边，让 N 在亮色背景上也有边界
    edge = _line_mask(pts, int(S * 0.195))
    edge_img = Image.new("RGBA", (S, S), (2, 4, 10, 235))
    edge_img.putalpha(edge.point(lambda v: int(v * 0.92)))
    bg = Image.alpha_composite(bg, edge_img)

    # 渐变主描线
    grad = _vertical_gradient(S, [
        (0.00, (120, 240, 255)),
        (0.35, (70, 190, 255)),
        (0.68, (100, 120, 255)),
        (1.00, (190, 120, 255)),
    ]).convert("RGBA")
    main_mask = _line_mask(pts, int(S * 0.150))
    main = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    main.paste(grad, (0, 0), main_mask)
    bg = Image.alpha_composite(bg, main)

    # 描线内部挖空，形成“空心描边 N”
    inner_mask = _line_mask(pts, int(S * 0.072))
    inner = Image.new("RGBA", (S, S), (6, 11, 22, 255))
    inner.putalpha(inner_mask)
    bg = Image.alpha_composite(bg, inner)

    # 中心极细高光，像电路走线
    core_mask = _line_mask(pts, max(2, int(S * 0.016)))
    core = Image.new("RGBA", (S, S), (210, 252, 255, 255))
    core.putalpha(core_mask.point(lambda v: int(v * 0.88)))
    bg = Image.alpha_composite(bg, core)

    # 右上角信号星
    spark = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(spark)
    _four_point_star(sd, int(0.805 * S), int(0.195 * S),
                     int(0.050 * S), (225, 253, 255, 255))
    _four_point_star(sd, int(0.830 * S), int(0.245 * S),
                     int(0.020 * S), (120, 225, 255, 210))
    spark = spark.filter(ImageFilter.GaussianBlur(int(S * 0.002)))
    bg = Image.alpha_composite(bg, spark)

    # 圆角裁切 + 内描边
    mask = _rounded_mask(S, int(S * 0.22))
    bg.putalpha(ImageChops.multiply(bg.getchannel("A"), mask))
    border = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bd.rounded_rectangle([2, 2, S - 3, S - 3], radius=int(S * 0.22),
                         outline=(120, 210, 255, 54), width=max(2, S // 360))
    bg = Image.alpha_composite(bg, border)

    os.makedirs(OUT, exist_ok=True)
    master = bg.resize((1024, 1024), Image.LANCZOS)
    master.save(os.path.join(OUT, "nexus-icon-1024.png"), "PNG")
    for size, name in ((512, "nexus-icon-512.png"),
                       (192, "nexus-icon-192.png"),
                       (180, "nexus-icon-180.png")):
        bg.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT, name), "PNG")
    icon = bg.resize((256, 256), Image.LANCZOS)
    icon.save(os.path.join(OUT, "nexus.ico"), format="ICO",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                     (32, 32), (16, 16)])
    print("Nexus icon written to", OUT)


if __name__ == "__main__":
    build()
