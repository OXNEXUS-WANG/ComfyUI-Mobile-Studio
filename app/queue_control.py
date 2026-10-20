# -*- coding: utf-8 -*-
"""队列控制：全局/单账号暂停、优先级提升、最长等待和维护窗口。

这个模块只保存“调度策略”，不碰任务正文。文件默认放在程序根目录的
queue_control.json；找不到就用默认值。
"""
import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ROOT, "queue_control.json")

DEFAULT_SETTINGS = {
    "paused": False,
    "pause_reason": "",
    "paused_at": 0.0,
    "paused_users": {},       # uid -> {"at": 0, "by": "", "reason": ""}
    "priority_boost": {},     # uid -> 0..100
    "max_wait_seconds": 0,    # 0 = 不限制
    "maintenance": {
        "enabled": False,
        "start": "02:00",
        "end": "04:00",
        "days": [],           # 0=周一 ... 6=周日；空=每天
    },
}

_LOCK = threading.RLock()
_CACHE = {"mtime": 0.0, "data": None}


def _as_int(value, lo, hi, default):
    try:
        n = int(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _clean_clock(value, default):
    text = str(value or "").strip()
    try:
        hh, mm = text.split(":", 1)
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return "%02d:%02d" % (h, m)
    except Exception:
        pass
    return default


def _clean(data):
    src = data if isinstance(data, dict) else {}
    out = {
        "paused": bool(src.get("paused")),
        "pause_reason": str(src.get("pause_reason") or "")[:200],
        "paused_at": float(src.get("paused_at") or 0),
        "paused_users": {},
        "priority_boost": {},
        "max_wait_seconds": _as_int(
            src.get("max_wait_seconds"), 0, 7 * 24 * 3600, 0),
        "maintenance": {},
    }
    raw_users = src.get("paused_users")
    if isinstance(raw_users, dict):
        for uid, rec in list(raw_users.items())[:500]:
            uid = str(uid or "")[:80]
            if not uid:
                continue
            rec = rec if isinstance(rec, dict) else {}
            out["paused_users"][uid] = {
                "at": float(rec.get("at") or 0),
                "by": str(rec.get("by") or "")[:80],
                "reason": str(rec.get("reason") or "")[:200],
            }
    raw_boost = src.get("priority_boost")
    if isinstance(raw_boost, dict):
        for uid, value in list(raw_boost.items())[:500]:
            uid = str(uid or "")[:80]
            if uid:
                out["priority_boost"][uid] = _as_int(value, 0, 100, 0)
    mt = src.get("maintenance") if isinstance(src.get("maintenance"), dict) else {}
    days = []
    for d in (mt.get("days") or [])[:7]:
        try:
            d = int(d)
        except Exception:
            continue
        if 0 <= d <= 6 and d not in days:
            days.append(d)
    out["maintenance"] = {
        "enabled": bool(mt.get("enabled")),
        "start": _clean_clock(mt.get("start"), "02:00"),
        "end": _clean_clock(mt.get("end"), "04:00"),
        "days": sorted(days),
    }
    return out


def load(force=False):
    try:
        mtime = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if (not force and _CACHE["data"] is not None
                and mtime == _CACHE["mtime"]):
            return dict(_CACHE["data"])
        data = dict(DEFAULT_SETTINGS)
        if mtime:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                data = dict(DEFAULT_SETTINGS)
        data = _clean(data)
        _CACHE["mtime"] = mtime
        _CACHE["data"] = data
        return dict(data)


def save(data):
    data = _clean(data)
    with _LOCK:
        tmp = SETTINGS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, SETTINGS_FILE)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        _CACHE["mtime"] = os.path.getmtime(SETTINGS_FILE)
        _CACHE["data"] = data
    return data


def _minutes(text):
    hh, mm = str(text or "00:00").split(":", 1)
    return int(hh) * 60 + int(mm)


def maintenance_active(now=None):
    data = load()
    mt = data.get("maintenance") or {}
    if not mt.get("enabled"):
        return False
    now = now or time.localtime()
    days = mt.get("days") or []
    if days and (now.tm_wday not in days):
        return False
    start = _minutes(mt.get("start"))
    end = _minutes(mt.get("end"))
    cur = now.tm_hour * 60 + now.tm_min
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    # 跨午夜，例如 23:00 - 02:00
    return cur >= start or cur < end


def dispatch_blocked():
    data = load()
    return bool(data.get("paused")) or maintenance_active()


def user_paused(uid):
    return str(uid or "") in (load().get("paused_users") or {})


def user_boost(uid):
    try:
        return int((load().get("priority_boost") or {}).get(str(uid or ""), 0))
    except Exception:
        return 0


def public(now=None):
    data = load()
    out = dict(data)
    out["maintenance_active"] = maintenance_active(now)
    out["server_time"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                      now or time.localtime())
    return out


def set_paused(paused, reason="", by=""):
    data = load()
    data["paused"] = bool(paused)
    data["pause_reason"] = str(reason or "")[:200]
    data["paused_at"] = time.time() if paused else 0.0
    return save(data)


def set_user_paused(uid, paused, reason="", by=""):
    uid = str(uid or "").strip()[:80]
    if not uid:
        return None
    data = load()
    users = dict(data.get("paused_users") or {})
    if paused:
        users[uid] = {"at": time.time(), "by": str(by or "")[:80],
                      "reason": str(reason or "")[:200]}
    else:
        users.pop(uid, None)
    data["paused_users"] = users
    return save(data)


def set_priority(uid, boost):
    uid = str(uid or "").strip()[:80]
    if not uid:
        return None
    data = load()
    boosts = dict(data.get("priority_boost") or {})
    boost = _as_int(boost, 0, 100, 0)
    if boost:
        boosts[uid] = boost
    else:
        boosts.pop(uid, None)
    data["priority_boost"] = boosts
    return save(data)


def set_max_wait(seconds):
    data = load()
    data["max_wait_seconds"] = _as_int(seconds, 0, 7 * 24 * 3600, 0)
    return save(data)


def set_maintenance(enabled, start="02:00", end="04:00", days=None):
    data = load()
    data["maintenance"] = {
        "enabled": bool(enabled),
        "start": _clean_clock(start, "02:00"),
        "end": _clean_clock(end, "04:00"),
        "days": list(days or []),
    }
    return save(data)
