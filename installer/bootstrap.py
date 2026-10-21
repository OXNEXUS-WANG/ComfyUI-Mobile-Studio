#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安装收尾：创建管理员、HTTPS 证书和运行目录。

由 install.ps1 调用，运行在目标目录的 python_embeded 里。
"""
import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path


def _backup_file(path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + ".bak-" + stamp)
    n = 2
    while backup.exists():
        backup = path.with_name(path.name + ".bak-" + stamp + "-" + str(n))
        n += 1
    try:
        path.replace(backup)
        return backup
    except OSError:
        return None


def _cert_ok(cert_path, key_path):
    """证书是否仍可用：未过期、包含本机/热点地址、私钥匹配。

    缺少 cryptography 时返回 True（宁可保留，不误删用户证书）。
    """
    if not (cert_path.is_file() and key_path.is_file()):
        return False
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        from cryptography.x509.oid import NameOID
    except Exception:
        return True
    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not names or names[0].value != u"手机出图":
            return False
        key = serialization.load_pem_private_key(
            key_path.read_bytes(), password=None)
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            not_after = cert.not_valid_after_utc
        except AttributeError:
            not_after = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        if not_after < now + datetime.timedelta(days=30):
            return False
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
        ips = {str(x) for x in san.get_values_for_type(x509.IPAddress)}
        if "127.0.0.1" not in ips or "192.168.137.1" not in ips:
            return False
        pub_cert = cert.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        pub_key = key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        return pub_cert == pub_key
    except Exception:
        return False


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
        renew = bool(args.force_cert)
        if cert.is_file() and key.is_file() and not args.force_cert:
            if _cert_ok(cert, key):
                print("[OK] HTTPS 证书已存在且有效，保留原证书")
            else:
                print("[警告] 现有 HTTPS 证书过期、缺少本机地址或私钥不匹配，准备续期")
                renew = True
        elif not (cert.is_file() and key.is_file()):
            renew = True
        if renew:
            old_cert = _backup_file(cert) if cert.is_file() else None
            old_key = _backup_file(key) if key.is_file() else None
            try:
                import security_setup
                security_setup.make_cert()
                print("[OK] 已生成 HTTPS 自签证书")
                if old_cert:
                    print("       旧证书已备份：%s" % old_cert.name)
            except Exception as exc:
                if old_cert:
                    try:
                        old_cert.replace(cert)
                    except OSError:
                        pass
                if old_key:
                    try:
                        old_key.replace(key)
                    except OSError:
                        pass
                print("[警告] HTTPS 证书生成失败：%s" % exc)
                print("       已尽量恢复旧证书；仍可通过 http 使用，但不建议在局域网明文传输")

    for name in ("generated", "web_uploads", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    print("[OK] 运行目录已准备")
    return 0


if __name__ == "__main__":
    sys.exit(main())
