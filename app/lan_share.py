# -*- coding: utf-8 -*-
"""局域网算力共享：worker 注册表、接入码、心跳与权限。

这个模块只管“节点数据”，不直接操作调度器/任务执行；app_core 和
web_server 通过这里的函数读写注册表。所有文件写入都是原子的。
"""

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path

import edition_policy
import monitor_center

ROOT = Path(__file__).resolve().parent
WORKERS_FILE = ROOT / "workers.json"

WORKERS_LOCK = threading.RLock()
WORKERS = {}
JOIN_CODES = {}
SETTINGS = {
    "remote_enabled": False,
    "local_enabled": True,
    "protocol": 1,
    "heartbeat_ttl": 20,
    "join_code_ttl": 900,
}
JOIN_ATTEMPTS = {}
_LAST_SAVE = 0.0
_DIRTY = False

HOTSPOT_NET = ipaddress.ip_network("192.168.137.0/24")
LOOPBACK_V4 = ipaddress.ip_network("127.0.0.0/8")
ROLE_ADMIN = "admin"

JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# --------------------------------------------------------------------- 基础

def _now():
    return time.time()


def _sha256(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _new_id():
    return "w_" + secrets.token_hex(6)


def _new_secret():
    return "wsec_" + secrets.token_urlsafe(32)


def normalize_ip(ip):
    text = str(ip or "").strip()
    if not text:
        return ""
    if text.lower().startswith("::ffff:"):
        text = text[7:]
    return text


def is_loopback_ip(ip):
    text = normalize_ip(ip)
    try:
        addr = ipaddress.ip_address(text)
        return addr.is_loopback
    except ValueError:
        return False


def worker_ip_allowed(ip):
    """只允许本机 + Windows 热点网段；校园网 172.24.x 明确拒绝。"""
    text = normalize_ip(ip)
    if not text:
        return False
    try:
        addr = ipaddress.ip_address(text)
    except ValueError:
        return False
    if addr.version == 6:
        return addr.is_loopback
    return addr in LOOPBACK_V4 or addr in HOTSPOT_NET


def worker_https_required(ip):
    return not is_loopback_ip(ip)


def _clean_name(value, fallback="未命名节点"):
    text = re.sub(r"[\r\n\t]+", " ", str(value or "")).strip()
    text = text[:48]
    return text or fallback


def _clean_list(values, limit=5000):
    out = []
    seen = set()
    for item in values or []:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:240])
        if len(out) >= limit:
            break
    return out


def _clean_models(models):
    models = models if isinstance(models, dict) else {}
    out = {}
    for folder in ("checkpoints", "diffusion_models", "unet", "text_encoders",
                   "clip", "vae", "loras", "upscale_models"):
        out[folder] = _clean_list(models.get(folder) or [])
    return out


def _clean_probe(probe):
    probe = probe if isinstance(probe, dict) else {}
    gpu = probe.get("gpu") if isinstance(probe.get("gpu"), dict) else {}
    models = probe.get("models") if isinstance(probe.get("models"), dict) else {}
    caps = probe.get("capabilities") if isinstance(probe.get("capabilities"), dict) else {}
    try:
        vram = float(probe.get("vram_mb") or gpu.get("vram_total_mb") or 0)
    except Exception:
        vram = 0
    try:
        max_pixels = int(caps.get("max_pixels") or probe.get("max_pixels") or 0)
    except Exception:
        max_pixels = 0
    try:
        max_count = int(caps.get("max_count") or probe.get("max_count") or 4)
    except Exception:
        max_count = 4
    return {
        "os": str(probe.get("os") or "")[:120],
        "hostname": _clean_name(probe.get("hostname") or "", ""),
        "python": str(probe.get("python") or "")[:40],
        "agent_version": str(probe.get("agent_version") or "")[:32],
        "protocol": int(probe.get("protocol") or 0),
        "gpu_name": str(probe.get("gpu_name") or gpu.get("name") or "")[:160],
        "vram_mb": round(vram, 1),
        "gpu_util": probe.get("gpu_util"),
        "vram_used_mb": probe.get("vram_used_mb"),
        "gpu_temp_c": probe.get("gpu_temp_c"),
        "comfy_version": str(probe.get("comfy_version") or "")[:40],
        "comfy_ready": bool(probe.get("comfy_ready")),
        "comfy_queue_depth": int(probe.get("comfy_queue_depth") or 0),
        "models": _clean_models(models),
        "nodes": _clean_list(probe.get("nodes") or []),
        "disk_free_mb": probe.get("disk_free_mb"),
        "capabilities": {
            "max_pixels": max_pixels,
            "max_count": max(1, min(8, max_count)),
            "max_job_sec": int(caps.get("max_job_sec") or 900),
            "kinds": _clean_list(caps.get("kinds") or ["gen"], 10),
        },
        "updated": _now(),
    }


def _worker_default(worker_id, name, secret, ip, probe, agent_version):
    probe = _clean_probe(probe)
    return {
        "id": worker_id,
        "name": _clean_name(name, probe.get("hostname") or "未命名节点"),
        "status": "pending",          # pending | approved | rejected | revoked
        "secret_hash": _sha256(secret),
        "created": _now(),
        "created_ip": normalize_ip(ip),
        "approved": False,
        "approved_at": 0,
        "approved_by": "",
        "owner_id": "admin",
        "trusted": False,
        "allowed_users": [],
        "paused_by_admin": False,
        "paused_by_owner": False,
        "enabled": True,
        "last_seen": _now(),
        "last_ip": normalize_ip(ip),
        "agent_version": str(agent_version or probe.get("agent_version") or "")[:32],
        "protocol": int(probe.get("protocol") or 0),
        "inventory": probe,
        "comfy_ready": bool(probe.get("comfy_ready")),
        "comfy_busy": False,
        "agent_paused": False,
        "accepting": True,
        "current_job": "",
        "current_attempt": 0,
        "last_error": "",
        "refresh_inventory": False,
        "stats": {"jobs": 0, "images": 0, "gpu_seconds": 0, "failures": 0},
        "revision": 1,
    }


# --------------------------------------------------------------------- 持久化

def _load_file():
    try:
        with open(WORKERS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_locked(force=False):
    global _LAST_SAVE, _DIRTY
    now = _now()
    if not force and not _DIRTY and now - _LAST_SAVE < 10:
        return
    payload = {
        "version": 1,
        "updated": now,
        "settings": dict(SETTINGS),
        "join_codes": dict(JOIN_CODES),
        "workers": dict(WORKERS),
    }
    tmp = str(WORKERS_FILE) + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, WORKERS_FILE)
        _LAST_SAVE = now
        _DIRTY = False
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def save_workers(force=True):
    with WORKERS_LOCK:
        _save_locked(force=force)


def _default_settings():
    return {"remote_enabled": False, "local_enabled": True,
            "protocol": 1, "heartbeat_ttl": 20, "join_code_ttl": 900}


def ensure_workers():
    global WORKERS, JOIN_CODES, SETTINGS
    with WORKERS_LOCK:
        if WORKERS:
            return
        data = _load_file()
        settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
        for key, default in _default_settings().items():
            value = settings.get(key, default)
            if key in ("remote_enabled", "local_enabled"):
                SETTINGS[key] = bool(value)
            else:
                try:
                    SETTINGS[key] = int(value)
                except Exception:
                    SETTINGS[key] = default
        workers = data.get("workers") if isinstance(data.get("workers"), dict) else {}
        now = _now()
        for wid, worker in workers.items():
            if not isinstance(worker, dict) or not str(wid).startswith("w_"):
                continue
            worker.setdefault("id", wid)
            worker.setdefault("status", "pending")
            worker.setdefault("owner_id", "admin")
            worker.setdefault("allowed_users", [])
            worker.setdefault("trusted", False)
            worker.setdefault("paused_by_admin", False)
            worker.setdefault("paused_by_owner", False)
            worker.setdefault("enabled", True)
            worker.setdefault("last_seen", 0)
            worker.setdefault("inventory", _clean_probe({}))
            worker.setdefault("stats", {"jobs": 0, "images": 0,
                                        "gpu_seconds": 0, "failures": 0})
            worker.setdefault("revision", 1)
            worker["allowed_users"] = _clean_list(worker.get("allowed_users") or [], 500)
            if worker.get("status") == "approved":
                worker["approved"] = True
            WORKERS[wid] = worker
        codes = data.get("join_codes") if isinstance(data.get("join_codes"), dict) else {}
        for key, item in codes.items():
            if not isinstance(item, dict):
                continue
            if float(item.get("expires") or 0) <= now:
                continue
            JOIN_CODES[key] = item
        _save_locked(force=True)


def reload_workers():
    """从 workers.json 重新载入；系统回滚后调用。"""
    global WORKERS, JOIN_CODES, SETTINGS
    with WORKERS_LOCK:
        WORKERS.clear()
        JOIN_CODES.clear()
        SETTINGS.clear()
        SETTINGS.update(_default_settings())
    ensure_workers()
    with WORKERS_LOCK:
        return {"workers": len(WORKERS), "settings": dict(SETTINGS)}


def reset_workers():
    """清空所有节点和接入码，关闭远程算力；系统重置时调用。"""
    global WORKERS, JOIN_CODES, SETTINGS
    with WORKERS_LOCK:
        WORKERS.clear()
        JOIN_CODES.clear()
        SETTINGS.clear()
        SETTINGS.update(_default_settings())
        _save_locked(force=True)
        return {"workers": 0, "settings": dict(SETTINGS)}


# --------------------------------------------------------------------- 查询 / 公开展示

def _online(worker, now=None):
    now = now or _now()
    ttl = max(5, int(SETTINGS.get("heartbeat_ttl") or 20))
    return bool(worker.get("last_seen")) and now - float(worker.get("last_seen") or 0) <= ttl


def worker_accepting(worker, now=None):
    if not worker:
        return False
    now = now or _now()
    inv = worker.get("inventory") or {}
    return bool(
        worker.get("status") == "approved"
        and worker.get("enabled", True)
        and not worker.get("paused_by_admin")
        and not worker.get("paused_by_owner")
        and not worker.get("agent_paused")
        and worker.get("accepting", True)
        and worker.get("comfy_ready", inv.get("comfy_ready", False))
        and not worker.get("comfy_busy")
        and _online(worker, now)
    )


def worker_public(worker, admin=False):
    inv = worker.get("inventory") or {}
    out = {
        "id": worker.get("id"),
        "name": worker.get("name"),
        "status": worker.get("status"),
        "approved": bool(worker.get("approved")),
        "owner_id": worker.get("owner_id") or "admin",
        "trusted": bool(worker.get("trusted")),
        "allowed_users": list(worker.get("allowed_users") or []),
        "paused_by_admin": bool(worker.get("paused_by_admin")),
        "paused_by_owner": bool(worker.get("paused_by_owner")),
        "agent_paused": bool(worker.get("agent_paused")),
        "enabled": bool(worker.get("enabled", True)),
        "online": _online(worker),
        "accepting": worker_accepting(worker),
        "last_seen": worker.get("last_seen") or 0,
        "agent_version": worker.get("agent_version") or "",
        "protocol": worker.get("protocol") or 0,
        "comfy_ready": bool(worker.get("comfy_ready")),
        "comfy_busy": bool(worker.get("comfy_busy")),
        "current_job": worker.get("current_job") or "",
        "last_error": worker.get("last_error") or "",
        "inventory": {
            "os": inv.get("os") or "",
            "hostname": inv.get("hostname") or "",
            "python": inv.get("python") or "",
            "gpu_name": inv.get("gpu_name") or "",
            "vram_mb": inv.get("vram_mb") or 0,
            "gpu_util": inv.get("gpu_util"),
            "vram_used_mb": inv.get("vram_used_mb"),
            "gpu_temp_c": inv.get("gpu_temp_c"),
            "comfy_version": inv.get("comfy_version") or "",
            "models": inv.get("models") or {},
            "nodes_count": len(inv.get("nodes") or []),
            "nodes": inv.get("nodes") or [],
            "disk_free_mb": inv.get("disk_free_mb"),
            "capabilities": inv.get("capabilities") or {},
            "updated": inv.get("updated") or 0,
        },
        "stats": worker.get("stats") or {},
        "revision": worker.get("revision") or 1,
    }
    if admin:
        out["last_ip"] = worker.get("last_ip") or ""
        out["created"] = worker.get("created") or 0
        out["created_ip"] = worker.get("created_ip") or ""
        out["approved_at"] = worker.get("approved_at") or 0
        out["approved_by"] = worker.get("approved_by") or ""
        out["refresh_inventory"] = bool(worker.get("refresh_inventory"))
    return out


def _used_worker_slots_locked():
    """调用方必须持有 WORKERS_LOCK；pending 和 approved 都占名额。"""
    return sum(1 for w in WORKERS.values()
               if w.get("status") in ("pending", "approved"))


def worker_quota():
    p = edition_policy.policy()
    with WORKERS_LOCK:
        used = _used_worker_slots_locked()
    maxn = max(0, int(p.get("max_workers") or 0))
    return {
        "edition": p.get("edition"),
        "label": p.get("label"),
        "label_en": p.get("label_en"),
        "used": used,
        "max": maxn,
        "remaining": max(0, maxn - used),
        "reached": bool(maxn and used >= maxn),
    }


def admin_payload():
    with WORKERS_LOCK:
        workers = [worker_public(w, admin=True) for w in WORKERS.values()]
        workers.sort(key=lambda x: (
            0 if x.get("status") == "pending" else 1,
            x.get("name") or x.get("id") or ""))
        return {
            "settings": dict(SETTINGS),
            "workers": workers,
            "quota": worker_quota(),
            "pending": sum(1 for w in workers if w.get("status") == "pending"),
            "online": sum(1 for w in workers if w.get("online")),
            "join_codes": [
                {"expires": item.get("expires"),
                 "created_by": item.get("created_by"),
                 "used_by": item.get("used_by") or ""}
                for item in JOIN_CODES.values()
            ],
        }


def owner_payload(uid):
    with WORKERS_LOCK:
        rows = [worker_public(w, admin=False) for w in WORKERS.values()
                if w.get("owner_id") == uid]
        rows.sort(key=lambda x: x.get("name") or "")
        return {"workers": rows}


def get_worker(wid):
    with WORKERS_LOCK:
        return WORKERS.get(str(wid or ""))


def list_workers():
    with WORKERS_LOCK:
        return list(WORKERS.values())


# --------------------------------------------------------------------- 接入码

def _code_hash(code):
    normalized = re.sub(r"[^A-Za-z0-9]", "", str(code or "")).upper()
    return _sha256("lan_share_join:" + normalized)


def _join_rate_limited(ip):
    now = _now()
    bucket = JOIN_ATTEMPTS.setdefault(normalize_ip(ip) or "?", deque())
    while bucket and now - bucket[0] > 600:
        bucket.popleft()
    if len(bucket) >= 10:
        return True
    bucket.append(now)
    return False


def create_join_code(created_by="admin", note=""):
    with WORKERS_LOCK:
        now = _now()
        for key in list(JOIN_CODES.keys()):
            if float(JOIN_CODES[key].get("expires") or 0) <= now:
                JOIN_CODES.pop(key, None)
        # 最多同时保留 10 个有效接入码
        active = [k for k, v in JOIN_CODES.items()
                  if not v.get("used_by")]
        if len(active) >= 10:
            oldest = min(active, key=lambda k: JOIN_CODES[k].get("created") or 0)
            JOIN_CODES.pop(oldest, None)
        raw = "".join(secrets.choice(JOIN_ALPHABET) for _ in range(8))
        code = raw
        expires = now + max(60, int(SETTINGS.get("join_code_ttl") or 900))
        JOIN_CODES[_code_hash(code)] = {
            "created": now,
            "expires": expires,
            "created_by": created_by,
            "note": str(note or "")[:120],
            "used_by": "",
            "used_at": 0,
        }
        _DIRTY = True
        _save_locked(force=True)
        return {"code": code, "expires": expires}


def redeem_join_code(code, ip, name, probe, agent_version):
    """返回 (worker, secret, error)。error 为中文原因。"""
    if not worker_ip_allowed(ip):
        return None, "", "这个来源地址不允许接入算力节点"
    if _join_rate_limited(ip):
        return None, "", "接入尝试太频繁，稍后再试"
    with WORKERS_LOCK:
        key = _code_hash(code)
        item = JOIN_CODES.get(key)
        now = _now()
        if not item:
            return None, "", "接入码无效"
        if float(item.get("expires") or 0) <= now:
            JOIN_CODES.pop(key, None)
            _save_locked(force=True)
            return None, "", "接入码已过期"
        if item.get("used_by"):
            return None, "", "接入码已经被使用"
        if _used_worker_slots_locked() >= edition_policy.max_workers():
            return None, "", edition_policy.quota_message("workers")
        wid = _new_id()
        secret = _new_secret()
        worker = _worker_default(wid, name, secret, ip, probe, agent_version)
        worker["status"] = "pending"
        WORKERS[wid] = worker
        item["used_by"] = wid
        item["used_at"] = now
        _DIRTY = True
        _save_locked(force=True)
        return worker, secret, ""


# --------------------------------------------------------------------- 认证 / 心跳

def _bad_token():
    return None


def worker_auth(header, ip):
    """Bearer <worker_id>.<secret>；返回 worker 或 None。"""
    text = str(header or "").strip()
    if not text.lower().startswith("bearer "):
        return None
    token = text[7:].strip()
    if "." not in token:
        return None
    wid, secret = token.split(".", 1)
    with WORKERS_LOCK:
        worker = WORKERS.get(wid)
        if not worker or not worker.get("enabled", True):
            return None
        expected = str(worker.get("secret_hash") or "")
        actual = _sha256(secret)
        if not expected or not hmac.compare_digest(expected, actual):
            return None
        if worker.get("status") in ("rejected", "revoked"):
            return None
        worker["last_ip"] = normalize_ip(ip)
        return worker


def heartbeat(worker_id, payload, ip):
    payload = payload if isinstance(payload, dict) else {}
    with WORKERS_LOCK:
        worker = WORKERS.get(str(worker_id or ""))
        if not worker:
            return None
        was_online = _online(worker)
        worker["last_seen"] = _now()
        worker["last_ip"] = normalize_ip(ip)
        for key in ("agent_version", "comfy_ready", "comfy_busy",
                    "agent_paused", "accepting", "current_job", "last_error"):
            if key in payload:
                worker[key] = payload[key]
        if "paused" in payload:
            worker["agent_paused"] = bool(payload.get("paused"))
        try:
            worker["current_attempt"] = int(payload.get("attempt") or 0)
        except Exception:
            worker["current_attempt"] = 0
        if isinstance(payload.get("inventory"), dict):
            worker["inventory"] = _clean_probe(payload["inventory"])
            worker["comfy_ready"] = bool(worker["inventory"].get("comfy_ready"))
            if payload["inventory"].get("agent_version"):
                worker["agent_version"] = str(payload["inventory"]["agent_version"])[:32]
            if payload["inventory"].get("protocol"):
                worker["protocol"] = int(payload["inventory"]["protocol"])
        refresh = bool(worker.get("refresh_inventory"))
        if refresh:
            worker["refresh_inventory"] = False
        try:
            inv = worker.get("inventory") or {}
            monitor_center.note_worker(worker.get("id") or worker_id, {
                "t": _now(),
                "gpu_util": inv.get("gpu_util"),
                "vram_used_mb": inv.get("vram_used_mb"),
                "vram_total_mb": inv.get("vram_mb"),
                "temp_c": inv.get("gpu_temp_c"),
                "busy": bool(worker.get("comfy_busy") or worker.get("current_job")),
                "online": True,
                "current_job": worker.get("current_job") or "",
            })
        except Exception:
            pass
        _DIRTY = True
        _save_locked(force=False)
        online = _online(worker)
        return {
            "ok": True,
            "approved": worker.get("status") == "approved",
            "status": worker.get("status"),
            "paused": bool(worker.get("paused_by_admin")
                           or worker.get("paused_by_owner")),
            "paused_by_admin": bool(worker.get("paused_by_admin")),
            "paused_by_owner": bool(worker.get("paused_by_owner")),
            "trusted": bool(worker.get("trusted")),
            "online": online,
            "was_online": was_online,
            "refresh_inventory": refresh,
            "cancel_jobs": [],       # M2 由 app_core 填充
            "server_time": _now(),
            "heartbeat_ttl": int(SETTINGS.get("heartbeat_ttl") or 20),
        }


# --------------------------------------------------------------------- 管理操作

def _bump(worker):
    worker["revision"] = int(worker.get("revision") or 1) + 1


def update_worker(wid, data, by="admin"):
    data = data if isinstance(data, dict) else {}
    with WORKERS_LOCK:
        worker = WORKERS.get(str(wid or ""))
        if not worker:
            return None, "节点不存在"
        if "name" in data:
            worker["name"] = _clean_name(data.get("name"), worker.get("name"))
        if "owner_id" in data:
            worker["owner_id"] = str(data.get("owner_id") or "admin")
        if "trusted" in data:
            worker["trusted"] = bool(data.get("trusted"))
        if "allowed_users" in data:
            worker["allowed_users"] = _clean_list(data.get("allowed_users") or [], 500)
        if "enabled" in data:
            worker["enabled"] = bool(data.get("enabled"))
        if "status" in data and data.get("status") in (
                "pending", "approved", "rejected", "revoked"):
            needs_slot = (
                (data["status"] == "approved"
                 and worker.get("status") != "approved")
                or (data["status"] == "pending"
                    and worker.get("status") not in ("pending", "approved")))
            if needs_slot:
                # 当前节点不计入 others；其他 pending/approved 已占满时拒绝。
                others = sum(
                    1 for oid, other in WORKERS.items()
                    if oid != str(wid or "")
                    and other.get("status") in ("pending", "approved"))
                if others >= edition_policy.max_workers():
                    return None, edition_policy.quota_message("workers")
            worker["status"] = data["status"]
            worker["approved"] = data["status"] == "approved"
            if worker["approved"]:
                worker["approved_at"] = _now()
                worker["approved_by"] = str(by or "admin")
        if data.get("pause_admin") is not None:
            worker["paused_by_admin"] = bool(data.get("pause_admin"))
        if data.get("pause_owner") is not None:
            worker["paused_by_owner"] = bool(data.get("pause_owner"))
        if data.get("refresh_inventory"):
            worker["refresh_inventory"] = True
        _bump(worker)
        _DIRTY = True
        _save_locked(force=True)
        return worker, ""


def approve_worker(wid, owner_id="admin", trusted=False, allowed_users=None,
                   name=None, by="admin"):
    data = {
        "status": "approved",
        "owner_id": owner_id or "admin",
        "trusted": bool(trusted),
        "allowed_users": allowed_users or [],
        "pause_admin": False,
    }
    if name:
        data["name"] = name
    return update_worker(wid, data, by=by)


def remove_worker(wid):
    with WORKERS_LOCK:
        worker = WORKERS.pop(str(wid or ""), None)
        if not worker:
            return False
        _DIRTY = True
        _save_locked(force=True)
        return True


def rotate_secret(wid):
    secret = _new_secret()
    with WORKERS_LOCK:
        worker = WORKERS.get(str(wid or ""))
        if not worker:
            return None, ""
        worker["secret_hash"] = _sha256(secret)
        _bump(worker)
        _DIRTY = True
        _save_locked(force=True)
        return worker, secret


def set_settings(data):
    data = data if isinstance(data, dict) else {}
    with WORKERS_LOCK:
        if "remote_enabled" in data:
            SETTINGS["remote_enabled"] = bool(data.get("remote_enabled"))
        if "local_enabled" in data:
            SETTINGS["local_enabled"] = bool(data.get("local_enabled"))
        _DIRTY = True
        _save_locked(force=True)
        return dict(SETTINGS)


def settings():
    with WORKERS_LOCK:
        return dict(SETTINGS)


def worker_owner(wid):
    worker = get_worker(wid)
    return (worker or {}).get("owner_id") or ""


# --------------------------------------------------------------------- 调度辅助

def _norm_model(name):
    text = str(name or "").replace("\\", "/").strip()
    return text.casefold()


def worker_has_models(worker, requirements):
    inv = (worker.get("inventory") or {}).get("models") or {}
    aliases = {
        "diffusion_models": ("diffusion_models", "unet"),
        "text_encoders": ("text_encoders", "clip"),
    }
    for req in requirements or []:
        folder = str(req.get("folder") or "")
        name = _norm_model(req.get("name"))
        if not folder or not name:
            continue
        folders = aliases.get(folder, (folder,))
        values = []
        for f in folders:
            values.extend(inv.get(f) or [])
        available = {_norm_model(v) for v in values}
        if name not in available:
            return False
    return True


def worker_can_take(worker, user, requirements=None, pixels=0, count=1):
    if not worker_accepting(worker):
        return False
    inv = worker.get("inventory") or {}
    caps = inv.get("capabilities") or {}
    try:
        max_pixels = int(caps.get("max_pixels") or 0)
        if max_pixels and pixels and pixels > max_pixels:
            return False
        max_count = int(caps.get("max_count") or 4)
        if count and count > max_count:
            return False
    except Exception:
        pass
    if requirements and not worker_has_models(worker, requirements):
        return False
    uid = (user or {}).get("id") or ""
    role = (user or {}).get("role") or ""
    if role == ROLE_ADMIN:
        return True
    if worker.get("owner_id") == uid:
        return True
    if not worker.get("trusted"):
        return False
    allowed = worker.get("allowed_users") or []
    if not allowed or uid not in allowed:
        return False
    return True


def pause_owned_workers(uid, by="system"):
    """owner 账号被禁用/删除时，暂停其节点接新任务。"""
    with WORKERS_LOCK:
        changed = 0
        for worker in WORKERS.values():
            if worker.get("owner_id") != uid:
                continue
            if not worker.get("paused_by_admin"):
                worker["paused_by_admin"] = True
                _bump(worker)
                changed += 1
        if changed:
            _DIRTY = True
            _save_locked(force=True)
        return changed


def note_worker_job(wid, seconds=0, images=0, ok=True):
    with WORKERS_LOCK:
        worker = WORKERS.get(str(wid or ""))
        if not worker:
            return
        stats = worker.setdefault("stats", {})
        try:
            stats["jobs"] = int(stats.get("jobs") or 0) + 1
            stats["images"] = int(stats.get("images") or 0) + max(0, int(images or 0))
            stats["gpu_seconds"] = round(
                float(stats.get("gpu_seconds") or 0) + max(0.0, float(seconds or 0)), 1)
            if not ok:
                stats["failures"] = int(stats.get("failures") or 0) + 1
        except Exception:
            pass
        _DIRTY = True
        _save_locked(force=False)


def scheduler_workers():
    """给调度器的只读快照，不包含 secret。"""
    out = []
    with WORKERS_LOCK:
        for worker in WORKERS.values():
            if worker.get("status") != "approved":
                continue
            inv = worker.get("inventory") or {}
            out.append({
                "id": worker.get("id"),
                "name": worker.get("name") or worker.get("id"),
                "owner_id": worker.get("owner_id") or "admin",
                "online": _online(worker),
                "accepting": worker_accepting(worker),
                "trusted": bool(worker.get("trusted")),
                "allowed_users": tuple(worker.get("allowed_users") or []),
                "models": inv.get("models") or {},
                "nodes": tuple(inv.get("nodes") or []),
                "caps": inv.get("capabilities") or {},
                "paused": bool(worker.get("paused_by_admin")
                               or worker.get("paused_by_owner")
                               or worker.get("agent_paused")),
                "comfy_ready": bool(worker.get("comfy_ready")),
                "comfy_busy": bool(worker.get("comfy_busy")),
                "current_job": worker.get("current_job") or "",
                "revision": worker.get("revision") or 1,
            })
    return out
