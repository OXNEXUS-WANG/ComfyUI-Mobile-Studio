# -*- coding: utf-8 -*-
"""守护进程与异常恢复设置。

文件放在安装根目录的 supervisor.json，由后台「系统设置」读写；
start_service.py --watch、网页服务和任务恢复逻辑都读取同一份配置。
"""
import json
import os
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ROOT, "supervisor.json")
_LOCK = threading.RLock()

DEFAULTS = {
    "enabled": True,
    "auto_restart_comfy": True,
    "auto_restart_web": True,
    "recovery_queued": True,
    "recovery_running_without_prompt": True,
    "max_restarts_per_hour": 6,
    "check_seconds": 5,
    # 智能让路：阈值和判定时长都做成配置，不同机器可以调。
    "guard_enabled": True,
    "guard_gpu_pct": 88,
    "guard_cpu_pct": 70,
    "guard_proc_pct": 150,
    "guard_enter_seconds": 5,
    "guard_recover_seconds": 6,
    "guard_cooldown_seconds": 10,
    "guard_presence_ttl": 75,
}
BOOL_KEYS = (
    "enabled", "auto_restart_comfy", "auto_restart_web",
    "recovery_queued", "recovery_running_without_prompt",
    "guard_enabled",
)
INT_RANGES = {
    "max_restarts_per_hour": (1, 100, 6),
    "check_seconds": (2, 60, 5),
    "guard_gpu_pct": (50, 100, 88),
    "guard_cpu_pct": (30, 100, 70),
    "guard_proc_pct": (50, 500, 150),
    "guard_enter_seconds": (2, 30, 5),
    "guard_recover_seconds": (2, 30, 6),
    "guard_cooldown_seconds": (0, 120, 10),
    "guard_presence_ttl": (10, 600, 75),
}


def normalize(raw):
    data = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key in BOOL_KEYS:
            if key in raw:
                data[key] = bool(raw[key])
        for key, (lo, hi, default) in INT_RANGES.items():
            try:
                value = int(raw.get(key))
            except Exception:
                continue
            data[key] = max(lo, min(hi, value))
    return data


def guard_config():
    """智能让路的有效配置；调用方不需要关心扁平键名。"""
    data = load()
    return {
        "enabled": bool(data.get("guard_enabled")),
        "gpu_pct": int(data.get("guard_gpu_pct") or 88),
        "cpu_pct": int(data.get("guard_cpu_pct") or 70),
        "proc_pct": int(data.get("guard_proc_pct") or 150),
        "enter_seconds": int(data.get("guard_enter_seconds") or 5),
        "recover_seconds": int(data.get("guard_recover_seconds") or 6),
        "cooldown_seconds": int(data.get("guard_cooldown_seconds") or 0),
        "presence_ttl": int(data.get("guard_presence_ttl") or 75),
    }


def load():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        raw = {}
    return normalize(raw)


def save(values):
    data = normalize(values)
    tmp = SETTINGS_FILE + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    return data


def status_file():
    return os.path.join(ROOT, "supervisor_status.json")


def read_status():
    path = status_file()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_status(**fields):
    path = status_file()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(fields, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pass
