# -*- coding: utf-8 -*-
"""按显存自动分档的生成上限。

默认从 nvidia-smi 读总显存；读不到时保守按 8GB 档处理。
也可以在安装根目录放 hardware.json：{"tier": "12gb"}，
或用环境变量 MGS_HARDWARE_TIER 覆盖，方便在非标准机器上手工调档。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "hardware.json")
_LOCK = threading.RLock()
_CACHE = {"t": 0.0, "data": None}
_CACHE_SECONDS = 60.0

TIERS = {
    # 4~6GB：只保证小图/短视频能跑
    "low": {
        "label": "4~6GB", "max_side": 1024, "max_pixels": 800_000,
        "max_count": 2, "source_megapixels": 0.8,
        "video_max_side": 640, "video_max_pixels": 307_200,
        "video_max_seconds": 2.0, "reserve_vram": 0.5,
    },
    # 6~10GB：当前 8GB 机器的默认档，保持原有行为
    "8gb": {
        "label": "8GB", "max_side": 1536, "max_pixels": 1_500_000,
        "max_count": 4, "source_megapixels": 1.3,
        "video_max_side": 960, "video_max_pixels": 480_000,
        "video_max_seconds": 3.0, "reserve_vram": 0.8,
    },
    # 10~16GB
    "12gb": {
        "label": "12GB", "max_side": 2048, "max_pixels": 2_500_000,
        "max_count": 6, "source_megapixels": 2.0,
        "video_max_side": 960, "video_max_pixels": 480_000,
        "video_max_seconds": 4.0, "reserve_vram": 1.0,
    },
    # 16~24GB
    "16gb": {
        "label": "16GB", "max_side": 2560, "max_pixels": 4_000_000,
        "max_count": 8, "source_megapixels": 3.0,
        "video_max_side": 960, "video_max_pixels": 480_000,
        "video_max_seconds": 5.0, "reserve_vram": 1.2,
    },
    # 24GB+
    "24gb": {
        "label": "24GB+", "max_side": 3072, "max_pixels": 6_000_000,
        "max_count": 8, "source_megapixels": 4.0,
        "video_max_side": 960, "video_max_pixels": 480_000,
        "video_max_seconds": 6.0, "reserve_vram": 1.5,
    },
}
DEFAULT_TIER = "8gb"


def _smi_path():
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if sys.platform.startswith("win"):
        for p in (r"C:\Windows\System32\nvidia-smi.exe",
                  r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.isfile(p):
                return p
    return ""


def _detect():
    """返回 (tier, vram_mb, gpu_name, source)。失败时按 8GB 档。"""
    override = str(os.environ.get("MGS_HARDWARE_TIER") or "").strip().lower()
    if not override:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            override = str((raw or {}).get("tier") or "").strip().lower()
        except Exception:
            override = ""
    if override in TIERS:
        return override, 0.0, "", "override"

    path = _smi_path()
    if not path:
        return DEFAULT_TIER, 0.0, "", "default"
    try:
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        out = subprocess.run(
            [path, "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, **kwargs)
        line = (out.stdout or "").strip().splitlines()[0]
        name, mb = [x.strip() for x in line.split(",", 1)]
        vram = float(mb or 0)
    except Exception:
        return DEFAULT_TIER, 0.0, "", "default"
    if vram <= 0:
        return DEFAULT_TIER, vram, name, "nvidia-smi"
    if vram < 6144:
        tier = "low"
    elif vram < 10240:
        tier = "8gb"
    elif vram < 16384:
        tier = "12gb"
    elif vram < 24576:
        tier = "16gb"
    else:
        tier = "24gb"
    return tier, vram, name, "nvidia-smi"


def limits(tier=None, refresh=False):
    """当前硬件档位。tier 显式传入时用于测试/手工覆盖。"""
    if tier in TIERS:
        data = dict(TIERS[tier])
        data["tier"] = tier
        data["vram_mb"] = 0.0
        data["gpu_name"] = ""
        data["source"] = "explicit"
        return data
    now = time.time()
    with _LOCK:
        cached = _CACHE.get("data")
        if (not refresh and cached and
                now - float(_CACHE.get("t") or 0) < _CACHE_SECONDS):
            return dict(cached)
        key, vram, name, source = _detect()
        data = dict(TIERS[key])
        data.update({"tier": key, "vram_mb": round(vram, 1),
                     "gpu_name": name, "source": source})
        _CACHE["data"] = data
        _CACHE["t"] = now
        return dict(data)


def public(tier=None, refresh=False):
    """给前端/日志用的精简字段。"""
    data = limits(tier, refresh)
    return {k: data.get(k) for k in (
        "tier", "label", "vram_mb", "gpu_name", "max_side", "max_pixels",
        "max_count", "source_megapixels", "video_max_side",
        "video_max_pixels", "video_max_seconds", "reserve_vram", "source")}


def cap_model_caps(caps, tier=None):
    """模型自身上限和硬件上限取较小值。"""
    hw = limits(tier)
    caps = caps if isinstance(caps, dict) else {}
    return {
        "max_side": min(int(caps.get("max_side") or hw["max_side"]),
                        int(hw["max_side"])),
        "max_pixels": min(int(caps.get("max_pixels") or hw["max_pixels"]),
                          int(hw["max_pixels"])),
    }


def fit_sizes(sizes, tier=None):
    """过滤掉超过硬件上限的画幅，至少保留一个可用的。"""
    hw = limits(tier)
    out = []
    for s in sizes or []:
        try:
            w, h = [int(x) for x in str(s).lower().split("x", 1)]
        except Exception:
            continue
        if w <= hw["max_side"] and h <= hw["max_side"] and \
                w * h <= hw["max_pixels"]:
            out.append("%dx%d" % (w, h))
    return out or ["512x512"]
