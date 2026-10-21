# -*- coding: utf-8 -*-
"""插件中心：安全 JSON 插件包 + ComfyUI 代码插件隔离审批。

安全边界（重要）：
- 安全插件包只接受 JSON 的风格 / 提示词模板 / 参数预设，不执行任何代码；
- ComfyUI 代码插件先存到隔离区，只做静态体检和风险扫描，绝不自动安装；
- 只有管理员审批后才写入 ComfyUI/custom_nodes，且必须先备份旧版本；
- 安装/禁用/回滚只动 custom_nodes，不改网页程序、账号、图库和证书；
- 代码插件最终仍在 ComfyUI 进程里运行，静态扫描不能代替杀毒或代码审计。
"""
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile

import node_manager

ROOT = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(ROOT, "plugins")
PACK_DIR = os.path.join(PLUGIN_DIR, "packs")
QUARANTINE_DIR = os.path.join(PLUGIN_DIR, "quarantine")
BACKUP_DIR = os.path.join(PLUGIN_DIR, "backups")
DISABLED_DIR = os.path.join(PLUGIN_DIR, "disabled")
REGISTRY_PATH = os.path.join(PLUGIN_DIR, "registry.json")
CUSTOM_NODES_DIR = os.path.join(ROOT, "ComfyUI", "custom_nodes")

MAX_PACK_BYTES = 256 * 1024
MAX_PACKS = 20
MAX_PACK_STYLES = 20
MAX_PACK_PROMPTS = 50
MAX_PACK_PRESETS = 20
MAX_SUBMIT_BYTES = 20 * 1024 * 1024
MAX_SUBMIT_EXTRACT_BYTES = 80 * 1024 * 1024
MAX_SUBMIT_FILES = 2000
MAX_PENDING_PER_USER = 3
MAX_QUARANTINE_ITEMS = 40
MAX_QUARANTINE_BYTES = 500 * 1024 * 1024
MAX_BACKUPS = 3
CLEANUP_DAYS = 7

_LOCK = threading.RLock()
_PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _locked(fn):
    """串行化注册表读改写，避免并发审批/提交互相覆盖。"""
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper
_UID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_SIZE_RE = re.compile(r"^(\d{2,4})x(\d{2,4})$")


# --------------------------------------------------------------- 基础工具
def _safe_uid(uid):
    uid = str(uid or "")
    if not _UID_RE.match(uid):
        raise ValueError("账号标识不合法")
    return uid


def _safe_pack_id(pid):
    pid = str(pid or "").strip().lower()
    if not _PACK_ID_RE.match(pid):
        raise ValueError("插件包 ID 只能是字母、数字、- 和 _")
    return pid


def _clean_text(value, limit, required=False):
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = text[:limit].strip()
    if required and not text:
        raise ValueError("插件包缺少必填文字")
    return text


def _slug(value, fallback=""):
    text = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").lower())
    text = re.sub(r"-{2,}", "-", text).strip("-_")
    if text:
        return text[:40]
    seed = str(fallback or value or secrets.token_hex(8))
    return "pack-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def _atomic_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp-" + secrets.token_hex(4)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data
    except Exception:
        return default


def _under(base, *parts):
    base_abs = os.path.abspath(base)
    path = os.path.abspath(os.path.join(base_abs, *parts))
    if path != base_abs and not path.startswith(base_abs + os.sep):
        raise ValueError("插件路径越界")
    return path


def _rel(path):
    path = os.path.abspath(path)
    base = os.path.abspath(PLUGIN_DIR)
    if not path.startswith(base + os.sep):
        raise ValueError("插件路径越界")
    return os.path.relpath(path, base)


def _resolve_rel(rel):
    rel = str(rel or "")
    if not rel:
        return ""
    path = os.path.abspath(os.path.join(PLUGIN_DIR, rel))
    base = os.path.abspath(PLUGIN_DIR)
    if not path.startswith(base + os.sep):
        return ""
    return path


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def tree_hash(path):
    """对目录内容做稳定哈希，用于发现插件被外部改动。"""
    path = os.path.abspath(str(path or ""))
    if not os.path.isdir(path):
        return ""
    h = hashlib.sha256()
    files = 0
    total = 0
    for walk_root, dirs, names in os.walk(path):
        dirs[:] = sorted(d for d in dirs
                         if d not in node_manager.SKIP_NAMES
                         and not d.startswith("."))
        for fn in sorted(names):
            full = os.path.join(walk_root, fn)
            if os.path.islink(full):
                continue
            rel = os.path.relpath(full, path).replace("\\", "/")
            h.update(rel.encode("utf-8", "replace"))
            try:
                size = os.path.getsize(full)
                h.update(str(size).encode("ascii"))
                total += size
                files += 1
                if files > 6000 or total > 400 * 1024 * 1024:
                    return ""
                with open(full, "rb") as fh:
                    while True:
                        chunk = fh.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
            except OSError:
                continue
    return h.hexdigest()


# --------------------------------------------------------------- 安全插件包
def _normalize_styles(raw):
    if isinstance(raw, dict):
        raw = [{"name": k, "suffix": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        raw = []
    out = []
    seen = set()
    for item in raw[:MAX_PACK_STYLES * 2]:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"), 24, True)
        suffix = _clean_text(item.get("suffix") or item.get("text"), 300, True)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "suffix": suffix})
        if len(out) >= MAX_PACK_STYLES:
            break
    return out


def _normalize_prompts(raw):
    if isinstance(raw, dict):
        raw = [{"name": k, "text": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        raw = []
    out = []
    seen = set()
    for item in raw[:MAX_PACK_PROMPTS * 2]:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"), 40, True)
        text = _clean_text(item.get("text") or item.get("prompt"), 2000, True)
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "text": text})
        if len(out) >= MAX_PACK_PROMPTS:
            break
    return out


def _normalize_presets(raw):
    if not isinstance(raw, list):
        raw = []
    out = []
    seen = set()
    for item in raw[:MAX_PACK_PRESETS * 2]:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"), 24, True)
        key = name.lower()
        if key in seen:
            continue
        preset = {"name": name}
        size = str(item.get("size") or "").strip().lower().replace("×", "x")
        match = _SIZE_RE.match(size)
        if match:
            w, h = int(match.group(1)), int(match.group(2))
            if 16 <= w <= 1536 and 16 <= h <= 1536:
                preset["size"] = "%dx%d" % (
                    max(16, round(w / 16) * 16),
                    max(16, round(h / 16) * 16))
        for field, lo, hi, cast in (("steps", 1, 60, int),
                                    ("cfg", 0.0, 20.0, float),
                                    ("count", 1, 4, int)):
            if field not in item:
                continue
            try:
                val = cast(item.get(field))
            except (TypeError, ValueError):
                continue
            if val < lo or val > hi:
                continue
            preset[field] = round(val, 2) if field == "cfg" else int(val)
        if len(preset) <= 1:
            continue
        seen.add(key)
        out.append(preset)
        if len(out) >= MAX_PACK_PRESETS:
            break
    return out


def normalize_pack(raw, uid, existing=None):
    if not isinstance(raw, dict):
        raise ValueError("插件包必须是 JSON 对象")
    try:
        schema = int(raw.get("schema") or 1)
    except Exception:
        schema = 0
    if schema != 1:
        raise ValueError("不支持的插件包版本（schema 必须是 1）")
    name = _clean_text(raw.get("name"), 40, True)
    pid = _safe_pack_id(raw.get("id") or (existing or {}).get("id")
                        or _slug(name, uid + "|" + name))
    version = _clean_text(raw.get("version") or "1.0.0", 20) or "1.0.0"
    version = re.sub(r"[^0-9A-Za-z._-]", "", version)[:20] or "1.0.0"
    pack = {
        "schema": 1,
        "id": pid,
        "name": name,
        "version": version,
        "author": _clean_text(raw.get("author"), 40),
        "description": _clean_text(raw.get("description"), 200),
        "owner": _safe_uid(uid),
        "styles": _normalize_styles(raw.get("styles")),
        "prompts": _normalize_prompts(raw.get("prompts")),
        "presets": _normalize_presets(raw.get("presets")),
        "enabled": bool((existing or {}).get("enabled", True)),
        "created": float((existing or {}).get("created") or time.time()),
        "updated": time.time(),
    }
    if existing:
        pack["created"] = float(existing.get("created") or pack["created"])
    if not (pack["styles"] or pack["prompts"] or pack["presets"]):
        raise ValueError("插件包是空的：至少要有一个风格、提示词或预设")
    if len(json.dumps(pack, ensure_ascii=False).encode("utf-8")) > MAX_PACK_BYTES:
        raise ValueError("插件包内容超过 256KB")
    return pack


def ensure_plugins():
    with _LOCK:
        for path in (PLUGIN_DIR, PACK_DIR, QUARANTINE_DIR, BACKUP_DIR,
                     DISABLED_DIR):
            os.makedirs(path, exist_ok=True)
        if not os.path.isfile(REGISTRY_PATH):
            baseline = []
            try:
                for fn in sorted(os.listdir(CUSTOM_NODES_DIR)):
                    if fn.startswith(".") or fn in node_manager.SKIP_NAMES:
                        continue
                    if os.path.isdir(os.path.join(CUSTOM_NODES_DIR, fn)):
                        baseline.append(fn)
            except OSError:
                pass
            _atomic_json(REGISTRY_PATH, {
                "version": 1, "baseline": baseline, "nodes": {},
                "submissions": {}, "restart_required": False,
                "updated": time.time()})
        cleanup_quarantine()
        return _registry()


def _registry():
    data = _read_json(REGISTRY_PATH, None)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", 1)
    data.setdefault("baseline", [])
    data.setdefault("nodes", {})
    data.setdefault("submissions", {})
    data.setdefault("restart_required", False)
    data.setdefault("updated", 0.0)
    return data


def _save_registry(data):
    data["updated"] = time.time()
    _atomic_json(REGISTRY_PATH, data)


def _pack_file(uid, pid):
    return _under(PACK_DIR, _safe_uid(uid), _safe_pack_id(pid) + ".json")


def list_user_packs(uid):
    uid = _safe_uid(uid)
    folder = _under(PACK_DIR, uid)
    if not os.path.isdir(folder):
        return []
    out = []
    for fn in os.listdir(folder):
        if not fn.endswith(".json"):
            continue
        data = _read_json(os.path.join(folder, fn), None)
        if isinstance(data, dict) and data.get("id"):
            out.append(data)
    out.sort(key=lambda x: (x.get("updated") or 0), reverse=True)
    return out


def list_all_packs():
    if not os.path.isdir(PACK_DIR):
        return []
    out = []
    for uid in sorted(os.listdir(PACK_DIR)):
        folder = os.path.join(PACK_DIR, uid)
        if not os.path.isdir(folder) or not _UID_RE.match(uid):
            continue
        for pack in list_user_packs(uid):
            pack = dict(pack)
            pack["owner"] = uid
            out.append(pack)
    out.sort(key=lambda x: (x.get("updated") or 0), reverse=True)
    return out


@_locked
def import_pack(uid, manifest):
    uid = _safe_uid(uid)
    packs = list_user_packs(uid)
    pid = str((manifest or {}).get("id") or "").strip().lower() if isinstance(
        manifest, dict) else ""
    existing = next((p for p in packs if p.get("id") == pid), None)
    if not pid:
        existing = None
    if existing is None and len(packs) >= MAX_PACKS:
        raise ValueError("每个账号最多保存 20 个插件包")
    pack = normalize_pack(manifest, uid, existing)
    if existing is None:
        same_name = next((p for p in packs
                          if str(p.get("name") or "") == pack["name"]), None)
        if same_name:
            pack["id"] = same_name["id"]
            pack["created"] = same_name.get("created") or pack["created"]
            pack["enabled"] = bool(same_name.get("enabled", True))
    _atomic_json(_pack_file(uid, pack["id"]), pack)
    return pack


@_locked
def set_pack_enabled(uid, pid, enabled):
    uid = _safe_uid(uid)
    path = _pack_file(uid, pid)
    data = _read_json(path, None)
    if not isinstance(data, dict):
        raise ValueError("插件包不存在")
    data["enabled"] = bool(enabled)
    data["updated"] = time.time()
    _atomic_json(path, data)
    return data


@_locked
def delete_pack(uid, pid):
    uid = _safe_uid(uid)
    path = _pack_file(uid, pid)
    if not os.path.isfile(path):
        raise ValueError("插件包不存在")
    os.remove(path)
    return True


def styles_for_user(uid):
    """把启用中的安全插件包风格合并进提示词风格条。"""
    try:
        uid = _safe_uid(uid)
    except ValueError:
        return {}
    packs = [p for p in list_user_packs(uid) if p.get("enabled", True)]
    out = {}
    used = set()
    for pack in packs:
        for style in pack.get("styles") or []:
            name = str(style.get("name") or "").strip()
            suffix = str(style.get("suffix") or "").strip()
            if not name or not suffix:
                continue
            key = name
            n = 2
            while key in used:
                key = "%s ·%d" % (name, n)
                n += 1
            used.add(key)
            out[key] = suffix
            if len(out) >= 80:
                return out
    return out


def user_center(uid):
    uid = _safe_uid(uid)
    return {
        "packs": list_user_packs(uid),
        "nodes": list_nodes(admin=False),
        "submissions": list_user_submissions(uid),
        "limits": {
            "max_pack_kb": MAX_PACK_BYTES // 1024,
            "max_packs": MAX_PACKS,
            "max_submit_mb": MAX_SUBMIT_BYTES // 1048576,
            "max_pending": MAX_PENDING_PER_USER,
        },
    }


# --------------------------------------------------------------- 代码插件
def _submission_dir(sid):
    sid = str(sid or "")
    if not re.match(r"^s_[0-9a-f]{16,24}$", sid):
        raise ValueError("提交编号不合法")
    return _under(QUARANTINE_DIR, sid)


def _submission_public(sub, admin=False):
    out = {
        "id": sub.get("id"),
        "name": sub.get("name"),
        "filename": sub.get("filename"),
        "size": sub.get("size"),
        "sha256": sub.get("sha256"),
        "status": sub.get("status"),
        "risk_level": sub.get("risk_level"),
        "risk_items": sub.get("risk_items") or [],
        "created": sub.get("created"),
        "updated": sub.get("updated"),
        "reject_reason": sub.get("reject_reason") or "",
        "approved_at": sub.get("approved_at") or 0,
        "installed_name": sub.get("installed_name") or "",
        "report": sub.get("report") or {},
    }
    if admin:
        out["owner"] = sub.get("owner") or ""
        out["approved_by"] = sub.get("approved_by") or ""
        out["zip_available"] = bool(sub.get("zip_available"))
    else:
        out["mine"] = True
    return out


def _pending_count(uid, reg):
    return sum(1 for s in (reg.get("submissions") or {}).values()
               if s.get("owner") == uid and s.get("status") == "pending")


@_locked
def submit_node(uid, filename, data, admin=False):
    uid = _safe_uid(uid)
    data = data or b""
    if not data:
        raise ValueError("上传内容为空")
    if len(data) > MAX_SUBMIT_BYTES:
        raise ValueError("代码插件 ZIP 最大 20MB；更大的包请让管理员从服务器路径导入")
    # 先看 ZIP 目录，挡住超大解压和 ZIP 炸弹，再落盘。
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            infos = [i for i in zf.infolist() if not i.filename.endswith("/")]
            if len(infos) > MAX_SUBMIT_FILES:
                raise ValueError("ZIP 文件数超过 2000")
            unpacked = sum(max(0, int(i.file_size)) for i in infos)
            if unpacked > MAX_SUBMIT_EXTRACT_BYTES:
                raise ValueError("ZIP 解压后超过 80MB")
            if any(i.flag_bits & 0x1 for i in infos):
                raise ValueError("ZIP 不能包含加密文件")
    except zipfile.BadZipFile:
        raise ValueError("文件不是合法的 ZIP")
    reg = ensure_plugins()
    if _pending_count(uid, reg) >= MAX_PENDING_PER_USER:
        raise ValueError("你已有 3 个待审批插件，请等管理员处理后再提交")
    if len(reg.get("submissions") or {}) >= MAX_QUARANTINE_ITEMS:
        raise ValueError("隔离区已满，请管理员先清理旧提交")
    used = sum(int(s.get("size") or 0)
               for s in (reg.get("submissions") or {}).values()
               if s.get("zip_available"))
    if used + len(data) > MAX_QUARANTINE_BYTES:
        raise ValueError("隔离区空间不足，请管理员先清理旧提交")
    sid = "s_" + secrets.token_hex(8)
    folder = _submission_dir(sid)
    os.makedirs(folder, exist_ok=True)
    zip_path = os.path.join(folder, "payload.zip")
    try:
        with open(zip_path, "wb") as fh:
            fh.write(data)
        info = node_manager.inspect_zip(
            zip_path, name=os.path.splitext(
                os.path.basename(str(filename or "")))[0])
        if info.get("errors"):
            raise ValueError("插件体检未通过：%s" % "；".join(
                str(x) for x in info.get("errors")[:3]))
        if not info.get("has_mapping") and not info.get("has_web_directory"):
            raise ValueError("没有找到 NODE_CLASS_MAPPINGS，这不是一个 ComfyUI 节点插件")
        name = node_manager.safe_node_name(
            info.get("payload_name") or info.get("name") or "plugin")
        target_exists = bool(name and os.path.isdir(
            os.path.join(CUSTOM_NODES_DIR, name)))
        submission = {
            "id": sid,
            "owner": uid,
            "name": name,
            "filename": os.path.basename(str(filename or "plugin.zip"))[:120],
            "size": len(data),
            "sha256": _sha256_bytes(data),
            "created": time.time(),
            "updated": time.time(),
            "status": "pending",
            "risk_level": info.get("risk_level") or "low",
            "risk_items": info.get("risk_items") or [],
            "report": {
                "level": info.get("level"),
                "files": info.get("files"),
                "size": info.get("size"),
                "has_mapping": bool(info.get("has_mapping")),
                "has_web_directory": bool(info.get("has_web_directory")),
                "requirements": info.get("requirements") or [],
                "missing_requirements": info.get("missing_requirements") or [],
                "syntax_errors": info.get("syntax_errors") or [],
                "binary_files": info.get("binary_files") or [],
                "warnings": info.get("warnings") or [],
                "target_exists": target_exists,
            },
            "reject_reason": "",
            "approved_by": "",
            "approved_at": 0,
            "installed_name": "",
            "zip_available": True,
        }
        reg = _registry()
        reg.setdefault("submissions", {})[sid] = submission
        _save_registry(reg)
        return _submission_public(submission, admin=admin)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def list_user_submissions(uid):
    uid = _safe_uid(uid)
    reg = _registry()
    rows = [s for s in (reg.get("submissions") or {}).values()
            if s.get("owner") == uid]
    rows.sort(key=lambda x: (x.get("created") or 0), reverse=True)
    return [_submission_public(s) for s in rows[:30]]


def list_all_submissions(limit=100):
    reg = _registry()
    rows = list((reg.get("submissions") or {}).values())
    rows.sort(key=lambda x: (x.get("status") == "pending",
                             x.get("created") or 0), reverse=True)
    return [_submission_public(s, admin=True) for s in rows[:limit]]


def get_submission(sid, admin=False):
    reg = _registry()
    sub = (reg.get("submissions") or {}).get(str(sid or ""))
    if not sub:
        raise ValueError("提交不存在")
    return _submission_public(sub, admin=admin), sub


def submission_zip(sid):
    sub, _raw = get_submission(sid, admin=True)
    path = os.path.join(_submission_dir(sid), "payload.zip")
    if not os.path.isfile(path):
        raise ValueError("原始 ZIP 已清理")
    return path, sub.get("filename") or "plugin.zip"


@_locked
def cancel_submission(uid, sid, admin=False):
    reg = _registry()
    sub = (reg.get("submissions") or {}).get(str(sid or ""))
    if not sub:
        raise ValueError("提交不存在")
    if not admin and sub.get("owner") != uid:
        raise ValueError("只能取消自己的提交")
    if sub.get("status") != "pending":
        raise ValueError("只有待审批的提交可以取消")
    sub["status"] = "cancelled"
    sub["updated"] = time.time()
    sub["zip_available"] = False
    _save_registry(reg)
    shutil.rmtree(_submission_dir(sid), ignore_errors=True)
    return True


@_locked
def reject_submission(sid, admin, reason=""):
    reg = _registry()
    sub = (reg.get("submissions") or {}).get(str(sid or ""))
    if not sub:
        raise ValueError("提交不存在")
    if sub.get("status") != "pending":
        raise ValueError("只有待审批的提交可以拒绝")
    sub["status"] = "rejected"
    sub["updated"] = time.time()
    sub["reject_reason"] = _clean_text(reason, 300)
    sub["approved_by"] = str((admin or {}).get("id") or "")[:40]
    sub["zip_available"] = False
    _save_registry(reg)
    shutil.rmtree(_submission_dir(sid), ignore_errors=True)
    return _submission_public(sub, admin=True)


def _node_target(name):
    return node_manager.node_dir(name)


def _backup_node(name):
    src = _node_target(name)
    if not src or not os.path.isdir(src):
        return ""
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    dest = _under(BACKUP_DIR, node_manager.safe_node_name(name), stamp, "node")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(src, dest,
                    ignore=shutil.ignore_patterns(*node_manager.SKIP_NAMES))
    _prune_backups(name)
    return _rel(dest)


def _prune_backups(name):
    folder = _under(BACKUP_DIR, node_manager.safe_node_name(name))
    try:
        items = sorted((x for x in os.listdir(folder)
                        if os.path.isdir(os.path.join(folder, x))), reverse=True)
    except OSError:
        return
    for old in items[MAX_BACKUPS:]:
        shutil.rmtree(os.path.join(folder, old), ignore_errors=True)


def _backup_count(name):
    folder = _under(BACKUP_DIR, node_manager.safe_node_name(name))
    try:
        return len([x for x in os.listdir(folder)
                    if os.path.isdir(os.path.join(folder, x))])
    except OSError:
        return 0


def _latest_backup(name):
    folder = _under(BACKUP_DIR, node_manager.safe_node_name(name))
    try:
        items = sorted((x for x in os.listdir(folder)
                        if os.path.isdir(os.path.join(folder, x))), reverse=True)
    except OSError:
        return ""
    for item in items:
        node = os.path.join(folder, item, "node")
        if os.path.isdir(node):
            return node
    return ""


@_locked
def approve_submission(sid, admin, force=False, replace=False):
    reg = _registry()
    sub = (reg.get("submissions") or {}).get(str(sid or ""))
    if not sub:
        raise ValueError("提交不存在")
    if sub.get("status") != "pending":
        raise ValueError("这个提交已经处理过了")
    if (sub.get("risk_level") == "high") and not force:
        raise ValueError("静态扫描发现高风险调用，需要管理员勾选强制批准")
    name = node_manager.safe_node_name(sub.get("name"))
    if not name:
        raise ValueError("插件名称不合法")
    target = _node_target(name)
    if os.path.exists(target) and not replace:
        raise ValueError("custom_nodes 里已经有同名插件；如确认覆盖请勾选覆盖")
    zip_path = os.path.join(_submission_dir(sid), "payload.zip")
    if not os.path.isfile(zip_path):
        raise ValueError("原始 ZIP 已清理，无法安装")
    backup = _backup_node(name) if os.path.exists(target) else ""
    try:
        info = node_manager.import_zip_file(zip_path, name, replace=replace)
    except Exception:
        # 安装失败时保留提交，管理员可以修好后重试
        raise
    node = {
        "name": name,
        "status": "active",
        "submission_id": sid,
        "owner": sub.get("owner") or "",
        "approved_by": str((admin or {}).get("id") or "")[:40],
        "approved_at": time.time(),
        "updated": time.time(),
        "sha256": subtree_hash(target),
        "zip_sha256": sub.get("sha256"),
        "size": info.get("size") or 0,
        "files": info.get("files") or 0,
        "risk_level": info.get("risk_level") or sub.get("risk_level") or "low",
        "risk_items": info.get("risk_items") or sub.get("risk_items") or [],
        "backup": backup,
        "source": "submission",
    }
    sub["status"] = "approved"
    sub["updated"] = time.time()
    sub["approved_by"] = node["approved_by"]
    sub["approved_at"] = node["approved_at"]
    sub["installed_name"] = name
    sub["zip_available"] = False
    reg.setdefault("nodes", {})[name] = node
    reg["restart_required"] = True
    _save_registry(reg)
    shutil.rmtree(_submission_dir(sid), ignore_errors=True)
    return _node_public(node, admin=True)


def subtree_hash(path):
    return tree_hash(path)


def _node_public(node, admin=False):
    out = {
        "name": node.get("name"),
        "status": node.get("status"),
        "risk_level": node.get("risk_level") or "low",
        "risk_items": node.get("risk_items") or [],
        "approved_at": node.get("approved_at") or 0,
        "updated": node.get("updated") or 0,
        "size": node.get("size") or 0,
        "files": node.get("files") or 0,
        "source": node.get("source") or "",
        "backup_count": _backup_count(node.get("name")),
        "can_disable": node.get("status") in ("active", "modified"),
        "can_enable": node.get("status") == "disabled",
        "can_rollback": bool(_latest_backup(node.get("name"))),
    }
    if admin:
        out["owner"] = node.get("owner") or ""
        out["approved_by"] = node.get("approved_by") or ""
        out["submission_id"] = node.get("submission_id") or ""
        out["tree_sha256"] = node.get("sha256") or ""
        out["backup"] = node.get("backup") or ""
        out["disabled_path"] = node.get("disabled_path") or ""
    return out


def list_nodes(admin=False):
    reg = _registry()
    nodes = reg.get("nodes") or {}
    rows = [_node_public(n, admin=admin) for n in nodes.values()
            if n.get("status") != "removed"]
    rows.sort(key=lambda x: (x.get("status") != "active",
                             x.get("name") or ""))
    return rows


@_locked
def adopt_installed(name, by=""):
    """管理员通过旧入口安装后，把节点纳入插件中心管理。"""
    name = node_manager.safe_node_name(name)
    info = node_manager.check_node(name)
    if not info.get("exists"):
        return None
    reg = _registry()
    target = _node_target(name)
    node = {
        "name": name,
        "status": "active",
        "submission_id": "",
        "owner": str(by or "")[:40],
        "approved_by": str(by or "")[:40],
        "approved_at": time.time(),
        "updated": time.time(),
        "sha256": tree_hash(target),
        "zip_sha256": "",
        "size": info.get("size") or 0,
        "files": info.get("files") or 0,
        "risk_level": info.get("risk_level") or "low",
        "risk_items": info.get("risk_items") or [],
        "backup": "",
        "source": "admin",
    }
    reg.setdefault("nodes", {})[name] = node
    if name in (reg.get("baseline") or []):
        reg["baseline"] = [x for x in reg["baseline"] if x != name]
    _save_registry(reg)
    return _node_public(node, admin=True)


@_locked
def note_removed(name):
    reg = _registry()
    node = (reg.get("nodes") or {}).get(name)
    if not node:
        return
    node["status"] = "removed"
    node["updated"] = time.time()
    _save_registry(reg)


def _require_managed(name):
    reg = _registry()
    node = (reg.get("nodes") or {}).get(name)
    if not node:
        raise ValueError("这个节点不在插件中心管理范围内")
    return reg, node


@_locked
def disable_node(name, admin):
    reg, node = _require_managed(name)
    if node.get("status") not in ("active", "modified"):
        raise ValueError("插件不是启用状态")
    src = _node_target(name)
    if not os.path.isdir(src):
        raise ValueError("节点目录不存在")
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    dest = _under(DISABLED_DIR, node_manager.safe_node_name(name) + "-" + stamp)
    shutil.move(src, dest)
    node["status"] = "disabled"
    node["disabled_path"] = _rel(dest)
    node["updated"] = time.time()
    reg["restart_required"] = True
    _save_registry(reg)
    return _node_public(node, admin=True)


@_locked
def enable_node(name, admin):
    reg, node = _require_managed(name)
    if node.get("status") != "disabled":
        raise ValueError("插件不是禁用状态")
    src = _resolve_rel(node.get("disabled_path"))
    if not src or not os.path.isdir(src):
        raise ValueError("禁用目录不存在，无法恢复")
    target = _node_target(name)
    if os.path.exists(target):
        raise ValueError("custom_nodes 里已经有同名目录，请先处理冲突")
    os.makedirs(CUSTOM_NODES_DIR, exist_ok=True)
    shutil.move(src, target)
    node["status"] = "active"
    node["disabled_path"] = ""
    node["updated"] = time.time()
    reg["restart_required"] = True
    _save_registry(reg)
    return _node_public(node, admin=True)


@_locked
def rollback_node(name, admin):
    reg, node = _require_managed(name)
    backup = _latest_backup(name)
    if not backup:
        raise ValueError("没有可回滚的备份")
    target = _node_target(name)
    if os.path.exists(target):
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        dest = _under(DISABLED_DIR,
                      node_manager.safe_node_name(name) + "-replaced-" + stamp)
        shutil.move(target, dest)
        node["disabled_path"] = _rel(dest)
    os.makedirs(CUSTOM_NODES_DIR, exist_ok=True)
    shutil.copytree(backup, target,
                    ignore=shutil.ignore_patterns(*node_manager.SKIP_NAMES))
    node["status"] = "active"
    node["sha256"] = tree_hash(target)
    node["updated"] = time.time()
    node["rolled_back_at"] = time.time()
    reg["restart_required"] = True
    _save_registry(reg)
    return _node_public(node, admin=True)


@_locked
def remove_managed_node(name, admin):
    reg, node = _require_managed(name)
    if node.get("status") == "removed":
        raise ValueError("插件已经移除")
    target = _node_target(name)
    if node.get("status") in ("active", "modified") and os.path.isdir(target):
        node_manager.remove_node(name)
    else:
        src = _resolve_rel(node.get("disabled_path"))
        if src and os.path.isdir(src):
            os.makedirs(node_manager.TRASH_DIR, exist_ok=True)
            dest = os.path.join(node_manager.TRASH_DIR, "%s-%s" % (
                node_manager.safe_node_name(name),
                time.strftime("%Y%m%d-%H%M%S")))
            shutil.move(src, dest)
    node["status"] = "removed"
    node["disabled_path"] = ""
    node["updated"] = time.time()
    reg["restart_required"] = True
    _save_registry(reg)
    return _node_public(node, admin=True)


@_locked
def verify_node(name, admin):
    reg, node = _require_managed(name)
    target = _node_target(name)
    if node.get("status") not in ("active", "modified") or not os.path.isdir(target):
        raise ValueError("插件不是启用状态")
    current = tree_hash(target)
    node["tree_hash_ok"] = bool(current and current == node.get("sha256"))
    node["updated"] = time.time()
    if not node["tree_hash_ok"]:
        node["status"] = "modified"
    _save_registry(reg)
    return _node_public(node, admin=True)


@_locked
def disable_all_managed(admin):
    reg = _registry()
    names = []
    for name, node in list((reg.get("nodes") or {}).items()):
        if node.get("status") in ("active", "modified"):
            try:
                disable_node(name, admin)
                names.append(name)
            except Exception:
                pass
    return names


@_locked
def clear_restart_flag():
    reg = _registry()
    reg["restart_required"] = False
    _save_registry(reg)


def restart_required():
    return bool(_registry().get("restart_required"))


def admin_snapshot():
    reg = ensure_plugins()
    rows = list_nodes(admin=True)
    pending = [s for s in (reg.get("submissions") or {}).values()
               if s.get("status") == "pending"]
    return {
        "submissions": list_all_submissions(),
        "pending_count": len(pending),
        "nodes": rows,
        "packs": list_all_packs(),
        "baseline": reg.get("baseline") or [],
        "restart_required": bool(reg.get("restart_required")),
        "stats": {
            "managed": len(rows),
            "active": sum(1 for x in rows if x["status"] == "active"),
            "disabled": sum(1 for x in rows if x["status"] == "disabled"),
            "pending": len(pending),
        },
    }


# --------------------------------------------------------------- 清理
@_locked
def cleanup_quarantine(now=None):
    now = float(now or time.time())
    reg = _read_json(REGISTRY_PATH, None)
    if not isinstance(reg, dict):
        return 0
    removed = 0
    changed = False
    for sid, sub in list((reg.get("submissions") or {}).items()):
        if sub.get("status") == "pending":
            if now - float(sub.get("created") or now) > 30 * 86400:
                sub["status"] = "rejected"
                sub["reject_reason"] = "超过 30 天未审批，自动清理"
                sub["updated"] = now
                sub["zip_available"] = False
                shutil.rmtree(_submission_dir(sid), ignore_errors=True)
                changed = True
            continue
        if now - float(sub.get("updated") or sub.get("created") or now) > \
                CLEANUP_DAYS * 86400:
            shutil.rmtree(_submission_dir(sid), ignore_errors=True)
            reg["submissions"].pop(sid, None)
            removed += 1
            changed = True
    if changed:
        _save_registry(reg)
    return removed
