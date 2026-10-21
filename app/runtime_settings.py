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
}
BOOL_KEYS = (
    "enabled", "auto_restart_comfy", "auto_restart_web",
    "recovery_queued", "recovery_running_without_prompt",
)


def normalize(raw):
    data = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key in BOOL_KEYS:
            if key in raw:
                data[key] = bool(raw[key])
        for key in ("max_restarts_per_hour", "check_seconds"):
            try:
                value = int(raw.get(key))
            except Exception:
                continue
            if key == "max_restarts_per_hour":
                data[key] = max(1, min(100, value))
            else:
                data[key] = max(2, min(60, value))
    return data


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
