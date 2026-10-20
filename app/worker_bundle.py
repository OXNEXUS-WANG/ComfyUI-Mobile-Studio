# -*- coding: utf-8 -*-
"""生成“算力节点部署包”：主机扫描模型/节点，打包 worker 与部署脚本。

部署包不包含模型权重，只包含清单；目标机器自行准备 ComfyUI 和模型。
"""
import io
import json
import os
import re
import socket
import time
import zipfile

MODEL_DIRS = (
    "checkpoints", "diffusion_models", "text_encoders", "vae", "loras",
    "upscale_models", "controlnet", "clip_vision", "embeddings",
    "style_models", "gligen", "hypernetworks", "photomaker",
    "animatediff_models", "animatediff_motion_lora",
)
MODEL_EXT = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".sft", ".onnx")


def _comfy_version(root):
    path = os.path.join(root, "ComfyUI", "comfyui_version.py")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            m = re.search(r'__version__\s*=\s*["\']([^"\']+)', fh.read())
        return m.group(1) if m else ""
    except OSError:
        return ""


def scan_models(root):
    out = []
    base = os.path.join(root, "ComfyUI", "models")
    for folder in MODEL_DIRS:
        top = os.path.join(base, folder)
        if not os.path.isdir(top):
            continue
        for cur, dirs, files in os.walk(top):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".cache")]
            for name in files:
                if not name.lower().endswith(MODEL_EXT):
                    continue
                path = os.path.join(cur, name)
                rel = os.path.relpath(path, top).replace("\\", "/")
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                out.append({"folder": folder, "name": rel, "size": size})
    out.sort(key=lambda x: (x["folder"], x["name"].lower()))
    return out


def scan_custom_nodes(root):
    base = os.path.join(root, "ComfyUI", "custom_nodes")
    out = []
    try:
        for name in os.listdir(base):
            path = os.path.join(base, name)
            if not os.path.isdir(path) or name in ("__pycache__",):
                continue
            out.append(name)
    except OSError:
        pass
    out.sort(key=str.lower)
    return out


def build_profile(root, central_url):
    return {
        "format": "comfyui-mobile-worker-bundle",
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": socket.gethostname(),
        "central_url": central_url,
        "comfyui_version": _comfy_version(root),
        "models": scan_models(root),
        "custom_nodes": scan_custom_nodes(root),
        "note": "模型文件不随部署包分发；目标机器按清单自行准备。",
    }


def _add_file(zf, path, arcname):
    if os.path.isfile(path):
        zf.write(path, arcname)


def build_bundle(root, central_url, worker_name="", include_cert=True):
    root = os.path.abspath(root)
    profile = build_profile(root, central_url)
    if worker_name:
        profile["suggested_name"] = worker_name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("node_profile.json",
                    json.dumps(profile, ensure_ascii=False, indent=2))
        worker = os.path.join(root, "worker")
        for name in ("worker_agent.py", "README_算力节点.md",
                     "启动算力节点.bat", "暂停接单.bat", "恢复接单.bat",
                     "接入算力节点.bat", "deploy_node.py",
                     "部署并启动.bat", "仅检测环境.bat", "README_部署包.txt"):
            _add_file(zf, os.path.join(worker, name), name)
        lock = os.path.join(root, "installer", "versions.lock.json")
        if not os.path.isfile(lock):
            lock = os.path.join(root, "versions.lock.json")
        if os.path.isfile(lock):
            _add_file(zf, lock, "versions.lock.json")
        else:
            zf.writestr("versions.lock.json", json.dumps({
                "schema": 1,
                "comfyui": {"version": profile.get("comfyui_version") or "",
                            "source": "installed-host"},
                "note": "主机没有留下完整锁文件；目标机器请以主机实际版本为准。",
            }, ensure_ascii=False, indent=2))
        if include_cert:
            _add_file(zf, os.path.join(root, "cert.pem"), "cert.pem")
        zf.writestr("生成说明.txt",
                    "由 ComfyUI Mobile Studio 主机生成。\n"
                    "部署包不含模型权重和账号密码。\n"
                    "先运行：仅检测环境.bat\n"
                    "再运行：部署并启动.bat\n")
    return buf.getvalue(), profile
