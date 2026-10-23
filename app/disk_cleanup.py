# -*- coding: utf-8 -*-
"""自动磁盘清理：默认关闭，只清旧图库文件，收藏永远保留。

清理策略刻意保守：
- 只处理 generated 下的图片/视频，以及可选的 ComfyUI/output 原始输出；
- 必须超过保留天数，按最旧优先；
- 收藏文件（图库里的收藏）永不删除；
- 磁盘剩余高于 min_free_gb 时不清理，清到 target_free_gb 为止；
- 单次最多删除 max_files_per_run 个，避免一次误删太多。
"""
import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ROOT, "cleanup.json")

DEFAULT_SETTINGS = {
    "enabled": False,
    "retention_days": 30,
    "min_free_gb": 10,          # 低于这个值触发自动清理
    "target_free_gb": 20,       # 清理到这个值以上
    "warn_free_gb": 10,         # 低于这个值在健康报告里告警
    "critical_free_gb": 1,      # 低于这个值直接暂停新任务/上传
    "include_videos": True,
    "include_comfy_output": False,
    "max_files_per_run": 500,
    "last_run": 0.0,
    "last_result": {},
}

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".webm")
MEDIA_EXT = IMAGE_EXT + VIDEO_EXT
_LOCK = threading.RLock()
_CACHE = {"mtime": 0.0, "settings": None}


def _clamp_int(value, lo, hi, default):
    try:
        n = int(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _clean(raw):
    src = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_SETTINGS)
    out["enabled"] = bool(src.get("enabled", out["enabled"]))
    out["include_videos"] = bool(src.get("include_videos", True))
    out["include_comfy_output"] = bool(
        src.get("include_comfy_output", False))
    out["retention_days"] = _clamp_int(
        src.get("retention_days"), 1, 3650, out["retention_days"])
    out["min_free_gb"] = _clamp_int(
        src.get("min_free_gb"), 1, 10000, out["min_free_gb"])
    out["target_free_gb"] = _clamp_int(
        src.get("target_free_gb"), 1, 10000, out["target_free_gb"])
    out["warn_free_gb"] = _clamp_int(
        src.get("warn_free_gb"), 1, 10000, out["warn_free_gb"])
    out["critical_free_gb"] = _clamp_int(
        src.get("critical_free_gb"), 1, 10000, out["critical_free_gb"])
    if out["critical_free_gb"] > out["warn_free_gb"]:
        out["critical_free_gb"] = out["warn_free_gb"]
    if out["min_free_gb"] < out["critical_free_gb"]:
        out["min_free_gb"] = out["critical_free_gb"]
    if out["target_free_gb"] < out["min_free_gb"]:
        out["target_free_gb"] = out["min_free_gb"]
    out["max_files_per_run"] = _clamp_int(
        src.get("max_files_per_run"), 1, 5000,
        out["max_files_per_run"])
    try:
        out["last_run"] = max(0.0, float(src.get("last_run") or 0))
    except Exception:
        out["last_run"] = 0.0
    result = src.get("last_result")
    out["last_result"] = result if isinstance(result, dict) else {}
    return out


def load(force=False):
    try:
        mtime = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if (not force and _CACHE["settings"] is not None
                and _CACHE["mtime"] == mtime):
            return dict(_CACHE["settings"])
        data = {}
        if mtime:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
            except Exception:
                data = {}
        cfg = _clean(data)
        _CACHE.update({"mtime": mtime, "settings": cfg})
        return dict(cfg)


def save(patch):
    with _LOCK:
        cfg = load(force=True)
        if isinstance(patch, dict):
            cfg.update(patch)
        cfg = _clean(cfg)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        _CACHE.update({"mtime": os.path.getmtime(SETTINGS_FILE),
                       "settings": cfg})
        return dict(cfg)


def public_settings(cfg=None):
    cfg = dict(cfg or load())
    return {
        "enabled": bool(cfg.get("enabled")),
        "retention_days": cfg.get("retention_days"),
        "min_free_gb": cfg.get("min_free_gb"),
        "target_free_gb": cfg.get("target_free_gb"),
        "warn_free_gb": cfg.get("warn_free_gb"),
        "critical_free_gb": cfg.get("critical_free_gb"),
        "include_videos": bool(cfg.get("include_videos")),
        "include_comfy_output": bool(cfg.get("include_comfy_output")),
        "max_files_per_run": cfg.get("max_files_per_run"),
        "last_run": cfg.get("last_run") or 0,
        "last_result": cfg.get("last_result") or {},
    }


def notice(cfg=None):
    """给普通图库用户的提示；关闭时返回 None。"""
    cfg = cfg or load()
    if not cfg.get("enabled"):
        return None
    return {
        "enabled": True,
        "retention_days": cfg.get("retention_days"),
        "min_free_gb": cfg.get("min_free_gb"),
        "keep_favorites": True,
        "include_videos": bool(cfg.get("include_videos")),
        "last_run": cfg.get("last_run") or 0,
        "last_result": cfg.get("last_result") or {},
    }


def _owner_of(rel):
    parts = str(rel or "").replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else ""


def _load_favorites(base):
    favs = {}
    if not os.path.isdir(base):
        return favs
    try:
        owners = [d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d))
                  and not d.startswith(".")]
    except OSError:
        owners = []
    for owner in owners:
        path = os.path.join(base, owner, ".favorites.json")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or []
            favs[owner] = set(str(x) for x in data if x)
        except Exception:
            continue
    # 旧版管理员收藏在 generated/.favorites.json
    try:
        with open(os.path.join(base, ".favorites.json"),
                  "r", encoding="utf-8") as fh:
            data = json.load(fh) or []
        favs["admin"] = favs.get("admin", set()) | set(
            str(x) for x in data if x)
    except Exception:
        pass
    return favs


def gallery_candidates(deliver_dir, retention_days=30, max_files=500,
                       include_videos=True, now=None):
    """扫描图库，返回按 mtime 从旧到新的可清理文件。

    返回项：rel / owner / size / mtime。仅扫描普通模型目录，跳过 .thumbs
    等点目录；收藏文件（按相对名或文件名匹配）不进入结果。
    """
    base = os.path.abspath(deliver_dir)
    if not os.path.isdir(base):
        return []
    now = float(now or time.time())
    cutoff = now - max(1, int(retention_days)) * 86400
    exts = MEDIA_EXT if include_videos else IMAGE_EXT
    favs = _load_favorites(base)
    out = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.startswith(".") or not fn.lower().endswith(exts):
                continue
            path = os.path.join(root, fn)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if st.st_mtime > cutoff:
                continue
            rel = os.path.relpath(path, base).replace(os.sep, "/")
            owner = _owner_of(rel)
            owner_favs = favs.get(owner, set())
            if rel in owner_favs or fn in owner_favs:
                continue
            out.append({"rel": rel, "owner": owner,
                        "size": st.st_size, "mtime": st.st_mtime})
    out.sort(key=lambda x: x["mtime"])
    return out[:max(1, int(max_files))]


def output_candidates(output_dir, retention_days=30, max_files=500,
                      include_videos=True, now=None):
    """ComfyUI/output 原始输出候选；只按扩展名和年龄判断。"""
    base = os.path.abspath(output_dir)
    if not os.path.isdir(base):
        return []
    now = float(now or time.time())
    cutoff = now - max(1, int(retention_days)) * 86400
    exts = MEDIA_EXT if include_videos else IMAGE_EXT
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return []
    for fn in names:
        if fn.startswith(".") or not fn.lower().endswith(exts):
            continue
        path = os.path.join(base, fn)
        try:
            if not os.path.isfile(path):
                continue
            st = os.stat(path)
        except OSError:
            continue
        if st.st_mtime > cutoff:
            continue
        out.append({"rel": fn, "owner": "", "size": st.st_size,
                    "mtime": st.st_mtime, "source": "output"})
    out.sort(key=lambda x: x["mtime"])
    return out[:max(1, int(max_files))]


def plan(target_bytes, candidates):
    """按最旧优先选出要删的文件，直到释放 target_bytes。"""
    picked = []
    total = 0
    for item in candidates:
        if total >= target_bytes:
            break
        picked.append(item)
        total += int(item.get("size") or 0)
    return picked, total
