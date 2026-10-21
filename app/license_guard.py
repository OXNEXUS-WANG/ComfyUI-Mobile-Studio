# -*- coding: utf-8 -*-
"""商用版机器码与离线授权码。

授权码由维护者的 Ed25519 私钥签发，程序只内置公钥；授权码绑定机器码，
可设置到期时间（0 = 永久）。Share 版不读取授权状态，也不会拦截。
"""
import base64
import ctypes
import hashlib
import json
import os
import platform
import re
import subprocess
import time
import uuid

import trusted_time

ROOT = os.path.dirname(os.path.abspath(__file__))
EDITION_FILE = os.path.join(ROOT, "EDITION")
LICENSE_FILE = os.path.join(ROOT, "license.json")

PUBLIC_KEY_B64 = "GO0yccjNbQ0j8nRbUJvXcCtBaPM5w/VjEqXByvXyyD4="
CODE_PREFIX = "MGS1."
MACHINE_SALT = "ComfyUI-Mobile-Studio-Commercial-V1"

_LOCK = None
_CACHE = {"key": None, "status": None}
_MACHINE = {"code": None}


def _lock():
    global _LOCK
    if _LOCK is None:
        import threading
        _LOCK = threading.RLock()
    return _LOCK


def edition():
    try:
        with open(EDITION_FILE, "r", encoding="utf-8") as fh:
            value = (fh.read() or "").strip().lower()
        if value in ("share", "commercial"):
            return value
    except OSError:
        pass
    return "share"


def is_commercial():
    return edition() == "commercial"


def _machine_guid():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography", 0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0))
        try:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
        finally:
            winreg.CloseKey(key)
        return str(value or "").strip().lower()
    except Exception:
        return ""


def _bios_uuid():
    try:
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
            capture_output=True, text=True, timeout=10,
            creationflags=flags)
        value = (out.stdout or "").strip().lower()
        if re.match(r"^[0-9a-f-]{16,40}$", value) and set(value) != {"0"}:
            return value
    except Exception:
        pass
    return ""


def _volume_serial():
    try:
        drive = (os.environ.get("SystemDrive") or "C:") + "\\"
        serial = ctypes.c_uint(0)
        name = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            drive, name, 261, ctypes.byref(serial), None, None, fs, 261)
        if ok:
            return "%08X" % (serial.value & 0xFFFFFFFF)
    except Exception:
        pass
    return ""


def machine_code():
    """稳定机器码：MachineGuid + BIOS UUID + 系统盘序列号，显示为 6 组。"""
    with _lock():
        if _MACHINE["code"]:
            return _MACHINE["code"]
        parts = []
        guid = _machine_guid()
        bios = _bios_uuid()
        vol = _volume_serial()
        if guid:
            parts.append("guid=" + guid)
        if bios:
            parts.append("bios=" + bios)
        if vol:
            parts.append("vol=" + vol)
        if not parts:
            parts.append("host=" + platform.node().lower())
            parts.append("mac=%012x" % uuid.getnode())
        digest = hashlib.sha256(
            (MACHINE_SALT + "|" + "|".join(parts)).encode("utf-8")
        ).hexdigest().upper()[:24]
        code = "-".join(digest[i:i + 4] for i in range(0, 24, 4))
        _MACHINE["code"] = code
        return code


def normalize_machine(code):
    return re.sub(r"[^0-9A-F]", "", str(code or "").upper())


def _b64d(text):
    text = str(text or "").strip()
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def _b64e(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _public_key():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(PUBLIC_KEY_B64))
    except Exception:
        return None


def _parse_code(raw):
    """返回 (payload, normalized_code)；签名不通过抛 ValueError。"""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("请填写授权码")
    if text.startswith("{"):
        try:
            obj = json.loads(text)
        except Exception:
            raise ValueError("授权文件格式不正确")
        text = str((obj or {}).get("code") or "").strip()
        if not text:
            raise ValueError("授权文件里没有 code 字段")
    if text.upper().startswith(CODE_PREFIX):
        text = text[len(CODE_PREFIX):]
    parts = text.split(".")
    if len(parts) != 2:
        raise ValueError("授权码格式不正确")
    try:
        raw_payload = _b64d(parts[0])
        signature = _b64d(parts[1])
    except Exception:
        raise ValueError("授权码编码不正确")
    if not raw_payload or len(raw_payload) > 4096 or len(signature) != 64:
        raise ValueError("授权码长度不正确")
    key = _public_key()
    if key is None:
        raise ValueError("缺少 cryptography 组件，无法验证授权")
    try:
        from cryptography.exceptions import InvalidSignature
        key.verify(signature, raw_payload)
    except InvalidSignature:
        raise ValueError("授权码签名无效")
    except Exception:
        raise ValueError("授权码验证失败")
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except Exception:
        raise ValueError("授权内容不是有效 JSON")
    if not isinstance(payload, dict):
        raise ValueError("授权内容格式不正确")
    return payload, CODE_PREFIX + parts[0] + "." + parts[1]


def _base_status():
    commercial = is_commercial()
    return {
        "edition": edition(),
        "commercial": commercial,
        "machine_code": machine_code() if commercial else "",
        "activated": False,
        "valid": not commercial,
        "error": "" if not commercial else "商用版尚未激活",
        "customer": "",
        "issued": 0,
        "expires": 0,
        "days_left": None,
        "activated_at": 0,
        "license_file": os.path.basename(LICENSE_FILE),
    }


def status(force=False):
    with _lock():
        try:
            mtime = os.path.getmtime(LICENSE_FILE)
        except OSError:
            mtime = 0.0
        cache_key = (edition(), mtime, os.path.abspath(LICENSE_FILE))
        if not force and _CACHE["key"] == cache_key and _CACHE["status"]:
            return dict(_CACHE["status"])
        out = _base_status()
        if not out["commercial"]:
            _CACHE.update(key=cache_key, status=dict(out))
            return dict(out)
        if not mtime:
            _CACHE.update(key=cache_key, status=dict(out))
            return dict(out)
        try:
            with open(LICENSE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception:
            out["error"] = "授权文件损坏，请重新激活"
            _CACHE.update(key=cache_key, status=dict(out))
            return dict(out)
        code = str(data.get("code") or "")
        out["activated_at"] = float(data.get("activated_at") or 0)
        try:
            payload, normalized = _parse_code(code)
        except ValueError as exc:
            out["error"] = str(exc)
            _CACHE.update(key=cache_key, status=dict(out))
            return dict(out)
        out["activated"] = True
        out["customer"] = str(payload.get("customer") or "")[:100]
        try:
            out["issued"] = int(payload.get("issued") or 0)
        except Exception:
            out["issued"] = 0
        try:
            out["expires"] = int(payload.get("expires") or 0)
        except Exception:
            out["expires"] = 0
        if int(payload.get("v") or 0) != 1:
            out["error"] = "授权版本不支持"
        elif str(payload.get("edition") or "") != "commercial":
            out["error"] = "授权版本与当前版本不匹配"
        elif normalize_machine(payload.get("machine")) != normalize_machine(
                out["machine_code"]):
            out["error"] = "授权码不属于这台机器"
        else:
            now = trusted_time.now()
            if out["issued"] and out["issued"] > now + 86400:
                out["error"] = "授权签发时间异常，请检查系统时间"
            elif out["expires"] and out["expires"] < now:
                out["error"] = "授权已过期，请续期"
            else:
                out["valid"] = True
                out["error"] = ""
                if out["expires"]:
                    out["days_left"] = max(
                        0, int((out["expires"] - now) // 86400))
        _CACHE.update(key=cache_key, status=dict(out))
        return dict(out)


def license_required():
    return is_commercial() and not status().get("valid")


def activate(code):
    """验证并写入 license.json；返回新状态。失败抛 ValueError。"""
    if not is_commercial():
        raise ValueError("分享版不需要激活")
    payload, normalized = _parse_code(code)
    if int(payload.get("v") or 0) != 1:
        raise ValueError("授权版本不支持")
    if str(payload.get("edition") or "") != "commercial":
        raise ValueError("授权版本与当前版本不匹配")
    if normalize_machine(payload.get("machine")) != normalize_machine(
            machine_code()):
        raise ValueError("授权码不属于这台机器")
    expires = int(payload.get("expires") or 0)
    if expires and expires < trusted_time.now():
        raise ValueError("授权已过期")
    issued = int(payload.get("issued") or 0)
    if issued and issued > trusted_time.now() + 86400:
        raise ValueError("授权签发时间异常")
    data = {"version": 1, "code": normalized,
            "activated_at": trusted_time.now()}
    tmp = LICENSE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, LICENSE_FILE)
    with _lock():
        _CACHE.update(key=None, status=None)
    return status(force=True)
