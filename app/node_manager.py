# -*- coding: utf-8 -*-
"""ComfyUI 自定义节点管理：目录 / ZIP 导入、依赖与语法体检、移入回收站。

安全边界：
- 只允许管理员调用；
- ZIP 必须无路径穿越、无符号链接、无加密条目；
- 只接受源码 / 配置 / 图片 / 字体等安全扩展名，拒绝 exe/dll/so/pyd/bat 等；
- 解压总大小、文件数、单文件都有上限，防 ZIP 炸弹；
- 导入后不会自动执行代码，必须由管理员重启 ComfyUI 才会加载。
"""
import importlib.util
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
CUSTOM_NODES_DIR = os.path.join(ROOT, "ComfyUI", "custom_nodes")
TRASH_DIR = os.path.join(ROOT, "_node_trash")
UPLOAD_DIR = os.path.join(ROOT, "_node_uploads")

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
CHUNK_MAX_BYTES = 8 * 1024 * 1024
MAX_EXTRACT_BYTES = 300 * 1024 * 1024
MAX_FILES = 5000
MAX_SOURCE_FILE = 2 * 1024 * 1024
MAX_SCAN_PY = 300
CLEANUP_TTL = 24 * 3600

SAFE_EXTS = {
    ".py", ".json", ".txt", ".md", ".rst", ".toml", ".yaml", ".yml",
    ".cfg", ".ini", ".csv", ".js", ".mjs", ".cjs", ".css", ".html",
    ".htm", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg",
    ".woff", ".woff2", ".ttf", ".otf", ".ico", ".map", ".lock",
    ".example", ".gitignore", ".gitattributes", ".editorconfig",
    ".gitkeep", ".mp3", ".wav", ".ogg", ".flac", ".m4a",
}
DANGEROUS_EXTS = {".exe", ".dll", ".so", ".pyd", ".bat", ".cmd",
                  ".ps1", ".com", ".scr", ".msi", ".jar", ".vbs"}
SKIP_NAMES = {"__pycache__", ".git", ".svn", ".hg", "__MACOSX",
              ".venv", "venv", "node_modules"}
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    "COM%d" % i for i in range(1, 10)} | {
    "LPT%d" % i for i in range(1, 10)}
_LOCK = threading.RLock()
_ID_RE = re.compile(r"^[0-9a-f]{16,32}$")


def safe_node_name(name):
    name = os.path.basename(str(name or "").replace("\\", "/")).strip()
    name = _BAD_CHARS.sub("_", name).strip(" .")
    if not name:
        return ""
    if name.upper() in _RESERVED:
        name = "_" + name
    return name[:80]


def node_dir(name):
    name = safe_node_name(name)
    if not name:
        return ""
    path = os.path.abspath(os.path.join(CUSTOM_NODES_DIR, name))
    base = os.path.abspath(CUSTOM_NODES_DIR)
    if not path.startswith(base + os.sep):
        return ""
    return path


def _source_stats(root):
    files = 0
    total = 0
    py_files = []
    for walk_root, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES
                   and not d.startswith(".")]
        for fn in names:
            if fn.startswith(".") and fn not in (".gitignore", ".gitattributes"):
                continue
            path = os.path.join(walk_root, fn)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            files += 1
            total += size
            if fn.lower().endswith(".py") and len(py_files) < MAX_SCAN_PY:
                py_files.append(path)
    return files, total, py_files


def _parse_requirements(path):
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return out
    for line in lines[:200]:
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        # 忽略环境标记 / URL / 版本约束，只保留包名
        line = line.split(";")[0].strip()
        if "://" in line or line.startswith("git+"):
            continue
        name = re.split(r"[<>=!~\[\s]", line, maxsplit=1)[0].strip()
        if name and name not in out:
            out.append(name[:80])
    return out


PKG_MODULE = {
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "pillow": "PIL",
    "pyyaml": "yaml",
    "python-dateutil": "dateutil",
    "beautifulsoup4": "bs4",
    "scikit-image": "skimage",
    "scikit-learn": "sklearn",
    "huggingface-hub": "huggingface_hub",
    "diffusers": "diffusers",
    "transformers": "transformers",
    "safetensors": "safetensors",
    "sentencepiece": "sentencepiece",
}


def _module_name(pkg):
    key = str(pkg or "").lower().strip()
    if key in PKG_MODULE:
        return PKG_MODULE[key]
    return key.replace("-", "_").replace(".", "_").lower()


def _module_available(pkg):
    name = _module_name(pkg)
    if not name:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _syntax_errors(py_files):
    errors = []
    for path in py_files:
        try:
            if os.path.getsize(path) > MAX_SOURCE_FILE:
                errors.append({"file": os.path.basename(path),
                               "error": "文件超过 2MB，跳过语法检查"})
                continue
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
            compile(source, path, "exec")
        except SyntaxError as exc:
            errors.append({"file": os.path.basename(path),
                           "error": "%s (line %s)" % (exc.msg, exc.lineno)})
        except Exception as exc:
            errors.append({"file": os.path.basename(path),
                           "error": str(exc)[:160]})
        if len(errors) >= 20:
            break
    return errors


def _scan_py_text(root, limit=80):
    """扫描根目录和一层子目录里的 .py，返回 (has_mapping, has_web_dir)。"""
    has_mapping = False
    has_web = False
    seen = 0
    for walk_root, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES
                   and not d.startswith(".")]
        depth = os.path.relpath(walk_root, root).count(os.sep)
        if depth >= 2:
            dirs[:] = []
        for fn in names:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(walk_root, fn)
            try:
                if os.path.getsize(path) > MAX_SOURCE_FILE:
                    continue
                with open(path, "r", encoding="utf-8",
                          errors="replace") as fh:
                    text = fh.read()
            except OSError:
                continue
            seen += 1
            if "NODE_CLASS_MAPPINGS" in text:
                has_mapping = True
            if "WEB_DIRECTORY" in text:
                has_web = True
            if has_mapping and has_web:
                return True, True
            if seen >= limit:
                return has_mapping, has_web
    return has_mapping, has_web


def _has_mapping(root):
    return _scan_py_text(root)[0]


def _has_web_directory(root):
    return _scan_py_text(root)[1]


def _binary_files(root):
    """只报告可执行/危险文件；普通二进制素材不算错误。"""
    out = []
    for walk_root, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
        for fn in names:
            ext = os.path.splitext(fn)[1].lower()
            if ext in DANGEROUS_EXTS:
                out.append(os.path.relpath(os.path.join(walk_root, fn), root))
                if len(out) >= 20:
                    return out
    return out


def check_node(name):
    name = safe_node_name(name)
    path = node_dir(name)
    if not path or not os.path.isdir(path):
        return {"name": name, "level": "error", "exists": False,
                "errors": ["节点目录不存在"], "warnings": []}
    files, total, py_files = _source_stats(path)
    init = os.path.join(path, "__init__.py")
    req_path = os.path.join(path, "requirements.txt")
    reqs = _parse_requirements(req_path)
    missing = [r for r in reqs if not _module_available(r)]
    errors = []
    warnings = []
    if not os.path.isfile(init):
        errors.append("缺少 __init__.py，ComfyUI 不会加载这个节点")
    syntax = _syntax_errors(py_files)
    if syntax:
        errors.append("Python 语法错误：%d 个文件" % len(syntax))
    if missing:
        warnings.append("缺少 Python 依赖：%s" % ", ".join(missing[:8]))
    mapping, web_dir = _scan_py_text(path)
    if not mapping and not web_dir:
        warnings.append("没有找到 NODE_CLASS_MAPPINGS")
    binary = _binary_files(path)
    if binary:
        warnings.append("包含可执行脚本：%s" % ", ".join(binary[:5]))
    level = "error" if errors else ("warn" if warnings else "ok")
    return {
        "name": name,
        "level": level,
        "exists": True,
        "path": path,
        "files": files,
        "size": total,
        "has_init": os.path.isfile(init),
        "has_requirements": os.path.isfile(req_path),
        "requirements": reqs,
        "missing_requirements": missing,
        "has_mapping": mapping,
        "has_web_directory": web_dir,
        "syntax_errors": syntax,
        "binary_files": binary,
        "errors": errors,
        "warnings": warnings,
        "mtime": os.path.getmtime(path),
    }


def list_nodes(check=False):
    if not os.path.isdir(CUSTOM_NODES_DIR):
        return []
    rows = []
    for fn in sorted(os.listdir(CUSTOM_NODES_DIR)):
        if fn in SKIP_NAMES or fn.startswith("."):
            continue
        path = os.path.join(CUSTOM_NODES_DIR, fn)
        if not os.path.isdir(path):
            continue
        if check:
            rows.append(check_node(fn))
        else:
            files, total, _py = _source_stats(path)
            rows.append({
                "name": fn,
                "level": "",
                "exists": True,
                "files": files,
                "size": total,
                "has_init": os.path.isfile(os.path.join(path, "__init__.py")),
                "has_requirements": os.path.isfile(
                    os.path.join(path, "requirements.txt")),
                "mtime": os.path.getmtime(path),
            })
    return rows


def check_all():
    rows = [check_node(row["name"]) for row in list_nodes(check=False)]
    summary = {"ok": 0, "warn": 0, "error": 0, "total": len(rows)}
    for row in rows:
        summary[row["level"]] = summary.get(row["level"], 0) + 1
    return {"nodes": rows, "summary": summary}


def _safe_zip_entries(zf):
    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        raise ValueError("ZIP 文件数超过上限")
    total = 0
    cleaned = []
    for info in infos:
        name = info.filename.replace("\\", "/")
        if not name or name.endswith("/"):
            continue
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            raise ValueError("ZIP 包含绝对路径")
        parts = [p for p in name.split("/") if p]
        if not parts or any(p == ".." for p in parts):
            raise ValueError("ZIP 包含路径穿越")
        if any(p in SKIP_NAMES for p in parts):
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError("ZIP 包含符号链接")
        if info.flag_bits & 0x1:
            raise ValueError("ZIP 包含加密文件")
        ext = os.path.splitext(parts[-1])[1].lower()
        if ext and ext not in SAFE_EXTS:
            raise ValueError("ZIP 包含不允许的文件类型：%s" % ext)
        total += info.file_size
        if total > MAX_EXTRACT_BYTES:
            raise ValueError("ZIP 解压后体积超过上限")
        cleaned.append((info, "/".join(parts)))
    if not cleaned:
        raise ValueError("ZIP 是空的")
    return cleaned, total


def _extract_zip(zip_path, staging):
    os.makedirs(staging, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        entries, total = _safe_zip_entries(zf)
        for info, rel in entries:
            dest = os.path.join(staging, *rel.split("/"))
            base = os.path.abspath(staging)
            dest_abs = os.path.abspath(dest)
            if not dest_abs.startswith(base + os.sep):
                raise ValueError("ZIP 路径越界")
            os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
            with zf.open(info, "r") as src, open(dest_abs, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
    return total


def _validate_tree(root):
    """目录导入同样做扩展名 / 大小 / 符号链接校验。"""
    files = 0
    total = 0
    for walk_root, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_NAMES]
        for fn in names:
            path = os.path.join(walk_root, fn)
            if os.path.islink(path):
                raise ValueError("节点目录包含符号链接")
            ext = os.path.splitext(fn)[1].lower()
            if ext and ext not in SAFE_EXTS:
                raise ValueError("节点目录包含不允许的文件类型：%s" % ext)
            try:
                total += os.path.getsize(path)
            except OSError:
                continue
            files += 1
            if files > MAX_FILES or total > MAX_EXTRACT_BYTES:
                raise ValueError("节点目录体积或文件数超过上限")
    return files, total


def _find_payload_root(staging):
    entries = [n for n in os.listdir(staging) if n not in SKIP_NAMES]
    entries = [n for n in entries if not n.startswith(".")]
    if len(entries) == 1:
        only = os.path.join(staging, entries[0])
        if os.path.isdir(only):
            return only
    if os.path.isfile(os.path.join(staging, "__init__.py")):
        return staging
    for name in entries:
        path = os.path.join(staging, name)
        if os.path.isdir(path) and os.path.isfile(
                os.path.join(path, "__init__.py")):
            return path
    raise ValueError("没有找到 __init__.py；请上传 ComfyUI 自定义节点目录或 ZIP")


def _replace_to_trash(target, name):
    if not os.path.exists(target):
        return ""
    os.makedirs(TRASH_DIR, exist_ok=True)
    dest = os.path.join(TRASH_DIR, "%s-%s" % (
        name, time.strftime("%Y%m%d-%H%M%S")))
    shutil.move(target, dest)
    return dest


def _install_staged(payload, name, replace=False):
    target = node_dir(name)
    if not target:
        raise ValueError("节点名称不合法")
    if os.path.exists(target):
        if not replace:
            raise ValueError("custom_nodes 里已经有同名节点")
        _replace_to_trash(target, name)
    os.makedirs(CUSTOM_NODES_DIR, exist_ok=True)
    shutil.move(payload, target)
    return target


def import_path(source, name="", replace=False):
    source = os.path.abspath(str(source or "").strip())
    if not source or not os.path.exists(source):
        raise ValueError("源路径不存在")
    base_name = safe_node_name(name) or os.path.basename(source)
    if os.path.isfile(source):
        if not source.lower().endswith(".zip"):
            raise ValueError("只支持目录或 ZIP 文件")
        return import_zip_file(source, base_name, replace=replace)
    if not os.path.isdir(source):
        raise ValueError("源路径不是目录")
    files, total, _py = _source_stats(source)
    if total > MAX_EXTRACT_BYTES:
        raise ValueError("节点目录体积超过上限")
    staging = os.path.join(UPLOAD_DIR, "stage-" + secrets.token_hex(8))
    os.makedirs(staging, exist_ok=True)
    try:
        copied = os.path.join(staging, "source")
        shutil.copytree(source, copied,
                        ignore=shutil.ignore_patterns(*SKIP_NAMES))
        _validate_tree(copied)
        payload = _find_payload_root(copied)
        target = _install_staged(payload, base_name, replace=replace)
        return check_node(os.path.basename(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def import_zip_file(zip_path, name="", replace=False):
    zip_path = os.path.abspath(str(zip_path or ""))
    if not os.path.isfile(zip_path):
        raise ValueError("ZIP 文件不存在")
    base_name = safe_node_name(name) or os.path.splitext(
        os.path.basename(zip_path))[0]
    staging = os.path.join(UPLOAD_DIR, "stage-" + secrets.token_hex(8))
    try:
        _extract_zip(zip_path, staging)
        payload = _find_payload_root(staging)
        target = _install_staged(payload, base_name, replace=replace)
        return check_node(os.path.basename(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def remove_node(name):
    name = safe_node_name(name)
    target = node_dir(name)
    if not target or not os.path.isdir(target):
        raise ValueError("节点不存在")
    dest = _replace_to_trash(target, name)
    return dest


# --------------------------------------------------------------- 分块上传
def _meta_path(uid):
    return os.path.join(UPLOAD_DIR, uid + ".json")


def _part_path(uid):
    return os.path.join(UPLOAD_DIR, uid + ".part")


def cleanup_uploads(now=None):
    now = float(now or time.time())
    try:
        names = os.listdir(UPLOAD_DIR)
    except OSError:
        return 0
    removed = 0
    for fn in names:
        path = os.path.join(UPLOAD_DIR, fn)
        try:
            if now - os.path.getmtime(path) > CLEANUP_TTL:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def upload_start(filename, size, by=""):
    base = safe_node_name(os.path.splitext(
        os.path.basename(str(filename or "")))[0])
    if not base:
        raise ValueError("文件名不合法")
    try:
        size = int(size)
    except Exception:
        raise ValueError("文件大小不合法")
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise ValueError("ZIP 大小超出限制（最大 200MB）")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    cleanup_uploads()
    with _LOCK:
        uid = secrets.token_hex(12)
        with open(_part_path(uid), "wb") as fh:
            fh.truncate(0)
        meta = {"id": uid, "name": base, "size": size,
                "received": 0, "created": time.time(),
                "by": str(by or "")[:80]}
        with open(_meta_path(uid), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
    return {"upload_id": uid, "name": base, "size": size,
            "chunk_size": CHUNK_MAX_BYTES, "received": 0}


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
    meta = _upload_meta(uid)
    data = data or b""
    if not data:
        raise ValueError("空数据块")
    if len(data) > CHUNK_MAX_BYTES:
        raise ValueError("数据块太大")
    offset = int(offset)
    with _LOCK:
        if offset != int(meta.get("received") or 0):
            raise ValueError("数据块顺序不对，请重新上传")
        total = offset + len(data)
        if total > int(meta.get("size") or 0):
            raise ValueError("数据超过声明大小")
        with open(_part_path(uid), "ab") as fh:
            fh.write(data)
        meta["received"] = total
        with open(_meta_path(uid), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
    return {"received": total, "size": int(meta.get("size") or 0)}


def upload_finish(uid, replace=False):
    meta = _upload_meta(uid)
    part = _part_path(uid)
    if not os.path.isfile(part) or os.path.getsize(part) != int(
            meta.get("size") or 0):
        raise ValueError("上传未完成")
    try:
        info = import_zip_file(part, meta.get("name") or "",
                               replace=bool(replace))
    finally:
        try:
            os.remove(part)
        except OSError:
            pass
        try:
            os.remove(_meta_path(uid))
        except OSError:
            pass
    return info


def upload_cancel(uid):
    _upload_meta(uid)
    removed = False
    for path in (_part_path(uid), _meta_path(uid)):
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed = True
        except OSError:
            pass
    return removed
