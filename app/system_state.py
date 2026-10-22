# -*- coding: utf-8 -*-
"""系统还原点：保存 / 列出 / 回滚少量配置文件。

只处理账号、节点、用量、任务状态和本地翻译配置，不复制图片、模型、
证书或日志。回滚前会先生成当前状态的还原点，避免二次误操作。
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile

CONFIG_FILES = (
    "users.json",
    "workers.json",
    "usage.json",
    "jobs_state.json",
    "local_llm.json",
    "monitor.json",
    "cleanup.json",
    "queue_control.json",
    "supervisor.json",
    "teams.json",
    "team_prompts.json",
    "trainings.json",
    "training_settings.json",
    "loras.json",
    "sensitive_filter.json",
)
FORMAT = "comfyui-mobile-studio-snapshot"
SNAPSHOT_DIR_NAME = "_restore_points"
MAX_SNAPSHOTS = 20
NAME_RE = re.compile(r"^snap-\d{8}-\d{6}-[0-9a-f]{6}\.zip$")
ALLOWED = set(CONFIG_FILES)


def snapshot_dir(root):
    return os.path.join(os.path.abspath(root), SNAPSHOT_DIR_NAME)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _safe_name(name):
    name = os.path.basename(str(name or "").replace("\\", "/"))
    return name if name in ALLOWED else ""


def _trim(root):
    folder = snapshot_dir(root)
    try:
        names = [n for n in os.listdir(folder) if NAME_RE.match(n)]
    except OSError:
        return
    names.sort(reverse=True)
    for name in names[MAX_SNAPSHOTS:]:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass


def create_snapshot(root, label="手动还原点"):
    root = os.path.abspath(root)
    folder = snapshot_dir(root)
    os.makedirs(folder, exist_ok=True)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    token = hashlib.sha256(
        (stamp + str(os.getpid()) + str(now.microsecond)).encode()).hexdigest()[:6]
    name = "snap-%s-%s.zip" % (stamp, token)
    path = os.path.join(folder, name)
    rows = []
    tmp = path + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for filename in CONFIG_FILES:
            src = os.path.join(root, filename)
            if not os.path.isfile(src):
                continue
            rows.append({
                "path": filename,
                "size": os.path.getsize(src),
                "sha256": _sha256(src),
            })
            zf.write(src, filename)
        manifest = {
            "format": FORMAT,
            "version": 1,
            "created": now.isoformat(timespec="seconds"),
            "label": str(label or "手动还原点")[:80],
            "files": rows,
        }
        zf.writestr("snapshot_manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(tmp, path)
    _trim(root)
    return {
        "name": name,
        "created": manifest["created"],
        "label": manifest["label"],
        "files": len(rows),
        "size": os.path.getsize(path),
    }


def _read_manifest(path):
    with zipfile.ZipFile(path) as zf:
        try:
            raw = zf.read("snapshot_manifest.json")
        except KeyError:
            raise ValueError("还原点缺少 snapshot_manifest.json")
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ValueError("还原点清单损坏")
    if data.get("format") != FORMAT:
        raise ValueError("不是本程序生成的还原点")
    rows = data.get("files")
    if not isinstance(rows, list):
        raise ValueError("还原点清单没有文件列表")
    return data, rows


def list_snapshots(root):
    folder = snapshot_dir(root)
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    for name in names:
        if not NAME_RE.match(name):
            continue
        path = os.path.join(folder, name)
        try:
            manifest, rows = _read_manifest(path)
            out.append({
                "name": name,
                "created": manifest.get("created") or "",
                "label": manifest.get("label") or "",
                "files": len(rows),
                "size": os.path.getsize(path),
            })
        except Exception:
            continue
    out.sort(key=lambda x: x.get("created") or "", reverse=True)
    return out


def _validated(root, name):
    if not NAME_RE.match(str(name or "")):
        raise ValueError("还原点名称不合法")
    path = os.path.join(snapshot_dir(root), name)
    if not os.path.isfile(path):
        raise ValueError("找不到这个还原点")
    manifest, rows = _read_manifest(path)
    checked = []
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for row in rows:
            rel = _safe_name(row.get("path"))
            if not rel:
                raise ValueError("还原点包含不允许恢复的文件")
            if rel not in names:
                raise ValueError("还原点缺少文件：%s" % rel)
            info = zf.getinfo(rel)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("还原点包含符号链接，已拒绝")
            checked.append((rel, row))
    return path, checked


def restore_snapshot(root, name):
    """回滚配置文件；调用方负责停止任务并重新加载内存状态。"""
    root = os.path.abspath(root)
    path, checked = _validated(root, name)
    safety = create_snapshot(root, "回滚前自动备份")
    stage = tempfile.mkdtemp(prefix="_snapshot_restore_", dir=root)
    try:
        with zipfile.ZipFile(path) as zf:
            for rel, row in checked:
                dest = os.path.join(stage, rel)
                with zf.open(rel) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                want = str(row.get("sha256") or "")
                if want and _sha256(dest) != want:
                    raise ValueError("还原点文件校验失败：%s" % rel)
        for rel, _row in checked:
            src = os.path.join(stage, rel)
            dst = os.path.join(root, rel)
            tmp = dst + ".restore.tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {
        "restored": [rel for rel, _ in checked],
        "safety": safety,
    }


def snapshot_summary(root):
    snaps = list_snapshots(root)
    return {
        "count": len(snaps),
        "latest": snaps[0] if snaps else None,
        "detail_available": True,
    }
