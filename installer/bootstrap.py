#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安装收尾：创建管理员、HTTPS 证书和运行目录。

由 install.ps1 调用，运行在目标目录的 python_embeded 里。
"""
import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--password-env", default="MGS_ADMIN_PASSWORD")
    ap.add_argument("--no-cert", action="store_true")
    ap.add_argument("--force-cert", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    sys.path.insert(0, str(root))

    import app_core

    app_core.ensure_users()
    password = os.environ.get(args.password_env) or ""
    admin = None
    for u in app_core.USERS.values():
        if u.get("role") == "admin":
            admin = u
            break
    if not admin:
        print("!! 没有找到管理员账号", file=sys.stderr)
        return 2
    if password:
        salt, digest = app_core.hash_password(password)
        admin["salt"] = salt
        admin["pw_hash"] = digest
        admin["enabled"] = True
        app_core.save_users()
        # 改密码后旧会话失效
        try:
            (root / "sessions.json").unlink()
        except OSError:
            pass
        print("[OK] 管理员密码已设置")
    else:
        print("[提示] 未提供管理员密码，保留首次启动生成的默认密码")

    try:
        import lan_share
        lan_share.ensure_workers()
    except Exception as exc:
        print("[警告] workers.json 初始化失败：%s" % exc)

    if not args.no_cert:
        cert = root / "cert.pem"
        key = root / "key.pem"
        if cert.is_file() and key.is_file() and not args.force_cert:
            print("[OK] HTTPS 证书已存在，保留原证书")
        else:
            try:
                import security_setup
                security_setup.make_cert()
                print("[OK] 已生成 HTTPS 自签证书")
            except Exception as exc:
                print("[警告] HTTPS 证书生成失败：%s" % exc)
                print("       仍可通过 http 使用，但不建议在局域网明文传输")

    for name in ("generated", "web_uploads", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    print("[OK] 运行目录已准备")
    return 0


if __name__ == "__main__":
    sys.exit(main())
