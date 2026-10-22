#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""备份手机出图的账号、算力节点、图库元数据和可选图片。

默认只备份配置/元数据，不复制几 GB 的图片；需要连图片一起备份时加 --images。
备份 ZIP 里包含账号密码哈希和 worker secret 哈希，请妥善保管。
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ROOT_FILES = (
    "users.json",
    "workers.json",
    "usage.json",
    "local_llm.json",
    "monitor.json",
    "cleanup.json",
    "queue_control.json",
    "supervisor.json",
    "teams.json",
    "team_prompts.json",
    "license.json",
    "access.json",
    "char_tags.json",
    "工作流_中文提示词.json",
    "README_VERY_IMPORTANT.txt",
    "jobs_state.json",
    "trainings.json",
    "training_settings.json",
    "loras.json",
    "sensitive_filter.json",
)
META_SUFFIX = ".json"
IMAGE_SUFFIX = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm")
SKIP_DIRS = {".thumbs", "__pycache__"}


def safe_arc(path):
    return path.replace("\\", "/")


def sha256_file(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def iter_generated(root, include_images):
    base = root / "generated"
    if not base.is_dir():
        return
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        suffix = p.suffix.lower()
        if suffix == META_SUFFIX or (include_images and suffix in IMAGE_SUFFIX):
            yield p


def iter_workflows(root):
    base = root / "workflows"
    if not base.is_dir():
        return
    for p in base.glob("*.json"):
        if p.is_file():
            yield p


def iter_plugins(root):
    """只备份插件注册表和安全插件包；隔离区 ZIP 和节点备份不进备份。"""
    base = root / "plugins"
    if not base.is_dir():
        return
    registry = base / "registry.json"
    if registry.is_file():
        yield registry
    packs = base / "packs"
    if packs.is_dir():
        for p in packs.rglob("*.json"):
            if p.is_file():
                yield p


def iter_logs(root):
    base = root / "logs"
    if not base.is_dir():
        return
    for p in base.rglob("*.jsonl"):
        if p.is_file():
            yield p


def build(root, out, include_images=False, include_logs=False):
    root = Path(root).resolve()
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for name in ROOT_FILES:
        p = root / name
        if p.is_file():
            files.append(p)
    files.extend(iter_generated(root, include_images))
    files.extend(iter_workflows(root))
    files.extend(iter_plugins(root))
    if include_logs:
        files.extend(iter_logs(root))
    # 去重并保持稳定顺序
    uniq = {}
    for p in files:
        uniq[str(p.resolve())] = p
    files = [uniq[k] for k in sorted(uniq)]
    manifest = {
        "format": "comfyui-mobile-studio-backup",
        "version": 1,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "root": str(root),
        "include_images": bool(include_images),
        "include_logs": bool(include_logs),
        "files": [],
    }
    tmp = str(out) + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            rel = safe_arc(str(p.relative_to(root)))
            st = p.stat()
            manifest["files"].append({
                "path": rel, "size": st.st_size,
                "mtime": int(st.st_mtime),
                "sha256": sha256_file(p),
            })
            z.write(p, rel)
        z.writestr("backup_manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(tmp, out)
    total = sum(x["size"] for x in manifest["files"])
    print("备份完成：%s" % out)
    print("文件 %d 个，原始大小 %.1f MB" % (
        len(manifest["files"]), total / 1048576.0))
    if not include_images:
        print("提示：默认没有备份图片；需要连图一起备份请加 --images。")
    print("注意：备份含账号哈希和 worker secret 哈希，不要公开分享。")


def main(argv=None):
    ap = argparse.ArgumentParser(description="备份 ComfyUI Mobile Studio")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--out", default="")
    ap.add_argument("--images", action="store_true", help="连图库图片/视频一起备份")
    ap.add_argument("--logs", action="store_true", help="连活动/安全日志一起备份")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if not (root / "users.json").is_file():
        print("找不到 users.json，确认 --root 指向安装目录。", file=sys.stderr)
        return 2
    if args.out:
        out = Path(args.out)
    else:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        out = root / "_backups" / ("backup-%s.zip" % stamp)
    build(root, out, args.images, args.logs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
