#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用本地 ComfyUI 出图。

给 QQ / 微信 等渠道当后端用：收到提示词 -> 出图 -> 返回图片路径。

用法:
    python gen_image.py "一个女孩，银发红瞳，站在夜晚的城堡前，月光"
    python gen_image.py "1girl, solo, silver hair, red eyes, castle, night, moonlight"
    python gen_image.py "..." --size 1216x832 --steps 30 --seed 42

提示词中文/英文都可以：
  - 含中文 -> 自动走 Argos 翻译节点翻成英文再喂给模型
  - 纯英文 -> 直接送进模型（不做翻译，避免把英文翻坏）

成功时最后一行输出图片的绝对路径，失败时退出码非 0 并输出原因。
"""

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request

SERVER = "http://127.0.0.1:8188"
COMFY_OUTPUT = r"D:\AI\ComfyUI_windows_portable\ComfyUI\output"
# 生成后复制一份到这里，方便渠道侧取用
DELIVER_DIR = r"D:\AI\ComfyUI_windows_portable\generated"

NEGATIVE = (
    "lowres, worst quality, low quality, low score, bad score, average score, "
    "bad anatomy, bad hands, bad proportions, missing fingers, extra digits, "
    "fewer digits, extra fingers, fused fingers, extra limbs, text, error, "
    "signature, watermark, username, blurry, jpeg artifacts, cropped"
)

CHECKPOINT = "Illustrious-XL-v2.0.safetensors"


def has_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def build_workflow(prompt, width, height, steps, cfg, seed, use_translate):
    """拼 ComfyUI 的 API 工作流。use_translate=True 时走 Argos 翻译节点。"""
    nodes = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEGATIVE, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler_ancestral",
                "scheduler": "normal",
                "denoise": 1,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "qq", "images": ["8", 0]},
        },
    }

    if use_translate:
        nodes["10"] = {
            "class_type": "ArgosTranslateTextNode",
            "inputs": {
                "from_translate": "chinese",
                "to_translate": "english",
                "text": prompt,
            },
        }
        nodes["6"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": ["10", 0], "clip": ["4", 1]},
        }
    else:
        nodes["6"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt, "clip": ["4", 1]},
        }

    return {"prompt": nodes, "client_id": "gen_image_cli"}


def post_json(path, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SERVER + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def get_json(path, timeout=30):
    with urllib.request.urlopen(SERVER + path, timeout=timeout) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", help="提示词，中文或英文")
    ap.add_argument("--size", default="832x1216", help="宽x高，默认 832x1216")
    ap.add_argument("--steps", type=int, default=28)
    ap.add_argument("--cfg", type=float, default=6.0)
    ap.add_argument("--seed", type=int, default=-1, help="-1 表示随机")
    ap.add_argument("--timeout", type=int, default=600, help="等待出图的秒数上限")
    args = ap.parse_args()

    try:
        width, height = (int(v) for v in args.size.lower().split("x"))
    except Exception:
        print("ERROR: --size 格式应为 宽x高，例如 832x1216", file=sys.stderr)
        return 2

    # ComfyUI 活着吗
    try:
        get_json("/system_stats", timeout=8)
    except Exception as e:
        print(
            "ERROR: 连不上 ComfyUI (%s)。请先双击桌面 ComfyUI 快捷方式启动。\n  %s"
            % (SERVER, e),
            file=sys.stderr,
        )
        return 3

    seed = args.seed
    if seed < 0:
        seed = int.from_bytes(os.urandom(4), "little") % (2 ** 31)

    # 中文先用手机网页那套词表转成 danbooru 标签（双马尾 -> twintails），
    # 词表覆盖不到的残句再退回 ComfyUI 里的 Argos 翻译节点。
    prompt_text = args.prompt
    prompt_en = ""
    if has_chinese(prompt_text):
        try:
            from app_core import USE_PROMPT_OPTIMIZER, optimize_prompt
            if USE_PROMPT_OPTIMIZER:
                cand = optimize_prompt(prompt_text)
                if cand and not has_chinese(cand):
                    prompt_en = cand
        except Exception:
            pass
    use_translate = (not prompt_en) and has_chinese(prompt_text)

    workflow = build_workflow(
        prompt_en or prompt_text, width, height, args.steps, args.cfg,
        seed, use_translate
    )

    try:
        resp = post_json("/prompt", workflow)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("ERROR: 提交失败 HTTP %s\n%s" % (e.code, body[:1500]), file=sys.stderr)
        return 4

    pid = resp.get("prompt_id")
    if not pid:
        print("ERROR: 没拿到 prompt_id: %s" % resp, file=sys.stderr)
        return 4

    deadline = time.time() + args.timeout
    images = None
    while time.time() < deadline:
        time.sleep(3)
        try:
            hist = get_json("/history/" + pid)
        except Exception:
            continue
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                print("ERROR: 出图失败\n%s" % json.dumps(status, ensure_ascii=False)[:1500],
                      file=sys.stderr)
                return 5
            for out in (entry.get("outputs") or {}).values():
                if out.get("images"):
                    images = out["images"]
                    break
            break

    if not images:
        print("ERROR: %ds 内没出图（超时）" % args.timeout, file=sys.stderr)
        return 6

    src = os.path.join(COMFY_OUTPUT, images[0]["filename"])
    if not os.path.exists(src):
        print("ERROR: 输出文件不存在: %s" % src, file=sys.stderr)
        return 7

    os.makedirs(DELIVER_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(DELIVER_DIR, "%s_%s" % (stamp, images[0]["filename"]))
    shutil.copy2(src, dst)

    print(dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
