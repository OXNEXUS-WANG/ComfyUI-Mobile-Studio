# -*- coding: utf-8 -*-
"""离线迁移包：把网页程序、模型（可选 ComfyUI 运行环境）打包到 U 盘。

包结构：
    MGS-Offline-.../
      bundle_manifest.json
      一键迁移到新机器.bat
      migrate_offline.py
      offline_bundle.py
      README_离线迁移.txt
      payload/                 # 与安装目录同结构
        app_core.py ...
        worker/ ...
        ComfyUI/models/ ...
        ComfyUI/ ...           # 仅完整运行环境模式
        python_embeded/ ...    # 仅完整运行环境模式
"""
import json
import os
import shutil
import time

FORMAT = "mgs-offline-bundle"
VERSION = 1

PROTECTED_FILES = {
    "users.json", "users.json.bak", "sessions.json", "workers.json", "usage.json",
    "jobs_state.json", "local_llm.json", "monitor.json",
    "monitor_alerts.json", "monitor_trends.json", "cleanup.json",
    "queue_control.json", "teams.json", "team_prompts.json",
    "trainings.json", "trainings.json.bak",
    "training_settings.json", "training_settings.json.bak",
    "loras.json", "loras.json.bak",
    "sensitive_filter.json", "sensitive_filter.json.bak",
    "disclaimer_accepted.json",
    "license.json", "access.json", "cert.pem", "key.pem",
    "worker_agent.json",
}
PROTECTED_DIR_NAMES = {
    "generated", "web_uploads", "logs", "_backups", "_restore_points",
    "_model_trash", "_model_uploads", "_node_trash", "_node_uploads",
    "workflows", "__pycache__", ".git",
    "trainer", "trainings", "training_uploads",
    "_training_trash", "_trainer_trash", "_lora_trash",
    "input", "output", "temp", "user",
}
APP_DIRS = ("worker", "docs", "installer", "tools", "webapp_templates")
ROOT_FILES = (
    "VERSION", "EDITION", "README.md", "README-COMMERCIAL.md",
    "MANUAL.md", "CHANGELOG.md", "使用说明.md", "安装说明.txt",
    "安装说明_商业版.txt",
    "DISCLAIMER.md", "COMMERCIAL_EULA.md", "COMMERCIAL_LICENSE.md", "LICENSE",
    "THIRD_PARTY_NOTICES.md", "VERSION_LOCK.md", "EDITIONS.md",
    "商用授权说明.md", "商用版授权协议.md",
)


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return "%.1f %s" % (n, unit)
        n /= 1024


def _safe_join(root, rel):
    root = os.path.abspath(root)
    dest = os.path.abspath(os.path.join(root, rel))
    if dest != root and not dest.startswith(root + os.sep):
        raise ValueError("路径越界：%s" % rel)
    return dest


def _is_protected(rel):
    parts = str(rel).replace("\\", "/").split("/")
    if not parts:
        return True
    if parts[-1] in PROTECTED_FILES:
        return True
    if any(p in PROTECTED_DIR_NAMES for p in parts):
        return True
    if parts[-1].endswith((".pyc", ".pyo", ".part", ".tmp")):
        return True
    return False


def _walk_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in PROTECTED_DIR_NAMES]
        for fn in files:
            path = os.path.join(base, fn)
            if os.path.isfile(path):
                yield path


def _copy_file(src, dst, skip_same=True):
    try:
        if skip_same and os.path.isfile(dst) and \
                os.path.getsize(src) == os.path.getsize(dst):
            return 0
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return os.path.getsize(src)
    except Exception:
        return 0


def _copy_tree(src, dst, skip_same=True, progress=None, label="",
               exclude_dirs=None):
    exclude_dirs = set(exclude_dirs or ())
    total = 0
    count = 0
    for path in _walk_files(src):
        rel = os.path.relpath(path, src)
        parts = rel.replace("\\", "/").split("/")
        if any(p in exclude_dirs for p in parts):
            continue
        dest = _safe_join(dst, rel)
        got = _copy_file(path, dest, skip_same=skip_same)
        total += got
        count += 1
        if progress and count % 100 == 0:
            progress(label, count, total)
    return count, total


def _copy_app_level(source, payload, progress=None):
    """把安装目录根部的网页程序复制到 payload 根（与安装目录同结构）。"""
    count = 0
    total = 0
    app_dir = os.path.join(source, "app")
    if os.path.isdir(app_dir):
        for item in os.listdir(app_dir):
            src = os.path.join(app_dir, item)
            dst = os.path.join(payload, item)
            if os.path.isdir(src):
                if item in PROTECTED_DIR_NAMES:
                    continue
                c, b = _copy_tree(src, dst, skip_same=False,
                                  progress=progress, label=item)
                count += c
                total += b
            elif os.path.isfile(src):
                if item in PROTECTED_FILES or item.endswith(
                        (".lnk", ".pyc", ".pyo", ".part", ".tmp")):
                    continue
                got = _copy_file(src, dst, skip_same=False)
                if got:
                    count += 1
                    total += got
    else:
        # 已安装目录：app 文件直接散落在根部
        for fn in os.listdir(source):
            src = os.path.join(source, fn)
            if not os.path.isfile(src):
                continue
            if fn in PROTECTED_FILES or fn.endswith((".lnk", ".pyc", ".pyo")):
                continue
            if not fn.lower().endswith((
                    ".py", ".js", ".html", ".json", ".bat", ".ico")):
                continue
            got = _copy_file(src, os.path.join(payload, fn), skip_same=False)
            if got:
                count += 1
                total += got
    # 已安装目录的品牌图标是根目录 PNG（PWA 192/512），也一起带走。
    for fn in os.listdir(source):
        if fn.startswith("cometink-icon-") and fn.lower().endswith(".png"):
            got = _copy_file(os.path.join(source, fn),
                             os.path.join(payload, fn), skip_same=False)
            if got:
                count += 1
                total += got
    for name in APP_DIRS:
        src = os.path.join(source, name)
        if os.path.isdir(src):
            c, b = _copy_tree(src, os.path.join(payload, name),
                              skip_same=False, progress=progress, label=name)
            count += c
            total += b
    for name in ROOT_FILES:
        src = os.path.join(source, name)
        if os.path.isfile(src):
            got = _copy_file(src, os.path.join(payload, name),
                             skip_same=False)
            if got:
                count += 1
                total += got
    for fn in os.listdir(source):
        if fn.lower().endswith(".bat"):
            got = _copy_file(os.path.join(source, fn),
                             os.path.join(payload, fn), skip_same=False)
            if got:
                count += 1
                total += got
    return count, total


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _write_migration_files(bundle_dir, source_root):
    here = os.path.dirname(os.path.abspath(__file__))
    self_src = os.path.join(here, "offline_bundle.py")
    if os.path.isfile(self_src):
        shutil.copy2(self_src, os.path.join(bundle_dir, "offline_bundle.py"))
    _write_text(os.path.join(bundle_dir, "migrate_offline.py"), '''# -*- coding: utf-8 -*-
"""把 U 盘离线包迁移到新机器。"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offline_bundle import migrate_bundle, human


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--target", required=True)
    args = ap.parse_args()
    try:
        result = migrate_bundle(args.bundle, args.target)
    except Exception as exc:
        print("\\n迁移失败：%s" % exc)
        return 1
    print("\\n迁移完成：%s 个文件，%s" % (
        result["files"], human(result["bytes"])))
    print("目标目录：%s" % result["target"])
    if result.get("runtime"):
        print("已包含 ComfyUI 运行环境，双击目标目录的「一键启动.bat」即可。")
    else:
        print("请确认目标目录已有 ComfyUI；然后双击「一键启动.bat」或安装器的启动脚本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
''')
    bat = '''@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   Migrate offline bundle to this computer
echo ============================================
echo.
set /p TARGET=Target install folder [D:\\CometInk]:
if "%TARGET%"=="" set TARGET=D:\\CometInk
if exist "%~dp0payload\\python_embeded\\python.exe" (
  "%~dp0payload\\python_embeded\\python.exe" "%~dp0migrate_offline.py" --bundle "%~dp0" --target "%TARGET%"
  goto done
)
if exist "%TARGET%\\python_embeded\\python.exe" (
  "%TARGET%\\python_embeded\\python.exe" "%~dp0migrate_offline.py" --bundle "%~dp0" --target "%TARGET%"
  goto done
)
python "%~dp0migrate_offline.py" --bundle "%~dp0" --target "%TARGET%"
:done
echo.
pause
'''
    _write_text(os.path.join(bundle_dir, "一键迁移到新机器.bat"), bat)
    edition = "unknown"
    try:
        with open(os.path.join(source_root, "EDITION"), "r",
                  encoding="utf-8") as fh:
            edition = (fh.read() or "").strip() or "unknown"
    except OSError:
        pass
    _write_text(os.path.join(bundle_dir, "README_离线迁移.txt"), (
        "ComfyUI Mobile Studio 离线迁移包\n"
        "================================\n\n"
        "1. 把整个文件夹复制到 U 盘。\n"
        "2. 在新电脑上双击「一键迁移到新机器.bat」。\n"
        "3. 输入安装目录（例如 D:\\CometInk）。\n"
        "4. 迁移完成后双击目标目录的「一键启动.bat」。\n\n"
        "说明：\n"
        "- 只迁移模型、网页程序和自定义节点时，新电脑需要先有 ComfyUI。\n"
        "- 选择完整运行环境时，包内已带 ComfyUI 和 Python，无需联网。\n"
        "- 包内不含账号、日志、图片、API Key、worker secret 或授权码。\n"
        "- 商用版迁移后仍会要求在新机器上重新激活（机器码不同）。\n"
        "- 来源版本：%s\n" % edition
    ))


def _tree_stats(root):
    count = 0
    total = 0
    for path in _walk_files(root):
        count += 1
        try:
            total += os.path.getsize(path)
        except OSError:
            pass
    return count, total


def create_bundle(source_root, bundle_dir, include_models=True,
                  include_runtime=False, models_already=False,
                  include_custom_nodes=True, progress=None):
    """生成离线包。models_already=True 表示 payload 里已经有模型。"""
    source_root = os.path.abspath(source_root)
    bundle_dir = os.path.abspath(bundle_dir)
    if not os.path.isdir(source_root):
        raise ValueError("安装目录不存在：%s" % source_root)
    src_comfy = os.path.join(source_root, "ComfyUI")
    if include_models and not models_already and not os.path.isdir(
            os.path.join(src_comfy, "models")):
        raise ValueError("安装目录里没有 ComfyUI/models")
    if include_runtime and not os.path.isdir(src_comfy):
        raise ValueError("安装目录里没有 ComfyUI，不能打完整运行环境包")
    if not models_already and not os.path.isdir(src_comfy) and \
            not os.path.isdir(os.path.join(source_root, "app")):
        raise ValueError("这个目录不像 ComfyUI Mobile Studio 安装目录")
    bundle_dir = os.path.abspath(bundle_dir)
    if bundle_dir == source_root or bundle_dir.startswith(source_root + os.sep):
        raise ValueError("离线包不能放在安装目录里面")
    os.makedirs(bundle_dir, exist_ok=True)
    payload = os.path.join(bundle_dir, "payload")
    os.makedirs(payload, exist_ok=True)
    if progress:
        progress("准备网页程序", 0, 0)
    count, total = _copy_app_level(source_root, payload, progress)
    if include_runtime:
        if progress:
            progress("复制 ComfyUI 运行环境", 0, 0)
        c, b = _copy_tree(
            src_comfy, os.path.join(payload, "ComfyUI"),
            progress=progress, label="ComfyUI",
            exclude_dirs={"models", "input", "output", "temp", "user",
                          "__pycache__", ".git"})
        count += c
        total += b
        py = os.path.join(source_root, "python_embeded")
        if os.path.isdir(py):
            c, b = _copy_tree(py, os.path.join(payload, "python_embeded"),
                              progress=progress, label="python_embeded",
                              exclude_dirs={"__pycache__", ".git"})
            count += c
            total += b
    if include_models and not models_already:
        if progress:
            progress("复制模型", 0, 0)
        c, b = _copy_tree(
            os.path.join(src_comfy, "models"),
            os.path.join(payload, "ComfyUI", "models"),
            progress=progress, label="models",
            exclude_dirs={"__pycache__", ".git"})
        count += c
        total += b
    if (not include_runtime and include_custom_nodes
            and os.path.isdir(os.path.join(src_comfy, "custom_nodes"))):
        if progress:
            progress("复制自定义节点", 0, 0)
        c, b = _copy_tree(
            os.path.join(src_comfy, "custom_nodes"),
            os.path.join(payload, "ComfyUI", "custom_nodes"),
            progress=progress, label="custom_nodes",
            exclude_dirs={"__pycache__", ".git"})
        count += c
        total += b
    files, size = _tree_stats(payload)
    source_edition = "share"
    try:
        with open(os.path.join(source_root, "EDITION"), "r",
                  encoding="utf-8") as fh:
            if (fh.read() or "").strip().lower() == "commercial":
                source_edition = "commercial"
    except OSError:
        pass
    manifest = {
        "format": FORMAT, "version": VERSION, "created": time.time(),
        "include_models": bool(include_models),
        "include_runtime": bool(include_runtime),
        "include_custom_nodes": bool(
            include_custom_nodes and not include_runtime),
        "source_edition": source_edition,
        "payload_files": files,
        "payload_bytes": size,
    }
    with open(os.path.join(bundle_dir, "bundle_manifest.json"), "w",
              encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    _write_migration_files(bundle_dir, source_root)
    return manifest


def migrate_bundle(bundle_dir, target, progress=None, skip_same=True):
    """把 payload 迁移到目标目录；跳过运行期数据和敏感文件。"""
    bundle_dir = os.path.abspath(bundle_dir)
    target = os.path.abspath(target)
    manifest_path = os.path.join(bundle_dir, "bundle_manifest.json")
    if not os.path.isfile(manifest_path):
        raise ValueError("不是有效的离线包（缺少 bundle_manifest.json）")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh) or {}
    if manifest.get("format") != FORMAT:
        raise ValueError("离线包格式不匹配")
    payload = os.path.join(bundle_dir, "payload")
    if not os.path.isdir(payload):
        raise ValueError("离线包缺少 payload 目录")
    if not manifest.get("include_runtime") and not os.path.isdir(
            os.path.join(target, "ComfyUI", "models")):
        raise ValueError(
            "目标目录没有 ComfyUI/models。请先安装 ComfyUI，或改用完整运行环境包。")
    os.makedirs(target, exist_ok=True)
    count = 0
    total = 0
    binary_exts = (".safetensors", ".ckpt", ".pt", ".pth", ".bin",
                   ".gguf", ".onnx", ".sft", ".mp4", ".webm", ".zip")
    for path in _walk_files(payload):
        rel = os.path.relpath(path, payload)
        if _is_protected(rel):
            continue
        dest = _safe_join(target, rel)
        same_ok = skip_same and rel.lower().endswith(binary_exts)
        got = _copy_file(path, dest, skip_same=same_ok)
        if got:
            count += 1
            total += got
        if progress and (count % 100 == 0):
            progress("迁移", count, total)
    return {"files": count, "bytes": total, "target": target,
            "runtime": bool(manifest.get("include_runtime")),
            "manifest": manifest}
