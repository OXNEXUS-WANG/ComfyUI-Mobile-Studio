# -*- coding: utf-8 -*-
"""模型文件管理：查看、浏览器分块上传、服务器路径导入、回收站。

只管理 ComfyUI/models 下固定的几个分类目录，所有文件名都做安全化处理，
不接受路径分隔符或 ..；删除先移动到 _model_trash，避免误删无法恢复。
"""
import json
import os
import re
import secrets
import shutil
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS_ROOT = os.path.join(ROOT, "ComfyUI", "models")
TRASH_DIR = os.path.join(ROOT, "_model_trash")
UPLOAD_DIR = os.path.join(ROOT, "_model_uploads")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024 * 1024      # 单文件 50GB
CHUNK_MAX_BYTES = 16 * 1024 * 1024
UPLOAD_TTL = 24 * 3600
TRASH_TTL_DAYS = 7

CATEGORIES = {
    "checkpoints": {"label": "底模", "label_en": "Checkpoints",
                    "exts": (".safetensors", ".ckpt")},
    "diffusion_models": {"label": "扩散模型 / UNet",
                         "label_en": "Diffusion / UNet",
                         "exts": (".safetensors", ".ckpt")},
    "text_encoders": {"label": "文本编码器", "label_en": "Text encoders",
                      "exts": (".safetensors", ".gguf", ".pt", ".bin")},
    "vae": {"label": "VAE", "label_en": "VAE",
            "exts": (".safetensors", ".pt", ".ckpt")},
    "loras": {"label": "LoRA", "label_en": "LoRA",
              "exts": (".safetensors", ".pt", ".ckpt")},
    "upscale_models": {"label": "放大模型", "label_en": "Upscalers",
                       "exts": (".pth", ".pt", ".safetensors")},
}

_LOCK = threading.RLock()
_ID_RE = re.compile(r"^[0-9a-f]{16,32}$")
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    "COM%d" % i for i in range(1, 10)} | {
    "LPT%d" % i for i in range(1, 10)}


def category_dir(key):
    key = str(key or "")
    if key not in CATEGORIES:
        return ""
    return os.path.join(MODELS_ROOT, key)


def category_public():
    return [{"key": k, "label": v["label"],
             "label_en": v.get("label_en") or v["label"],
             "exts": list(v["exts"])} for k, v in CATEGORIES.items()]


def ext_allowed(key, filename):
    cat = CATEGORIES.get(str(key or ""))
    if not cat:
        return False
    return os.path.splitext(str(filename or ""))[1].lower() in cat["exts"]


def safe_filename(name):
    """只保留文件名本身；去掉路径、控制字符和 Windows 非法字符。"""
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = _BAD_CHARS.sub("_", name).strip(" .")
    if not name:
        return ""
    stem, ext = os.path.splitext(name)
    if stem.upper() in _RESERVED:
        stem = "_" + stem
    if len(name) > 180:
        keep = max(1, 180 - len(ext))
        name = stem[:keep] + ext
    return name


def _file_info(path, name=None):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return {"name": name or os.path.basename(path),
            "size": st.st_size,
            "mtime": st.st_mtime}


def list_all():
    with _LOCK:
        cats = []
        for key, cat in CATEGORIES.items():
            folder = category_dir(key)
            files = []
            try:
                names = os.listdir(folder)
            except OSError:
                names = []
            for fn in names:
                if fn.startswith(".") or not ext_allowed(key, fn):
                    continue
                info = _file_info(os.path.join(folder, fn), fn)
                if info:
                    files.append(info)
            files.sort(key=lambda x: x["name"].lower())
            cats.append({"key": key, "label": cat["label"],
                         "label_en": cat.get("label_en") or cat["label"],
                         "dir": os.path.join("ComfyUI", "models", key),
                         "files": files,
                         "bytes": sum(x["size"] for x in files)})
        try:
            usage = shutil.disk_usage(MODELS_ROOT)
            free_gb = round(usage.free / 1073741824.0, 2)
        except OSError:
            free_gb = 0
        return {"categories": cats,
                "trash": trash_entries(),
                "free_gb": free_gb,
                "max_upload_gb": round(MAX_UPLOAD_BYTES / 1073741824.0, 1)}


def _sidecar(tid):
    return os.path.join(TRASH_DIR, tid + ".json")


def _trash_file(tid, meta=None):
    if meta and meta.get("trash_name"):
        return os.path.join(TRASH_DIR, meta["trash_name"])
    # 兼容没有 sidecar 的旧文件：<id>__<name>
    try:
        names = os.listdir(TRASH_DIR)
    except OSError:
        return ""
    for fn in names:
        if fn.startswith(tid + "__"):
            return os.path.join(TRASH_DIR, fn)
    return ""


def trash_entries():
    entries = []
    try:
        names = os.listdir(TRASH_DIR)
    except OSError:
        return entries
    for fn in names:
        if not fn.endswith(".json"):
            continue
        tid = fn[:-5]
        if not _ID_RE.match(tid):
            continue
        try:
            with open(os.path.join(TRASH_DIR, fn), "r", encoding="utf-8") as fh:
                meta = json.load(fh) or {}
        except Exception:
            continue
        if meta.get("category") not in CATEGORIES:
            continue
        path = _trash_file(tid, meta)
        if not path or not os.path.isfile(path):
            continue
        entries.append({
            "id": tid,
            "category": meta.get("category"),
            "name": meta.get("name") or os.path.basename(path),
            "size": meta.get("size") or os.path.getsize(path),
            "deleted_at": meta.get("deleted_at") or 0,
            "expires_at": (meta.get("deleted_at") or 0) + TRASH_TTL_DAYS * 86400,
        })
    entries.sort(key=lambda x: x.get("deleted_at") or 0, reverse=True)
    return entries


def remove_model(category, name, by=""):
    """移动到回收站；返回记录。调用方负责检查任务是否正在使用。"""
    key = str(category or "")
    cat_dir = category_dir(key)
    if not cat_dir:
        raise ValueError("未知的模型分类")
    raw_name = str(name or "")
    if "/" in raw_name or "\\" in raw_name:
        raise ValueError("文件名不合法")
    safe = safe_filename(raw_name)
    if not safe or safe != raw_name:
        raise ValueError("文件名不合法")
    if not ext_allowed(key, safe):
        raise ValueError("这个分类不支持该文件类型")
    src = os.path.join(cat_dir, safe)
    if not os.path.isfile(src):
        raise ValueError("模型文件不存在")
    try:
        size = os.path.getsize(src)
    except OSError:
        size = 0
    os.makedirs(TRASH_DIR, exist_ok=True)
    with _LOCK:
        tid = secrets.token_hex(8)
        trash_name = tid + "__" + safe
        dest = os.path.join(TRASH_DIR, trash_name)
        try:
            shutil.move(src, dest)
        except Exception as exc:
            raise ValueError("删除失败（模型可能正在被 ComfyUI 使用）：%s" % exc)
        meta = {"id": tid, "category": key, "name": safe,
                "trash_name": trash_name, "size": size,
                "deleted_at": time.time(), "by": str(by or "")}
        with open(_sidecar(tid), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
    return meta


def restore_model(tid):
    tid = str(tid or "")
    if not _ID_RE.match(tid):
        raise ValueError("回收站记录不合法")
    with _LOCK:
        try:
            with open(_sidecar(tid), "r", encoding="utf-8") as fh:
                meta = json.load(fh) or {}
        except Exception:
            raise ValueError("回收站记录不存在")
        key = meta.get("category")
        cat_dir = category_dir(key)
        if not cat_dir:
            raise ValueError("原分类不存在")
        name = safe_filename(meta.get("name"))
        if not name:
            raise ValueError("原文件名不合法")
        os.makedirs(cat_dir, exist_ok=True)
        dest = os.path.join(cat_dir, name)
        if os.path.exists(dest):
            raise ValueError("目标位置已经有同名模型")
        src = _trash_file(tid, meta)
        if not src or not os.path.isfile(src):
            raise ValueError("回收站文件不存在")
        shutil.move(src, dest)
        try:
            os.remove(_sidecar(tid))
        except OSError:
            pass
        return meta


def purge_model(tid):
    tid = str(tid or "")
    if not _ID_RE.match(tid):
        raise ValueError("回收站记录不合法")
    with _LOCK:
        meta = {}
        try:
            with open(_sidecar(tid), "r", encoding="utf-8") as fh:
                meta = json.load(fh) or {}
        except Exception:
            pass
        removed = 0
        src = _trash_file(tid, meta)
        if src and os.path.isfile(src):
            os.remove(src)
            removed += 1
        try:
            os.remove(_sidecar(tid))
            removed += 1
        except OSError:
            pass
        if not removed:
            raise ValueError("回收站记录不存在")
        return removed


def empty_trash():
    removed = 0
    for item in trash_entries():
        try:
            removed += purge_model(item["id"])
        except Exception:
            pass
    return removed


def import_path(category, source_path, move=False, by=""):
    """从服务器上的绝对路径导入模型；默认复制，勾选移动才删除源文件。"""
    key = str(category or "")
    cat_dir = category_dir(key)
    if not cat_dir:
        raise ValueError("未知的模型分类")
    src = os.path.abspath(str(source_path or "").strip().strip('"'))
    if not src or not os.path.isfile(src):
        raise ValueError("找不到源文件，请填写服务器上的完整路径")
    name = safe_filename(os.path.basename(src))
    if not name or not ext_allowed(key, name):
        raise ValueError("文件类型不属于这个分类")
    dest = os.path.join(cat_dir, name)
    if os.path.abspath(src) == os.path.abspath(dest):
        raise ValueError("源文件已经在这个模型目录里")
    if os.path.exists(dest):
        raise ValueError("目标位置已经有同名模型")
    size = os.path.getsize(src)
    os.makedirs(cat_dir, exist_ok=True)
    if not move:
        try:
            free = shutil.disk_usage(cat_dir).free
        except OSError:
            free = size
        if free < size + 64 * 1024 * 1024:
            raise ValueError("磁盘剩余空间不足")
    try:
        if move:
            shutil.move(src, dest)
        else:
            shutil.copy2(src, dest)
    except Exception as exc:
        raise ValueError("导入失败：%s" % exc)
    info = _file_info(dest, name) or {}
    info["category"] = key
    return info


def _meta_path(uid):
    return os.path.join(UPLOAD_DIR, uid + ".json")


def _part_path(uid):
    return os.path.join(UPLOAD_DIR, uid + ".part")


def cleanup_uploads(now=None):
    """清理超过 24 小时未完成的上传。"""
    now = float(now or time.time())
    try:
        names = os.listdir(UPLOAD_DIR)
    except OSError:
        return 0
    removed = 0
    for fn in names:
        path = os.path.join(UPLOAD_DIR, fn)
        try:
            if now - os.path.getmtime(path) > UPLOAD_TTL:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def upload_start(category, filename, size, by=""):
    key = str(category or "")
    cat_dir = category_dir(key)
    if not cat_dir:
        raise ValueError("未知的模型分类")
    name = safe_filename(filename)
    if not name or not ext_allowed(key, name):
        raise ValueError("文件类型不属于这个分类")
    try:
        size = int(size)
    except Exception:
        raise ValueError("文件大小不合法")
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise ValueError("文件大小超出限制")
    os.makedirs(cat_dir, exist_ok=True)
    if os.path.exists(os.path.join(cat_dir, name)):
        raise ValueError("目标位置已经有同名模型")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    try:
        free = shutil.disk_usage(cat_dir).free
    except OSError:
        free = size
    if free < size + 256 * 1024 * 1024:
        raise ValueError("磁盘剩余空间不足")
    cleanup_uploads()
    with _LOCK:
        uid = secrets.token_hex(12)
        with open(_part_path(uid), "wb") as fh:
            fh.truncate(0)
        meta = {"id": uid, "category": key, "name": name, "size": size,
                "received": 0, "created": time.time(), "by": str(by or "")}
        with open(_meta_path(uid), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
    return {"upload_id": uid, "chunk_size": 8 * 1024 * 1024,
            "received": 0, "size": size}


def _upload_meta(uid):
    uid = str(uid or "")
    if not _ID_RE.match(uid):
        raise ValueError("上传任务不合法")
    try:
        with open(_meta_path(uid), "r", encoding="utf-8") as fh:
            meta = json.load(fh) or {}
    except Exception:
        raise ValueError("上传任务不存在或已过期")
    return meta


def upload_chunk(uid, offset, data):
    try:
        offset = int(offset or 0)
    except Exception:
        raise ValueError("上传位置不合法")
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("上传内容为空")
    if len(data) > CHUNK_MAX_BYTES:
        raise ValueError("单个分块太大")
    with _LOCK:
        meta = _upload_meta(uid)
        size = int(meta.get("size") or 0)
        received = int(meta.get("received") or 0)
        if offset != received:
            return {"received": received, "size": size,
                    "error": "上传位置不一致，请续传"}
        if received + len(data) > size:
            raise ValueError("上传内容超过文件大小")
        with open(_part_path(uid), "r+b") as fh:
            fh.seek(received)
            fh.write(data)
        meta["received"] = received + len(data)
        with open(_meta_path(uid), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
        return {"received": meta["received"], "size": size}


def upload_finish(uid):
    with _LOCK:
        meta = _upload_meta(uid)
        size = int(meta.get("size") or 0)
        received = int(meta.get("received") or 0)
        if received != size:
            raise ValueError("文件还没有上传完整")
        key = meta.get("category")
        cat_dir = category_dir(key)
        if not cat_dir:
            raise ValueError("未知的模型分类")
        name = safe_filename(meta.get("name"))
        dest = os.path.join(cat_dir, name)
        if os.path.exists(dest):
            raise ValueError("目标位置已经有同名模型")
        os.makedirs(cat_dir, exist_ok=True)
        try:
            shutil.move(_part_path(uid), dest)
        except Exception as exc:
            raise ValueError("保存模型失败：%s" % exc)
        try:
            os.remove(_meta_path(uid))
        except OSError:
            pass
        info = _file_info(dest, name) or {}
        info["category"] = key
        return info


def upload_cancel(uid):
    uid = str(uid or "")
    if not _ID_RE.match(uid):
        raise ValueError("上传任务不合法")
    removed = 0
    with _LOCK:
        for path in (_part_path(uid), _meta_path(uid)):
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    if not removed:
        raise ValueError("上传任务不存在")
    return removed
