# -*- coding: utf-8 -*-
"""LoRA 训练管理器：项目、审核、数据集、GPU 闸门、训练进程和安装器。

依赖方向：app_core 可以 import 本模块；本模块绝不 import app_core。
app_core 在文件末尾通过 bind_runtime() 注入调度器/审计/用量等回调。
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
import zipfile
from urllib.parse import quote

import psutil

import model_profiles
import training_profiles

DEFAULT_ROOT = os.path.dirname(os.path.abspath(__file__))
ID_RE = re.compile(r"^t_[a-z0-9]{8,20}$")
IMG_RE = re.compile(r"^i_[a-z0-9]{8,20}$")
UPLOAD_RE = re.compile(r"^u_[a-z0-9]{8,20}$")
TRAINED_RE = re.compile(
    r"^lora_(anima|sdxl)_t_[a-z0-9]{8,20}(?:-\d+)?\.safetensors$")
TURBO_LORA = "anima-turbo-lora-v0.2.safetensors"
VIDEO_EXT = (".mp4", ".webm")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

DEFAULT_SETTINGS = {
    "version": 1,
    "enabled": False,
    "approval_required": True,
    "allowed_profiles": ["anima", "sdxl"],
    "allowed_sdxl_models": [],
    "window": {"enabled": False, "start": "01:00", "end": "07:00",
               "days": []},
    "drain_mode": "active_only",
    "drain_timeout_seconds": 600,
    "min_idle_seconds": 5,
    "max_pending_per_user": 1,
    "max_projects_per_user": 5,
    "max_dataset_images": 100,
    "max_dataset_mb": 2048,
    "max_image_mb": 25,
    "max_image_pixels": 30_000_000,
    "max_steps": 3000,
    "max_epochs": 30,
    "max_resolution": 1024,
    "min_free_vram_mb_anima": 4200,
    "min_free_vram_mb_sdxl": 6000,
    "min_free_ram_mb": 3500,
    "min_free_disk_mb": 3000,
    "max_gpu_temp_c": 88,
    "keep_checkpoints": 2,
    "dataset_keep_days": 30,
    "allow_user_cancel": True,
    "auto_share_lora": False,
    "allow_sdxl_vpred": False,
    "allow_remote_gen_during_training": True,
    "paused": False,
    "pause_reason": "",
    "install": {
        "github_proxy": "https://gh-proxy.com/",
        "github_direct": "https://github.com/",
        "pip_index": "https://pypi.tuna.tsinghua.edu.cn/simple",
    },
}

STATUS_LABELS = {
    "draft": "草稿",
    "pending": "待审核",
    "approved": "已批准",
    "waiting_window": "等待训练窗口",
    "waiting_resources": "等待 GPU 空闲",
    "waiting_component": "等待训练组件",
    "queued": "排队中",
    "running": "训练中",
    "saving": "保存中",
    "done": "已完成",
    "error": "失败",
    "rejected": "已拒绝",
    "cancelled": "已取消",
}

ACTIVE_STATUSES = ("approved", "waiting_window", "waiting_resources",
                   "waiting_component", "queued", "running", "saving")


def _now():
    return time.time()


def _id(prefix):
    return prefix + secrets.token_hex(6)


def _safe_uid(uid):
    s = str(uid or "")
    return s if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s) else ""


def _safe_name(value, limit=80):
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _safe_slug(value, limit=40):
    text = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "")).strip("._")
    return (text[:limit] or "lora")


def _as_int(value, lo, hi, default):
    try:
        n = int(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _as_float(value, lo, hi, default):
    try:
        n = float(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _as_bool(value, default=False):
    if value is None:
        return default
    return bool(value)


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


def _atomic_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.flush()
        try:
            os.fsync(fh.fileno())
        except OSError:
            pass
    os.replace(tmp, path)


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _copy_bak(path):
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                json.load(fh)
            shutil.copy2(path, path + ".bak")
    except Exception:
        pass


class TrainingManager:
    def __init__(self, root=DEFAULT_ROOT):
        self.root = os.path.abspath(root)
        self.trainings_dir = os.path.join(self.root, "trainings")
        self.uploads_dir = os.path.join(self.root, "training_uploads")
        self.trash_dir = os.path.join(self.root, "_training_trash")
        self.trainer_dir = os.path.join(self.root, "trainer")
        self.pysite = os.path.join(self.trainer_dir, "pysite")
        self.sd_scripts = os.path.join(self.trainer_dir, "sd-scripts")
        self.trainer_state = os.path.join(self.trainer_dir, "state.json")
        self.trainer_log = os.path.join(self.trainer_dir, "install.log")
        self.loras_file = os.path.join(self.root, "loras.json")
        self.projects_file = os.path.join(self.root, "trainings.json")
        self.settings_file = os.path.join(self.root, "training_settings.json")
        self.lora_dir = os.path.join(self.root, "ComfyUI", "models", "loras")
        self.lock = threading.RLock()
        self.projects = {}
        self.settings = dict(DEFAULT_SETTINGS)
        self.loras = {}
        self.gate = "off"
        self.active_tid = ""
        self.proc = None
        self.pid = 0
        self.log_offset = 0
        self.log_path = ""
        self.cancel_flag = False
        self.worker_started = False
        self.stop_worker = False
        self.wake = threading.Event()
        self.last_save = 0.0
        self.install_state = {}
        self.install_thread = None
        self.health_cache = {"t": 0, "data": None}
        self.hardware_cache = {"t": 0, "data": {}}
        self.hooks = {}
        self.load()

    # ------------------------------------------------------------ 回调
    def bind_runtime(self, **hooks):
        self.hooks.update(hooks)

    def _hook(self, name, *args, **kwargs):
        fn = self.hooks.get(name)
        if not callable(fn):
            return None
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None

    # ------------------------------------------------------------ 读写
    def load(self):
        with self.lock:
            # 只有主文件缺失/损坏时才回退到 .bak。
            # 主文件合法且 projects 为空表示“用户删光了项目”，不能再从旧备份复活。
            raw = _read_json(self.projects_file, None)
            if isinstance(raw, dict) and isinstance(raw.get("projects"), dict):
                self.projects = raw["projects"]
            else:
                bak = _read_json(self.projects_file + ".bak", None)
                bp = (bak.get("projects")
                      if isinstance(bak, dict) else None)
                self.projects = bp if isinstance(bp, dict) else {}
            self.settings = self._normalize_settings(
                _read_json(self.settings_file, {}))
            lraw = _read_json(self.loras_file, {})
            loras = lraw.get("loras") if isinstance(lraw, dict) else {}
            self.loras = loras if isinstance(loras, dict) else {}
            self.install_state = _read_json(
                os.path.join(self.trainer_dir, "install_state.json"), {})
        self._prune_lora_meta()

    def _normalize_settings(self, raw):
        src = raw if isinstance(raw, dict) else {}
        out = dict(DEFAULT_SETTINGS)
        out["window"] = dict(DEFAULT_SETTINGS["window"])
        out["install"] = dict(DEFAULT_SETTINGS["install"])
        for key in ("enabled", "approval_required", "allow_user_cancel",
                    "auto_share_lora", "allow_sdxl_vpred",
                    "allow_remote_gen_during_training", "paused"):
            if key in src:
                out[key] = _as_bool(src.get(key), out[key])
        out["pause_reason"] = _safe_name(src.get("pause_reason"), 200)
        for key, hi in (("max_pending_per_user", 20),
                        ("max_projects_per_user", 100),
                        ("max_dataset_images", 500),
                        ("max_dataset_mb", 20000),
                        ("max_image_mb", 200),
                        ("max_image_pixels", 100_000_000),
                        ("max_steps", 20000),
                        ("max_epochs", 200),
                        ("max_resolution", 2048),
                        ("min_free_vram_mb_anima", 8000),
                        ("min_free_vram_mb_sdxl", 8000),
                        ("min_free_ram_mb", 16000),
                        ("min_free_disk_mb", 100000),
                        ("max_gpu_temp_c", 100),
                        ("keep_checkpoints", 10),
                        ("dataset_keep_days", 3650),
                        ("drain_timeout_seconds", 3600),
                        ("min_idle_seconds", 3600)):
            if key in src:
                out[key] = _as_int(src.get(key), 0, hi, out[key])
        if str(src.get("drain_mode") or "") in ("active_only", "idle"):
            out["drain_mode"] = str(src.get("drain_mode"))
        profiles = src.get("allowed_profiles")
        if isinstance(profiles, list):
            allowed = [x for x in ("anima", "sdxl") if x in profiles]
            if allowed:
                out["allowed_profiles"] = allowed
        models = src.get("allowed_sdxl_models")
        if isinstance(models, list):
            out["allowed_sdxl_models"] = [
                os.path.basename(str(x))[:200] for x in models[:50]
                if str(x).strip()]
        win = src.get("window") if isinstance(src.get("window"), dict) else {}
        out["window"] = {
            "enabled": _as_bool(win.get("enabled"), False),
            "start": _clean_clock(win.get("start"), "01:00"),
            "end": _clean_clock(win.get("end"), "07:00"),
            "days": [],
        }
        for d in (win.get("days") or [])[:7]:
            try:
                d = int(d)
            except Exception:
                continue
            if 0 <= d <= 6 and d not in out["window"]["days"]:
                out["window"]["days"].append(d)
        out["window"]["days"].sort()
        inst = src.get("install") if isinstance(src.get("install"), dict) else {}
        for key in ("github_proxy", "github_direct", "pip_index"):
            if str(inst.get(key) or "").startswith(("http://", "https://")):
                out["install"][key] = str(inst.get(key))[:300]
        return out

    def save_projects(self, force=True):
        now = _now()
        with self.lock:
            if not force and now - self.last_save < 5:
                return
            self.last_save = now
            _copy_bak(self.projects_file)
            _atomic_json(self.projects_file, {
                "version": 1, "saved_at": now,
                "projects": self.projects,
            })

    def save_settings(self):
        with self.lock:
            _copy_bak(self.settings_file)
            _atomic_json(self.settings_file, self.settings)

    def save_loras(self):
        with self.lock:
            _copy_bak(self.loras_file)
            _atomic_json(self.loras_file, {
                "version": 1, "saved_at": _now(), "loras": self.loras,
            })

    # ------------------------------------------------------------ 工具
    def _project(self, tid):
        tid = str(tid or "")
        p = self.projects.get(tid)
        return p if isinstance(p, dict) else None

    def _project_dir(self, project):
        uid = _safe_uid(project.get("user_id"))
        tid = str(project.get("id") or "")
        if not uid or not ID_RE.match(tid):
            return ""
        return os.path.join(self.trainings_dir, uid, tid)

    def _dataset_dir(self, project):
        base = self._project_dir(project)
        return os.path.join(base, "dataset") if base else ""

    def _output_dir(self, project):
        base = self._project_dir(project)
        return os.path.join(base, "output") if base else ""

    def _log_path(self, project):
        base = self._project_dir(project)
        return os.path.join(base, "logs", "train.log") if base else ""

    def _manifest_path(self, project):
        d = self._dataset_dir(project)
        return os.path.join(d, "manifest.json") if d else ""

    def _load_manifest(self, project):
        data = _read_json(self._manifest_path(project), {})
        images = data.get("images") if isinstance(data, dict) else []
        return {"version": 1, "images": images if isinstance(images, list)
                else []}

    def _save_manifest(self, project, manifest):
        path = self._manifest_path(project)
        if path:
            _atomic_json(path, manifest)
        total = 0
        for item in manifest.get("images") or []:
            try:
                total += int(item.get("bytes") or 0)
            except Exception:
                pass
        d = project.setdefault("dataset", {})
        d["images"] = len(manifest.get("images") or [])
        d["bytes"] = total
        d["updated"] = _now()

    def _history(self, project, before, after, by=""):
        item = {"t": _now(), "from": before, "to": after, "by": str(by or "")}
        hist = project.setdefault("history", [])
        hist.append(item)
        if len(hist) > 50:
            del hist[:-50]

    def _set_status(self, project, status, by="", reason=""):
        before = project.get("status") or "draft"
        project["status"] = status
        project["updated"] = _now()
        if reason:
            project["reason"] = _safe_name(reason, 500)
        self._history(project, before, status, by)
        self.save_projects(force=True)

    @staticmethod
    def _is_admin(user):
        return bool(user and user.get("role") == "admin"
                    and user.get("enabled", True))

    def _owner(self, project, user, admin=False):
        if not project:
            return False
        if admin and self._is_admin(user):
            return True
        return (project.get("user_id") or "") == (user or {}).get("id")

    def _public_project(self, project, admin=False, include_dataset=False):
        p = dict(project)
        p.pop("dataset_dir", None)
        p.pop("log_path", None)
        p["status_label"] = STATUS_LABELS.get(
            project.get("status") or "", project.get("status") or "")
        p["queue_position"] = self._queue_position(project.get("id"))
        p["queue_size"] = len(self._queue())
        if not admin:
            p.pop("approved_by", None)
            p.pop("reject_reason", None)
        if include_dataset:
            p["dataset_detail"] = self.dataset_payload(
                project.get("id"), {"id": project.get("user_id"),
                                    "role": "admin" if admin else "user"})
        return p

    def _queue(self):
        items = [p for p in self.projects.values()
                 if p.get("status") in ACTIVE_STATUSES]
        items.sort(key=lambda p: (-int(p.get("priority") or 0),
                                  float(p.get("approved_at") or
                                        p.get("submitted_at") or 0),
                                  p.get("id") or ""))
        return items

    def _queue_position(self, tid):
        for i, p in enumerate(self._queue(), 1):
            if p.get("id") == tid:
                return i
        return 0

    # ------------------------------------------------------------ 项目
    def list_projects(self, user, admin=False):
        uid = (user or {}).get("id") or ""
        out = []
        for p in self.projects.values():
            if not self._owner(p, user, admin):
                continue
            out.append(self._public_project(p, admin=self._is_admin(user)))
        out.sort(key=lambda p: float(p.get("updated") or 0), reverse=True)
        return out

    def get_project(self, tid, user, admin=False):
        p = self._project(tid)
        if not p:
            raise KeyError("训练项目不存在")
        if not self._owner(p, user, admin):
            raise PermissionError("无权访问这个训练项目")
        return p

    def project_detail(self, tid, user, admin=False):
        p = self.get_project(tid, user, admin)
        out = self._public_project(p, admin=self._is_admin(user),
                                   include_dataset=True)
        out["images"] = self.dataset_payload(
            tid, user, admin=admin).get("images") or []
        return out

    def create_project(self, user, data):
        uid = _safe_uid((user or {}).get("id"))
        if not uid:
            raise ValueError("账号无效")
        data = data if isinstance(data, dict) else {}
        profile = str(data.get("profile") or "anima")
        if profile not in training_profiles.PROFILES:
            raise ValueError("不支持的训练类型")
        name = _safe_name(data.get("name"), 60)
        if not name:
            raise ValueError("请填写训练名称")
        base = os.path.basename(str(data.get("base_model") or ""))
        if profile == "anima":
            base = training_profiles.ANIMA_MODEL
        if not base:
            raise ValueError("请选择底模")
        tid = _id("t_")
        now = _now()
        params = training_profiles.normalize_params(
            profile, data.get("params"), self.settings)
        vpred = bool(data.get("vpred"))
        if profile == "sdxl":
            try:
                prof = model_profiles.profile_for(
                    base, os.path.join(self.root, "ComfyUI", "models",
                                       "checkpoints", base))
                vpred = bool(prof.get("vpred"))
            except Exception:
                pass
        project = {
            "id": tid,
            "user_id": uid,
            "username": (user or {}).get("username") or "",
            "user_name": (user or {}).get("name") or "",
            "name": name,
            "profile": profile,
            "base_model": base,
            "vpred": vpred,
            "status": "draft",
            "created": now,
            "updated": now,
            "submitted_at": 0,
            "approved_at": 0,
            "approved_by": "",
            "priority": 0,
            "trigger": _safe_name(data.get("trigger"), 60),
            "caption_prefix": training_profiles.clean_text(
                data.get("caption_prefix") or "", 300),
            "caption_default": training_profiles.clean_text(
                data.get("caption_default") or "", 500),
            "dataset": {"images": 0, "bytes": 0, "updated": now},
            "params": params,
            "output_name": "lora_%s_%s" % (profile, tid),
            "output": {
                "name": "", "size": 0, "sha256": "", "public": False,
                "family": profile, "published_at": 0,
            },
            "progress": {"step": 0, "total_steps": params["max_steps"],
                         "epoch": 0, "total_epochs": params["epochs"],
                         "percent": 0, "loss": None, "eta_seconds": 0,
                         "phase": "draft"},
            "elapsed": 0,
            "error": "",
            "reason": "",
            "history": [],
        }
        self._history(project, "", "draft", uid)
        with self.lock:
            self.projects[tid] = project
        os.makedirs(self._dataset_dir(project), exist_ok=True)
        os.makedirs(os.path.join(self._project_dir(project), "output"),
                    exist_ok=True)
        os.makedirs(os.path.join(self._project_dir(project), "logs"),
                    exist_ok=True)
        self._save_manifest(project, {"version": 1, "images": []})
        self.save_projects(force=True)
        return project

    def update_project(self, tid, user, patch):
        p = self.get_project(tid, user)
        if p.get("status") not in ("draft", "rejected", "cancelled"):
            raise ValueError("只有草稿、被拒绝或已取消的项目可以修改")
        patch = patch if isinstance(patch, dict) else {}
        if "name" in patch:
            name = _safe_name(patch.get("name"), 60)
            if name:
                p["name"] = name
        if "trigger" in patch:
            p["trigger"] = _safe_name(patch.get("trigger"), 60)
        if "caption_prefix" in patch:
            p["caption_prefix"] = training_profiles.clean_text(
                patch.get("caption_prefix") or "", 300)
        if "caption_default" in patch:
            p["caption_default"] = training_profiles.clean_text(
                patch.get("caption_default") or "", 500)
        if "base_model" in patch and p.get("profile") == "sdxl":
            base = os.path.basename(str(patch.get("base_model") or ""))
            if base:
                p["base_model"] = base
        if "vpred" in patch:
            p["vpred"] = bool(patch.get("vpred"))
        if isinstance(patch.get("params"), dict):
            merged = dict(p.get("params") or {})
            merged.update(patch.get("params"))
            p["params"] = training_profiles.normalize_params(
                p.get("profile"), merged, self.settings)
        if p.get("status") in ("rejected", "cancelled"):
            self._set_status(p, "draft", (user or {}).get("id") or "")
        p["updated"] = _now()
        self.save_projects(force=True)
        return p

    def project_dataset_stats(self, project):
        m = self._load_manifest(project)
        total = 0
        for item in m.get("images") or []:
            try:
                total += int(item.get("bytes") or 0)
            except Exception:
                pass
        return len(m.get("images") or []), total

    def check_project_limits(self, project, limits=None, usage=None):
        """返回 (错误文本, 结构化配额)；None 表示通过。"""
        limits = limits if isinstance(limits, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        params = project.get("params") or {}
        count, total = self.project_dataset_stats(project)
        max_images = int(limits.get("max_dataset_images") or 0)
        if max_images and count > max_images:
            return ("训练集超过上限（最多 %d 张）。" % max_images,
                    {"kind": "max_dataset_images", "used": count,
                     "limit": max_images, "unit": "张"})
        max_mb = int(limits.get("max_dataset_mb") or 0)
        if max_mb and total > max_mb * 1048576:
            return ("训练集超过上限（最多 %d MB）。" % max_mb,
                    {"kind": "max_dataset_mb",
                     "used": round(total / 1048576.0, 1),
                     "limit": max_mb, "unit": "MB"})
        max_steps = int(limits.get("max_train_steps") or 0)
        if max_steps and int(params.get("max_steps") or 0) > max_steps:
            return ("训练步数超过上限（最多 %d 步）。" % max_steps,
                    {"kind": "max_train_steps",
                     "used": int(params.get("max_steps") or 0),
                     "limit": max_steps, "unit": "步"})
        max_res = int(limits.get("max_train_resolution") or 0)
        if max_res and int(params.get("resolution") or 0) > max_res:
            return ("训练分辨率超过上限（最多 %d）。" % max_res,
                    {"kind": "max_train_resolution",
                     "used": int(params.get("resolution") or 0),
                     "limit": max_res, "unit": "px"})
        daily = int(limits.get("daily_training_jobs") or 0)
        used_jobs = int(usage.get("train_jobs_today") or 0)
        if daily and used_jobs >= daily:
            return ("今天的训练次数用完了（每天 %d 次）。" % daily,
                    {"kind": "daily_training_jobs", "used": used_jobs,
                     "limit": daily, "unit": "次", "reset": "daily"})
        month_minutes = int(limits.get("monthly_training_minutes") or 0)
        used_min = float(usage.get("train_seconds_month") or 0) / 60.0
        est = training_profiles.estimate_seconds(
            project.get("profile"), params.get("max_steps"),
            params.get("resolution"), count) / 60.0
        if month_minutes and used_min + est > month_minutes:
            return ("本月训练时长额度不够（每月 %d 分钟）。" % month_minutes,
                    {"kind": "monthly_training_minutes",
                     "used": round(used_min, 1), "limit": month_minutes,
                     "unit": "分钟", "reset": "monthly"})
        max_minutes = int(limits.get("max_training_minutes") or 0)
        if max_minutes and est > max_minutes:
            return ("这次训练预计超过单次上限（最多 %d 分钟）。" % max_minutes,
                    {"kind": "max_training_minutes", "used": round(est, 1),
                     "limit": max_minutes, "unit": "分钟"})
        return None, None

    def _quota_for(self, project):
        uid = project.get("user_id") or ""
        limits = self._hook("limits_for", uid) or {}
        usage = self._hook("usage_for", uid) or {}
        return self.check_project_limits(project, limits, usage)

    def submit_project(self, tid, user, limits=None, usage=None):
        p = self.get_project(tid, user)
        if p.get("status") not in ("draft", "rejected", "cancelled"):
            raise ValueError("当前状态不能提交")
        count, _ = self.project_dataset_stats(p)
        if count < 5:
            raise ValueError("至少需要 5 张训练图片")
        params = p.get("params") or {}
        if not p.get("trigger") and not p.get("caption_default"):
            raise ValueError("请填写触发词或默认描述，方便生成 caption")
        self._check_caption_filter(p.get("trigger") or "")
        self._check_caption_filter(p.get("caption_default") or "")
        hardware = self._hardware_error(p)
        if hardware:
            raise ValueError(hardware)
        if limits is not None:
            err, quota = self.check_project_limits(p, limits, usage)
            if err:
                return err, quota
        pending = sum(1 for x in self.projects.values()
                      if x.get("user_id") == p.get("user_id")
                      and x.get("status") == "pending")
        if pending >= int(self.settings.get("max_pending_per_user") or 1):
            raise ValueError("你已经有待审核的训练，请等管理员处理")
        owned = sum(1 for x in self.projects.values()
                    if x.get("user_id") == p.get("user_id")
                    and x.get("status") not in ("done", "cancelled",
                                                "rejected"))
        if owned > int(self.settings.get("max_projects_per_user") or 5):
            raise ValueError("未完成的训练项目太多，先完成或删除一些")
        self._rewrite_captions(p)
        p["submitted_at"] = _now()
        p["error"] = ""
        p["reason"] = ""
        self._set_status(p, "pending", (user or {}).get("id") or "")
        self.wake.set()
        return None, None

    def approve_project(self, tid, admin, data=None):
        if not self._is_admin(admin):
            raise PermissionError("只有管理员可以审核")
        p = self._project(tid)
        if not p:
            raise KeyError("训练项目不存在")
        if p.get("status") != "pending":
            raise ValueError("只有待审核项目可以批准")
        err, quota = self._quota_for(p)
        if err:
            raise ValueError(err)
        data = data if isinstance(data, dict) else {}
        p["approved_at"] = _now()
        p["approved_by"] = (admin or {}).get("id") or "admin"
        p["priority"] = _as_int(data.get("priority"), -100, 100, 0)
        p["max_minutes"] = _as_int(data.get("max_minutes"), 1, 10080, 240)
        p["reason"] = ""
        if data.get("share_lora"):
            p.setdefault("output", {})["public"] = True
        self._set_status(p, "approved", p["approved_by"])
        self.wake.set()
        return p

    def reject_project(self, tid, admin, reason):
        if not self._is_admin(admin):
            raise PermissionError("只有管理员可以审核")
        p = self._project(tid)
        if not p:
            raise KeyError("训练项目不存在")
        if p.get("status") not in ("pending", "approved"):
            raise ValueError("当前状态不能拒绝")
        text = _safe_name(reason, 300)
        if not text:
            raise ValueError("请填写拒绝原因")
        p["reject_reason"] = text
        p["reason"] = text
        self._set_status(p, "rejected", (admin or {}).get("id") or "admin",
                         text)
        return p

    def cancel_project(self, tid, user, admin=False, reason="用户取消"):
        p = self._project(tid)
        if not p:
            raise KeyError("训练项目不存在")
        if not self._owner(p, user, admin):
            raise PermissionError("无权取消这个训练")
        if not admin and not self.settings.get("allow_user_cancel", True):
            raise ValueError("管理员关闭了用户取消训练")
        status = p.get("status")
        if status not in ("pending", "approved", "waiting_window",
                          "waiting_resources", "waiting_component", "queued",
                          "running", "saving"):
            raise ValueError("当前状态不能取消")
        if status in ("running", "saving") and p.get("id") == self.active_tid:
            self.cancel_flag = True
            p["reason"] = "正在停止训练…"
            self._set_status(p, "cancelled", (user or {}).get("id") or "",
                             reason)
            self._terminate_process()
            return p
        p["reason"] = _safe_name(reason, 300)
        self._set_status(p, "cancelled", (user or {}).get("id") or "",
                         p["reason"])
        return p

    def retry_project(self, tid, user, admin=False):
        p = self._project(tid)
        if not p:
            raise KeyError("训练项目不存在")
        if not self._owner(p, user, admin):
            raise PermissionError("无权重试这个训练")
        if p.get("status") not in ("error", "cancelled", "rejected"):
            raise ValueError("只有失败、取消或拒绝的项目可以重试")
        p["error"] = ""
        p["reason"] = ""
        p["progress"] = {"step": 0,
                         "total_steps": (p.get("params") or {}).get(
                             "max_steps") or 1000,
                         "epoch": 0,
                         "total_epochs": (p.get("params") or {}).get(
                             "epochs") or 1,
                         "percent": 0, "loss": None, "eta_seconds": 0,
                         "phase": "draft"}
        p["run"] = {}
        p["elapsed"] = 0
        self._set_status(p, "draft", (user or {}).get("id") or "")
        return p

    def delete_project(self, tid, user, admin=False, delete_lora=False):
        p = self._project(tid)
        if not p:
            raise KeyError("训练项目不存在")
        if not self._owner(p, user, admin):
            raise PermissionError("无权删除这个训练")
        if p.get("status") in ("running", "saving", "queued", "approved",
                               "waiting_window", "waiting_resources",
                               "waiting_component"):
            raise ValueError("请先取消训练再删除")
        out_name = (p.get("output") or {}).get("name") or ""
        if delete_lora and out_name:
            self.delete_lora(out_name, user, admin=True)
        base = self._project_dir(p)
        if base and os.path.isdir(base):
            os.makedirs(self.trash_dir, exist_ok=True)
            target = os.path.join(self.trash_dir,
                                  "%s_%s" % (p.get("id"), int(_now())))
            try:
                shutil.move(base, target)
            except Exception:
                shutil.rmtree(base, ignore_errors=True)
        with self.lock:
            self.projects.pop(tid, None)
        self.save_projects(force=True)

    # ------------------------------------------------------------ 数据集
    def _effective_caption(self, project, raw):
        parts = []
        prefix = training_profiles.clean_text(
            project.get("caption_prefix") or "", 300)
        trigger = training_profiles.clean_text(project.get("trigger") or "",
                                               60)
        text = training_profiles.clean_text(raw or "", 2000)
        for item in (prefix, trigger, text):
            if item and item not in parts:
                parts.append(item)
        return ", ".join(parts)

    def _rewrite_captions(self, project):
        manifest = self._load_manifest(project)
        d = self._dataset_dir(project)
        if not d:
            return
        for item in manifest.get("images") or []:
            image_id = str(item.get("id") or "")
            if not IMG_RE.match(image_id):
                continue
            text = self._effective_caption(project, item.get("caption"))
            with open(os.path.join(d, "img_%s.txt" % image_id), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        self._save_manifest(project, manifest)

    def _next_image_id(self, manifest):
        used = {str(x.get("id") or "") for x in manifest.get("images") or []}
        for _ in range(20):
            image_id = _id("i_")
            if image_id not in used:
                return image_id
        raise ValueError("无法分配图片编号")

    def _check_image_limits(self, project, add_bytes=0, limits=None):
        limits = limits if isinstance(limits, dict) else {}
        count, total = self.project_dataset_stats(project)
        max_images = int(limits.get("max_dataset_images")
                         or self.settings.get("max_dataset_images") or 0)
        if max_images and count + 1 > max_images:
            raise ValueError("训练集最多 %d 张图片" % max_images)
        max_mb = int(limits.get("max_dataset_mb")
                      or self.settings.get("max_dataset_mb") or 0)
        if max_mb and total + int(add_bytes or 0) > max_mb * 1048576:
            raise ValueError("训练集最多 %d MB" % max_mb)

    def _check_caption_filter(self, caption):
        text = str(caption or "")
        if not text:
            return
        message = self._hook("check_caption", text)
        if message:
            raise ValueError(str(message))

    def _add_image_file(self, project, src, caption="", source="upload",
                        limits=None):
        from PIL import Image, ImageOps
        self._check_caption_filter(caption)
        limits = limits if isinstance(limits, dict) else {}
        self._check_image_limits(project, os.path.getsize(src), limits)
        max_mb = int(limits.get("max_image_mb")
                      or self.settings.get("max_image_mb") or 25)
        if os.path.getsize(src) > max_mb * 1048576:
            raise ValueError("单张图片不能超过 %d MB" % max_mb)
        max_pixels = int(limits.get("max_image_pixels")
                         or self.settings.get("max_image_pixels")
                         or 30_000_000)
        try:
            with Image.open(src) as im:
                if getattr(im, "is_animated", False):
                    raise ValueError("不支持动图，请用单帧图片")
                im.load()
                width, height = im.size
                if width * height > max_pixels or max(width, height) > 12000:
                    raise ValueError("图片像素太大，请先缩小")
                fixed = ImageOps.exif_transpose(im).convert("RGB")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("图片无法解码：%s" % exc)
        manifest = self._load_manifest(project)
        image_id = self._next_image_id(manifest)
        d = self._dataset_dir(project)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "img_%s.png" % image_id)
        fixed.save(out, "PNG", optimize=True)
        raw_caption = training_profiles.clean_text(caption, 2000)
        item = {
            "id": image_id,
            "file": "img_%s.png" % image_id,
            "caption": raw_caption,
            "bytes": os.path.getsize(out),
            "width": fixed.width,
            "height": fixed.height,
            "source": source,
            "created": _now(),
        }
        manifest.setdefault("images", []).append(item)
        self._save_manifest(project, manifest)
        with open(os.path.join(d, "img_%s.txt" % image_id), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(self._effective_caption(project, raw_caption))
        project["updated"] = _now()
        self.save_projects(force=True)
        return item

    def add_gallery_image(self, tid, user, src_path, caption="", limits=None):
        p = self.get_project(tid, user)
        if p.get("status") not in ("draft", "rejected", "cancelled"):
            raise ValueError("当前状态不能添加图片")
        if not os.path.isfile(src_path):
            raise ValueError("图库图片不存在")
        return self._add_image_file(p, src_path, caption, "gallery", limits)

    def set_caption(self, tid, user, image_id, caption):
        p = self.get_project(tid, user)
        if p.get("status") not in ("draft", "rejected", "cancelled"):
            raise ValueError("当前状态不能修改 caption")
        image_id = str(image_id or "")
        if not IMG_RE.match(image_id):
            raise ValueError("图片编号无效")
        manifest = self._load_manifest(p)
        found = None
        for item in manifest.get("images") or []:
            if item.get("id") == image_id:
                found = item
                break
        if not found:
            raise KeyError("图片不存在")
        raw = training_profiles.clean_text(caption, 2000)
        self._check_caption_filter(raw)
        found["caption"] = raw
        self._save_manifest(p, manifest)
        d = self._dataset_dir(p)
        with open(os.path.join(d, "img_%s.txt" % image_id), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(self._effective_caption(p, raw))
        p["updated"] = _now()
        self.save_projects(force=True)
        return found

    def delete_image(self, tid, user, image_id):
        p = self.get_project(tid, user)
        if p.get("status") not in ("draft", "rejected", "cancelled"):
            raise ValueError("当前状态不能删除图片")
        image_id = str(image_id or "")
        if not IMG_RE.match(image_id):
            raise ValueError("图片编号无效")
        manifest = self._load_manifest(p)
        images = [x for x in manifest.get("images") or []
                  if x.get("id") != image_id]
        if len(images) == len(manifest.get("images") or []):
            raise KeyError("图片不存在")
        manifest["images"] = images
        self._save_manifest(p, manifest)
        d = self._dataset_dir(p)
        for suffix in (".png", ".txt"):
            try:
                os.remove(os.path.join(d, "img_%s%s" % (image_id, suffix)))
            except OSError:
                pass
        p["updated"] = _now()
        self.save_projects(force=True)

    def dataset_payload(self, tid, user, admin=False):
        p = self.get_project(tid, user, admin)
        manifest = self._load_manifest(p)
        items = []
        for item in manifest.get("images") or []:
            image_id = str(item.get("id") or "")
            if not IMG_RE.match(image_id):
                continue
            items.append({
                "id": image_id,
                "url": "/api/training/preview/%s/%s.png" % (tid, image_id),
                "caption": item.get("caption") or "",
                "bytes": int(item.get("bytes") or 0),
                "width": int(item.get("width") or 0),
                "height": int(item.get("height") or 0),
                "source": item.get("source") or "",
            })
        return {"project_id": tid, "images": items,
                "count": len(items),
                "bytes": sum(x["bytes"] for x in items)}

    def image_path(self, tid, image_id, user, admin=False):
        p = self.get_project(tid, user, admin)
        image_id = str(image_id or "")
        if not IMG_RE.match(image_id):
            raise KeyError("图片不存在")
        path = os.path.join(self._dataset_dir(p), "img_%s.png" % image_id)
        if not os.path.isfile(path):
            raise KeyError("图片不存在")
        return path

    # ------------------------------------------------------------ 分块上传
    def _upload_dir(self, uid):
        uid = _safe_uid(uid)
        return os.path.join(self.uploads_dir, uid) if uid else ""

    def upload_start(self, tid, user, filename, size, limits=None):
        p = self.get_project(tid, user)
        if p.get("status") not in ("draft", "rejected", "cancelled"):
            raise ValueError("当前状态不能上传")
        size = _as_int(size, 1, 200 * 1048576, 1)
        max_mb = int((limits or {}).get("max_image_mb")
                     or self.settings.get("max_image_mb") or 25)
        if size > max_mb * 1048576:
            raise ValueError("单张图片不能超过 %d MB" % max_mb)
        self._check_image_limits(p, size, limits)
        uid = _safe_uid((user or {}).get("id"))
        upload_id = _id("u_")
        d = self._upload_dir(uid)
        os.makedirs(d, exist_ok=True)
        meta = {
            "id": upload_id, "uid": uid, "tid": tid,
            "filename": _safe_name(os.path.basename(str(filename or "")), 120),
            "size": size, "received": 0, "created": _now(),
        }
        _atomic_json(os.path.join(d, upload_id + ".json"), meta)
        with open(os.path.join(d, upload_id + ".part"), "wb"):
            pass
        return {"upload_id": upload_id, "chunk_size": 4 * 1048576,
                "received": 0, "size": size}

    def _upload_meta(self, uid, upload_id):
        upload_id = str(upload_id or "")
        if not UPLOAD_RE.match(upload_id):
            raise KeyError("上传不存在")
        path = os.path.join(self._upload_dir(uid), upload_id + ".json")
        meta = _read_json(path, {})
        if not meta or meta.get("uid") != uid:
            raise KeyError("上传不存在")
        return meta, path

    def upload_chunk(self, user, upload_id, offset, data):
        uid = _safe_uid((user or {}).get("id"))
        meta, meta_path = self._upload_meta(uid, upload_id)
        part = os.path.join(self._upload_dir(uid), upload_id + ".part")
        try:
            offset = int(offset)
        except Exception:
            raise ValueError("上传位置无效")
        try:
            current = os.path.getsize(part)
        except OSError:
            current = 0
        if offset != current:
            raise ValueError("上传位置不连续，请重新开始")
        if current + len(data) > int(meta.get("size") or 0):
            raise ValueError("上传内容超过声明大小")
        with open(part, "ab") as fh:
            fh.write(data)
        meta["received"] = current + len(data)
        _atomic_json(meta_path, meta)
        return {"received": meta["received"], "size": meta["size"]}

    def upload_finish(self, user, upload_id, caption="", limits=None):
        uid = _safe_uid((user or {}).get("id"))
        meta, meta_path = self._upload_meta(uid, upload_id)
        part = os.path.join(self._upload_dir(uid), upload_id + ".part")
        actual = os.path.getsize(part) if os.path.isfile(part) else 0
        if actual != int(meta.get("size") or 0):
            raise ValueError("上传尚未完成")
        p = self.get_project(meta.get("tid"), user)
        try:
            item = self._add_image_file(p, part, caption, "upload", limits)
        finally:
            try:
                os.remove(part)
            except OSError:
                pass
            try:
                os.remove(meta_path)
            except OSError:
                pass
        return item

    def cleanup_uploads(self):
        cutoff = _now() - 24 * 3600
        if not os.path.isdir(self.uploads_dir):
            return 0
        removed = 0
        for uid in os.listdir(self.uploads_dir):
            d = os.path.join(self.uploads_dir, uid)
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                path = os.path.join(d, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                        removed += 1
                except OSError:
                    pass
        return removed

    # ------------------------------------------------------------ LoRA
    def _prune_lora_meta(self):
        if not self.loras or not os.path.isdir(self.lora_dir):
            return
        names = set()
        try:
            names = {x for x in os.listdir(self.lora_dir)
                     if x.lower().endswith((".safetensors", ".pt", ".ckpt"))}
        except OSError:
            return
        dead = [x for x in self.loras if x not in names]
        if dead:
            with self.lock:
                for x in dead:
                    self.loras.pop(x, None)
            self.save_loras()

    def lora_meta(self, name):
        return self.loras.get(str(name or "")) or {}

    def lora_family(self, name):
        name = str(name or "")
        meta = self.lora_meta(name)
        if meta.get("family"):
            return meta["family"]
        path = os.path.join(self.lora_dir, name)
        return model_profiles.detect_lora_family(name, path)

    def list_visible_loras(self, user):
        admin = self._is_admin(user)
        uid = (user or {}).get("id") or ""
        out = []
        try:
            names = sorted(os.listdir(self.lora_dir))
        except OSError:
            names = []
        for name in names:
            low = name.lower()
            if low == TURBO_LORA or not low.endswith((".safetensors", ".pt",
                                                       ".ckpt")):
                continue
            meta = self.lora_meta(name)
            trained = bool(TRAINED_RE.match(name))
            if not admin:
                if meta:
                    if (meta.get("owner_id") not in ("", uid)
                            and not meta.get("public")):
                        continue
                elif trained:
                    # 元数据丢失时 fail-closed，不让私有训练结果意外公开
                    continue
            out.append({
                "name": name,
                "family": meta.get("family") or self.lora_family(name),
                "mine": bool(uid and meta.get("owner_id") == uid),
                "public": bool(meta.get("public")),
                "training_id": meta.get("project_id") or "",
            })
        return out

    def lora_allowed(self, user, name):
        name = str(name or "")
        if not name or name != os.path.basename(name):
            return False
        path = os.path.join(self.lora_dir, name)
        if not os.path.isfile(path):
            return False
        if self._is_admin(user):
            return True
        meta = self.lora_meta(name)
        trained = bool(TRAINED_RE.match(name))
        if meta:
            return (meta.get("owner_id") in ("", (user or {}).get("id"))
                    or bool(meta.get("public")))
        return not trained

    def share_lora(self, name, public, admin):
        if not self._is_admin(admin):
            raise PermissionError("只有管理员可以共享 LoRA")
        name = str(name or "")
        if not os.path.isfile(os.path.join(self.lora_dir, name)):
            raise KeyError("LoRA 不存在")
        meta = self.loras.get(name)
        if not meta:
            if not TRAINED_RE.match(name):
                raise ValueError("这个 LoRA 没有训练归属信息")
            meta = {"owner_id": "", "family": self.lora_family(name),
                    "project_id": "", "display_name": name,
                    "created": _now()}
        meta["public"] = bool(public)
        meta["shared_at"] = _now() if public else 0
        meta["shared_by"] = (admin or {}).get("id") or "admin"
        with self.lock:
            self.loras[name] = meta
        self.save_loras()
        return meta

    def delete_lora(self, name, user, admin=False):
        name = str(name or "")
        if not self._is_admin(user) and not admin:
            meta = self.lora_meta(name)
            if meta.get("owner_id") != (user or {}).get("id"):
                raise PermissionError("无权删除这个 LoRA")
        if self._hook("lora_in_use", name):
            raise ValueError("这个 LoRA 正在被排队或运行中的任务使用")
        path = os.path.join(self.lora_dir, name)
        if not os.path.isfile(path):
            raise KeyError("LoRA 不存在")
        trash = os.path.join(self.root, "_lora_trash")
        os.makedirs(trash, exist_ok=True)
        target = os.path.join(trash, "%s_%d" % (os.path.basename(name),
                                                int(_now())))
        try:
            shutil.move(path, target)
        except Exception:
            os.remove(path)
        with self.lock:
            self.loras.pop(name, None)
        self.save_loras()
        return target

    def model_in_use(self, name):
        base = os.path.basename(str(name or ""))
        for p in self.projects.values():
            if p.get("status") not in ACTIVE_STATUSES:
                continue
            if os.path.basename(str(p.get("base_model") or "")) == base:
                return True
        return False

    def active_models(self):
        out = set()
        for p in self.projects.values():
            if p.get("status") in ACTIVE_STATUSES:
                name = os.path.basename(str(p.get("base_model") or ""))
                if name:
                    out.add(name)
        return sorted(out)

    # ------------------------------------------------------------ 闸门/摘要
    def local_gpu_blocked(self):
        return self.gate in ("reserved", "starting", "running", "stopping")

    def gate_snapshot(self):
        return {"state": self.gate, "active": self.local_gpu_blocked(),
                "project_id": self.active_tid}

    def gate_message(self, user=None):
        if not self.local_gpu_blocked():
            return ""
        p = self._project(self.active_tid) or {}
        if not self._is_admin(user) and p.get("user_id") != (user or {}).get(
                "id"):
            return "LoRA 训练正在使用本机显卡，出图暂时停一下；训练结束后会自动恢复。"
        name = p.get("name") or "LoRA 训练"
        return "「%s」正在使用本机显卡，出图暂时停一下；训练结束后会自动恢复。" % name

    def summary(self, admin=False, user=None):
        p = self._project(self.active_tid) if self.active_tid else None
        active = None
        if p and p.get("status") in ("running", "saving"):
            prog = p.get("progress") or {}
            is_owner = p.get("user_id") == (user or {}).get("id")
            active = {
                "project_id": p.get("id"),
                "name": (p.get("name") if (admin or is_owner)
                         else "LoRA 训练"),
                "profile": p.get("profile"), "status": p.get("status"),
                "step": int(prog.get("step") or 0),
                "total_steps": int(prog.get("total_steps") or 0),
                "percent": float(prog.get("percent") or 0),
                "loss": prog.get("loss") if (admin or is_owner) else None,
                "eta_seconds": int(prog.get("eta_seconds") or 0),
                "elapsed": int(p.get("elapsed") or 0),
            }
            if admin:
                active["user_id"] = p.get("user_id")
                active["user_name"] = p.get("user_name") or p.get("username")
        return {
            "gate": self.gate,
            "active": active,
            "blocked": self.local_gpu_blocked(),
            "queue": len(self._queue()),
            "pending": sum(1 for x in self.projects.values()
                           if x.get("status") == "pending"),
            "paused": bool(self.settings.get("paused")),
            "enabled": bool(self.settings.get("enabled")),
            "message": self.gate_message(user),
        }

    def settings_public(self, admin=False):
        out = {
            "enabled": bool(self.settings.get("enabled")),
            "approval_required": bool(self.settings.get("approval_required")),
            "allowed_profiles": list(self.settings.get("allowed_profiles")
                                     or []),
            "window": dict(self.settings.get("window") or {}),
            "paused": bool(self.settings.get("paused")),
            "pause_reason": self.settings.get("pause_reason") or "",
            "max_dataset_images": int(self.settings.get("max_dataset_images")
                                      or 0),
            "max_dataset_mb": int(self.settings.get("max_dataset_mb") or 0),
            "max_steps": int(self.settings.get("max_steps") or 0),
            "max_resolution": int(self.settings.get("max_resolution") or 0),
            "allow_user_cancel": bool(self.settings.get("allow_user_cancel")),
        }
        if admin:
            out["raw"] = dict(self.settings)
            out["stats"] = self.storage_stats()
        return out

    def update_settings(self, admin, patch):
        if not self._is_admin(admin):
            raise PermissionError("只有管理员可以修改训练设置")
        src = dict(self.settings)
        patch = patch if isinstance(patch, dict) else {}
        for key, value in patch.items():
            if key not in DEFAULT_SETTINGS:
                continue
            if key in ("version",):
                continue
            src[key] = value
        with self.lock:
            self.settings = self._normalize_settings(src)
        self.save_settings()
        self.wake.set()
        return self.settings

    def storage_stats(self):
        def size_of(path):
            total = 0
            if not os.path.isdir(path):
                return 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    try:
                        total += os.path.getsize(os.path.join(root, name))
                    except OSError:
                        pass
            return total
        return {
            "trainings_bytes": size_of(self.trainings_dir),
            "uploads_bytes": size_of(self.uploads_dir),
            "trainer_bytes": size_of(self.trainer_dir),
            "projects": len(self.projects),
        }

    # ------------------------------------------------------------ 训练器
    def _manifest(self):
        return _read_json(os.path.join(self.root, "training_manifest.json"), {})

    def _required_trainer_files(self):
        req = (self._manifest().get("required_files") or [])
        if not req:
            req = ["anima_train_network.py", "sdxl_train_network.py",
                   "networks/lora_anima.py", "library/train_util.py"]
        return [x for x in req if x]

    def trainer_status(self):
        missing = []
        for rel in self._required_trainer_files():
            path = os.path.join(self.sd_scripts, rel.replace("/", os.sep))
            if not os.path.exists(path):
                missing.append(rel)
        state = _read_json(self.trainer_state, {})
        health = state.get("health") if isinstance(state, dict) else None
        installed = os.path.isdir(self.sd_scripts) and os.path.isdir(self.pysite)
        return {
            "installed": installed,
            "ready": bool(installed and not missing
                          and isinstance(health, dict) and health.get("ok")),
            "missing": missing,
            "version": (state.get("version") or
                        (self._manifest().get("sd_scripts") or {}).get(
                            "version") or ""),
            "commit": (state.get("commit") or
                       (self._manifest().get("sd_scripts") or {}).get(
                           "commit") or ""),
            "health": health or {},
            "installing": bool(self.install_thread and
                               self.install_thread.is_alive()),
            "install": dict(self.install_state),
            "size_mb": round(self.storage_stats().get("trainer_bytes", 0)
                             / 1048576.0, 1),
        }

    def check_trainer_health(self, force=False):
        now = _now()
        if (not force and self.health_cache.get("data")
                and now - float(self.health_cache.get("t") or 0) < 300):
            return dict(self.health_cache["data"])
        launcher = os.path.join(self.root, "training_launcher.py")
        if not os.path.isfile(launcher):
            data = {"ok": False, "error": "training_launcher.py 缺失"}
            self.health_cache = {"t": now, "data": data}
            return data
        env = self._trainer_env()
        try:
            out = subprocess.run(
                [os.sys.executable, "-s", launcher, "--health"],
                capture_output=True, text=True, timeout=180,
                cwd=self.root, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            text = (out.stdout or "").strip().splitlines()
            data = {}
            for line in reversed(text):
                try:
                    data = json.loads(line)
                    break
                except Exception:
                    continue
            if not data:
                data = {"ok": False,
                        "error": (out.stderr or out.stdout or "")[-500:]}
        except Exception as exc:
            data = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        self.health_cache = {"t": now, "data": data}
        return data

    def _trainer_env(self, site=None, scripts=None):
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP",
                    "PYTHONUSERBASE", "PIP_TARGET", "PIP_USER"):
            env.pop(key, None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        env["OMP_NUM_THREADS"] = "1"
        env["OPENBLAS_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        env["NUMEXPR_NUM_THREADS"] = "1"
        env["VECLIB_MAXIMUM_THREADS"] = "1"
        env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        env["HF_HOME"] = os.path.join(self.trainer_dir, "cache", "hf")
        env["TORCH_HOME"] = os.path.join(self.trainer_dir, "cache", "torch")
        env["HF_ENDPOINT"] = "https://hf-mirror.com"
        env["MGS_TRAIN_SITE"] = site or self.pysite
        env["MGS_TRAIN_SCRIPTS"] = scripts or self.sd_scripts
        return env

    def _install_log(self, text):
        os.makedirs(self.trainer_dir, exist_ok=True)
        with open(self.trainer_log, "a", encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), text))

    def _set_install(self, **patch):
        state = dict(self.install_state)
        state.update(patch)
        state["updated"] = _now()
        self.install_state = state
        try:
            _atomic_json(os.path.join(self.trainer_dir,
                                      "install_state.json"), state)
        except Exception:
            pass

    def install_trainer(self, admin):
        if not self._is_admin(admin):
            raise PermissionError("只有管理员可以安装训练组件")
        if self.local_gpu_blocked():
            raise ValueError("训练运行中，不能安装/修复组件")
        if self.install_thread and self.install_thread.is_alive():
            raise ValueError("训练组件正在安装")
        self.install_thread = threading.Thread(
            target=self._install_loop, daemon=True, name="trainer-install")
        self.install_thread.start()
        return {"started": True}

    def _download(self, url, dst, expected_size=0):
        req = urllib.request.Request(url, headers={"User-Agent":
                                                   "MGS-Trainer/1"})
        with urllib.request.urlopen(req, timeout=60) as resp, \
                open(dst, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or
                        expected_size or 0)
            got = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if total:
                    self._set_install(progress=min(99, int(got * 100 / total)))
                if got > 128 * 1024 * 1024:
                    raise ValueError("训练器压缩包超出大小限制")
        return got

    def _safe_extract(self, zip_path, dst):
        base = os.path.abspath(dst)
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if len(names) > 20000:
                raise ValueError("压缩包文件过多")
            top = None
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if not name or name.endswith("/"):
                    continue
                if name.startswith("/") or ".." in name.split("/"):
                    raise ValueError("压缩包路径不安全")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise ValueError("压缩包包含符号链接")
                if top is None:
                    top = name.split("/", 1)[0]
                target = os.path.abspath(os.path.join(base, *name.split("/")))
                if os.path.commonpath([base, target]) != base:
                    raise ValueError("压缩包路径越界")
            if not top:
                raise ValueError("压缩包为空")
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if not name or name.endswith("/"):
                    continue
                parts = name.split("/")
                if parts and parts[0] == top:
                    parts = parts[1:]
                if not parts:
                    continue
                target = os.path.join(base, *parts)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)

    def _install_loop(self):
        stage = "download"
        try:
            self._set_install(status="installing", stage=stage, progress=0,
                              error="", started=_now())
            self._install_log("开始安装训练组件")
            manifest = self._manifest().get("sd_scripts") or {}
            url = manifest.get("url") or ""
            fallback = manifest.get("fallback_url") or ""
            want = str(manifest.get("sha256") or "").lower()
            downloads = os.path.join(self.trainer_dir, "downloads")
            os.makedirs(downloads, exist_ok=True)
            zip_path = os.path.join(downloads, "sd-scripts.zip")
            ok = False
            last = ""
            for candidate in (url, fallback):
                if not candidate:
                    continue
                try:
                    self._install_log("下载 %s" % candidate)
                    self._download(candidate, zip_path,
                                   int(manifest.get("size") or 0))
                    if want:
                        got = hashlib.sha256()
                        with open(zip_path, "rb") as fh:
                            for chunk in iter(lambda: fh.read(1024 * 1024),
                                              b""):
                                got.update(chunk)
                        if not hmac.compare_digest(got.hexdigest(), want):
                            raise ValueError("训练器压缩包校验失败")
                    ok = True
                    break
                except Exception as exc:
                    last = "%s: %s" % (type(exc).__name__, exc)
                    self._install_log("下载失败：%s" % last)
            if not ok:
                raise RuntimeError(last or "训练器下载失败")
            stage = "extract"
            self._set_install(stage=stage, progress=0)
            sds_new = self.sd_scripts + ".new"
            if os.path.isdir(sds_new):
                shutil.rmtree(sds_new, ignore_errors=True)
            os.makedirs(sds_new, exist_ok=True)
            self._safe_extract(zip_path, sds_new)
            stage = "pip"
            self._set_install(stage=stage, progress=0)
            site_new = self.pysite + ".new"
            if os.path.isdir(site_new):
                shutil.rmtree(site_new, ignore_errors=True)
            os.makedirs(site_new, exist_ok=True)
            req = os.path.join(self.root, "training_requirements.txt")
            if not os.path.isfile(req):
                raise RuntimeError("training_requirements.txt 缺失")
            inst = self.settings.get("install") or {}
            cmd = [os.sys.executable, "-s", "-m", "pip", "install",
                   "--target", site_new, "--no-deps", "--no-cache-dir",
                   "--disable-pip-version-check", "--no-warn-script-location",
                   "--require-hashes", "-r", req,
                   "--index-url", inst.get("pip_index"),
                   "--trusted-host", "pypi.tuna.tsinghua.edu.cn"]
            self._install_log("安装 Python 依赖")
            proc = subprocess.Popen(
                cmd, cwd=self.root, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in proc.stdout or []:
                line = line.rstrip()
                if line:
                    self._install_log(line)
            if proc.wait() != 0:
                raise RuntimeError("训练依赖安装失败，请查看安装日志")
            stage = "health"
            self._set_install(stage=stage, progress=85)
            env = self._trainer_env(site_new, sds_new)
            launcher = os.path.join(self.root, "training_launcher.py")
            out = subprocess.run(
                [os.sys.executable, "-s", launcher, "--health"],
                capture_output=True, text=True, timeout=180, cwd=self.root,
                env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            health = {}
            for line in reversed((out.stdout or "").splitlines()):
                try:
                    health = json.loads(line)
                    break
                except Exception:
                    continue
            if not health.get("ok"):
                raise RuntimeError("训练组件自检失败：%s" %
                                   (health.get("error") or
                                    (out.stderr or "")[-300:]))
            stage = "swap"
            self._set_install(stage=stage, progress=95)
            trash = os.path.join(self.trainer_dir, "_old_%d" % int(_now()))
            os.makedirs(trash, exist_ok=True)
            for old, new in ((self.sd_scripts, sds_new),
                             (self.pysite, site_new)):
                if os.path.isdir(old):
                    shutil.move(old, os.path.join(trash,
                                                  os.path.basename(old)))
                os.replace(new, old)
            state = {
                "version": (manifest.get("version") or ""),
                "commit": (manifest.get("commit") or ""),
                "installed_at": _now(),
                "health": health,
            }
            _atomic_json(self.trainer_state, state)
            self.health_cache = {"t": _now(), "data": health}
            self._set_install(status="done", stage="done", progress=100,
                              error="", finished=_now())
            self._install_log("训练组件安装完成")
        except Exception as exc:
            msg = "%s: %s" % (type(exc).__name__, exc)
            self._set_install(status="error", stage=stage, error=msg[:800],
                              finished=_now())
            self._install_log("安装失败：%s" % msg)

    def install_log_tail(self, lines=200):
        try:
            with open(self.trainer_log, "r", encoding="utf-8",
                      errors="replace") as fh:
                data = fh.read()[-65536:]
            return "\n".join(data.splitlines()[-lines:])
        except OSError:
            return ""

    def uninstall_trainer(self, admin):
        if not self._is_admin(admin):
            raise PermissionError("只有管理员可以卸载训练组件")
        if self.local_gpu_blocked():
            raise ValueError("训练运行中不能卸载")
        trash = os.path.join(self.trainer_dir, "_uninstalled_%d" % int(_now()))
        os.makedirs(trash, exist_ok=True)
        for path in (self.sd_scripts, self.pysite):
            if os.path.isdir(path):
                shutil.move(path, os.path.join(trash,
                                               os.path.basename(path)))
        try:
            os.remove(self.trainer_state)
        except OSError:
            pass
        self.health_cache = {"t": 0, "data": None}
        self._set_install(status="uninstalled", stage="done", progress=0,
                          error="")
        return {"ok": True}

    # ------------------------------------------------------------ 运行器
    def ensure_started(self):
        with self.lock:
            if self.worker_started:
                return
            self.worker_started = True
        self._reconcile()
        threading.Thread(target=self._worker_loop, daemon=True,
                         name="train-worker").start()

    def shutdown(self):
        self.stop_worker = True
        self.wake.set()
        # 不主动杀训练子进程：网页服务重启后可以在 ensure_started() 里接管。
        # 明确取消训练请调用 cancel_project()。

    def _pid_is_trainer(self, pid, project):
        if not pid:
            return False
        try:
            proc = psutil.Process(int(pid))
            if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
                return False
            created = float((project.get("run") or {}).get("pid_create") or 0)
            if created and abs(proc.create_time() - created) > 5:
                return False
            cmdline = " ".join(proc.cmdline())
            return ("training_launcher.py" in cmdline
                    and (".py" in cmdline))
        except Exception:
            return False

    def _reconcile(self):
        running = [p for p in self.projects.values()
                   if p.get("status") in ("running", "saving")]
        if not running:
            return
        adopted = False
        for p in running:
            tid = p.get("id") or ""
            run = p.get("run") or {}
            pid = int(run.get("pid") or 0)
            if not adopted and self._pid_is_trainer(pid, p):
                self.active_tid = tid
                self.pid = pid
                self.proc = None
                self.gate = "running"
                self.log_path = self._log_path(p)
                try:
                    self.log_offset = max(0, os.path.getsize(self.log_path)
                                          - 200000)
                except OSError:
                    self.log_offset = 0
                adopted = True
                self._audit("adopt", p, "服务重启后接管训练")
                continue
            out_dir = self._output_dir(p)
            found = self._find_output(out_dir, p.get("output_name") or "")
            if p.get("status") == "saving" or found:
                try:
                    self._publish(p, found)
                    self._finish_success(p, _now() - float(p.get("started")
                                                           or _now()))
                    continue
                except Exception as exc:
                    p["error"] = "服务重启后补发布失败：%s" % exc
            p["error"] = "服务重启，训练进程已退出"
            p["reason"] = p["error"]
            self._set_status(p, "error", "system", p["error"])
            self._audit("error", p, p["error"])
        if not adopted:
            self.gate = "off"
            self.active_tid = ""
        self.save_projects(force=True)

    def _worker_loop(self):
        while not self.stop_worker:
            try:
                self._tick()
            except Exception as exc:
                self._audit("worker_error", None,
                            "%s: %s" % (type(exc).__name__, exc))
            self.wake.wait(2.0)
            self.wake.clear()

    def _window_open(self, now=None):
        win = self.settings.get("window") or {}
        if not win.get("enabled"):
            return True
        now = now or time.localtime()
        days = win.get("days") or []
        if days and now.tm_wday not in days:
            return False
        try:
            sh, sm = [int(x) for x in str(win.get("start") or "01:00").split(":")]
            eh, em = [int(x) for x in str(win.get("end") or "07:00").split(":")]
        except Exception:
            return True
        start, end = sh * 60 + sm, eh * 60 + em
        cur = now.tm_hour * 60 + now.tm_min
        if start == end:
            return True
        if start < end:
            return start <= cur < end
        return cur >= start or cur < end

    def _gpu_info(self):
        hook = self._hook("gpu_snapshot")
        snap = hook if isinstance(hook, dict) else {}
        if not snap:
            snap = {}
            try:
                exe = shutil.which("nvidia-smi") or r"C:\Windows\System32\nvidia-smi.exe"
                out = subprocess.run(
                    [exe, "--query-gpu=memory.used,memory.total,"
                     "temperature.gpu,utilization.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                parts = [x.strip() for x in (out.stdout or "").splitlines()[0]
                         .split(",")]
                snap = {"vram_used": float(parts[0]),
                        "vram_total": float(parts[1]),
                        "gpu_temp": float(parts[2]),
                        "gpu": float(parts[3])}
            except Exception:
                return {}
        try:
            used = float(snap.get("vram_used") or 0)
            total = float(snap.get("vram_total") or 0)
            return {
                "vram_used": used, "vram_total": total,
                "vram_free": max(0.0, total - used) if total else 0.0,
                "gpu_temp": float(snap.get("gpu_temp") or 0),
                "gpu": float(snap.get("gpu") or 0),
            }
        except Exception:
            return {}

    def _ram_free_mb(self):
        try:
            return psutil.virtual_memory().available / 1048576.0
        except Exception:
            return 999999.0

    def _ram_total_mb(self):
        try:
            return psutil.virtual_memory().total / 1048576.0
        except Exception:
            return 0.0

    def hardware_summary(self, max_age=60):
        """总显存/总内存（MB），缓存 60 秒，供前端提前提示硬件不达标。"""
        now = _now()
        cached = self.hardware_cache or {}
        if cached.get("data") and now - float(cached.get("t") or 0) < max_age:
            return dict(cached["data"])
        gpu = self._gpu_info() or {}
        data = {
            "vram_total_mb": float(gpu.get("vram_total") or 0),
            "ram_total_mb": float(self._ram_total_mb() or 0),
        }
        self.hardware_cache = {"t": now, "data": data}
        return dict(data)

    def _hardware_error(self, project):
        """整套硬件达不到 profile 的最低要求时直接给出明确错误。

        与 _check_resources 的区别：这里检查的是总显存/总内存，不是当前空闲。
        8GB 显存的机器再怎么等空闲也装不下 SDXL U-Net，继续排队只会白等。
        """
        profile = training_profiles.profile_for(project.get("profile"))
        min_vram = float(profile.get("min_total_vram_mb") or 0)
        min_ram = float(profile.get("min_total_ram_mb") or 0)
        if not min_vram and not min_ram:
            return ""
        gpu = self._gpu_info()
        short = []
        if min_vram and gpu.get("vram_total"):
            total = float(gpu.get("vram_total") or 0)
            if total < min_vram:
                short.append("总显存 %.0f GB < %.0f GB"
                             % (total / 1024.0, min_vram / 1024.0))
        total_ram = self._ram_total_mb()
        if min_ram and total_ram and total_ram < min_ram:
            short.append("总内存 %.0f GB < %.0f GB"
                         % (total_ram / 1024.0, min_ram / 1024.0))
        if not short:
            return ""
        return ("当前机器硬件不满足训练要求（%s）。%s 需要 12GB+ 显存、"
                "24GB+ 内存；请改用 Anima 2B，或换更强的机器。"
                % ("，".join(short), profile.get("label") or "SDXL"))

    def _disk_free_mb(self):
        try:
            return shutil.disk_usage(self.root).free / 1048576.0
        except Exception:
            return 999999.0

    def _check_resources(self, project):
        hardware = self._hardware_error(project)
        if hardware:
            return False, hardware
        profile = training_profiles.profile_for(project.get("profile"))
        key = ("min_free_vram_mb_%s" % profile["key"])
        min_vram = float(self.settings.get(key) or
                         profile.get("min_free_vram_mb") or 4200)
        gpu = self._gpu_info()
        if not gpu:
            return False, "读不到显卡信息，先确认 nvidia-smi 可用"
        if gpu.get("vram_free", 0) < min_vram:
            return (False, "显存不够（空闲 %.0f MB，需要约 %.0f MB）"
                    % (gpu.get("vram_free", 0), min_vram))
        if gpu.get("gpu_temp", 0) >= int(self.settings.get("max_gpu_temp_c")
                                         or 88):
            return False, "显卡温度过高（%.0f°C）" % gpu.get("gpu_temp", 0)
        ram = self._ram_free_mb()
        if ram < int(self.settings.get("min_free_ram_mb") or 3500):
            return False, "系统内存不够（可用 %.0f MB）" % ram
        disk = self._disk_free_mb()
        if disk < int(self.settings.get("min_free_disk_mb") or 3000):
            return False, "磁盘空间不够（剩余 %.0f MB）" % disk
        return True, ""

    def _local_active(self):
        try:
            n = self._hook("local_active")
            return int(n or 0)
        except Exception:
            return 0

    def _guard_heavy(self):
        snap = self._hook("guard_snapshot")
        if isinstance(snap, dict):
            return bool(snap.get("heavy")), str(snap.get("reason") or "")
        return False, ""

    def _set_waiting(self, p, status, reason):
        p["retry_at"] = _now() + (300 if status == "waiting_window" else 60)
        if p.get("status") != status:
            self._set_status(p, status, "system", reason)
        else:
            p["reason"] = _safe_name(reason, 300)
            p["updated"] = _now()
            self.save_projects(force=True)

    def _tick(self):
        if self.active_tid and (self.pid or self.proc):
            self._monitor_tick()
            return
        if not self.settings.get("enabled") or self.settings.get("paused"):
            return
        queue = self._queue()
        if not queue:
            return
        p = queue[0]
        if p.get("status") == "queued":
            # 项目被标记为排队但运行器已经不在（例如上次异常退出）
            self._set_status(p, "approved", "system", "重新排队")
            return
        if p.get("status") not in ("approved", "waiting_window",
                                   "waiting_resources", "waiting_component"):
            return
        if float(p.get("retry_at") or 0) > _now():
            return
        can_train = self._hook("can_train", p.get("user_id") or "")
        if can_train is False:
            p["error"] = "管理员关闭了你的 LoRA 训练功能"
            p["reason"] = p["error"]
            self._set_status(p, "error", "system", p["error"])
            self._audit("error", p, p["error"])
            return
        hardware_error = self._hardware_error(p)
        if hardware_error:
            p["error"] = hardware_error
            p["reason"] = hardware_error
            self._set_status(p, "error", "system", hardware_error)
            self._audit("error", p, hardware_error)
            return
        trainer = self.trainer_status()
        if not trainer.get("ready"):
            health = self.check_trainer_health()
            if not health.get("ok"):
                self._set_waiting(p, "waiting_component",
                                  "训练组件未安装/自检失败")
                return
        if not self._window_open():
            self._set_waiting(p, "waiting_window", "还没到训练时间窗口")
            return
        heavy, why = self._guard_heavy()
        if heavy:
            self._set_waiting(p, "waiting_resources",
                              "电脑正在忙（%s），等空闲再训练" % (why or "高负载"))
            return
        err, quota = self._quota_for(p)
        if err:
            p["error"] = err
            p["reason"] = err
            self._set_status(p, "error", "system", err)
            self._audit("error", p, err)
            return
        ram = self._ram_free_mb()
        if ram < int(self.settings.get("min_free_ram_mb") or 3500):
            # 先让 ComfyUI 卸掉模型；它常驻的模型也会占系统内存。
            try:
                self._hook("free_comfy")
            except Exception:
                pass
            time.sleep(2.0)
            ram = self._ram_free_mb()
            if ram < int(self.settings.get("min_free_ram_mb") or 3500):
                self._set_waiting(p, "waiting_resources",
                                  "系统内存不够（可用 %.0f MB）" % ram)
                return
        disk = self._disk_free_mb()
        if disk < int(self.settings.get("min_free_disk_mb") or 3000):
            self._set_waiting(p, "waiting_resources",
                              "磁盘空间不够（剩余 %.0f MB）" % disk)
            return
        self._start_project(p)

    def _start_project(self, p):
        tid = p.get("id") or ""
        self.gate = "reserved"
        self.active_tid = tid
        self._set_status(p, "queued", "system", "等待当前出图任务结束")
        self._hook("scheduler_kick")
        deadline = _now() + int(self.settings.get("drain_timeout_seconds")
                                or 600)
        while self._local_active() > 0:
            if _now() > deadline:
                self.gate = "off"
                self.active_tid = ""
                self._set_waiting(p, "waiting_resources",
                                  "出图任务一直没结束，稍后再试")
                self._hook("scheduler_kick")
                return
            time.sleep(1.0)
        try:
            self._hook("free_comfy")
        except Exception:
            pass
        time.sleep(2.0)
        ok, why = self._check_resources(p)
        if not ok:
            self.gate = "off"
            self.active_tid = ""
            self._set_waiting(p, "waiting_resources", why)
            self._hook("scheduler_kick")
            return
        try:
            self._rewrite_captions(p)
            self._prepare_dataset(p)
            self._launch(p)
        except Exception as exc:
            p["error"] = "%s: %s" % (type(exc).__name__, exc)
            self._set_status(p, "error", "system", p["error"])
            self._audit("error", p, p["error"])
            self._release_gate()

    def _prepare_dataset(self, p):
        d = self._dataset_dir(p)
        if not d:
            raise ValueError("训练目录无效")
        # 训练器缓存可能引用旧 caption；每次启动前删掉
        for name in os.listdir(d):
            if name.lower().endswith(".npz"):
                try:
                    os.remove(os.path.join(d, name))
                except OSError:
                    pass
        cfg = os.path.join(self._project_dir(p), "dataset.toml")
        with open(cfg, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(training_profiles.dataset_toml(p, d))
        os.makedirs(self._output_dir(p), exist_ok=True)
        os.makedirs(os.path.dirname(self._log_path(p)), exist_ok=True)
        return cfg

    def _launch(self, p):
        tid = p.get("id") or ""
        trainer = self.trainer_status()
        if not trainer.get("ready"):
            health = self.check_trainer_health()
            if not health.get("ok"):
                raise RuntimeError("训练组件未就绪")
        launcher = os.path.join(self.root, "training_launcher.py")
        if not os.path.isfile(launcher):
            raise RuntimeError("training_launcher.py 缺失")
        cfg = os.path.join(self._project_dir(p), "dataset.toml")
        cmd = training_profiles.build_train_command(
            self.root, launcher, p, cfg, self._output_dir(p))
        log_path = self._log_path(p)
        try:
            if os.path.getsize(log_path) > 50 * 1024 * 1024:
                os.replace(log_path, log_path + ".old")
        except OSError:
            pass
        env = self._trainer_env()
        env["MGS_TRAINING_ID"] = tid
        env["MGS_TRAINING_PROFILE"] = p.get("profile") or "anima"
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        self.log_path = log_path
        self.log_offset = 0
        self.cancel_flag = False
        fh = open(log_path, "a", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(
                cmd, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                stdout=fh, stderr=subprocess.STDOUT, creationflags=flags)
        finally:
            fh.close()
        self.proc = proc
        self.pid = int(proc.pid)
        try:
            create_time = psutil.Process(self.pid).create_time()
        except Exception:
            create_time = 0
        p["run"] = {
            "pid": self.pid, "pid_create": create_time, "started": _now(),
            "log": log_path,
        }
        p["started"] = _now()
        p["error"] = ""
        p["reason"] = ""
        p.setdefault("progress", {})["phase"] = "training"
        self.gate = "starting"
        self._set_status(p, "running", "system", "")
        try:
            _atomic_json(os.path.join(self._project_dir(p), "train.pid"),
                         p["run"])
        except Exception:
            pass
        self._audit("start", p, "")
        self._activity("start", p)
        self.save_projects(force=True)

    def _read_log(self):
        if not self.log_path:
            return ""
        try:
            size = os.path.getsize(self.log_path)
        except OSError:
            return ""
        if self.log_offset > size:
            self.log_offset = 0
        try:
            with open(self.log_path, "r", encoding="utf-8",
                      errors="replace") as fh:
                fh.seek(self.log_offset)
                data = fh.read(256 * 1024)
                self.log_offset = fh.tell()
            return data
        except OSError:
            return ""

    def _monitor_tick(self):
        p = self._project(self.active_tid)
        if not p:
            self._release_gate()
            return
        data = self._read_log()
        if data:
            prog = training_profiles.parse_log_tail(
                data, p.get("progress") or {})
            prog["phase"] = "training"
            p["progress"] = prog
            p["elapsed"] = int(_now() - float(p.get("started") or _now()))
            if self.gate == "starting":
                self.gate = "running"
            self.save_projects(force=False)
        if self.proc is not None:
            code = self.proc.poll()
            if code is not None:
                self._finish_process(p, code)
                return
        elif self.pid:
            if not self._pid_is_trainer(self.pid, p):
                self._finish_process(p, 0)
                return
        elapsed = _now() - float(p.get("started") or _now())
        p["elapsed"] = int(elapsed)
        max_min = int(p.get("max_minutes") or 0)
        if not max_min:
            limits = self._hook("limits_for", p.get("user_id")) or {}
            max_min = int(limits.get("max_training_minutes") or 240)
        if max_min and elapsed > max_min * 60:
            p["reason"] = "超过管理员设定的最长时间（%d 分钟），已停止" % max_min
            self.cancel_flag = True
            self._terminate_process()
        if self.cancel_flag:
            self._terminate_process()
        self.save_projects(force=False)

    def _terminate_process(self):
        pid = int(self.pid or (self.proc.pid if self.proc else 0))
        if not pid:
            return
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess,
                                                 "CREATE_NO_WINDOW", 0))
            return
        except Exception:
            pass
        try:
            proc = psutil.Process(pid)
            for child in proc.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            proc.kill()
        except Exception:
            pass

    def _find_output(self, output_dir, output_name):
        exact = os.path.join(output_dir, output_name + ".safetensors")
        if os.path.isfile(exact):
            return exact
        best = ""
        best_t = 0
        try:
            for name in os.listdir(output_dir):
                if not name.lower().endswith(".safetensors"):
                    continue
                path = os.path.join(output_dir, name)
                t = os.path.getmtime(path)
                if t > best_t:
                    best, best_t = path, t
        except OSError:
            pass
        return best

    def _finish_success(self, p, elapsed=0):
        p["elapsed"] = int(max(0, elapsed or 0))
        p.setdefault("progress", {})["percent"] = 100.0
        p["progress"]["phase"] = "done"
        p["reason"] = ""
        p["error"] = ""
        self._set_status(p, "done", "system", "")
        self._audit("done", p, "", seconds=int(elapsed or 0))
        self._activity("done", p)
        self._note_usage(p, elapsed or 0)
        self.gate = "off"
        self.active_tid = ""
        self.proc = None
        self.pid = 0
        self._hook("scheduler_kick")

    def _finish_process(self, p, code):
        cancelled = bool(self.cancel_flag or
                         p.get("status") == "cancelled")
        elapsed = max(0.0, _now() - float(p.get("started") or _now()))
        if cancelled:
            p["elapsed"] = int(elapsed)
            p["error"] = ""
            p["reason"] = p.get("reason") or "训练已取消"
            self._set_status(p, "cancelled", "system", p["reason"])
            self._audit("cancel", p, p["reason"])
            self._activity("cancel", p)
            self._note_usage(p, elapsed)
            self._release_gate()
            return
        if code != 0:
            text = ""
            try:
                with open(self.log_path, "r", encoding="utf-8",
                          errors="replace") as fh:
                    text = fh.read()[-12000:]
            except OSError:
                pass
            msg, hint = training_profiles.classify_error(text)
            p["error"] = (msg + " " + hint).strip()
            p["reason"] = p["error"]
            p["elapsed"] = int(elapsed)
            self._set_status(p, "error", "system", p["error"])
            self._audit("error", p, p["error"])
            self._activity("error", p)
            self._note_usage(p, elapsed)
            self._release_gate()
            return
        out = self._find_output(self._output_dir(p),
                                p.get("output_name") or "")
        if not out:
            p["error"] = "训练进程结束，但没有找到 LoRA 文件。"
            p["reason"] = p["error"]
            self._set_status(p, "error", "system", p["error"])
            self._audit("error", p, p["error"])
            self._note_usage(p, elapsed)
            self._release_gate()
            return
        try:
            self._set_status(p, "saving", "system", "正在保存 LoRA")
            self._publish(p, out)
            p["elapsed"] = int(elapsed)
            self._set_status(p, "done", "system", "")
            p["progress"]["percent"] = 100.0
            p["progress"]["phase"] = "done"
            self._audit("done", p, "", seconds=int(elapsed))
            self._activity("done", p)
            self._note_usage(p, elapsed)
        except Exception as exc:
            p["error"] = "保存 LoRA 失败：%s" % exc
            p["reason"] = p["error"]
            self._set_status(p, "error", "system", p["error"])
            self._audit("error", p, p["error"])
            self._note_usage(p, elapsed)
        self._release_gate()

    def _publish(self, p, src):
        if not os.path.isfile(src) or os.path.getsize(src) < 1024:
            raise ValueError("LoRA 文件为空或不存在")
        ok, count, err = training_profiles.safe_open_check(src)
        if not ok:
            raise ValueError("LoRA 文件损坏：%s" % err)
        tmp = src + ".comfy"
        if p.get("profile") == "anima":
            launcher = os.path.join(self.root, "training_launcher.py")
            if not os.path.isfile(launcher):
                raise ValueError("training_launcher.py 缺失")
            out = subprocess.run(
                training_profiles.convert_command(
                    self.root, launcher, src, tmp),
                capture_output=True, text=True, timeout=600, cwd=self.root,
                env=self._trainer_env(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.returncode != 0 or not os.path.isfile(tmp):
                raise ValueError("Anima LoRA 转换失败：%s" %
                                 ((out.stderr or out.stdout or "")[-400:]))
        else:
            shutil.copyfile(src, tmp)
        os.makedirs(self.lora_dir, exist_ok=True)
        base = training_profiles.lora_filename(p)
        target = os.path.join(self.lora_dir, base)
        n = 2
        while os.path.exists(target):
            target = os.path.join(
                self.lora_dir,
                base[:-len(".safetensors")] + "-%d.safetensors" % n)
            n += 1
        final_tmp = os.path.join(self.lora_dir, ".publish-" +
                                 str(p.get("id")) + ".tmp")
        try:
            training_profiles.strip_metadata(tmp, final_tmp)
            os.replace(final_tmp, target)
        finally:
            for path in (tmp, final_tmp):
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
        name = os.path.basename(target)
        meta = {
            "owner_id": p.get("user_id") or "",
            "project_id": p.get("id") or "",
            "family": p.get("profile") or "anima",
            "base_model": p.get("base_model") or "",
            "display_name": p.get("name") or name,
            "trigger_word": p.get("trigger") or "",
            "public": bool((p.get("output") or {}).get("public")
                           or self.settings.get("auto_share_lora")),
            "sha256": _sha256(target),
            "size": os.path.getsize(target),
            "created": _now(),
        }
        try:
            with self.lock:
                self.loras[name] = meta
            self.save_loras()
        except Exception:
            try:
                trash = os.path.join(self.root, "_lora_trash")
                os.makedirs(trash, exist_ok=True)
                os.replace(target, os.path.join(trash,
                                                os.path.basename(target)))
            except Exception:
                pass
            raise RuntimeError("写入 LoRA 归属信息失败，已移入回收站")
        p["output"] = {
            "name": name, "size": meta["size"], "sha256": meta["sha256"],
            "public": meta["public"], "family": meta["family"],
            "published_at": _now(),
            "source": os.path.basename(src),
        }
        p["progress"]["percent"] = 100.0
        self.save_projects(force=True)
        return meta

    def _release_gate(self):
        self.gate = "off"
        self.active_tid = ""
        self.proc = None
        self.pid = 0
        self.cancel_flag = False
        p = None
        self._hook("scheduler_kick")
        try:
            self._hook("free_comfy")
        except Exception:
            pass
        self.save_projects(force=True)

    def _note_usage(self, p, seconds):
        try:
            self._hook("note_usage", p.get("user_id") or "", max(0, seconds))
        except Exception:
            pass

    def _audit(self, action, p, reason="", **detail):
        try:
            pid = (p or {}).get("id") or ""
            uid = (p or {}).get("user_id") or ""
            self._hook("audit", "activity", "training_" + action,
                       user_id=uid or None, project_id=pid,
                       profile=(p or {}).get("profile") or "",
                       reason=str(reason or "")[:300], **detail)
        except Exception:
            pass

    def _activity(self, phase, p):
        try:
            self._hook("activity", "training", phase=phase,
                       project_id=(p or {}).get("id") or "",
                       user_id=(p or {}).get("user_id") or "",
                       profile=(p or {}).get("profile") or "",
                       percent=((p or {}).get("progress") or {}).get(
                           "percent") or 0)
        except Exception:
            pass

    def stop_all(self, reason="系统维护"):
        with self.lock:
            self.cancel_flag = True
            if self.pid:
                self._terminate_process()
            for p in self.projects.values():
                if p.get("status") in ACTIVE_STATUSES:
                    p["reason"] = reason
                    self._set_status(p, "cancelled", "system", reason)
            self.gate = "off"
            self.active_tid = ""
            self.proc = None
            self.pid = 0
        self._hook("scheduler_kick")
        self.save_projects(force=True)

    def cancel_user(self, uid, reason="账号已停用"):
        uid = _safe_uid(uid)
        if not uid:
            return 0
        n = 0
        with self.lock:
            for p in list(self.projects.values()):
                if p.get("user_id") != uid:
                    continue
                if p.get("status") in ACTIVE_STATUSES:
                    p["reason"] = reason
                    self._set_status(p, "cancelled", "system", reason)
                    n += 1
                    if p.get("id") == self.active_tid:
                        self.cancel_flag = True
                        self._terminate_process()
        if n:
            self._hook("scheduler_kick")
            self.save_projects(force=True)
        return n

    def reset_all(self, reason="系统重置"):
        self.stop_all(reason)
        trash = os.path.join(self.trash_dir, "reset_%d" % int(_now()))
        os.makedirs(trash, exist_ok=True)
        for path in (self.trainings_dir, self.uploads_dir):
            if os.path.isdir(path):
                try:
                    shutil.move(path, os.path.join(trash,
                                                   os.path.basename(path)))
                except Exception:
                    shutil.rmtree(path, ignore_errors=True)
        with self.lock:
            self.projects = {}
            old = dict(self.settings)
            self.settings = self._normalize_settings({})
            self.settings["enabled"] = bool(old.get("enabled"))
            self.settings["install"] = dict(old.get("install") or
                                            DEFAULT_SETTINGS["install"])
        self.save_projects(force=True)
        self.save_settings()

    def reload(self):
        self.load()
        self.wake.set()


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# 模块级单例；app_core / web_server / 测试都可以直接使用。
M = TrainingManager()


def bind_runtime(**hooks):
    M.bind_runtime(**hooks)


def ensure_started():
    M.ensure_started()


def shutdown():
    M.shutdown()


