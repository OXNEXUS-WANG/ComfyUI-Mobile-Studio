# -*- coding: utf-8 -*-
"""生成 CometInk 彗墨品牌图标：深色圆角底 + 彗星墨迹 C。

输出（app/ 目录）：
  cometink-icon-1024.png
  cometink-icon-512.png
  cometink-icon-192.png
  cometink-icon-180.png
  cometink.ico
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

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
        lo, hi = stops[0], stops[-1]
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


def _polar(cx, cy, r, deg):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def _comet_stroke(cx, cy, radius, start_deg, end_deg, steps,
                  head_w, tail_w, pad=0):
    """沿一段圆弧画一条由粗到细的彗星/毛笔轨迹。"""
    mask = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(mask)
    pts = []
    widths = []
    for i in range(steps + 1):
        t = i / float(steps)
        angle = start_deg + (end_deg - start_deg) * t
        pts.append(_polar(cx, cy, radius, angle))
        # 靠近彗核粗，靠近尾端细；pad 用于生成深色描边。
        w = head_w * (1.0 - t) ** 0.82 + tail_w + pad
        widths.append(max(2.0, w))
    for i in range(steps):
        w = (widths[i] + widths[i + 1]) * 0.5
        draw.line([pts[i], pts[i + 1]], fill=255, width=int(w),
                  joint="curve")
        for x, y in (pts[i], pts[i + 1]):
            r = w * 0.5
            draw.ellipse([x - r, y - r, x + r, y + r], fill=255)
    return mask, pts, widths


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

    # 背后一圈很淡的轨道
    ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ring)
    rd.ellipse([int(0.12 * S), int(0.30 * S), int(0.88 * S), int(0.70 * S)],
               outline=(120, 210, 255, 34), width=max(2, int(S * 0.003)))
    rd.ellipse([int(0.20 * S), int(0.37 * S), int(0.80 * S), int(0.63 * S)],
               outline=(150, 120, 255, 22), width=max(2, int(S * 0.002)))
    bg = Image.alpha_composite(bg, ring)

    # C 形彗星轨迹：右上角是彗核，向左下绕一圈后收尾。
    cx, cy = 0.50 * S, 0.50 * S
    radius = 0.292 * S
    start, end = 310.0, 50.0
    head_w = 0.130 * S
    tail_w = 0.022 * S
    steps = 360

    # 深色描边，保证亮色背景上也有边界
    edge_mask, _, _ = _comet_stroke(
        cx, cy, radius, start, end, steps, head_w, tail_w,
        pad=int(S * 0.016))
    edge = Image.new("RGBA", (S, S), (2, 4, 10, 235))
    edge.putalpha(edge_mask.point(lambda v: int(v * 0.92)))
    bg = Image.alpha_composite(bg, edge)

    # 主轨迹：青色到紫色渐变
    main_mask, pts, widths = _comet_stroke(
        cx, cy, radius, start, end, steps, head_w, tail_w)
    grad = _vertical_gradient(S, [
        (0.00, (120, 240, 255)),
        (0.35, (70, 190, 255)),
        (0.68, (110, 130, 255)),
        (1.00, (190, 120, 255)),
    ]).convert("RGBA")
    main = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    main.paste(grad, (0, 0), main_mask)
    bg = Image.alpha_composite(bg, main)

    # 轨迹中心细高光，像蘸满墨的笔锋
    core_mask, _, _ = _comet_stroke(
        cx, cy, radius, start, end, steps,
        head_w * 0.20, max(1.0, tail_w * 0.20))
    core = Image.new("RGBA", (S, S), (220, 252, 255, 255))
    core.putalpha(core_mask.point(lambda v: int(v * 0.72)))
    bg = Image.alpha_composite(bg, core)

    # 彗核：发光圆点 + 四角星
    hx, hy = _polar(cx, cy, radius, start)
    halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    for rr, aa in ((0.16, 34), (0.115, 64), (0.082, 110)):
        r = rr * S
        hd.ellipse([hx - r, hy - r, hx + r, hy + r],
                   fill=(120, 235, 255, aa))
    halo = halo.filter(ImageFilter.GaussianBlur(int(S * 0.020)))
    bg = Image.alpha_composite(bg, halo)

    head = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hdd = ImageDraw.Draw(head)
    r = 0.072 * S
    hdd.ellipse([hx - r, hy - r, hx + r, hy + r],
                fill=(228, 253, 255, 255))
    r2 = 0.040 * S
    hdd.ellipse([hx - r2, hy - r2, hx + r2, hy + r2],
                fill=(255, 255, 255, 255))
    _four_point_star(hdd, hx, hy, 0.112 * S, (210, 250, 255, 220))
    _four_point_star(hdd, hx, hy, 0.062 * S, (255, 255, 255, 255))
    bg = Image.alpha_composite(bg, head)

    # 尾端墨滴
    drops = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(drops)
    tx, ty = pts[-1]
    for dx, dy, rr, col in (
            (0.018, -0.012, 0.020, (150, 225, 255, 220)),
            (0.046, 0.022, 0.014, (180, 160, 255, 210)),
            (0.012, 0.040, 0.011, (120, 210, 255, 190)),
            (0.060, -0.018, 0.008, (210, 150, 255, 170)),
            (-0.018, 0.036, 0.007, (150, 230, 255, 160))):
        x, y = tx + dx * S, ty + dy * S
        r = rr * S
        dd.ellipse([x - r, y - r, x + r, y + r], fill=col)
    drops = drops.filter(ImageFilter.GaussianBlur(int(S * 0.0015)))
    bg = Image.alpha_composite(bg, drops)

    # 圆角裁切 + 内描边
    mask = _rounded_mask(S, int(S * 0.22))
    bg.putalpha(ImageChops.multiply(bg.getchannel("A"), mask))
    border = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(border)
    bd.rounded_rectangle([2, 2, S - 3, S - 3], radius=int(S * 0.22),
                         outline=(120, 210, 255, 54), width=max(2, S // 360))
    bg = Image.alpha_composite(bg, border)

    os.makedirs(OUT, exist_ok=True)
    bg.resize((1024, 1024), Image.LANCZOS).save(
        os.path.join(OUT, "cometink-icon-1024.png"), "PNG")
    for size, name in ((512, "cometink-icon-512.png"),
                       (192, "cometink-icon-192.png"),
                       (180, "cometink-icon-180.png")):
        bg.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT, name), "PNG")
    icon = bg.resize((256, 256), Image.LANCZOS)
    for name in ("cometink.ico", "comfyui.ico"):
        icon.save(os.path.join(OUT, name), format="ICO",
                  sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                         (32, 32), (16, 16)])
    print("CometInk icon written to", OUT)


if __name__ == "__main__":
    build()
