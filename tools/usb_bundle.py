# -*- coding: utf-8 -*-
"""一键把当前安装打包到 U 盘（模型可选、完整运行环境可选）。"""
import argparse
import ctypes
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import offline_bundle


def removable_drives():
    out = []
    try:
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = letter + ":\\"
            if not os.path.exists(root):
                continue
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 2:
                out.append(root)
    except Exception:
        pass
    return out


def dir_size(path):
    total = 0
    for base, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(base, fn))
            except OSError:
                pass
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(description="打包到 U 盘")
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--target", default="")
    ap.add_argument("--no-models", action="store_true",
                    help="不包含模型")
    ap.add_argument("--runtime", action="store_true",
                    help="包含 ComfyUI 和 Python 完整运行环境")
    ap.add_argument("--yes", action="store_true", help="不询问确认")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(os.path.join(root, "ComfyUI")):
        print("这个目录里没有 ComfyUI，请在安装目录里运行。")
        return 2
    include_models = not args.no_models
    if not args.target:
        drives = removable_drives()
        print("\n检测到可移动磁盘：")
        if drives:
            for i, d in enumerate(drives, 1):
                free = shutil.disk_usage(d).free
                print("  %d) %s  剩余 %s" % (i, d, offline_bundle.human(free)))
        else:
            print("  没有检测到 U 盘；也可以手动输入一个目录。")
        default = ((drives[0] + "MGS-Offline-" + time.strftime("%Y%m%d"))
                   if drives else
                   ("D:\\MGS-Offline-" + time.strftime("%Y%m%d")))
        try:
            raw = input("\nU 盘/目标目录 [%s]: " % default).strip().strip('"')
        except (EOFError, KeyboardInterrupt):
            return 0
        args.target = raw or default
    target = os.path.abspath(args.target)
    if os.path.isdir(target) and os.listdir(target):
        if not args.yes:
            try:
                answer = input("目标目录不是空的，继续会合并文件 [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return 0
            if answer not in ("y", "yes"):
                print("已取消。")
                return 0
    try:
        free = shutil.disk_usage(target).free
    except OSError:
        try:
            free = shutil.disk_usage(
                os.path.splitdrive(target)[0] + "\\").free
        except OSError:
            free = 0
    need = 0
    if include_models:
        need += dir_size(os.path.join(root, "ComfyUI", "models"))
    if args.runtime:
        need += dir_size(os.path.join(root, "ComfyUI")) + \
            dir_size(os.path.join(root, "python_embeded"))
    elif os.path.isdir(os.path.join(root, "ComfyUI", "custom_nodes")):
        need += dir_size(os.path.join(root, "ComfyUI", "custom_nodes"))
    print("\n将打包到：%s" % target)
    print("包含模型：%s" % ("是" if include_models else "否"))
    print("包含自定义节点：%s" % (
        "是（含在运行环境里）" if args.runtime else "是"))
    print("包含 ComfyUI 运行环境：%s" % ("是" if args.runtime else "否"))
    print("预计需要：%s；目标剩余：%s" % (
        offline_bundle.human(need), offline_bundle.human(free)))
    if free and free < need + 512 * 1024 * 1024:
        print("目标空间不足，至少还要预留 512MB。")
        return 3
    if not args.yes:
        try:
            answer = input("开始打包？[y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0
        if answer not in ("y", "yes"):
            print("已取消。")
            return 0

    def progress(label, count, total):
        print("  %-16s %6d 个文件  %s" % (
            label, count, offline_bundle.human(total)), end="\r", flush=True)

    print("")
    try:
        manifest = offline_bundle.create_bundle(
            root, target, include_models=include_models,
            include_runtime=args.runtime, progress=progress)
    except Exception as exc:
        print("\n打包失败：%s" % exc)
        return 1
    print(" " * 70, end="\r")
    print("打包完成：%s" % target)
    print("文件：%s 个，%s" % (
        manifest["payload_files"],
        offline_bundle.human(manifest["payload_bytes"])))
    print("\n把整个目录拷到 U 盘；在新电脑双击「一键迁移到新机器.bat」。")
    if manifest["source_edition"] == "commercial":
        print("注意：商用版迁移后需要在新机器上重新激活（机器码不同）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
