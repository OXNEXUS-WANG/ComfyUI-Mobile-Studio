#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从 Hugging Face 镜像下载本项目的模型。

模型不放进安装包；本脚本支持断点续传，安装时和安装后都可以运行。
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "ComfyUI-Mobile-Studio/1.0"
HF_MIRROR = "https://hf-mirror.com"
HF_DIRECT = "https://huggingface.co"

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
try:
    import offline_bundle
except Exception:
    offline_bundle = None


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f%s" % (n, unit)
        n /= 1024


def load_manifest(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not isinstance(data.get("packs"), dict):
        raise ValueError("模型清单格式不对：%s" % path)
    return data


def safe_dest(root, rel):
    root = Path(root).resolve()
    dest = (root / rel).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        raise ValueError("模型目标路径越界：%s" % rel)
    return dest


def pack_size(pack):
    return sum(int(f.get("size") or 0) for f in (pack.get("files") or []))


def print_packs(manifest):
    packs = manifest["packs"]
    print("\n可选模型包：")
    for i, (key, pack) in enumerate(packs.items(), 1):
        default = " [默认]" if key in (manifest.get("default_packs") or []) else ""
        print("  %d) %-12s %-28s %6.1f GB%s" % (
            i, key, pack.get("label") or key,
            pack_size(pack) / 1000000000, default))
        if pack.get("desc"):
            print("       %s" % pack["desc"])
    print("\n输入编号（逗号分隔），直接回车使用默认包，输入 all 下载全部。")
    print("例如：1,2  或  anima,upscale")


def choose_packs(manifest):
    packs = manifest["packs"]
    keys = list(packs.keys())
    default = [k for k in (manifest.get("default_packs") or []) if k in packs]
    print_packs(manifest)
    try:
        raw = input("\n选择模型包: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return []
    if not raw:
        return default
    if raw == "all":
        return keys
    selected = []
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(keys):
                selected.append(keys[idx])
        elif part in packs:
            selected.append(part)
    return list(dict.fromkeys(selected))


def _removable_drives():
    out = []
    try:
        import ctypes
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = letter + ":\\"
            if os.path.exists(root) and \
                    ctypes.windll.kernel32.GetDriveTypeW(root) == 2:
                out.append(root)
    except Exception:
        pass
    return out


def choose_offline_target(local_root):
    """下载前询问：本机安装，还是下载到 U 盘离线包。"""
    print("\n这次模型要装到哪台机器？")
    print("  1) 本机：直接下载到当前安装目录 [默认]")
    print("  2) 另一台电脑：先下载到 U 盘离线包，之后一键迁移")
    try:
        choice = input("请选择 [1/2]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return None, None
    if choice not in ("2", "u", "usb", "另一台", "u盘", "离线"):
        return Path(local_root).resolve(), None

    drives = _removable_drives()
    default = ((drives[0] + "MGS-Offline-" + time.strftime("%Y%m%d"))
               if drives else ("D:\\MGS-Offline-" + time.strftime("%Y%m%d")))
    if drives:
        print("\n检测到 U 盘：")
        for d in drives:
            try:
                free = shutil.disk_usage(d).free
            except OSError:
                free = 0
            print("  %s  剩余 %s" % (d, human(free)))
    try:
        raw = input("\nU 盘/离线包目录 [%s]: " % default).strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        print("\n已取消")
        return None, None
    bundle = Path(raw or default).expanduser().resolve()
    if bundle.drive and len(bundle.parts) == 1:
        bundle = bundle / ("MGS-Offline-" + time.strftime("%Y%m%d"))
    local = Path(local_root).resolve()
    if str(bundle).lower().startswith(str(local).lower() + os.sep):
        print("离线包不能放在安装目录里面。")
        return None, None
    payload = bundle / "payload"
    payload.mkdir(parents=True, exist_ok=True)
    print("\n模型会下载到：%s" % (payload / "ComfyUI" / "models"))
    print("全部下载完成后会自动生成迁移脚本。")
    return payload, bundle


def download_one(urls, dest, expected, label):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    expected = int(expected or 0)
    if dest.is_file() and (not expected or dest.stat().st_size == expected):
        print("  [跳过] %s 已存在 (%s)" % (label, human(dest.stat().st_size)))
        return True
    part = Path(str(dest) + ".part")
    if dest.is_file() and expected and dest.stat().st_size != expected:
        try:
            dest.unlink()
        except OSError:
            pass

    last_error = ""
    for base in urls:
        try:
            have = part.stat().st_size if part.is_file() else 0
            headers = {"User-Agent": UA, "Accept": "*/*"}
            if have:
                headers["Range"] = "bytes=%d-" % have
            req = urllib.request.Request(base, headers=headers)
            print("  下载 %s" % label)
            print("    %s" % base)
            with urllib.request.urlopen(req, timeout=60) as resp:
                status = getattr(resp, "status", 200)
                mode = "ab" if (have and status == 206) else "wb"
                if mode == "wb":
                    have = 0
                total = expected or int(resp.headers.get("Content-Length") or 0)
                if total and have:
                    total = max(total, have)
                done = have
                started = time.time()
                last_print = 0.0
                with open(part, mode) as fh:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if now - last_print >= 1.0:
                            last_print = now
                            pct = ("%.1f%%" % (done * 100.0 / total)) if total else human(done)
                            speed = done / max(0.1, now - started)
                            print("    %s  %s  %s/s" % (pct, human(done), human(speed)),
                                  end="\r", flush=True)
                print()
            size = part.stat().st_size if part.is_file() else 0
            if expected and size != expected:
                raise IOError("下载大小不对：%s / %s" % (size, expected))
            os.replace(part, dest)
            print("  [完成] %s (%s)" % (label, human(size)))
            return True
        except Exception as exc:
            last_error = "%s: %s" % (type(exc).__name__, exc)
            print("\n  [失败] %s" % last_error)
            # 尝试下一个镜像；已下载的 .part 保留，继续断点续传
    print("  [放弃] %s：%s" % (label, last_error))
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="下载 ComfyUI Mobile Studio 模型")
    ap.add_argument("--root", required=True, help="安装目录（包含 ComfyUI）")
    ap.add_argument("--manifest", required=True, help="models_manifest.json")
    ap.add_argument("--packs", default="", help="逗号分隔的模型包 key；空=交互选择")
    ap.add_argument("--mirror", default=HF_MIRROR, help="Hugging Face 镜像")
    ap.add_argument("--direct", default=HF_DIRECT, help="镜像失败时的直连地址")
    ap.add_argument("--list", action="store_true", help="只列出模型包")
    ap.add_argument("--ask-target", action="store_true",
                    help="下载前询问本机安装还是做 U 盘离线包")
    ap.add_argument("--bundle-dir", default="",
                    help="直接指定离线包目录（跳过本机/离线询问）")
    args = ap.parse_args(argv)

    local_root = Path(args.root).resolve()
    root = local_root
    bundle_dir = None
    manifest = load_manifest(args.manifest)
    packs = manifest["packs"]

    if args.list:
        print_packs(manifest)
        return 0

    if args.bundle_dir:
        bundle_dir = Path(args.bundle_dir).expanduser().resolve()
        root = bundle_dir / "payload"
        root.mkdir(parents=True, exist_ok=True)
        if str(bundle_dir).lower().startswith(
                str(local_root).lower() + os.sep):
            print("离线包不能放在安装目录里面。", file=sys.stderr)
            return 2
        print("\n离线包模式：模型将下载到 %s" %
              (root / "ComfyUI" / "models"))
    elif args.ask_target:
        root, bundle_dir = choose_offline_target(local_root)
        if root is None:
            return 0

    if args.packs:
        selected = [x.strip() for x in args.packs.replace("，", ",").split(",") if x.strip()]
        selected = list(dict.fromkeys(selected))
    else:
        selected = choose_packs(manifest)
    if not selected:
        print("没有选择模型包。")
        return 0
    unknown = [x for x in selected if x not in packs]
    if unknown:
        print("未知模型包：%s" % ", ".join(unknown), file=sys.stderr)
        return 2

    need = sum(pack_size(packs[k]) for k in selected)
    free = shutil.disk_usage(root).free if root.exists() else 0
    print("\n将下载 %d 个模型包，共约 %.1f GB；目标盘剩余 %.1f GB。" % (
        len(selected), need / 1000000000, free / 1000000000))
    if free and free < need + 1024 * 1024 * 1024:
        print("磁盘剩余空间不足，至少还要预留 1GB。请先清理磁盘。", file=sys.stderr)
        return 3

    failed = []
    for key in selected:
        pack = packs[key]
        print("\n=== %s ===" % (pack.get("label") or key))
        for f in pack.get("files") or []:
            dest = safe_dest(root, f.get("dest") or "")
            label = "%s/%s" % (f.get("repo"), f.get("path"))
            urls = []
            revision = str(f.get("revision") or "main")
            for base in (args.mirror.rstrip("/"), args.direct.rstrip("/")):
                if base:
                    urls.append("%s/%s/resolve/%s/%s?download=true" % (
                        base, f["repo"], revision, f["path"].lstrip("/")))
            if not download_one(urls, dest, f.get("size"), label):
                failed.append(label)
    if failed:
        print("\n以下文件没有下载完成：", file=sys.stderr)
        for x in failed:
            print("  - %s" % x, file=sys.stderr)
        print("可以重新运行本脚本断点续传。", file=sys.stderr)
        return 1
    if bundle_dir:
        if offline_bundle is None:
            print("\n模型已下载，但缺少 tools\\offline_bundle.py，"
                  "无法生成迁移脚本。", file=sys.stderr)
            return 1
        print("\n正在整理离线包（复制网页程序和迁移脚本）…")
        try:
            meta = offline_bundle.create_bundle(
                local_root, bundle_dir, include_models=True,
                include_runtime=False, models_already=True)
        except Exception as exc:
            print("整理离线包失败：%s" % exc, file=sys.stderr)
            return 1
        print("\n离线包已生成：%s" % bundle_dir)
        print("文件 %d 个，共 %s。" % (
            meta["payload_files"], human(meta["payload_bytes"])))
        print("把整个目录拷到 U 盘；新电脑上双击「一键迁移到新机器.bat」。")
        if meta.get("source_edition") == "commercial":
            print("商用版迁移后需要在新机器上重新激活（机器码不同）。")
    else:
        print("\n全部模型下载完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
