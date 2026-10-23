#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""在第二台机器上检测 ComfyUI/模型，并接入中央算力节点。

由主机生成部署包时自动复制；只用标准库。模型不随包分发，只做清单比对。
"""
import argparse
import html
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODEL_DIRS = (
    "checkpoints", "diffusion_models", "text_encoders", "vae", "loras",
    "upscale_models", "controlnet", "clip_vision", "embeddings",
    "style_models", "gligen", "hypernetworks", "photomaker",
    "animatediff_models", "animatediff_motion_lora",
)
MODEL_EXT = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".sft", ".onnx")


def load_profile():
    path = HERE / "node_profile.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def valid_comfy(path):
    if not path:
        return False
    p = Path(path)
    return (p / "ComfyUI" / "main.py").is_file() and \
        (p / "python_embeded" / "python.exe").is_file()


def find_comfy(arg=""):
    candidates = [arg, os.environ.get("COMFYUI_DIR", "")]
    candidates += [
        str(HERE), str(HERE.parent),
        r"D:\CometInk",
        r"C:\CometInk",
        str(Path.home() / "ComfyUI_windows_portable"),
        str(Path.home() / "Desktop" / "ComfyUI_windows_portable"),
    ]
    for c in candidates:
        if c and valid_comfy(c):
            return str(Path(c).resolve())
    print("没有自动找到 ComfyUI。")
    try:
        c = input("请输入 ComfyUI_windows_portable 目录：").strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        return ""
    return str(Path(c).resolve()) if valid_comfy(c) else ""


def scan_local(comfy):
    base = Path(comfy) / "ComfyUI" / "models"
    found = {}
    for folder in MODEL_DIRS:
        top = base / folder
        if not top.is_dir():
            continue
        for p in top.rglob("*"):
            if p.is_file() and p.suffix.lower() in MODEL_EXT:
                rel = str(p.relative_to(top)).replace("\\", "/")
                found[(folder, rel)] = p.stat().st_size
    return found


def compare(profile, comfy):
    local = scan_local(comfy)
    missing = []
    size_bad = []
    for item in profile.get("models") or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("folder") or ""), str(item.get("name") or ""))
        want = int(item.get("size") or 0)
        if key not in local:
            missing.append({"folder": key[0], "name": key[1], "want": want,
                            "have": None})
        elif want and local[key] != want:
            size_bad.append({"folder": key[0], "name": key[1], "want": want,
                             "have": local[key]})
    nodes = []
    custom = Path(comfy) / "ComfyUI" / "custom_nodes"
    have_nodes = {p.name for p in custom.iterdir() if p.is_dir()} \
        if custom.is_dir() else set()
    for name in profile.get("custom_nodes") or []:
        if name not in have_nodes:
            nodes.append(str(name))
    return local, missing, size_bad, nodes


def comfy_version(comfy):
    path = Path(comfy) / "ComfyUI" / "comfyui_version.py"
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'__version__\s*=\s*["\']([^"\']+)', text)
        return m.group(1) if m else ""
    except OSError:
        return ""


def comfy_running():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats",
                                    timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


def human(n):
    try:
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return "%.1f%s" % (n, unit)
            n /= 1024
    except Exception:
        pass
    return "?"


def make_report(profile, comfy, missing, size_bad, nodes, version):
    def rows(items, kind):
        if not items:
            return ""
        out = []
        for x in items:
            if kind == "node":
                out.append("<tr><td>%s</td><td>缺少</td><td>—</td><td>—</td></tr>"
                           % html.escape(x))
            else:
                out.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                           % (html.escape(x["folder"] + "/" + x["name"]),
                              "缺少" if kind == "missing" else "大小不一致",
                              human(x.get("want")), human(x.get("have"))))
        return "".join(out)

    total = len(profile.get("models") or [])
    ok = total - len(missing) - len(size_bad)
    status = "环境完整，可以接入" if not missing and not size_bad and not nodes \
        else "环境不完整，请先补齐模型/节点"
    generated = profile.get("generated_at") or ""
    profile_ver = profile.get("comfyui_version") or ""
    ver_note = ""
    if profile_ver and version and profile_ver != version:
        ver_note = ('<p class="warn">ComfyUI 版本不同：主机 %s / 本机 %s。'
                    '建议使用相同版本。</p>' % (html.escape(profile_ver),
                                                 html.escape(version)))
    model_rows = (rows(missing, "missing") + rows(size_bad, "size"))
    node_rows = rows(nodes, "node")
    table = ""
    if model_rows:
        table += ('<h2>缺少或大小不一致的模型</h2><table>'
                  '<tr><th>文件</th><th>状态</th><th>主机大小</th><th>本机大小</th></tr>'
                  + model_rows + '</table>')
    if node_rows:
        table += ('<h2>缺少的自定义节点目录</h2><table>'
                  '<tr><th>目录</th><th>状态</th><th></th><th></th></tr>'
                  + node_rows + '</table>')
    if not table:
        table = '<div class="okbox">模型和自定义节点清单全部匹配。</div>'
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>节点环境检测 · ComfyUI Mobile Studio</title>
<style>
:root{--bg:#070b14;--card:rgba(20,28,48,.72);--line:rgba(150,180,255,.16);
--tx:#e8eefc;--tx2:#aab8d4;--ac:#7fb0ff;--ok:#7ee0b8;--bad:#ff9aa5;--warn:#ffd18a}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1000px 500px at 75%% -10%%,#18325a 0,transparent 60%%),var(--bg);
color:var(--tx);font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif;padding:28px}
.wrap{max-width:980px;margin:0 auto}.head{padding:22px 24px;background:var(--card);
border:1px solid var(--line);border-radius:18px;backdrop-filter:blur(14px);margin-bottom:16px}
h1{margin:0 0 4px;font-size:22px;letter-spacing:.02em}.sub{color:var(--tx2)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0}
.stat{padding:14px 16px;background:var(--card);border:1px solid var(--line);border-radius:14px}
.stat b{display:block;font-size:22px;color:var(--ac)}.stat span{color:var(--tx2);font-size:12px}
.card{padding:20px 22px;background:var(--card);border:1px solid var(--line);border-radius:18px;
backdrop-filter:blur(14px)}h2{font-size:15px;margin:18px 0 8px}
table{width:100%%;border-collapse:collapse;margin:6px 0 12px}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid rgba(150,180,255,.10);font-size:13px}
th{color:var(--tx2);font-weight:500}.ok{color:var(--ok)}.bad{color:var(--bad)}
.warn{color:var(--warn)}.okbox{padding:16px;border-radius:12px;background:rgba(126,224,184,.10);
border:1px solid rgba(126,224,184,.28);color:var(--ok)}.foot{color:var(--tx2);font-size:12px;margin-top:14px}
</style><body><div class="wrap">
<div class="head"><h1>节点环境检测</h1>
<div class="sub">ComfyUI Mobile Studio · 部署包生成的本地报告</div>
<div class="grid">
<div class="stat"><b class="%s">%s</b><span>%s</span></div>
<div class="stat"><b>%d</b><span>主机模型清单</span></div>
<div class="stat"><b>%d</b><span>缺少/大小不一致</span></div>
</div></div>
<div class="card"><p><b>ComfyUI：</b>%s<br><b>版本：</b>%s<br><b>检测时间：</b>%s</p>
%s%s%s<div class="foot">模型不会自动复制。缺什么就把主机对应的文件按相同目录结构复制到本机。
完成后重新运行「仅检测环境.bat」。</div></div></div></body></html>""" % (
        "ok" if not missing and not size_bad and not nodes else "bad",
        html.escape(status), html.escape(comfy), total,
        len(missing) + len(size_bad), html.escape(comfy),
        html.escape(version or "未知"), html.escape(generated), ver_note,
        table, "")


def run_join(comfy, server, code, name):
    py = Path(comfy) / "python_embeded" / "python.exe"
    agent = HERE / "worker_agent.py"
    cfg = HERE / "worker_agent.json"
    cert = HERE / "cert.pem"
    args = [str(py), str(agent), "join", "--server", server,
            "--code", code, "--name", name,
            "--comfy", "http://127.0.0.1:8188",
            "--config", str(cfg), "--force"]
    if cert.is_file():
        args += ["--ca", str(cert)]
    else:
        args += ["--insecure"]
    print("接入中央：" + server)
    return subprocess.run(args, cwd=str(HERE)).returncode == 0


def start_agent(comfy):
    py = Path(comfy) / "python_embeded" / "python.exe"
    agent = HERE / "worker_agent.py"
    cfg = HERE / "worker_agent.json"
    args = [str(py), str(agent), "run", "--config", str(cfg)]
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(args, cwd=str(HERE), creationflags=flags)
    print("已启动算力节点，控制页：http://127.0.0.1:8199/")
    try:
        webbrowser.open("http://127.0.0.1:8199/")
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description="ComfyUI 节点环境检测与接入")
    ap.add_argument("--comfy", default="")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--server", default="")
    ap.add_argument("--code", default="")
    ap.add_argument("--name", default="")
    args = ap.parse_args(argv)
    profile = load_profile()
    comfy = find_comfy(args.comfy)
    if not comfy:
        print("未找到有效的 ComfyUI 目录。")
        return 2
    local, missing, size_bad, nodes = compare(profile, comfy)
    version = comfy_version(comfy)
    print("ComfyUI:", comfy)
    print("模型清单:", len(profile.get("models") or []),
          "缺少:", len(missing), "大小不一致:", len(size_bad),
          "缺少节点目录:", len(nodes))
    report = HERE / "环境检测结果.html"
    report.write_text(make_report(profile, comfy, missing, size_bad, nodes, version),
                      encoding="utf-8")
    if not args.no_open:
        try:
            webbrowser.open(report.as_uri())
        except Exception:
            pass
    if args.check_only:
        print("检测报告：" + str(report))
        return 0 if not missing and not size_bad and not nodes else 1
    if missing or size_bad or nodes:
        print("环境不完整：请先按报告补齐模型/节点；仍可继续接入，但任务可能失败。")
        try:
            if input("仍然接入？[y/N] ").strip().lower() not in ("y", "yes"):
                return 1
        except (EOFError, KeyboardInterrupt):
            return 1
    if not comfy_running():
        print("提示：ComfyUI 当前没有在 127.0.0.1:8188 运行；启动 ComfyUI 后 worker 才会接单。")
    server = args.server or profile.get("central_url") or ""
    if not server:
        server = input("中央服务地址（例如 https://192.168.137.1:8800）：").strip()
    code = args.code
    if not code:
        code = input("管理员生成的接入码：").strip()
    name = args.name or profile.get("suggested_name") or socket.gethostname()
    if not server or not code:
        print("缺少中央地址或接入码。")
        return 2
    if not run_join(comfy, server, code, name):
        print("接入失败：检查接入码、证书和中央服务是否可达。")
        return 3
    start_agent(comfy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
