#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Nexus 服务 · 安全设置

两个设置：
  1. 管理员密码 —— 多用户账号系统里 admin 的登录密码。
  2. HTTPS 加密 —— 加了自签证书，防止同一网络里的人被动嗅探。
     手机第一次打开会提示「不安全」，点继续访问即可。

普通账号请到网页「3D 星图 → 安全网关 → 用户管理」里创建和限制。
改完都要重启「启动手机出图.bat」才生效。
"""

import datetime
import getpass
import hashlib
import ipaddress
import json
import os
import secrets
import socket
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
ACCESS_FILE = os.path.join(ROOT, "access.json")
USERS_FILE = os.path.join(ROOT, "users.json")
SESSION_FILE = os.path.join(ROOT, "sessions.json")
CERT_FILE = os.path.join(ROOT, "cert.pem")
KEY_FILE = os.path.join(ROOT, "key.pem")
HOTSPOT_IP = "192.168.137.1"
PORT = 8800


# ---------------------------------------------------------------- 状态

def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh) or {}
        users = d.get("users")
        return users if isinstance(users, dict) else {}
    except Exception:
        return {}


def save_users(users):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "users": users}, fh,
                  ensure_ascii=False, indent=1)
    os.replace(tmp, USERS_FILE)


def admin_account(users):
    if "admin" in users:
        return users["admin"]
    for u in users.values():
        if u.get("role") == "admin":
            return u
    return None


def has_password():
    users = load_users()
    return any(u.get("pw_hash") for u in users.values())


def has_https():
    return os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE)


def lan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


# ---------------------------------------------------------------- 密码

def _set_admin_password(pw):
    users = load_users()
    admin = admin_account(users)
    if not admin:
        print("  !! 没找到管理员账号，请先启动一次服务生成 users.json")
        return False
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"),
                                 bytes.fromhex(salt), 200_000).hex()
    admin["salt"] = salt
    admin["pw_hash"] = digest
    admin["enabled"] = True
    save_users(users)
    # 密码变了，之前的登录全部作废
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass
    print()
    print("  [OK] 管理员密码已保存。账号：%s" % admin.get("username"))
    print("  ** 重启「启动手机出图.bat」后生效 **")
    return True


def set_password():
    print()
    print("  修改的是管理员账号的密码；普通账号请到")
    print("  网页「3D 星图 → 安全网关 → 用户管理」里管理。")
    print("  密码至少 8 位，建议字母 + 数字混排。")
    print()
    try:
        pw = getpass.getpass("  新管理员密码: ")
        pw2 = getpass.getpass("  再输一次: ")
    except (EOFError, KeyboardInterrupt):
        print("\n  已取消")
        return

    if len(pw) < 8:
        print("  !! 太短了，至少 8 位")
        return
    if pw != pw2:
        print("  !! 两次输入不一致")
        return
    _set_admin_password(pw)


def remove_password():
    print()
    print("  多用户模式下不能直接取消密码。")
    print("  这个选项会把管理员重置为 admin / admin（忘记密码时救急用）。")
    print("  重置后请马上在星图用户管理里改掉。")
    print()
    ans = input("  确定重置？输入 yes 确认: ").strip().lower()
    if ans != "yes":
        print("  已取消操作")
        return
    _set_admin_password("admin")
    print("  !! 管理员账号：admin  密码：admin")


# ---------------------------------------------------------------- HTTPS

def make_cert():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"Nexus"),
    ])

    alt = [x509.DNSName(u"localhost"),
           x509.IPAddress(ipaddress.ip_address(u"127.0.0.1")),
           x509.IPAddress(ipaddress.ip_address(HOTSPOT_IP))]
    for ip in lan_ips():
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .sign(key, hashes.SHA256()))

    with open(KEY_FILE, "wb") as fh:
        fh.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()))
    with open(CERT_FILE, "wb") as fh:
        fh.write(cert.public_bytes(serialization.Encoding.PEM))


def enable_https():
    print()
    print("  HTTPS 用的是自签证书（本机自己签的，没有第三方机构认证）。")
    print("  好处：同一网络里的人抓包也看不到内容。")
    print("  代价：手机第一次打开会弹「您的连接不是私密连接」，")
    print("        点【高级】->【继续前往】就能用。")
    print()
    ans = input("  开启 HTTPS？输入 yes 确认: ").strip().lower()
    if ans != "yes":
        print("  已取消操作")
        return
    try:
        make_cert()
    except ImportError:
        print("  !! 缺少 cryptography 组件，无法生成证书。")
        return
    except Exception as e:
        print("  !! 生成证书失败: %s" % e)
        return
    print()
    print("  [OK] 证书已生成：")
    print("       %s" % CERT_FILE)
    print("       %s" % KEY_FILE)
    print("  ** 重启「启动手机出图.bat」后生效，地址会变成 https:// **")


def disable_https():
    print()
    for p in (CERT_FILE, KEY_FILE):
        try:
            os.remove(p)
        except OSError:
            pass
    print("  [OK] 已关闭 HTTPS，重启服务后恢复为 http://")


# ---------------------------------------------------------------- 菜单

def show_status():
    scheme = "https" if has_https() else "http"
    users = load_users()
    admin = admin_account(users)
    print()
    if users:
        print("  账号系统：已启用（%d 个账号，管理员 %s）" % (
            len(users), admin.get("username") if admin else "?"))
    else:
        print("  账号系统：未初始化（启动一次服务会自动创建 admin）")
    print("  传输加密：%s" % (
        "已开启 HTTPS（自签证书）" if has_https() else "未开启（HTTP）"))
    print()
    print("  服务只对本机 + 热点开放，校园网访问不到。")
    print("  电脑打开：   %s://127.0.0.1:%d" % (scheme, PORT))
    print("  手机连热点： %s://192.168.137.1:%d" % (scheme, PORT))


def main():
    while True:
        print()
        print("=" * 54)
        print("  Nexus 服务 · 安全设置")
        print("=" * 54)
        show_status()
        print()
        print("  1. 修改管理员密码")
        print("  2. 重置管理员为 admin / admin（救急）")
        print("  3. 开启 HTTPS 加密传输")
        print("  4. 关闭 HTTPS 加密传输")
        print("  0. 退出")
        print()
        try:
            choice = input("  请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if choice == "1":
            set_password()
        elif choice == "2":
            remove_password()
        elif choice == "3":
            enable_https()
        elif choice == "4":
            disable_https()
        elif choice == "0":
            print()
            return 0
        else:
            print("  没这个选项")


if __name__ == "__main__":
    sys.exit(main())
