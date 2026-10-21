#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 backup.py 生成的 ZIP 恢复账号、节点、图库元数据和图片。

恢复前会自动把当前状态再备份一份。恢复采用“覆盖同名文件 + 保留新增文件”的
合并方式，不会删除备份里没有的现有图片。恢复完成后需要重启手机出图服务。
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

# 便携版 python313._pth 不会自动把脚本目录加进 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup  # noqa: E402

ROOT_FILES = set(backup.ROOT_FILES)
ALLOWED_PREFIXES = ("generated/", "logs/", "workflows/", "plugins/",
                    "trainings/")
SKIP_VERSION = 1


def service_running(port=8800):
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.8):
                return True
        except OSError:
            pass
    return False


def safe_name(name):
    raw = str(name or "").replace("\\", "/")
    p = PurePosixPath(raw)
    if not raw or p.is_absolute() or ".." in p.parts:
        return ""
    if raw in ROOT_FILES:
        return raw
    if any(raw.startswith(x) for x in ALLOWED_PREFIXES):
        return raw
    return ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def validate_zip(zf):
    names = zf.namelist()
    if "backup_manifest.json" not in names:
        raise ValueError("ZIP 里缺少 backup_manifest.json，不是本工具生成的备份。")
    try:
        manifest = json.loads(zf.read("backup_manifest.json").decode("utf-8"))
    except Exception as exc:
        raise ValueError("备份清单损坏：%s" % exc)
    if manifest.get("format") != "comfyui-mobile-studio-backup":
        raise ValueError("备份格式不匹配。")
    rows = manifest.get("files") or []
    checked = []
    for row in rows:
        name = safe_name(row.get("path"))
        if not name:
            raise ValueError("备份里有不允许恢复的路径：%s" % row.get("path"))
        if name not in names:
            raise ValueError("备份缺少清单中的文件：%s" % name)
        info = zf.getinfo(name)
        # 拒绝符号链接和异常压缩包
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ValueError("备份里包含符号链接，已拒绝：%s" % name)
        checked.append((name, row))
    return manifest, checked


def make_pre_restore(root, manifest):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = root / "_backups" / ("pre-restore-%s.zip" % stamp)
    has_images = any(str(r.get("path", "")).lower().endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"))
        for r in manifest.get("files") or [])
    backup.build(root, out, include_images=has_images,
                 include_logs=bool(manifest.get("include_logs")))
    return out


def restore(zip_path, root, yes=False):
    root = Path(root).resolve()
    zip_path = Path(zip_path).resolve()
    if not zip_path.is_file():
        print("找不到备份文件：%s" % zip_path, file=sys.stderr)
        return 2
    if service_running():
        print("服务正在运行。请先关闭手机出图（或运行「停止服务.bat」），再恢复。",
              file=sys.stderr)
        return 3
    with zipfile.ZipFile(zip_path) as zf:
        try:
            manifest, checked = validate_zip(zf)
        except ValueError as exc:
            print("备份校验失败：%s" % exc, file=sys.stderr)
            return 4
        if not yes:
            print("即将把下面 %d 个文件恢复到：%s" % (len(checked), root))
            print("恢复采用合并覆盖，不会删除现有图片。")
            if input("输入 RESTORE 继续：").strip() != "RESTORE":
                print("已取消。")
                return 0
        pre = make_pre_restore(root, manifest)
        print("当前状态已备份到：%s" % pre)
        stage = Path(tempfile.mkdtemp(prefix="_restore_", dir=str(root)))
        try:
            for name, row in checked:
                dest = stage / Path(name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                expected = row.get("sha256")
                if expected and sha256_file(dest) != expected:
                    raise ValueError("文件校验失败：%s" % name)
            for name, row in checked:
                src = stage / Path(name)
                dest = root / Path(name)
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(src, dest)
            print("恢复完成：%d 个文件。" % len(checked))
            print("请重新启动手机出图服务。")
            return 0
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="恢复 ComfyUI Mobile Studio 备份")
    ap.add_argument("zip", help="backup.py 生成的 ZIP")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args(argv)
    return restore(args.zip, args.root, args.yes)


if __name__ == "__main__":
    raise SystemExit(main())
