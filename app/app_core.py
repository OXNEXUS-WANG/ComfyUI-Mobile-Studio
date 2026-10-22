#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
手机出图 · 局域网网页版

在电脑上跑一个小网页服务，手机连上电脑热点就能打开：
    http://192.168.137.1:8800

只依赖 Python 标准库（缩略图和图标用 Pillow，ComfyUI 自带）。
后台调用本机的 ComfyUI（127.0.0.1:8188）。
"""

import base64
import hashlib
import hmac
import io
import json
import os
import platform
import queue
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile
from collections import deque

try:
    import psutil
except Exception:       # 便携版没装也能跑，负载页只是少几项
    psutil = None

import disk_cleanup
import edition_policy
import health_report
import lan_share
import license_guard
import local_llm
import model_manager
import model_profiles
import monitor_center
import queue_control
import runtime_settings
import sensitive_filter
import system_state
import teams
import training_manager
import training_profiles
import trusted_time

COMFY = "http://127.0.0.1:8188"
ROOT = os.path.dirname(os.path.abspath(__file__))
# 便携版 python313._pth 不会自动把脚本目录加进 sys.path，拆模块后要手动加
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
OUTPUT_DIR = os.path.join(ROOT, "ComfyUI", "output")
INPUT_DIR = os.path.join(ROOT, "ComfyUI", "input")
DELIVER_DIR = os.path.join(ROOT, "generated")
CKPT_DIR = os.path.join(ROOT, "ComfyUI", "models", "checkpoints")
UPSCALE_DIR = os.path.join(ROOT, "ComfyUI", "models", "upscale_models")
LORA_DIR = os.path.join(ROOT, "ComfyUI", "models", "loras")
THUMB_DIR = os.path.join(DELIVER_DIR, ".thumbs")
FAV_FILE = os.path.join(DELIVER_DIR, ".favorites.json")
CHAR_FILE = os.path.join(ROOT, "char_tags.json")   # 中文角色名 → danbooru 标签
PORT = 8800

# ---- 访问安全 ----
# access.json 存在 = 开启密码保护（由 安全设置.bat 生成）
ACCESS_FILE = os.path.join(ROOT, "access.json")
SESSION_FILE = os.path.join(ROOT, "sessions.json")
USERS_FILE = os.path.join(ROOT, "users.json")
PBKDF2_ROUNDS = 200_000
CERT_FILE = os.path.join(ROOT, "cert.pem")
KEY_FILE = os.path.join(ROOT, "key.pem")
COOKIE_NAME = "mg_session"
SESSION_TTL = 30 * 86400        # 登录一次管 30 天
LOGIN_MAX_FAILS = 5             # 同一 IP 连续错 5 次
LOGIN_LOCK_SECONDS = 600        # 锁 10 分钟
MAX_BODY_BYTES = 40 * 1024 * 1024   # 请求体上限（图生图的 base64 大约 27MB）

THUMB_WIDTH = 420
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".webm")
MEDIA_EXT = IMAGE_EXT + VIDEO_EXT
MEDIA_CTYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".mp4": "video/mp4", ".webm": "video/webm",
}

# ---- 图片隔离 ----
# 网页上传的参考图 / 蒙版 / 放大临时图先放这里，绝不直接留在模型目录。
UPLOAD_DIR = os.path.join(ROOT, "web_uploads")
UPLOAD_MAX_BYTES = 20 * 1024 * 1024
UPLOAD_MAX_PIXELS = 40_000_000
UPLOAD_MAX_SIDE = 12000
INPUT_STAGE_PREFIX = "_web_"

# ---- 图库打包下载 ----
# ZIP 放在 generated/.archives 下，1 小时后自动删除；图片不重复压缩。
ARCHIVE_DIR = os.path.join(DELIVER_DIR, ".archives")
ARCHIVE_TTL = 3600
ARCHIVE_MAX_FILES = 200
ARCHIVE_MAX_BYTES = 4 * 1024 * 1024 * 1024
ARCHIVE_LOCK = threading.Lock()
ARCHIVE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def safe_media_rel(name):
    """把图库里的相对路径限制成安全格式；允许 模型目录/文件名.png，拒绝 ..。"""
    if not name:
        return ""
    name = str(name).replace("\\", "/").strip().lstrip("/")
    parts = []
    for part in name.split("/"):
        if part in ("", ".", ".."):
            continue
        if "\x00" in part or ":" in part:
            return ""
        parts.append(part)
    if not parts:
        return ""
    rel = "/".join(parts)
    if not rel.lower().endswith(MEDIA_EXT):
        return ""
    return rel


def media_path(name):
    """相对名 → generated 下的绝对路径，越界返回 None。"""
    rel = safe_media_rel(name)
    if not rel:
        return None
    base = os.path.abspath(DELIVER_DIR)
    path = os.path.abspath(os.path.join(base, *rel.split("/")))
    try:
        if os.path.commonpath([base, path]) != base:
            return None
    except Exception:
        return None
    return path


def model_folder(ckpt):
    """底模文件名 → 图库里的安全子目录名。"""
    base = os.path.splitext(os.path.basename(str(ckpt or "")))[0]
    base = re.sub(r"[^0-9A-Za-z._\-一-鿿]+", "_", base).strip("._")
    return (base[:64] or "unknown_model")


def safe_uid(uid):
    s = str(uid or "")
    return s if re.fullmatch(r"[A-Za-z0-9_-]{1,40}", s) else ""


def user_gallery_root(uid):
    uid = safe_uid(uid)
    return os.path.join(DELIVER_DIR, uid) if uid else DELIVER_DIR


def user_fav_file(uid):
    return os.path.join(user_gallery_root(uid), ".favorites.json")


def user_upload_root(uid):
    uid = safe_uid(uid)
    return os.path.join(UPLOAD_DIR, uid) if uid else UPLOAD_DIR


def split_media_rel(rel):
    """媒体相对名 → (用户ID, 模型目录, 文件名)；新结构是 uid/model/file。"""
    parts = str(rel or "").split("/")
    if len(parts) >= 3:
        return safe_uid(parts[0]), parts[1], "/".join(parts[2:])
    if len(parts) == 2:
        return "", parts[0], parts[1]
    return "", "", parts[0] if parts else ""

# 视频：Wan 2.1 T2V 1.3B（ComfyUI 官方重打包版）
VIDEO_UNET = "wan2.1_t2v_1.3B_fp16.safetensors"
VIDEO_VACE = "wan2.1_vace_1.3B_fp16.safetensors"
VIDEO_CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VIDEO_VAE = "wan_2.1_vae.safetensors"
VIDEO_FPS = 16
VIDEO_NEGATIVE = "low quality, blurry, distorted, watermark, text, static"
UNET_DIR = os.path.join(ROOT, "ComfyUI", "models", "diffusion_models")
TEXT_ENC_DIR = os.path.join(ROOT, "ComfyUI", "models", "text_encoders")
VAE_DIR = os.path.join(ROOT, "ComfyUI", "models", "vae")

# 图生图 / 局部重绘的参考图像素上限（百万像素）。
# 8GB 显存下超过这个数就会爆显存，表现为浏览器一直转圈、ComfyUI 卡死。
# 超过的参考图会自动等比缩到这个上限（比例不变，不会被拉变形）。
# 1.3MP ≈ 1024x1270，和常用的 832x1216(1.01MP) 同一量级，留了点余量。
MAX_SOURCE_MEGAPIXELS = 1.3

# 提示词处理方式
#   True  = optimize_prompt：中文先按词表转 danbooru 标签，再补质量词、过滤毁图词
#   False = 原来的 Argos 机翻（中→英自然语言，交给 ComfyUI 里的翻译节点）
# 2026-10-17 用户实测标签转换出图效果不如原来的机翻，关闭。改回 True 即可重新启用。
USE_PROMPT_OPTIMIZER = False

DEFAULT_CHECKPOINT = "Illustrious-XL-v2.0.safetensors"

# Anima 2B（CircleStone Labs × Comfy Org，2026）：Cosmos 架构，动漫专用。
# 它不走 CheckpointLoader，UNet / 文本编码器 / VAE 三个文件分开加载。
ANIMA_MODEL = "anima-aesthetic-v1.1.safetensors"
ANIMA_CLIP = "qwen_3_06b_base.safetensors"
ANIMA_VAE = "qwen_image_vae.safetensors"
ANIMA_NEGATIVE = ("worst quality, low quality, score_1, score_2, score_3, "
                  "blurry, jpeg artifacts, sepia")
# 官方 Turbo LoRA：8 步 / CFG 1，出图快一倍多，质量略降
ANIMA_TURBO_LORA = "anima-turbo-lora-v0.2.safetensors"
ANIMA_TURBO_STEPS = 8
ANIMA_TURBO_CFG = 1.0

# NoobAI-XL Vpred（官方 Vpred 线最新版是 1.0；1.1 官方只有 epsilon）
NOOB_MODEL = "NoobAI-XL-Vpred-v1.0.safetensors"
NOOB_NEGATIVE = ("nsfw, worst quality, old, early, low quality, lowres, signature, "
                 "username, logo, bad hands, mutated hands, mammal, anthro, furry, "
                 "ambiguous form, feral, semi-anthro")
# 中文提示词经 Argos 翻出来会丢标签、变自然语言，NoobAI 容易画成 2.5D；
# 用 ConditioningConcat 在翻译结果前面补一段固定的英文质量/动漫标签。
NOOB_PREFIX = ("masterpiece, best quality, newest, absurdres, highres, safe, "
               "anime style, ")

# Pony 系必须带 score_9 等质量标签，否则很容易出低质量图。用 ConditioningConcat
# 单独编码，避免中文提示词经 Argos 翻译时把这些标签弄坏。
PONY_PREFIX = "score_9, score_8_up, score_7_up, "

# 视频画幅：Wan 2.1 1.3B 的原生档位是 480p，这里给几组像素量接近的
# 16 倍数画幅；单边/总像素超过上限时后端会等比缩小，防止 8GB 显存爆掉。
VIDEO_SIZES = ["480x480", "480x832", "832x480",
               "640x480", "480x640", "640x640"]
VIDEO_MAX_SIDE = 960
VIDEO_MAX_PIXELS = 480000
VIDEO_MIN_SECONDS = 0.5
VIDEO_MAX_SECONDS = 6.0

# 每个底模的显示名和推荐参数。Lightning 类模型步数少、CFG 低，选错会出糊图。
CKPT_PRESETS = {
    ANIMA_MODEL: {
        # Anima 官方推荐 30 步 / CFG 4；2B 模型，8GB 显存比 SDXL 更宽裕
        "label": "动漫 · Anima 2B（2026）", "steps": 30, "cfg": 4.0,
        "kind": "anime", "family": "anima", "sampler": "euler",
        "tip": "最懂你的描述，动漫首选。用不了 SDXL 的 LoRA 和 PAG；「更多」里可开 8 步极速。"},
    NOOB_MODEL: {
        # v-pred：必须 Euler + CFG 4~5 + clip skip 2 + v_prediction + RescaleCFG
        "label": "动漫 · NoobAI Vpred", "steps": 30, "cfg": 4.5,
        "kind": "anime", "family": "noob", "vpred": True, "sampler": "euler",
        "tip": "Tag 知识最全，冷门角色/画师最准。v-pred 模型，只用 Euler，30 步 / CFG 4.5。"},
    "Juggernaut-XI-byRunDiffusion.safetensors": {
        # 风景/写实：XI v11 是 v9 的全面升级，官方推荐 DPM++ 2M Karras
        "label": "写实 · Juggernaut XI 风景", "steps": 30, "cfg": 5.0,
        "kind": "photo", "orientation": "landscape", "sampler": "dpmpp_2m",
        "tip": "XI v11：手、脸、构图和提示词都更强。自动横图，DPM++ 2M，30 步 / CFG 5。"},
    "Illustrious-XL-v2.0.safetensors": {
        # 实测 20 步比 28 步快约 34%，画质肉眼看不出差别（Illustrious 收敛得快）
        "label": "动漫 · Illustrious", "steps": 20, "cfg": 6.0, "kind": "anime",
        "tip": "老牌动漫模型，SDXL 的 LoRA 最多；想加 LoRA 就用它。"},
    "RealVisXL_V5.0_Lightning_fp16.safetensors": {
        "label": "写实 · RealVis Lightning", "steps": 8, "cfg": 2.0, "kind": "photo",
        "tip": "写实人像和照片，8 步就出图，速度最快。"},
    "Counterfeit-V2.5_pruned.safetensors": {
        "label": "动漫 · Counterfeit（旧）", "steps": 28, "cfg": 6.0, "kind": "anime",
        "tip": "很老的 SD1.5 模型，现在基本用不到，可以删掉腾空间。"},
}

# 采样器。Illustrious 官方推荐 Euler a；DPM++ 细节稍好但每步更慢。
SAMPLERS = {
    "euler":           {"label": "Euler",      "sampler": "euler",           "sched": "normal"},
    "euler_ancestral": {"label": "Euler a",    "sampler": "euler_ancestral", "sched": "normal"},
    "dpmpp_2m":        {"label": "DPM++ 2M",   "sampler": "dpmpp_2m",        "sched": "karras"},
    "dpmpp_2m_sde":    {"label": "DPM++ SDE",  "sampler": "dpmpp_2m_sde",    "sched": "karras"},
    "uni_pc":          {"label": "UniPC",      "sampler": "uni_pc",          "sched": "normal"},
    "ddim":            {"label": "DDIM",       "sampler": "ddim",            "sched": "normal"},
}
DEFAULT_SAMPLER = "euler_ancestral"

# PAG（扰动注意力引导）：每步多算一次扰动注意力，线条、蕾丝、花瓣等细节
# 明显更利落，同种子下比原图更清晰。8GB 上每张约多花 20 秒，默认开启。
PAG_SCALE = 2.0

DEFAULT_NEGATIVE = (
    "lowres, worst quality, low quality, low score, bad score, average score, "
    "bad anatomy, bad hands, bad proportions, missing fingers, extra digits, "
    "fewer digits, extra fingers, fused fingers, extra limbs, text, error, "
    "signature, watermark, username, blurry, jpeg artifacts, cropped"
)

# 放大模型：动漫用 anime 版，写实照片用通用版
UPSCALE_ANIME = "RealESRGAN_x4plus_anime_6B.pth"
UPSCALE_PHOTO = "RealESRGAN_x4plus.pth"
UPSCALE_PHOTO_SHARP = "4x-UltraSharp.pth"   # 写实/风景更锐，优先给照片用

JOBS = {}
JOBS_LOCK = threading.Lock()
# 任务状态落盘：重启后至少还能查到最近任务，并把被中断的排队/运行任务标成错误，
# 而不是让前端拿到 404。只写安全字段，绝不写提示词、输入图路径或工作流正文。
JOBS_STATE_FILE = os.path.join(ROOT, "jobs_state.json")
JOBS_STATE_LOCK = threading.Lock()
JOBS_STATE_META = {"last_write": 0.0, "loaded": False}
JOBS_KEEP_SECONDS = 7 * 86400
JOBS_KEEP_MAX = 120
# 只给“还没提交给 ComfyUI”的任务保存恢复参数；提交成功后立即删除。
# 这里会短暂包含提示词和临时输入文件名，但不会进入 jobs_state.json 或日志。
JOBS_RESUME_FILE = os.path.join(ROOT, "jobs_resume.json")
JOBS_RESUME_LOCK = threading.RLock()
JOBS_RESUME_MAX = 60
RECOVERY_PENDING = []

# --------------------------------------------------------------------- 多账号排队
# ComfyUI 在 8GB 显存上只能一次跑一个任务。所有账号的任务先进这里，
# 按“账号”轮转派发：A、B、A、B……而不是让一个人先把 ComfyUI 队列塞满。
# max_concurrent 表示该账号最多同时占用多少个“排队 + 运行”的位置。
SCHED_LOCK = threading.RLock()
SCHED_MAX_QUEUE = 60          # 全局等待上限，防止无限堆积
SCHED_PER_USER_CAP = 20       # 单账号绝对上限（管理员也受这个保护）
SCHEDULER = {
    "active": "",             # 当前真正交给 ComfyUI 的 job_id
    "queues": {},             # uid -> deque(job_id)
    "last_served": {},        # uid -> 上次派发序号（越小越优先）
    "served_cost": {},        # uid -> 累计预计 GPU 秒，用于加权公平
    "serve_seq": 0,
    "events": {},             # job_id -> threading.Event
    "seq": 0,
}


def _sched_job_locked(jid):
    return JOBS.get(jid) or {}


def _sched_pending_locked():
    return sum(len(q) for q in SCHEDULER["queues"].values())


def _sched_user_pending_locked(uid):
    return len(SCHEDULER["queues"].get(uid) or ())


def _sched_user_cap(uid):
    """单账号最多能占的排队 + 运行位置。"""
    user = get_user(uid) or {}
    if is_admin(user):
        return SCHED_PER_USER_CAP
    lim = user_limits(user)
    try:
        n = int(lim.get("max_concurrent") or 0)
    except Exception:
        n = 0
    return n if n > 0 else SCHED_PER_USER_CAP


def _sched_clean_locked():
    """清掉已经取消/结束的任务，保持轮转表干净。"""
    for uid in list(SCHEDULER["queues"].keys()):
        q = SCHEDULER["queues"].get(uid)
        if q is None:
            continue
        while q:
            jid = q[0]
            job = _sched_job_locked(jid)
            if job and job.get("status") == "queued":
                break
            q.popleft()
            ev = SCHEDULER["events"].pop(jid, None)
            if ev:
                ev.set()
        if not q:
            SCHEDULER["queues"].pop(uid, None)


def _sched_pick_locked(last_served):
    """在还有等待任务的账号里，选“最久没轮到”的那个。"""
    best_uid = None
    best_key = None
    for uid, q in SCHEDULER["queues"].items():
        if not q:
            continue
        job = _sched_job_locked(q[0])
        seq = job.get("queue_seq") or 0
        key = (last_served.get(uid, 0), seq)
        if best_key is None or key < best_key:
            best_key = key
            best_uid = uid
    return best_uid


def _sched_order_locked():
    """按“最久未服务优先”预测实际派发顺序，用于排队位置和预计等待。"""
    tmp = {uid: deque(q) for uid, q in SCHEDULER["queues"].items()}
    last = dict(SCHEDULER["last_served"])
    serve = SCHEDULER["serve_seq"]
    out = []
    while True:
        best_uid = None
        best_key = None
        for uid, q in tmp.items():
            if not q:
                continue
            job = _sched_job_locked(q[0])
            key = (last.get(uid, 0), job.get("queue_seq") or 0)
            if best_key is None or key < best_key:
                best_key = key
                best_uid = uid
        if best_uid is None:
            break
        jid = tmp[best_uid].popleft()
        out.append(jid)
        serve += 1
        last[best_uid] = serve
        if not tmp[best_uid]:
            tmp.pop(best_uid, None)
    return out


def _sched_info_locked(jid):
    """排队位置（1 开始）、总等待数、预计等待秒数。"""
    job = _sched_job_locked(jid)
    if not job:
        return {"queue_position": 0, "queue_size": 0, "queue_eta": 0}
    if SCHEDULER["active"] == jid:
        return {"queue_position": 0,
                "queue_size": _sched_pending_locked(),
                "queue_eta": 0}
    order = _sched_order_locked()
    try:
        idx = order.index(jid)
    except ValueError:
        return {"queue_position": 0, "queue_size": len(order), "queue_eta": 0}
    eta = 0.0
    for ahead in order[:idx]:
        j = _sched_job_locked(ahead)
        try:
            eta += float(j.get("eta") or 60)
        except Exception:
            eta += 60
    active = _sched_job_locked(SCHEDULER["active"])
    if active:
        try:
            left = float(active.get("eta") or 60) - float(active.get("elapsed") or 0)
            eta += max(0.0, left)
        except Exception:
            pass
    return {"queue_position": idx + 1,
            "queue_size": len(order),
            "queue_eta": round(eta, 1)}


def scheduler_job_info(jid):
    with SCHED_LOCK:
        _sched_clean_locked()
        return _sched_info_locked(jid)


def scheduler_active_count(uid):
    with SCHED_LOCK:
        _sched_clean_locked()
        n = _sched_user_pending_locked(uid)
        active = _sched_job_locked(SCHEDULER["active"])
        if active and active.get("user_id") == uid:
            n += 1
        return n


def _sched_dispatch_locked():
    """如果 GPU 空闲，挑“最久没轮到”的账号的下一个任务放行。"""
    if SCHEDULER["active"]:
        return
    _sched_clean_locked()
    while SCHEDULER["queues"]:
        uid = _sched_pick_locked(SCHEDULER["last_served"])
        if not uid:
            break
        q = SCHEDULER["queues"].get(uid)
        if not q:
            SCHEDULER["queues"].pop(uid, None)
            continue
        jid = q.popleft()
        job = _sched_job_locked(jid)
        if not job or job.get("status") != "queued":
            continue
        if not q:
            SCHEDULER["queues"].pop(uid, None)
        SCHEDULER["serve_seq"] += 1
        SCHEDULER["last_served"][uid] = SCHEDULER["serve_seq"]
        now = time.time()
        job["status"] = "running"
        job["started"] = now
        job["dispatched_at"] = now
        job["elapsed"] = 0
        SCHEDULER["active"] = jid
        payload = job_activity_fields(job)
        u = get_user(job.get("user_id") or "admin") or {}
        payload.setdefault("user_id", job.get("user_id") or "admin")
        payload.setdefault("username", u.get("username") or job.get("username") or "")
        payload.setdefault("user_name", u.get("name") or job.get("user_name") or "")
        payload["job_id"] = jid
        payload["queue_position"] = 0
        payload["queue_size"] = _sched_pending_locked()
        activity("job", phase="start", **payload)
        ev = SCHEDULER["events"].get(jid)
        if ev:
            ev.set()
        return


def scheduler_enqueue(jid):
    """把任务放进公平队列；返回 None 表示成功，否则返回中文拦截原因。"""
    with SCHED_LOCK:
        job = _sched_job_locked(jid)
        if not job:
            return "任务不存在"
        uid = job.get("user_id") or "admin"
        if _sched_pending_locked() >= SCHED_MAX_QUEUE:
            return ("排队任务太多了（最多 %d 个），等前面的跑完再提交。"
                    % SCHED_MAX_QUEUE)
        cap = _sched_user_cap(uid)
        active_n = _sched_user_pending_locked(uid)
        active = _sched_job_locked(SCHEDULER["active"])
        if active and active.get("user_id") == uid:
            active_n += 1
        if active_n >= cap:
            return ("你已经有 %d 个任务在排队或运行，等完成再提交。"
                    % active_n)
        SCHEDULER["seq"] += 1
        job["status"] = "queued"
        job["queued_at"] = time.time()
        job["queue_seq"] = SCHEDULER["seq"]
        q = SCHEDULER["queues"].setdefault(uid, deque())
        q.append(jid)
        SCHEDULER["events"][jid] = threading.Event()
        info = _sched_info_locked(jid)
        payload = job_activity_fields(job)
        u = get_user(uid) or {}
        payload.setdefault("user_id", uid)
        payload.setdefault("username", u.get("username") or job.get("username") or "")
        payload.setdefault("user_name", u.get("name") or job.get("user_name") or "")
        payload.update({"job_id": jid,
                        "queue_position": info["queue_position"],
                        "queue_size": info["queue_size"],
                        "queue_eta": info["queue_eta"]})
        activity("job", phase="queued", **payload)
        _sched_dispatch_locked()
        return None


def scheduler_wait(jid, timeout=86400):
    """等轮到自己。返回 False 表示排队期间被取消/账号停用。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with SCHED_LOCK:
            job = _sched_job_locked(jid)
            status = job.get("status")
            if SCHEDULER["active"] == jid and status == "running":
                return True
            if status not in ("queued", "running"):
                return False
            ev = SCHEDULER["events"].get(jid)
        if ev is None:
            # 已经被取消/清理
            with SCHED_LOCK:
                job = _sched_job_locked(jid)
                return (SCHEDULER["active"] == jid
                        and job.get("status") == "running")
        ev.wait(0.5)
    return False


def scheduler_cancel_job(jid):
    """把任务从等待队列移除；正在跑的任务由调用方 interrupt。"""
    with SCHED_LOCK:
        for uid in list(SCHEDULER["queues"].keys()):
            q = SCHEDULER["queues"].get(uid)
            if q and jid in q:
                try:
                    q.remove(jid)
                except ValueError:
                    pass
                if not q:
                    SCHEDULER["queues"].pop(uid, None)
        ev = SCHEDULER["events"].get(jid)
        if ev:
            ev.set()
        _sched_clean_locked()


def scheduler_cancel_user(uid):
    with SCHED_LOCK:
        q = SCHEDULER["queues"].get(uid)
        jids = list(q or ())
        if q:
            q.clear()
            SCHEDULER["queues"].pop(uid, None)
        for jid in jids:
            ev = SCHEDULER["events"].get(jid)
            if ev:
                ev.set()
        _sched_clean_locked()
        return jids


def scheduler_release(jid):
    with SCHED_LOCK:
        if SCHEDULER["active"] == jid:
            SCHEDULER["active"] = ""
        # 排队中被取消 / 已结束的任务，事件对象不再需要
        SCHEDULER["events"].pop(jid, None)
        _sched_dispatch_locked()


# 队列快照函数定义在调度器代码后部（会按登录账号过滤）。


# 最近的出图耗时 (ckpt, steps, count, seconds)，用来估算进度条
DURATIONS = deque(maxlen=30)

FAV_LOCK = threading.Lock()

# 让 Argos 走本地分词模型（与 ComfyUI 启动脚本里的设置保持一致）
os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")

# 实时进度：ComfyUI 通过 WebSocket 推过来
WS_LOCK = threading.Lock()
WS_PROGRESS = {}    # comfy prompt_id -> {"value": n, "max": m}
WS_PREVIEW = {}     # comfy prompt_id -> 最新预览图字节
WS_CURRENT = {"pid": None}

# 挂机造图
AUTO = {"running": False, "done": 0, "target": 0, "stop": False,
        "user_id": "", "username": ""}

# 实时活动：3D 星图轮询 /api/activity，让正在工作的星球亮起来。
# 只记录路由、模式、模型、耗时等元数据，绝不记录提示词 / 文件名等隐私内容。
ACTIVITY = deque(maxlen=260)
ACTIVITY_LOCK = threading.Lock()
ACTIVITY_SEQ = 0
ACTIVITY_THROTTLE = {}
_ACTIVITY_CTX = threading.local()

# 管理员后台的私有活动：只能定向推送给发起操作的账号。
# key = uid, value = list[queue.Queue]
ACTIVITY_SUBSCRIBERS = {}
ACTIVITY_SUB_LOCK = threading.Lock()


def subscribe_activity(uid):
    uid = str(uid or "")
    q = queue.Queue(maxsize=120)
    if not uid:
        return q
    with ACTIVITY_SUB_LOCK:
        ACTIVITY_SUBSCRIBERS.setdefault(uid, []).append(q)
    return q


def unsubscribe_activity(uid, q):
    uid = str(uid or "")
    with ACTIVITY_SUB_LOCK:
        items = ACTIVITY_SUBSCRIBERS.get(uid) or []
        if q in items:
            items.remove(q)
        if not items:
            ACTIVITY_SUBSCRIBERS.pop(uid, None)


def _dispatch_activity_event(ev):
    """只把带 private_user_id 的事件推给对应用户的 WebSocket。"""
    target = str(ev.get("private_user_id") or "")
    if not target or ev.get("silent"):
        return
    with ACTIVITY_SUB_LOCK:
        subs = list(ACTIVITY_SUBSCRIBERS.get(target) or ())
    for q in subs:
        try:
            q.put_nowait(dict(ev))
        except queue.Full:
            try:
                q.get_nowait()
                q.put_nowait(dict(ev))
            except Exception:
                pass


def activity_user_id():
    ctx = getattr(_ACTIVITY_CTX, "user", None)
    return (ctx or {}).get("id") or ""


def set_activity_user(user=None, ip=""):
    """当前请求的用户上下文；None 表示清空，避免线程复用串号。"""
    if not user:
        _ACTIVITY_CTX.user = None
        return
    _ACTIVITY_CTX.user = {
        "id": str(user.get("id") or ""),
        "username": str(user.get("username") or ""),
        "name": str(user.get("name") or ""),
        "ip": str(ip or ""),
    }

# 持久化日志：activity = 用户操作，security = 登录 / 权限 / 管理动作。
# 每天一个 JSONL，默认保留 30 天；绝不写入密码、提示词正文和图片文件名。
LOG_DIR = os.path.join(ROOT, "logs")
AUDIT_LOCK = threading.Lock()
AUDIT_RETAIN_DAYS = 30
AUDIT_LAST_PRUNE = {"t": 0.0}

# 在线用户：最近一次认证请求的时间 + 请求过的路由。
# 只存在内存里，不落盘；用于星图详情面板显示“谁在使用”。
PRESENCE_LOCK = threading.Lock()
USER_PRESENCE = {}
PRESENCE_TTL = 120

# 账号消耗统计：请求数、上下行字节、图片数、GPU 秒、任务数。
# 只存计数器，不存提示词 / 文件名；按天 / 月分桶，usage.json 落盘。
USAGE_FILE = os.path.join(ROOT, "usage.json")
USAGE_LOCK = threading.Lock()
USAGE_LAST_SAVE = {"t": 0.0}
USAGE_DIRTY = {"v": False}


def _new_usage_counter():
    return {"requests": 0, "rx": 0, "tx": 0, "images": 0,
            "gpu_seconds": 0.0, "jobs": 0,
            "train_seconds": 0.0, "train_jobs": 0, "kinds": {}}


def _load_usage():
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        if isinstance(data.get("users"), dict):
            return data
    except Exception:
        pass
    return {"version": 1, "users": {}}


USAGE = _load_usage()


def usage_export_rows(uid=None):
    """导出用量明细：每个账号每天一行，管理员可导出全部。"""
    rows = []
    with USAGE_LOCK:
        users = USAGE.get("users") or {}
        for ruid, item in users.items():
            if uid and ruid != uid:
                continue
            if not isinstance(item, dict):
                continue
            user = get_user(ruid) or {}
            days = item.get("days") or {}
            for day in sorted(days):
                bucket = days.get(day)
                if not isinstance(bucket, dict):
                    continue
                rows.append({
                    "user_id": ruid,
                    "username": user.get("username") or ruid,
                    "name": user.get("name") or "",
                    "role": user.get("role") or "user",
                    "date": day,
                    "requests": int(bucket.get("requests") or 0),
                    "rx_bytes": int(bucket.get("rx") or 0),
                    "tx_bytes": int(bucket.get("tx") or 0),
                    "images": int(bucket.get("images") or 0),
                    "gpu_seconds": round(float(bucket.get("gpu_seconds") or 0), 1),
                    "jobs": int(bucket.get("jobs") or 0),
                    "kinds": dict(bucket.get("kinds") or {}),
                })
    rows.sort(key=lambda r: (r["date"], r["user_id"]))
    return rows


def reload_usage():
    """系统回滚后重新载入 usage.json。"""
    data = _load_usage()
    with USAGE_LOCK:
        USAGE.clear()
        USAGE.update(data)
        USAGE_DIRTY["v"] = False
        USAGE_LAST_SAVE["t"] = time.time()
    return USAGE


def _usage_keys(now=None):
    now = now or trusted_time.now()
    lt = trusted_time.localtime(now)
    return (time.strftime("%Y-%m-%d", lt), time.strftime("%Y-%m", lt))


def _usage_user_locked(uid):
    uid = str(uid or "")
    if not uid:
        return None
    users = USAGE.setdefault("users", {})
    item = users.get(uid)
    if not isinstance(item, dict):
        item = {"days": {}, "months": {}, "total": _new_usage_counter()}
        users[uid] = item
    for key in ("days", "months"):
        if not isinstance(item.get(key), dict):
            item[key] = {}
    if not isinstance(item.get("total"), dict):
        item["total"] = _new_usage_counter()
    return item


def _usage_bucket(uid, period):
    item = _usage_user_locked(uid)
    if item is None:
        return None
    day, month = _usage_keys()
    key = month if period == "month" else day
    bucket = item[period + "s"].get(key)
    if not isinstance(bucket, dict):
        bucket = _new_usage_counter()
        item[period + "s"][key] = bucket
    for k, v in _new_usage_counter().items():
        bucket.setdefault(k, v)
    if not isinstance(bucket.get("kinds"), dict):
        bucket["kinds"] = {}
    return bucket


def _prune_usage_locked(now=None):
    now = now or trusted_time.now()
    try:
        cutoff_day = time.strftime("%Y-%m-%d", time.localtime(now - 90 * 86400))
        cutoff_month = time.strftime("%Y-%m", time.localtime(now - 366 * 86400))
        for item in USAGE.get("users", {}).values():
            days = item.get("days") or {}
            for k in list(days.keys()):
                if k < cutoff_day:
                    days.pop(k, None)
            months = item.get("months") or {}
            for k in list(months.keys()):
                if k < cutoff_month:
                    months.pop(k, None)
    except Exception:
        pass


def _save_usage_locked(now=None):
    try:
        _prune_usage_locked(now)
        os.makedirs(ROOT, exist_ok=True)
        tmp = USAGE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(USAGE, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, USAGE_FILE)
        USAGE_DIRTY["v"] = False
        USAGE_LAST_SAVE["t"] = now or time.time()
    except Exception:
        pass


def note_traffic(uid, rx=0, tx=0, requests=0):
    """记录账号请求 / 上下行流量；写盘做 2 秒节流。"""
    uid = str(uid or "")
    if not uid:
        return
    rx = max(0, int(rx or 0))
    tx = max(0, int(tx or 0))
    requests = max(0, int(requests or 0))
    if not (rx or tx or requests):
        return
    now = time.time()
    with USAGE_LOCK:
        total = _usage_user_locked(uid).get("total")
        for bucket in (_usage_bucket(uid, "day"), _usage_bucket(uid, "month"),
                       total):
            if not bucket:
                continue
            bucket["requests"] += requests
            bucket["rx"] += rx
            bucket["tx"] += tx
        USAGE_DIRTY["v"] = True
        if now - USAGE_LAST_SAVE["t"] >= 2.0:
            _save_usage_locked(now)


def note_job_usage(uid, seconds=0, images=0, kind="gen", ok=True):
    """任务结束时累计 GPU 秒 / 图片数 / 任务数。"""
    uid = str(uid or "")
    if not uid:
        return
    seconds = max(0.0, float(seconds or 0))
    images = max(0, int(images or 0))
    now = time.time()
    with USAGE_LOCK:
        total = _usage_user_locked(uid).get("total")
        for bucket in (_usage_bucket(uid, "day"), _usage_bucket(uid, "month"),
                       total):
            if not bucket:
                continue
            bucket["gpu_seconds"] += seconds
            bucket["images"] += images
            bucket["jobs"] += 1
            kinds = bucket.setdefault("kinds", {})
            kinds[kind] = int(kinds.get(kind, 0)) + 1
        USAGE_DIRTY["v"] = True
        if now - USAGE_LAST_SAVE["t"] >= 2.0:
            _save_usage_locked(now)


def note_training_usage(uid, seconds=0, ok=True):
    """训练单独记账，不重复占用生图的 GPU 秒配额。"""
    uid = str(uid or "")
    if not uid:
        return
    seconds = max(0.0, float(seconds or 0))
    now = time.time()
    with USAGE_LOCK:
        total = _usage_user_locked(uid).get("total")
        for bucket in (_usage_bucket(uid, "day"), _usage_bucket(uid, "month"),
                       total):
            if not bucket:
                continue
            bucket["train_seconds"] = float(
                bucket.get("train_seconds") or 0.0) + seconds
            bucket["train_jobs"] = int(bucket.get("train_jobs") or 0) + 1
            kinds = bucket.setdefault("kinds", {})
            kinds["train"] = int(kinds.get("train", 0)) + 1
        USAGE_DIRTY["v"] = True
        if now - USAGE_LAST_SAVE["t"] >= 2.0:
            _save_usage_locked(now)


def usage_snapshot(uid):
    """返回某账号今天 / 本月 / 累计的消耗计数。"""
    uid = str(uid or "")
    day, month = _usage_keys()
    with USAGE_LOCK:
        item = _usage_user_locked(uid) or {}
        today = dict((item.get("days") or {}).get(day) or _new_usage_counter())
        mon = dict((item.get("months") or {}).get(month) or _new_usage_counter())
        total = dict(item.get("total") or _new_usage_counter())
    for b in (today, mon, total):
        b["traffic"] = int(b.get("rx", 0)) + int(b.get("tx", 0))
        b.setdefault("kinds", {})
    return {"today": today, "month": mon, "total": total,
            "traffic_today": today["traffic"],
            "traffic_month": mon["traffic"],
            "traffic_total": total["traffic"],
            "train_seconds_today": round(
                float(today.get("train_seconds") or 0), 1),
            "train_seconds_month": round(
                float(mon.get("train_seconds") or 0), 1),
            "train_jobs_today": int(today.get("train_jobs") or 0),
            "train_jobs_month": int(mon.get("train_jobs") or 0)}


def _audit_user(user=None, user_id=None):
    """把用户对象 / uid 归一成日志里的安全字段。"""
    obj = user if isinstance(user, dict) else None
    if obj is None and user_id:
        try:
            obj = get_user(user_id)
        except Exception:
            obj = None
    if not obj:
        return (str(user_id or ""), "", "", "")
    return (str(obj.get("id") or user_id or ""),
            str(obj.get("username") or ""),
            str(obj.get("name") or ""),
            str(obj.get("role") or ""))


def _prune_audit(now=None):
    now = now or time.time()
    if now - AUDIT_LAST_PRUNE["t"] < 3600:
        return
    AUDIT_LAST_PRUNE["t"] = now
    try:
        if not os.path.isdir(LOG_DIR):
            return
        cutoff = now - AUDIT_RETAIN_DAYS * 86400
        for fn in os.listdir(LOG_DIR):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(LOG_DIR, fn)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except Exception:
        pass


def license_audit_fields():
    """商用版审计附加字段：客户名 + 机器指纹（不写授权码原文/完整机器码）。"""
    try:
        lic = license_guard.status()
        if not lic.get("commercial"):
            return {}
        machine = str(lic.get("machine_code") or "")
        out = {"license_customer": str(lic.get("customer") or "")[:100]}
        if machine:
            out["license_fp"] = hashlib.sha256(
                machine.encode("utf-8")).hexdigest()[:12]
        return out
    except Exception:
        return {}


def audit(category, action, user=None, ip="", ok=True, user_id=None, **detail):
    """追加一条持久日志。category 只能是 activity / security。"""
    if category not in ("activity", "security"):
        category = "activity"
    now = trusted_time.now()
    uid, username, name, role = _audit_user(user, user_id)
    rec = {
        "ts": round(now, 3),
        "time": trusted_time.strftime("%Y-%m-%d %H:%M:%S", now),
        "category": category,
        "action": str(action or "")[:80],
        "ok": bool(ok),
        "user_id": uid,
        "username": username,
        "name": name,
        "role": role,
        "ip": str(ip or "")[:64],
        "detail": detail,
    }
    lic_fields = license_audit_fields()
    if lic_fields:
        rec.update(lic_fields)
    try:
        with AUDIT_LOCK:
            _prune_audit(now)
            os.makedirs(LOG_DIR, exist_ok=True)
            path = os.path.join(
                LOG_DIR, "%s-%s.jsonl" %
                (category, trusted_time.strftime("%Y-%m-%d", now)))
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return rec


def read_audit(category="activity", limit=100, user_id=None, q=""):
    """读最近的日志（新的在前）；最多 200 条。"""
    if category not in ("activity", "security"):
        category = "activity"
    try:
        limit = max(1, min(200, int(limit)))
    except Exception:
        limit = 100
    needle = str(q or "").strip().lower()
    out = []
    try:
        names = sorted(
            [fn for fn in os.listdir(LOG_DIR)
             if fn.startswith(category + "-") and fn.endswith(".jsonl")],
            reverse=True)
    except OSError:
        names = []
    for fn in names:
        path = os.path.join(LOG_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if user_id and str(rec.get("user_id") or "") != str(user_id):
                continue
            if needle:
                hay = json.dumps(rec, ensure_ascii=False).lower()
                if needle not in hay:
                    continue
            out.append(rec)
            if len(out) >= limit:
                return out
    return out


def note_user_presence(user, route="", ip=""):
    """记录已登录用户最近在线和访问过的路由（只存内存）。"""
    if not user:
        return
    uid = str(user.get("id") or "")
    if not uid:
        return
    now = time.time()
    route = str(route or "").split("?")[0][:160]
    with PRESENCE_LOCK:
        item = USER_PRESENCE.get(uid)
        if not item:
            item = {"id": uid,
                    "username": str(user.get("username") or ""),
                    "name": str(user.get("name") or ""),
                    "role": str(user.get("role") or ""),
                    "since": now, "last": now, "ip": str(ip or ""),
                    "routes": {}}
        item["username"] = str(user.get("username") or item.get("username") or "")
        item["name"] = str(user.get("name") or item.get("name") or "")
        item["role"] = str(user.get("role") or item.get("role") or "")
        if ip:
            item["ip"] = str(ip)[:64]
        item["last"] = now
        if route:
            item["routes"][route] = now
        for r, ts in list(item["routes"].items()):
            if now - ts > PRESENCE_TTL:
                item["routes"].pop(r, None)
        USER_PRESENCE[uid] = item


def drop_presence(uid):
    with PRESENCE_LOCK:
        USER_PRESENCE.pop(str(uid or ""), None)


def presence_snapshot():
    """返回最近在线用户，带每个路由的最近访问时间。"""
    now = time.time()
    out = []
    with PRESENCE_LOCK:
        for uid, item in list(USER_PRESENCE.items()):
            if now - item.get("last", 0) > PRESENCE_TTL:
                USER_PRESENCE.pop(uid, None)
                continue
            routes = {k: round(v, 3) for k, v in
                      (item.get("routes") or {}).items()
                      if now - v <= PRESENCE_TTL}
            out.append({
                "id": uid,
                "username": item.get("username") or "",
                "name": item.get("name") or "",
                "role": item.get("role") or "",
                "ip": item.get("ip") or "",
                "last": round(item.get("last", 0), 3),
                "age": round(now - item.get("last", now), 1),
                "routes": routes,
            })
    out.sort(key=lambda x: x.get("last") or 0, reverse=True)
    return out[:50]


def activity(event_kind, throttle=None, throttle_key=None,
             silent=False, private_user_id=None, **fields):
    """追加一条活动事件。throttle 秒内同一个 key 只记录一次。

    event_kind 是事件大类（request / job），fields 里的 kind 是任务种类
    （gen / video / upscale），两者不能共用参数名。

    silent=True：不进入前端的实时视觉流（日志照常写）。
    private_user_id：只推给这个账号的 WebSocket，不进入普通轮询。
    """
    global ACTIVITY_SEQ
    now = time.time()
    with ACTIVITY_LOCK:
        if throttle and throttle_key:
            last = ACTIVITY_THROTTLE.get(throttle_key, 0.0)
            if now - last < throttle:
                return None
            ACTIVITY_THROTTLE[throttle_key] = now
            if len(ACTIVITY_THROTTLE) > 300:
                for k, ts in list(ACTIVITY_THROTTLE.items()):
                    if now - ts > 300:
                        ACTIVITY_THROTTLE.pop(k, None)
        ACTIVITY_SEQ += 1
        ev = {"seq": ACTIVITY_SEQ, "t": round(now, 3), "event": event_kind}
        if silent:
            ev["silent"] = True
        if private_user_id:
            ev["private_user_id"] = str(private_user_id)
        ctx = getattr(_ACTIVITY_CTX, "user", None)
        if ctx:
            ev.setdefault("user", ctx.get("username") or "")
            ev.setdefault("user_id", ctx.get("id") or "")
            ev.setdefault("user_name", ctx.get("name") or "")
            if ctx.get("ip"):
                ev.setdefault("ip", ctx["ip"])
        ev.update(fields)
        ACTIVITY.append(ev)
        _dispatch_activity_event(ev)
        return ev


def activity_request(route, method="GET", throttle=0.0, key=None,
                     silent=False, private_user_id=None, **fields):
    """记录一次接口请求。route 用稳定值（如 /thumb），避免把文件名带出去。"""
    return activity("request", route=route, method=method,
                    throttle=throttle or None,
                    throttle_key=key or ("%s %s" % (method, route)),
                    silent=silent, private_user_id=private_user_id,
                    **fields)


def job_activity_fields(job):
    """从 JOBS 快照里挑出能安全公开的任务元数据。"""
    keep = ("kind", "mode", "model", "hires", "pag", "turbo", "loras",
            "inpaint", "img2img", "frames", "steps", "cfg", "sampler",
            "factor", "user_id", "username", "user_name")
    out = {}
    for k in keep:
        v = job.get(k)
        if v is not None:
            out[k] = v
    return out


# ------------------------------------------------------------- 任务状态落盘
# 只保存状态页需要的安全字段。提示词、输入图路径、工作流正文一律不落盘。
JOB_STATE_KEYS = (
    "status", "started", "queued_at", "dispatched_at", "submitted_at",
    "first_progress_at", "saved_at", "finished_at", "elapsed", "eta",
    "image", "images", "error", "seed", "kind", "mode", "model", "family",
    "hires", "pag", "turbo", "loras", "inpaint", "img2img", "frames",
    "steps", "cfg", "sampler", "count", "pixels", "user_id", "username",
    "user_name", "worker_id", "worker_name", "worker_kind", "retry_count",
    "dispatch_state", "recovered", "recovery_attempts", "comfy_prompt_id",
    "auto",
)


def _job_state_record(job):
    rec = {}
    for k in JOB_STATE_KEYS:
        if k in job:
            rec[k] = job.get(k)
    if rec.get("images"):
        rec["images"] = list(rec["images"])[:8]
    return rec


def _job_state_ts(job):
    try:
        return max(float(job.get("started") or 0),
                   float(job.get("queued_at") or 0),
                   float(job.get("finished_at") or 0))
    except Exception:
        return 0.0


def persist_jobs(force=False, min_interval=1.5):
    """把最近任务安全地写入 jobs_state.json；进度更新做节流。"""
    now = time.time()
    if (not force
            and now - float(JOBS_STATE_META.get("last_write") or 0)
            < min_interval):
        return
    with JOBS_LOCK:
        rows = []
        for jid, job in JOBS.items():
            rec = _job_state_record(job)
            rec["job_id"] = jid
            rows.append(rec)
    rows.sort(key=_job_state_ts, reverse=True)
    rows = rows[:JOBS_KEEP_MAX]
    payload = {"version": 1, "saved_at": now, "jobs": rows}
    tmp = JOBS_STATE_FILE + ".tmp"
    try:
        with JOBS_STATE_LOCK:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, JOBS_STATE_FILE)
        JOBS_STATE_META["last_write"] = now
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _read_resume_map():
    try:
        with open(JOBS_RESUME_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data.get("jobs") if isinstance(data, dict) else None
        return rows if isinstance(rows, dict) else {}
    except Exception:
        return {}


def _write_resume_map(rows):
    payload = {"version": 1, "saved_at": time.time(), "jobs": rows}
    tmp = JOBS_RESUME_FILE + ".tmp"
    with JOBS_RESUME_LOCK:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, JOBS_RESUME_FILE)


def save_job_resume(jid, payload):
    """保存尚未提交任务的恢复参数；提交成功后必须调用 drop_job_resume。"""
    if not jid or not isinstance(payload, dict):
        return
    with JOBS_RESUME_LOCK:
        rows = _read_resume_map()
        rows[jid] = payload
        if len(rows) > JOBS_RESUME_MAX:
            ordered = sorted(rows.items(),
                             key=lambda kv: float(kv[1].get("created") or 0),
                             reverse=True)[:JOBS_RESUME_MAX]
            rows = dict(ordered)
        _write_resume_map(rows)


def drop_job_resume(jid):
    if not jid:
        return
    with JOBS_RESUME_LOCK:
        rows = _read_resume_map()
        if jid in rows:
            rows.pop(jid, None)
            _write_resume_map(rows)


def load_job_resume_map():
    with JOBS_RESUME_LOCK:
        return _read_resume_map()


def load_jobs_state():
    """启动时恢复最近任务；被中断的排队/运行任务明确标成错误。"""
    if JOBS_STATE_META.get("loaded"):
        return
    JOBS_STATE_META["loaded"] = True
    try:
        with open(JOBS_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        rows = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return
    except Exception:
        return
    cutoff = time.time() - JOBS_KEEP_SECONDS
    settings = runtime_settings.load()
    resumes = load_job_resume_map()
    RECOVERY_PENDING.clear()
    restored = 0
    drop_ids = []
    now = time.time()
    for rec in rows:
        if not isinstance(rec, dict):
            continue
        jid = str(rec.get("job_id") or "")
        if not jid or jid in JOBS:
            continue
        if _job_state_ts(rec) < cutoff:
            continue
        status = str(rec.get("status") or "")
        if status in ("queued", "running"):
            resume = resumes.get(jid)
            kind = str(rec.get("kind") or "gen")
            uid = str(rec.get("user_id") or "admin")
            user = get_user(uid)
            retryable = (bool(resume) and kind == "gen"
                         and not rec.get("auto"))
            attempts = int(rec.get("recovery_attempts") or 0)
            if not user or not user_is_active(user):
                rec["status"] = "error"
                rec["error"] = "账号已停用或删除，任务不再自动恢复。"
                rec["dispatch_state"] = "interrupted"
                rec["finished_at"] = now
            elif (status == "queued" and retryable
                  and settings.get("recovery_queued", True)):
                if attempts >= 3:
                    rec["status"] = "error"
                    rec["error"] = "任务多次恢复失败，已停止自动重试；请重新提交。"
                    rec["dispatch_state"] = "interrupted"
                    rec["finished_at"] = now
                    drop_ids.append(jid)
                else:
                    rec["status"] = "queued"
                    rec["recovered"] = True
                    rec["recovery_attempts"] = attempts + 1
                    rec["queued_at"] = now
                    rec["started"] = 0
                    rec["elapsed"] = 0
                    rec["dispatch_state"] = "recovered"
                    RECOVERY_PENDING.append(jid)
            elif (status == "running" and not rec.get("comfy_prompt_id")
                  and retryable
                  and settings.get("recovery_running_without_prompt", True)):
                if attempts >= 3:
                    rec["status"] = "error"
                    rec["error"] = "任务多次恢复失败，已停止自动重试；请重新提交。"
                    rec["dispatch_state"] = "interrupted"
                    rec["finished_at"] = now
                    drop_ids.append(jid)
                else:
                    rec["status"] = "queued"
                    rec["recovered"] = True
                    rec["recovery_attempts"] = attempts + 1
                    rec["queued_at"] = now
                    rec["started"] = 0
                    rec["elapsed"] = 0
                    rec["dispatch_state"] = "recovered"
                    RECOVERY_PENDING.append(jid)
            else:
                rec["status"] = "error"
                if status == "running" and rec.get("comfy_prompt_id"):
                    rec["error"] = ("服务重启时任务已经提交给 ComfyUI；"
                                    "为避免重复出图不再自动重试，请先查看图库。")
                elif not resume:
                    rec["error"] = "服务重启，任务恢复数据缺失；请重新提交。"
                else:
                    rec["error"] = "服务重启，任务已中断；请重新提交。"
                rec["dispatch_state"] = "interrupted"
                rec["finished_at"] = now
                rec["recovered"] = True
                drop_ids.append(jid)
        with JOBS_LOCK:
            JOBS[jid] = rec
        restored += 1
    for jid in list(resumes.keys()):
        if jid not in JOBS:
            drop_ids.append(jid)
    for jid in drop_ids:
        drop_job_resume(jid)
    if restored:
        persist_jobs(force=True)


def _fail_recovered_job(jid, message, resume=None):
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if job:
            job["status"] = "error"
            job["error"] = message
            job["dispatch_state"] = "interrupted"
            job["finished_at"] = time.time()
    if resume:
        cleanup_stage(resume.get("user_id") or "admin",
                      resume.get("stage_id"))
    drop_job_resume(jid)
    scheduler_cancel_job(jid)
    persist_jobs(force=True)


def recover_queued_jobs():
    """把 load_jobs_state 标记的待恢复任务重新排队并启动执行线程。

    只恢复 kind=gen 且保存了恢复参数、临时输入还在的任务；已经提交给
    ComfyUI 的 running 任务不会重试，避免重复出图。
    """
    pending = list(RECOVERY_PENDING)
    RECOVERY_PENDING.clear()
    if not pending:
        return 0
    resumes = load_job_resume_map()
    started = 0
    for jid in pending:
        resume = resumes.get(jid)
        with JOBS_LOCK:
            job = dict(JOBS.get(jid) or {})
        if not job or job.get("status") != "queued":
            continue
        if not resume:
            _fail_recovered_job(jid, "任务恢复数据缺失；请重新提交。")
            continue
        uid = resume.get("user_id") or "admin"
        user = get_user(uid)
        if not user or not user_is_active(user):
            _fail_recovered_job(jid, "账号已停用或删除，任务不再恢复。", resume)
            continue
        ckpt = str(resume.get("ckpt") or "")
        available = {m.get("name") for m in list_models()}
        if not ckpt or ckpt not in available:
            _fail_recovered_job(jid, "恢复失败：底模文件不存在，请重新提交。", resume)
            continue
        init_image = resume.get("init_image")
        init_mask = resume.get("init_mask")
        if init_image and not os.path.isfile(os.path.join(INPUT_DIR, init_image)):
            _fail_recovered_job(jid, "恢复失败：参考图临时文件已清理，请重新提交。", resume)
            continue
        if init_mask and not os.path.isfile(os.path.join(INPUT_DIR, init_mask)):
            _fail_recovered_job(jid, "恢复失败：蒙版临时文件已清理，请重新提交。", resume)
            continue
        queue_err = scheduler_enqueue(jid)
        if queue_err:
            _fail_recovered_job(jid, "恢复排队失败：%s" % queue_err, resume)
            continue
        try:
            threading.Thread(
                target=run_job,
                args=(jid, resume.get("prompt", ""),
                      resume.get("negative", ""),
                      int(resume.get("width") or 832),
                      int(resume.get("height") or 1216),
                      int(resume.get("steps") or 20),
                      float(resume.get("cfg") or 6.0),
                      int(resume.get("seed") or 0),
                      int(resume.get("count") or 1),
                      init_image, init_mask,
                      float(resume.get("denoise") or 1.0),
                      ckpt, resume.get("kind") or "gen",
                      resume.get("loras") or [],
                      bool(resume.get("hires")),
                      resume.get("prompt_en") or "",
                      resume.get("sampler") or DEFAULT_SAMPLER,
                      int(resume.get("frames") or 16),
                      bool(resume.get("pag", True)),
                      bool(resume.get("turbo")),
                      resume.get("char_tags"),
                      resume.get("prompt_display") or "",
                      resume.get("stage_id"), uid),
                daemon=True,
                name="run-job-recovered-%s" % jid).start()
            started += 1
            audit("activity", "job_recovered", user=user,
                  ip="", job_id=jid, kind=resume.get("kind") or "gen",
                  model=os.path.basename(ckpt))
            activity_request("job", phase="recovered", job_id=jid,
                             user_id=uid, silent=True)
        except Exception as exc:
            _fail_recovered_job(jid, "恢复启动失败：%s" % exc, resume)
    return started


def reload_jobs_state():
    """清空内存任务后，从 jobs_state.json 重新读取（系统回滚用）。"""
    with JOBS_LOCK:
        JOBS.clear()
    JOBS_STATE_META["loaded"] = False
    load_jobs_state()
    pending = list(RECOVERY_PENDING)
    RECOVERY_PENDING.clear()
    for jid in pending:
        _fail_recovered_job(jid, "系统回滚，任务未恢复；请重新提交。")
    with JOBS_LOCK:
        return dict(JOBS)


# ------------------------------------------------------------- 星图：工作流快照
# 星图读取 ComfyUI 最近一次执行的工作流（/history），把节点和连线画成新星球。
# 只输出结构、节点类型/标题和少量安全参数，绝不输出提示词、文件名等内容。
WORKFLOW_DIR = os.path.join(ROOT, "ComfyUI", "user", "default", "workflows")
WF_LOCK = threading.Lock()
WF_CACHE = {"t": 0.0, "data": None}
LAST_WORKFLOW = {"t": 0.0, "data": None}
WF_FILE_CACHE = {"path": "", "mtime": 0.0, "data": None}
UI_SKIP = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode",
           "PreviewAny", "ShowText|pysssss"}
UI_WIDGETS = {
    "KSampler": ["seed", "control_after_generate", "steps", "cfg",
                 "sampler_name", "scheduler", "denoise"],
    "KSamplerAdvanced": ["add_noise", "noise_seed", "steps", "cfg",
                         "sampler_name", "scheduler", "start_at_step",
                         "end_at_step", "return_with_leftover_noise"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "EmptyHunyuanLatentVideo": ["width", "height", "length", "batch_size"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "CLIPLoader": ["clip_name", "type"],
    "VAELoader": ["vae_name"],
    "LoraLoader": ["lora_name", "strength_model", "strength_clip"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "WanVaceToVideo": ["width", "height", "length", "batch_size", "strength"],
    "VHS_VideoCombine": ["frame_rate", "loop_count", "filename_prefix",
                         "format", "pingpong", "save_output"],
}
WF_SAFE_INPUTS = {
    "steps", "cfg", "sampler_name", "scheduler", "denoise", "seed",
    "noise_seed", "width", "height", "batch_size", "frames", "fps",
    "ckpt_name", "lora_name", "vae_name", "clip_name", "unet_name",
    "upscale_model", "strength_model", "strength_clip", "resolution",
    "factor", "shift", "start_at_step", "end_at_step", "add_noise", "turbo",
}


def _wf_safe_inputs(inputs):
    out = {}
    if not isinstance(inputs, dict):
        return out
    for k, v in inputs.items():
        if k not in WF_SAFE_INPUTS:
            continue
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = round(v, 4) if isinstance(v, float) else v
        elif isinstance(v, str):
            out[k] = v[:48]
    return out


def normalize_workflow(wf, source="last-run", prompt_id="", title="",
                       created_at=None):
    """把 ComfyUI API 格式的 prompt 图变成星图能吃的节点/边。"""
    if not isinstance(wf, dict):
        return None
    nodes_in = {}
    for k, v in wf.items():
        if isinstance(v, dict) and v.get("class_type"):
            nodes_in[str(k)] = v
    if not nodes_in:
        return None

    incoming = {i: set() for i in nodes_in}
    outgoing = {i: set() for i in nodes_in}
    edges = set()
    for nid, node in nodes_in.items():
        inputs = node.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        for val in inputs.values():
            if (isinstance(val, list) and len(val) == 2
                    and isinstance(val[0], (str, int))):
                src = str(val[0])
                if src in nodes_in and src != nid:
                    incoming[nid].add(src)
                    outgoing[src].add(nid)
                    edges.add((src, nid))

    # 拓扑排序（有环时剩下的按 id 补齐），再算最长层级
    indeg = {i: len(incoming[i]) for i in nodes_in}
    ready = deque(sorted([i for i in nodes_in if indeg[i] == 0]))
    order = []
    while ready:
        i = ready.popleft()
        order.append(i)
        for dst in sorted(outgoing[i]):
            indeg[dst] -= 1
            if indeg[dst] == 0:
                ready.append(dst)
    for i in sorted(nodes_in):
        if i not in order:
            order.append(i)
    level = {i: 0 for i in nodes_in}
    for i in order:
        for dst in outgoing[i]:
            level[dst] = max(level[dst], level[i] + 1)
    step = {i: n + 1 for n, i in enumerate(order)}

    kept = order[:48]
    kept_set = set(kept)
    out_nodes = []
    for i in kept:
        node = nodes_in[i]
        typ = str(node.get("class_type") or "Node")[:60]
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
        name = str(meta.get("title") or typ)[:80]
        out_nodes.append({
            "id": i,
            "type": typ,
            "title": name,
            "step": step[i],
            "level": level.get(i, 0),
            "inputs": _wf_safe_inputs(node.get("inputs") or {}),
            "in": sorted(incoming[i]),
            "out": sorted(outgoing[i]),
        })
    out_edges = [[a, b] for a, b in sorted(edges)
                 if a in kept_set and b in kept_set]
    sig_src = json.dumps({
        "nodes": [(i, nodes_in[i].get("class_type"),
                   (nodes_in[i].get("_meta") or {}).get("title", ""))
                  for i in sorted(kept)],
        "edges": out_edges,
    }, sort_keys=True, ensure_ascii=False)
    sig = hashlib.sha1(sig_src.encode("utf-8")).hexdigest()[:16]
    return {
        "available": True,
        "source": source,
        "prompt_id": prompt_id,
        "title": title or "ComfyUI 工作流",
        "signature": sig,
        "ts": round(time.time(), 3),
        "created_at": round(float(created_at), 3) if created_at else 0,
        "nodes": out_nodes,
        "edges": out_edges,
        "truncated": len(order) > len(kept),
        "total_nodes": len(order),
    }


def _ui_widget_params(ntype, widgets):
    out = {}
    if isinstance(widgets, dict):
        for k, v in widgets.items():
            if k in WF_SAFE_INPUTS and isinstance(v, (str, int, float, bool)):
                out[k] = v[:48] if isinstance(v, str) else v
        return out
    names = UI_WIDGETS.get(ntype)
    if not names or not isinstance(widgets, list):
        return out
    for k, v in zip(names, widgets):
        if k in WF_SAFE_INPUTS and isinstance(v, (str, int, float, bool)):
            out[k] = v[:48] if isinstance(v, str) else v
    return out


def normalize_ui_workflow(data, title="", mtime=0.0):
    """把 ComfyUI 界面保存的工作流（nodes/links）转成同样的节点图。"""
    if not isinstance(data, dict):
        return None
    all_nodes = {}
    for n in (data.get("nodes") or []):
        if isinstance(n, dict) and n.get("id") is not None:
            all_nodes[str(n["id"])] = n
    raw_nodes = {i: n for i, n in all_nodes.items()
                 if str(n.get("type") or "") not in UI_SKIP}
    if not raw_nodes:
        return None

    # 输入连线：目标节点 -> [(来源, 来源槽)]
    target_links = {}
    links = data.get("links") or []
    for l in links:
        if isinstance(l, list) and len(l) >= 5:
            target_links.setdefault(str(l[3]), []).append((str(l[1]), l[2]))

    def resolve(src):
        seen = set()
        while src in all_nodes and str(all_nodes[src].get("type")) in UI_SKIP:
            if src in seen:
                return None
            seen.add(src)
            ins = target_links.get(src) or []
            if not ins:
                return None
            src = ins[0][0]
        return src if src in raw_nodes else None

    wf_api = {}
    for nid, node in raw_nodes.items():
        ntype = str(node.get("type") or "Node")
        meta_title = node.get("title") or ntype
        wf_api[nid] = {
            "class_type": ntype,
            "_meta": {"title": str(meta_title)[:80]},
            "inputs": _ui_widget_params(ntype, node.get("widgets_values")),
        }
    for idx, l in enumerate(links):
        if not (isinstance(l, list) and len(l) >= 4):
            continue
        src = resolve(str(l[1]))
        dst = str(l[3])
        if src and dst in raw_nodes:
            wf_api[dst]["inputs"]["_ui_link_%d" % idx] = [src, l[2]]
    return normalize_workflow(wf_api, source="saved-workflow",
                              title=title or "保存的工作流",
                              created_at=mtime)


def _saved_workflow_snapshot():
    best = None
    try:
        for root, _dirs, files in os.walk(WORKFLOW_DIR):
            for fn in files:
                if not fn.lower().endswith(".json"):
                    continue
                p = os.path.join(root, fn)
                try:
                    m = os.path.getmtime(p)
                except OSError:
                    continue
                if best is None or m > best[0]:
                    best = (m, p)
    except Exception:
        return None
    if not best:
        return None
    mtime, path = best
    with WF_LOCK:
        cached = WF_FILE_CACHE.get("data")
        if (cached and WF_FILE_CACHE.get("path") == path
                and abs(WF_FILE_CACHE.get("mtime", 0) - mtime) < 0.01):
            return cached
    try:
        if os.path.getsize(path) > 4 * 1024 * 1024:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    snap = normalize_ui_workflow(
        data, title=os.path.splitext(os.path.basename(path))[0], mtime=mtime)
    if snap:
        with WF_LOCK:
            WF_FILE_CACHE.update(path=path, mtime=mtime, data=snap)
    return snap


def remember_workflow(wf, title=""):
    """本服务提交成功后留一份，ComfyUI /history 不可用时兜底。"""
    try:
        snap = normalize_workflow(wf, source="last-run", title=title,
                                  created_at=time.time())
        if not snap:
            return
        with WF_LOCK:
            LAST_WORKFLOW.update(t=time.time(), data=snap)
            WF_CACHE.update(t=0.0, data=snap)
    except Exception:
        pass


def _workflow_from_history():
    try:
        hist = http_json("/history?max_items=1", timeout=4)
    except Exception:
        return None
    if not isinstance(hist, dict) or not hist:
        return None
    try:
        pid, entry = list(hist.items())[-1]
    except Exception:
        return None
    if not isinstance(entry, dict):
        return None
    prompt = entry.get("prompt")
    wf = None
    created = 0.0
    if isinstance(prompt, list):
        # ComfyUI 结构：[序号, prompt_id, 工作流, extra_data, 输出节点]
        for idx in (2, 1):
            cand = prompt[idx] if len(prompt) > idx else None
            if isinstance(cand, dict) and any(
                    isinstance(v, dict) and v.get("class_type")
                    for v in cand.values()):
                wf = cand
                break
        if len(prompt) > 3 and isinstance(prompt[3], dict):
            ct = prompt[3].get("create_time")
            if isinstance(ct, (int, float)) and ct > 0:
                created = ct / 1000.0
    elif isinstance(prompt, dict):
        wf = prompt
    if not wf:
        return None
    return normalize_workflow(wf, source="comfyui-history",
                              prompt_id=str(pid), title="ComfyUI 最近执行",
                              created_at=created)


def workflow_snapshot():
    now = time.time()
    with WF_LOCK:
        cached = WF_CACHE.get("data")
        if cached and now - WF_CACHE.get("t", 0) < 2.0:
            d = dict(cached)
            d["ts"] = round(now, 3)
            return d

    candidates = []
    hist = _workflow_from_history()
    if hist:
        candidates.append(hist)
    saved = _saved_workflow_snapshot()
    if saved:
        candidates.append(saved)
    with WF_LOCK:
        last = LAST_WORKFLOW.get("data")
    if last:
        candidates.append(dict(last))

    if candidates:
        # 谁更新用谁：保存的工作流 mtime / ComfyUI 执行时间 / 本服务最近提交
        prio = {"saved-workflow": 3, "comfyui-history": 2, "last-run": 1}
        snap = max(candidates, key=lambda d: (
            d.get("created_at") or 0, prio.get(d.get("source"), 0)))
        snap = dict(snap)
        snap["ts"] = round(now, 3)
    else:
        snap = {"available": False, "source": "none", "ts": round(now, 3),
                "nodes": [], "edges": [], "signature": "",
                "total_nodes": 0, "truncated": False}
    with WF_LOCK:
        WF_CACHE.update(t=now, data=snap)
    return snap


# --------------------------------------------------------------------- 系统负载

LOAD_LOCK = threading.Lock()
LOAD_STATE = {"ts": 0}
LOAD_STARTED = {"v": False}
LOAD_NVSMI = {"path": None}


def _nvidia_smi():
    """找 nvidia-smi；找不到就返回 None（负载页只显示 CPU/内存）。"""
    if LOAD_NVSMI["path"] is None:
        p = shutil.which("nvidia-smi") or ""
        if not p:
            for cand in (
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
            ):
                if os.path.isfile(cand):
                    p = cand
                    break
        LOAD_NVSMI["path"] = p
    return LOAD_NVSMI["path"] or None


def _sample_gpu():
    """一次 nvidia-smi 查询：利用率 / 显存 / 温度 / 功耗。"""
    exe = _nvidia_smi()
    if not exe:
        return {}
    cmd = [exe,
           "--query-gpu=name,utilization.gpu,utilization.memory,"
           "memory.used,memory.total,temperature.gpu,power.draw,power.limit",
           "--format=csv,noheader,nounits"]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        lines = (out.stdout or "").strip().splitlines()
        if not lines:
            return {}
        parts = [p.strip() for p in lines[0].split(",")]
        if len(parts) < 8:
            return {}

        def num(x):
            try:
                return round(float(x), 1)
            except (TypeError, ValueError):
                return None

        return {
            "gpu_name": parts[0],
            "gpu": num(parts[1]),
            "gpu_mem_util": num(parts[2]),
            "vram_used": num(parts[3]),
            "vram_total": num(parts[4]),
            "gpu_temp": num(parts[5]),
            "gpu_power": num(parts[6]),
            "gpu_power_limit": num(parts[7]),
        }
    except Exception:
        return {}


def _load_sampler():
    while True:
        snap = {"ts": round(time.time(), 3)}
        try:
            if psutil:
                cpu = psutil.cpu_percent(interval=1.0)
                vm = psutil.virtual_memory()
                snap["cpu"] = round(cpu, 1)
                snap["ram_used"] = round(vm.used / (1024 * 1024), 1)
                snap["ram_total"] = round(vm.total / (1024 * 1024), 1)
                snap["ram_percent"] = round(vm.percent, 1)
        except Exception:
            pass
        snap.update(_sample_gpu())
        with LOAD_LOCK:
            LOAD_STATE.clear()
            LOAD_STATE.update(snap)
        time.sleep(0.4)


def ensure_load_sampler():
    """第一次请求 /api/load 时才启动采样线程，避免无谓开销。"""
    with LOAD_LOCK:
        if LOAD_STARTED["v"]:
            return
        LOAD_STARTED["v"] = True
    threading.Thread(target=_load_sampler, daemon=True,
                     name="load-sampler").start()


# --------------------------------------------------------- 智能让路（前台高负载）
# 只有网页开着（/api/load 或 /api/guard 在轮询）时才启用。检测到前台程序
# 或整机持续高负载，就临时拒绝新的出图任务；负载降下来自动恢复。
# 自己正在跑的任务不算“占用”，否则一开图就会把自己拦住。
GUARD_LOCK = threading.Lock()
GUARD_STARTED = {"v": False}
GUARD_PRESENCE = {"t": 0.0}
GUARD_TTL = 75.0                 # 网页心跳超过这么久没来，就认为页面已关
GUARD = {"enabled": False, "heavy": False, "reason": "", "since": 0.0,
         "gpu": None, "cpu": None, "fg": "", "fg_cpu": None, "cooldown": 0.0}
GUARD_FG = {"pid": 0, "proc": None, "name": "", "cpu": 0.0}

# 这些前台进程不算“用户在大量占用”：浏览器自己会渲染星图，python 是本服务
# 或 ComfyUI，explorer/dwm 等是系统外壳。
GUARD_BROWSERS = {
    "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe",
    "vivaldi.exe", "chromium.exe", "iexplore.exe",
}
GUARD_IGNORE = GUARD_BROWSERS | {
    "python.exe", "pythonw.exe", "explorer.exe", "dwm.exe",
    "searchhost.exe", "shellexperiencehost.exe", "applicationframehost.exe",
    "systemsettings.exe", "lockapp.exe", "textinputhost.exe",
    "startmenuexperiencehost.exe",
}


def touch_presence():
    """网页每次轮询负载/守卫时调用；页面关掉后 75 秒自动失效。"""
    GUARD_PRESENCE["t"] = time.time()


def _foreground_proc():
    """前台窗口进程名 + CPU%（psutil 单核基准，可超过 100）。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pid = int(pid.value)
        if not pid:
            return ""
        if pid != GUARD_FG["pid"]:
            try:
                proc = psutil.Process(pid) if psutil else None
                if proc:
                    proc.cpu_percent(None)   # 第一次调用只是打点
                GUARD_FG.update(pid=pid, proc=proc,
                                name=(proc.name() if proc else ""), cpu=0.0)
            except Exception:
                GUARD_FG.update(pid=pid, proc=None, name="", cpu=0.0)
            return GUARD_FG["name"]
        proc = GUARD_FG.get("proc")
        if proc is not None:
            try:
                GUARD_FG["cpu"] = round(proc.cpu_percent(None), 1)
            except Exception:
                GUARD_FG["proc"] = None
                GUARD_FG["cpu"] = 0.0
        return GUARD_FG.get("name") or ""
    except Exception:
        return ""


def _own_job_running():
    """本机 GPU 是否在跑任务；远端任务不算，避免误触发“让路”。"""
    if training_manager.M.local_gpu_blocked():
        return True
    with JOBS_LOCK:
        return any(j.get("status") == "running"
                   and (j.get("worker_id") in ("", "local"))
                   for j in JOBS.values())


def guard_snapshot():
    with GUARD_LOCK:
        out = {k: GUARD.get(k) for k in
               ("enabled", "heavy", "reason", "since", "gpu", "cpu", "fg",
                "fg_cpu")}
        out["ttl"] = GUARD_TTL
    return out


def guard_block_message():
    """高负载时返回给前端的拦截文案；否则 None。"""
    with GUARD_LOCK:
        if not GUARD["enabled"] or not GUARD["heavy"]:
            return None
        reason = GUARD.get("reason") or "电脑占用较高"
    return ("检测到你正在大量占用电脑（%s），生图已自动暂停。"
            "占用降下来后会自动恢复，不用手动设置。" % reason)


def _guard_loop():
    hot = cool = 0
    was_running = False
    while True:
        time.sleep(1.0)
        now = time.time()
        if (now - GUARD_PRESENCE["t"]) > GUARD_TTL:
            hot = cool = 0
            was_running = False
            with GUARD_LOCK:
                GUARD.update(enabled=False, heavy=False, reason="", since=0.0,
                             gpu=None, cpu=None, fg="", fg_cpu=None,
                             cooldown=0.0)
            continue

        with LOAD_LOCK:
            snap = dict(LOAD_STATE)
        gpu = snap.get("gpu")
        cpu = snap.get("cpu")
        fg = _foreground_proc()
        fg_cpu = float(GUARD_FG.get("cpu") or 0.0)
        fg_low = fg.lower()
        fg_browser = fg_low in GUARD_BROWSERS
        fg_ignored = (not fg) or (fg_low in GUARD_IGNORE)
        own = _own_job_running()

        if own:
            was_running = True
            hot = 0
        elif was_running:
            # 自己任务刚结束，GPU 还会残留一小段，冷却 10 秒再判断
            was_running = False
            with GUARD_LOCK:
                GUARD["cooldown"] = now + 10.0
        with GUARD_LOCK:
            cooldown = now < GUARD.get("cooldown", 0.0)

        heavy_now = False
        reason = ""
        if not own and not cooldown:
            if gpu is not None and gpu >= 88:
                heavy_now = True
                reason = "GPU 占用 %d%%" % gpu
            elif cpu is not None and cpu >= 70 and not fg_browser:
                # 前台是浏览器时不看整机 CPU：星图自己也吃 CPU，容易误伤
                heavy_now = True
                reason = "CPU 占用 %d%%" % cpu
            elif (not fg_ignored) and fg_cpu >= 150:
                # psutil 的进程 CPU 以单核为 100%，150% ≈ 一个半核
                heavy_now = True
                reason = "前台程序 %s 占用 %.0f%% CPU" % (fg, fg_cpu)

        if heavy_now:
            hot += 1
            cool = 0
        else:
            hot = 0
            cool += 1

        with GUARD_LOCK:
            if hot >= 5 and not GUARD["heavy"]:
                GUARD.update(heavy=True, since=now, reason=reason)
            elif GUARD["heavy"]:
                if not heavy_now and cool >= 6:
                    GUARD.update(heavy=False, reason="", since=0.0)
                elif heavy_now:
                    GUARD["reason"] = reason
            GUARD.update(enabled=True, gpu=gpu, cpu=cpu, fg=fg,
                         fg_cpu=round(fg_cpu, 1))


def ensure_guard():
    with GUARD_LOCK:
        if GUARD_STARTED["v"]:
            return
        GUARD_STARTED["v"] = True
    ensure_load_sampler()
    threading.Thread(target=_guard_loop, daemon=True, name="gen-guard").start()


# --------------------------------------------------------------------- 访问安全

def load_access():
    """读出 access.json 里的 salt / 密码哈希；没有就返回 None。"""
    try:
        with open(ACCESS_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh) or {}
        salt = str(d.get("salt") or "").strip()
        pw = str(d.get("pw_hash") or "").strip()
        if salt and pw:
            return salt, pw
    except Exception:
        pass
    return None


ACCESS = load_access()          # 旧版单密码文件，仅用于迁移管理员账号


# --------------------------------------------------------------------- 多用户
# users.json 是账号的唯一来源；旧 access.json 会在首次启动时迁移成 admin。
USERS = {}
USERS_LOCK = threading.Lock()

# 管理员可以单独开关的功能；“暂时关闭”只影响普通账号。
FEATURE_LABELS = {
    "txt2img": "文生图",
    "img2img": "图生图",
    "inpaint": "局部重绘",
    "video": "视频生成",
    "upscale": "放大",
    "auto": "挂机造图",
    "upload": "上传参考图",
    "gallery": "图库浏览",
    "delete": "删除图片",
    "organize": "拼图 / 导出",
    "translate": "中文翻译",
    # 安全插件包只含 JSON，不执行代码；代码插件提交只进隔离区，
    # 真正安装必须管理员审批。两者默认允许，管理员可以按账号关闭。
    "plugin_pack": "安装安全插件",
    "plugin_submit": "提交代码插件",
    "train": "LoRA 训练",
}
DEFAULT_FEATURES = {k: True for k in FEATURE_LABELS}
# 训练会长时间占用显卡，普通账号默认关闭，由管理员逐个开启。
DEFAULT_FEATURES["train"] = False

GUEST_TTL_SECONDS = 24 * 3600
GUEST_DEFAULT_HOURS = 24


def normalize_translation_mode(value):
    """账号选择的提示词翻译方式：argos（默认）或本地大模型。"""
    return "local" if str(value or "").strip().lower() == "local" else "argos"


def normalize_home(value):
    """账号的默认主页：flat（平面工作台）或 star（沉浸式星图）。

    没设置过 / 新账号一律回落到平面工作台，降低学习门槛。
    """
    v = str(value or "").strip().lower()
    if v in ("star", "universe", "3d", "star_map", "starmap"):
        return "star"
    return "flat"


def _default_limits():
    return {
        "daily_images": 100,
        "max_images": 500,
        "max_storage_mb": 2000,
        "max_upload_mb": 20,
        "max_pixels": 40_000_000,
        "max_steps": 50,
        "max_count": 4,
        "max_concurrent": 1,
        "daily_traffic_mb": 0,
        "monthly_traffic_mb": 0,
        "daily_gpu_seconds": 0,
        "monthly_gpu_seconds": 0,
        "daily_training_jobs": 1,
        "monthly_training_minutes": 180,
        "max_training_minutes": 120,
        "max_train_steps": 2000,
        "max_dataset_images": 50,
        "max_dataset_mb": 1024,
        "max_train_resolution": 1024,
        "features": dict(DEFAULT_FEATURES),
        # 兼容旧字段；新代码优先看 features
        "allow_video": True,
        "allow_upscale": True,
        "allow_auto": True,
        "allowed_models": [],
    }


# 普通账号默认限额；0 表示不限制
USER_DEFAULT_LIMITS = _default_limits()
ADMIN_DEFAULT_LIMITS = dict(
    _default_limits(), daily_images=0, max_images=0, max_storage_mb=0,
    max_steps=0, max_count=0, max_concurrent=0, daily_training_jobs=0,
    monthly_training_minutes=0, max_training_minutes=0, max_train_steps=0,
    max_dataset_images=0, max_dataset_mb=0, max_train_resolution=0)


def _as_int(value, lo, hi, default):
    try:
        n = int(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def normalize_limits(raw, role="user"):
    """把管理员填入的限额收拾成固定字段，防止异常值。"""
    src = raw if isinstance(raw, dict) else {}
    out = dict(ADMIN_DEFAULT_LIMITS if role == "admin"
               else USER_DEFAULT_LIMITS)
    out["features"] = dict(out.get("features") or DEFAULT_FEATURES)
    for key in ("daily_images", "max_images", "max_storage_mb",
                "daily_traffic_mb", "monthly_traffic_mb",
                "daily_gpu_seconds", "monthly_gpu_seconds"):
        if key in src:
            out[key] = _as_int(src.get(key), 0, 100_000_000, out.get(key, 0))
    for key, hi in (("daily_training_jobs", 100),
                    ("monthly_training_minutes", 100_000),
                    ("max_training_minutes", 10_080),
                    ("max_train_steps", 20_000),
                    ("max_dataset_images", 500),
                    ("max_dataset_mb", 50_000)):
        if key in src:
            out[key] = _as_int(src.get(key), 0, hi, out.get(key, 0))
    if "max_train_resolution" in src:
        out["max_train_resolution"] = _as_int(
            src.get("max_train_resolution"), 0, 2048,
            out.get("max_train_resolution", 1024))
    if "max_upload_mb" in src:
        n = _as_int(src.get("max_upload_mb"), 0,
                    UPLOAD_MAX_BYTES // 1048576, out["max_upload_mb"])
        out["max_upload_mb"] = n if n > 0 else out["max_upload_mb"]
    if "max_pixels" in src:
        n = _as_int(src.get("max_pixels"), 0,
                    UPLOAD_MAX_PIXELS, out["max_pixels"])
        out["max_pixels"] = n if n > 0 else out["max_pixels"]
    for key, hi in (("max_steps", 200), ("max_count", 8),
                    ("max_concurrent", 8)):
        if key in src:
            n = _as_int(src.get(key), 0, hi, out[key])
            out[key] = n if n > 0 else out[key]
    feat_src = src.get("features")
    if isinstance(feat_src, dict):
        for key in FEATURE_LABELS:
            if key in feat_src:
                out["features"][key] = bool(feat_src.get(key))
    else:
        # 旧账号没有 features 字段：把原来的 allow_* 迁移过来
        for key in ("video", "upscale", "auto"):
            old = src.get("allow_" + key)
            if old is not None:
                out["features"][key] = bool(old)
    for key in ("allow_video", "allow_upscale", "allow_auto"):
        if key in src:
            out[key] = bool(src.get(key))
    # 新逻辑统一看 features；旧字段保持同步，避免旧前端显示不一致
    out["allow_video"] = bool(out["features"].get("video", True))
    out["allow_upscale"] = bool(out["features"].get("upscale", True))
    out["allow_auto"] = bool(out["features"].get("auto", True))
    models = src.get("allowed_models")
    if isinstance(models, list):
        out["allowed_models"] = [str(x)[:160] for x in models[:50]
                                 if str(x).strip()]
    return out


def guest_limits():
    """游客默认限额：能体验出图/图生图/重绘，不开放视频、放大和挂机。"""
    out = normalize_limits(None, "user")
    out.update({
        "daily_images": 60,
        "max_images": 120,
        "max_storage_mb": 500,
        "max_upload_mb": 10,
        "max_pixels": 20_000_000,
        "max_steps": 40,
        "max_count": 2,
        "max_concurrent": 1,
        "daily_traffic_mb": 300,
        "monthly_traffic_mb": 3000,
    })
    feats = {k: False for k in FEATURE_LABELS}
    for key in ("txt2img", "img2img", "inpaint", "upload", "gallery",
                "translate"):
        feats[key] = True
    out["features"] = feats
    out["allow_video"] = False
    out["allow_upscale"] = False
    out["allow_auto"] = False
    return out


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", str(password or "").encode("utf-8"),
        bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
    return salt, digest


def verify_user_password(user, password):
    if not user:
        return False
    try:
        salt, want = user.get("salt"), user.get("pw_hash")
        if not salt or not want:
            return False
        got = hashlib.pbkdf2_hmac(
            "sha256", str(password or "").encode("utf-8"),
            bytes.fromhex(salt), PBKDF2_ROUNDS).hex()
        return hmac.compare_digest(got, want)
    except Exception:
        return False


def _save_users_locked():
    try:
        # 保留上一份可解析的账号文件；users.json 损坏时还能从 .bak 恢复，
        # 避免磁盘错误导致账号全部丢失或退回默认管理员。
        if os.path.isfile(USERS_FILE):
            try:
                with open(USERS_FILE, "r", encoding="utf-8") as fh:
                    json.load(fh)
                shutil.copy2(USERS_FILE, USERS_FILE + ".bak")
            except Exception:
                pass
        tmp = USERS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "users": USERS}, fh,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, USERS_FILE)
        return True
    except Exception:
        return False


def save_users():
    with USERS_LOCK:
        return _save_users_locked()


def ensure_users():
    """加载 users.json；第一次启动时从 access.json 迁移出 admin。"""
    global USERS
    with USERS_LOCK:
        loaded = None
        for path in (USERS_FILE, USERS_FILE + ".bak"):
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
                users = data.get("users") if isinstance(data, dict) else None
                if isinstance(users, dict):
                    loaded = {str(k): v for k, v in users.items()
                              if isinstance(v, dict)}
                    break
            except Exception:
                continue
        if loaded is not None:
            USERS = loaded
        if USERS:
            # 旧账号补上默认主页；新账号 / 未设置一律平面工作台
            changed = False
            for u in USERS.values():
                if u.get("default_home") not in ("flat", "star"):
                    u["default_home"] = normalize_home(u.get("default_home"))
                    changed = True
                if u.get("translation_mode") not in ("argos", "local"):
                    u["translation_mode"] = "argos"
                    changed = True
                if "guest" not in u:
                    u["guest"] = False
                    changed = True
            # 保证至少有一个管理员；没有就提升第一个账号
            if not any((u.get("role") == "admin" and u.get("enabled", True))
                       for u in USERS.values()):
                first = next(iter(USERS.values()))
                first["role"] = "admin"
                changed = True
            if changed:
                _save_users_locked()
            return USERS
        access = load_access()
        if access:
            salt, pw_hash = access
        else:
            salt, pw_hash = hash_password("admin")
        admin = {
            "id": "admin",
            "username": "admin",
            "name": "管理员",
            "role": "admin",
            "enabled": True,
            "salt": salt,
            "pw_hash": pw_hash,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_login": "",
            "default_home": "flat",
            "translation_mode": "argos",
            "guest": False,
            "limits": dict(ADMIN_DEFAULT_LIMITS),
        }
        USERS = {"admin": admin}
        _save_users_locked()
        if not access:
            if os.environ.get("MGS_ADMIN_PASSWORD"):
                print("  [账号] 已创建初始管理员 admin，安装收尾会设置你输入的密码。")
            else:
                print("  [账号] 已创建初始管理员 admin / admin，请尽快改密码。")
        else:
            print("  [账号] 已把旧访问密码迁移为管理员账号 admin")
        return USERS


def user_expires_at(user):
    try:
        return float((user or {}).get("expires_at") or 0)
    except Exception:
        return 0.0


def user_expired(user, now=None):
    """游客账号到期判断；普通账号没有 expires_at，永远不过期。"""
    if not user or not user.get("guest"):
        return False
    exp = user_expires_at(user)
    return bool(exp and (now or trusted_time.now()) >= exp)


def user_is_active(user, now=None):
    return bool(user and user.get("enabled", True)
                and not user_expired(user, now))


def find_user(username):
    name = str(username or "").strip().lower()
    if not name:
        return None
    with USERS_LOCK:
        for user in USERS.values():
            if str(user.get("username") or "").lower() == name:
                return user
    return None


def get_user(uid):
    with USERS_LOCK:
        return USERS.get(str(uid or ""))


def public_user(user, include_limits=True):
    if not user:
        return None
    out = {
        "id": user.get("id"),
        "username": user.get("username"),
        "name": user.get("name") or user.get("username"),
        "role": user.get("role") or "user",
        "enabled": bool(user.get("enabled", True)),
        "default_home": normalize_home(user.get("default_home")),
        "translation_mode": normalize_translation_mode(
            user.get("translation_mode")),
        "guest": bool(user.get("guest")),
        "expires_at": user_expires_at(user),
        "expires_in": max(0, int(user_expires_at(user) - trusted_time.now()))
        if user.get("guest") and user_expires_at(user) else 0,
        "expired": user_expired(user),
        "created": user.get("created", ""),
        "last_login": user.get("last_login", ""),
    }
    if include_limits:
        out["limits"] = normalize_limits(user.get("limits"),
                                         out["role"])
    return out


def is_admin(user):
    return bool(user and user.get("role") == "admin"
                and user_is_active(user))


def admin_users_payload():
    """管理员用户列表：账号信息 + 用量 + 限额。"""
    with USERS_LOCK:
        users = [dict(u) for u in USERS.values()]
    out = []
    for u in users:
        item = public_user(u)
        usage = user_usage(u.get("id"))
        item["usage"] = usage
        item["usage_mb"] = round(usage.get("bytes", 0) / 1048576, 1)
        out.append(item)
    out.sort(key=lambda x: (x.get("role") != "admin",
                            str(x.get("username") or "").lower()))
    return out


def _active_accounts_locked():
    """调用方必须持有 USERS_LOCK；过期游客不占名额。"""
    return sum(1 for u in USERS.values() if user_is_active(u))


def account_quota():
    """当前版本的启用账号额度；停用/删除/过期游客会释放名额。"""
    p = edition_policy.policy()
    with USERS_LOCK:
        used = _active_accounts_locked()
    maxn = max(0, int(p.get("max_accounts") or 0))
    return {
        "edition": p.get("edition"),
        "label": p.get("label"),
        "label_en": p.get("label_en"),
        "used": used,
        "max": maxn,
        "remaining": max(0, maxn - used),
        "reached": bool(maxn and used >= maxn),
    }


def create_user(username, password, name="", role="user", limits=None):
    username = str(username or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,32}", username):
        raise ValueError("用户名只能 2~32 位字母、数字、点、下划线或短横线")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少 6 位")
    if find_user(username):
        raise ValueError("用户名已经存在")
    role = "admin" if str(role) == "admin" else "user"
    salt, pw_hash = hash_password(password)
    uid = "admin" if (role == "admin" and not USERS) else \
        "u_" + secrets.token_hex(6)
    user = {
        "id": uid,
        "username": username,
        "name": str(name or username).strip()[:32] or username,
        "role": role,
        "enabled": True,
        "salt": salt,
        "pw_hash": pw_hash,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_login": "",
        "default_home": "flat",
        "translation_mode": "argos",
        "guest": False,
        "limits": normalize_limits(limits, role),
    }
    with USERS_LOCK:
        # 并发创建时也必须再查一次用户名和版本额度。
        for existing in USERS.values():
            if str(existing.get("username") or "").lower() == username.lower():
                raise ValueError("用户名已经存在")
        if _active_accounts_locked() >= edition_policy.max_accounts():
            raise ValueError(edition_policy.quota_message("accounts"))
        USERS[uid] = user
        _save_users_locked()
    return user


def update_user(uid, patch):
    uid = str(uid or "")
    disabled = False
    with USERS_LOCK:
        user = USERS.get(uid)
        if not user:
            raise ValueError("账号不存在")
        patch = patch or {}
        if "name" in patch:
            user["name"] = str(patch.get("name") or "").strip()[:32] \
                or user.get("username")
        if patch.get("password"):
            pw = str(patch["password"])
            if len(pw) < 6:
                raise ValueError("密码至少 6 位")
            user["salt"], user["pw_hash"] = hash_password(pw)
        if "role" in patch:
            role = "admin" if patch.get("role") == "admin" else "user"
            if (user.get("role") == "admin" and role != "admin"
                    and sum(1 for u in USERS.values()
                            if u.get("role") == "admin" and u.get("enabled", True)) <= 1):
                raise ValueError("至少要保留一个管理员")
            if (user.get("role") == "admin" and role == "user"
                    and "limits" not in patch):
                # 管理员降级为普通账号时恢复普通默认限额，避免保留“无限”
                user["limits"] = normalize_limits(None, "user")
            user["role"] = role
        if "enabled" in patch:
            enabled = bool(patch.get("enabled"))
            if enabled and not user.get("enabled", True):
                if _active_accounts_locked() >= edition_policy.max_accounts():
                    raise ValueError(edition_policy.quota_message("accounts"))
            user["enabled"] = enabled
            if (user.get("role") == "admin" and not enabled
                    and sum(1 for u in USERS.values()
                            if u.get("role") == "admin" and u.get("enabled", True)) <= 1):
                raise ValueError("至少要保留一个启用的管理员")
            if not enabled:
                disabled = True
        if "limits" in patch:
            user["limits"] = normalize_limits(patch.get("limits"),
                                              user.get("role") or "user")
        if "default_home" in patch:
            user["default_home"] = normalize_home(patch.get("default_home"))
        if "translation_mode" in patch:
            user["translation_mode"] = normalize_translation_mode(
                patch.get("translation_mode"))
        _save_users_locked()
        result = user
    if disabled:
        drop_presence(uid)
        stop_user_jobs(uid, "账号已停用")
        lan_share.pause_owned_workers(uid, by="account_disabled")
    return result


def delete_user(uid):
    uid = str(uid or "")
    with USERS_LOCK:
        user = USERS.get(uid)
        if not user:
            raise ValueError("账号不存在")
        if user.get("role") == "admin" and user.get("enabled", True):
            active_admins = sum(1 for u in USERS.values()
                                if u.get("role") == "admin"
                                and u.get("enabled", True))
            if active_admins <= 1:
                raise ValueError("至少要保留一个管理员")
        USERS.pop(uid, None)
        _save_users_locked()
    drop_user_sessions(uid)
    drop_presence(uid)
    stop_user_jobs(uid, "账号已删除")
    lan_share.pause_owned_workers(uid, by="account_deleted")
    for root in (user_upload_root(uid), user_gallery_root(uid)):
        try:
            if os.path.isdir(root) and not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass
    return user


def reload_users():
    """系统回滚后从磁盘重新载入账号；解析失败时保留当前内存状态。"""
    global USERS
    with USERS_LOCK:
        if not os.path.isfile(USERS_FILE):
            return USERS
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
            users = data.get("users") if isinstance(data, dict) else None
            if not isinstance(users, dict):
                raise ValueError("users.json 格式不对")
        except Exception:
            return USERS
        fresh = {str(k): v for k, v in users.items() if isinstance(v, dict)}
        for u in fresh.values():
            u["default_home"] = normalize_home(u.get("default_home"))
            u["translation_mode"] = normalize_translation_mode(
                u.get("translation_mode"))
            u["guest"] = bool(u.get("guest"))
        if not any(u.get("role") == "admin" and user_is_active(u)
                   for u in fresh.values()):
            first = next(iter(fresh.values()), None)
            if first is not None:
                first["role"] = "admin"
                first["enabled"] = True
        USERS = fresh
        _save_users_locked()
        return USERS


def _random_guest_password(length=10):
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_guest(created_by=None, hours=GUEST_DEFAULT_HOURS):
    """生成一个 24 小时有效的游客账号，返回一次性明文密码。"""
    try:
        hours = max(1, min(168, int(hours or GUEST_DEFAULT_HOURS)))
    except Exception:
        hours = GUEST_DEFAULT_HOURS
    for _ in range(12):
        username = "guest_" + secrets.token_hex(3)
        if not find_user(username):
            break
    else:
        raise ValueError("游客账号生成失败，请重试")
    password = _random_guest_password()
    user = create_user(username, password, name="临时游客",
                       role="user", limits=guest_limits())
    uid = user.get("id")
    expires = trusted_time.now() + hours * 3600
    with USERS_LOCK:
        target = USERS.get(uid)
        if not target:
            raise ValueError("游客账号创建失败")
        target["guest"] = True
        target["expires_at"] = expires
        target["guest_created_by"] = str((created_by or {}).get("id") or "")
        target["guest_created"] = trusted_time.strftime("%Y-%m-%d %H:%M:%S")
        _save_users_locked()
        target = dict(target)
    return {"user": target, "password": password,
            "expires_at": expires, "hours": hours}


def renew_guest(uid, hours=GUEST_DEFAULT_HOURS):
    try:
        hours = max(1, min(168, int(hours or GUEST_DEFAULT_HOURS)))
    except Exception:
        hours = GUEST_DEFAULT_HOURS
    with USERS_LOCK:
        user = USERS.get(str(uid or ""))
        if not user or not user.get("guest"):
            raise ValueError("这个账号不是游客账号")
        if not user_is_active(user):
            if _active_accounts_locked() >= edition_policy.max_accounts():
                raise ValueError(edition_policy.quota_message("accounts"))
        user["expires_at"] = trusted_time.now() + hours * 3600
        user["enabled"] = True
        user.pop("expired_at", None)
        user.pop("guest_expired", None)
        _save_users_locked()
        return dict(user)


def expire_guests(now=None):
    """把到期游客标记为禁用并踢掉会话；保留账号文件和图片归属。"""
    now = now or trusted_time.now()
    expired = []
    with USERS_LOCK:
        changed = False
        for uid, user in USERS.items():
            if (user.get("guest") and user.get("enabled", True)
                    and user_expired(user, now)):
                user["enabled"] = False
                user["guest_expired"] = True
                user["expired_at"] = trusted_time.strftime(
                    "%Y-%m-%d %H:%M:%S", now)
                expired.append((uid, user.get("username") or uid))
                changed = True
        if changed:
            _save_users_locked()
    for uid, username in expired:
        drop_user_sessions(uid)
        drop_presence(uid)
        stop_user_jobs(uid, "游客账号已到期")
        lan_share.pause_owned_workers(uid, by="guest_expired")
        audit("security", "guest_expired", user_id=uid,
              target=username, ok=True)
        audit("activity", "guest_expired", user_id=uid, target=username)
    return expired


_GUEST_SWEEPER = {"started": False}


def _guest_sweeper_loop():
    while True:
        try:
            expire_guests()
        except Exception:
            pass
        time.sleep(60)


def ensure_guest_sweeper():
    if _GUEST_SWEEPER.get("started"):
        return
    _GUEST_SWEEPER["started"] = True
    threading.Thread(target=_guest_sweeper_loop, daemon=True,
                     name="guest-sweeper").start()


def auth_enabled():
    return bool(USERS) or ACCESS is not None


def proxy_auth_enabled():
    """可选的企业反向代理 SSO：只信任本机代理转发的用户名头。"""
    return str(os.environ.get("MGS_TRUSTED_PROXY") or "").lower() in (
        "1", "true", "yes", "on")


def proxy_auth_header():
    name = str(os.environ.get("MGS_PROXY_HEADER") or "X-Remote-User").strip()
    return name or "X-Remote-User"


def proxy_auth_user(header_value, client_ip):
    """仅允许回环地址使用代理认证，避免局域网机器伪造用户名。"""
    if not proxy_auth_enabled():
        return None
    if str(client_ip or "") not in ("127.0.0.1", "::1"):
        return None
    username = str(header_value or "").strip()[:64]
    if not username:
        return None
    user = find_user(username)
    return user if user_is_active(user) else None


def https_enabled():
    return os.path.isfile(CERT_FILE) and os.path.isfile(KEY_FILE)


def certificate_days_left():
    """HTTPS 证书剩余天数；解析失败返回 None。"""
    try:
        from cryptography import x509
        with open(CERT_FILE, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
        expiry = cert.not_valid_after_utc.timestamp()
        return max(0, round((expiry - trusted_time.now()) / 86400, 1))
    except Exception:
        return None


def verify_password(pw):
    """PBKDF2-SHA256 比对，常数时间，防时序侧信道。"""
    if not ACCESS:
        return False
    salt, want = ACCESS
    try:
        got = hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"),
                                  bytes.fromhex(salt), 200_000).hex()
    except Exception:
        return False
    return hmac.compare_digest(got, want)


# 会话：只存 token 的 sha256，磁盘上拿到也反推不出 cookie。
SESSIONS = {}
SESSIONS_LOCK = threading.Lock()
_SESSION_TOUCH = {"at": 0.0}


def _token_key(tok):
    return hashlib.sha256((tok or "").encode("utf-8")).hexdigest()


def load_sessions():
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as fh:
            d = json.load(fh) or {}
    except Exception:
        return
    now = time.time()
    with SESSIONS_LOCK:
        for k, item in d.items():
            if (isinstance(item, dict)
                    and isinstance(item.get("exp"), (int, float))
                    and item["exp"] > now
                    and item.get("uid") in USERS):
                SESSIONS[k] = {
                    "sid": item.get("sid") or secrets.token_hex(8),
                    "exp": item["exp"], "uid": item["uid"],
                    "created": float(item.get("created") or now),
                    "last_seen": float(item.get("last_seen") or now),
                    "ip": str(item.get("ip") or "")[:64],
                    "ua": str(item.get("ua") or "")[:220],
                }


def save_sessions():
    now = time.time()
    with SESSIONS_LOCK:
        valid = [(k, v) for k, v in SESSIONS.items()
                 if isinstance(v, dict) and v.get("exp", 0) > now]
        # 每个账号只保留最近 15 个会话，避免长期登录记录无限膨胀
        valid.sort(key=lambda kv: float(kv[1].get("last_seen") or 0),
                   reverse=True)
        keep = {}
        per_user = {}
        for key, item in valid:
            uid = str(item.get("uid") or "")
            per_user.setdefault(uid, 0)
            if per_user[uid] >= 15:
                continue
            per_user[uid] += 1
            keep[key] = item
        SESSIONS.clear()
        SESSIONS.update(keep)
        data = keep
    try:
        tmp = SESSION_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, SESSION_FILE)
    except Exception:
        pass


def new_session(uid, ip="", ua=""):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with SESSIONS_LOCK:
        SESSIONS[_token_key(tok)] = {
            "sid": secrets.token_hex(8),
            "exp": now + SESSION_TTL,
            "uid": str(uid),
            "created": now,
            "last_seen": now,
            "ip": str(ip or "")[:64],
            "ua": str(ua or "")[:220],
        }
    save_sessions()
    return tok


def drop_session(tok):
    if not tok:
        return
    with SESSIONS_LOCK:
        SESSIONS.pop(_token_key(tok), None)
    save_sessions()


def drop_user_sessions(uid):
    uid = str(uid or "")
    with SESSIONS_LOCK:
        for key in [k for k, v in SESSIONS.items()
                    if isinstance(v, dict) and v.get("uid") == uid]:
            SESSIONS.pop(key, None)
    save_sessions()


def session_user(tok):
    """有效会话返回用户记录；账号被禁用/删除后自动失效。"""
    if not tok:
        return None
    k = _token_key(tok)
    now = time.time()
    touched = False
    with SESSIONS_LOCK:
        item = SESSIONS.get(k)
        if not item:
            return None
        if not isinstance(item, dict) or item.get("exp", 0) < now:
            SESSIONS.pop(k, None)
            return None
        item["last_seen"] = now
        if now - float(_SESSION_TOUCH.get("at") or 0) > 60:
            _SESSION_TOUCH["at"] = now
            touched = True
        uid = item.get("uid")
    user = get_user(uid)
    if not user_is_active(user):
        return None
    if touched:
        save_sessions()
    return user


def session_valid(tok):
    return session_user(tok) is not None


def session_sid(tok):
    if not tok:
        return ""
    with SESSIONS_LOCK:
        item = SESSIONS.get(_token_key(tok)) or {}
    return str(item.get("sid") or "")


def session_info(tok):
    if not tok:
        return {}
    with SESSIONS_LOCK:
        item = dict(SESSIONS.get(_token_key(tok)) or {})
    if not item:
        return {}
    return {"sid": item.get("sid") or "",
            "uid": item.get("uid") or "",
            "created": item.get("created") or 0,
            "last_seen": item.get("last_seen") or 0,
            "ip": item.get("ip") or "",
            "ua": item.get("ua") or ""}


def sessions_for_user(uid):
    uid = str(uid or "")
    now = time.time()
    rows = []
    with SESSIONS_LOCK:
        for key, item in list(SESSIONS.items()):
            if not isinstance(item, dict):
                continue
            if item.get("exp", 0) < now:
                SESSIONS.pop(key, None)
                continue
            if item.get("uid") != uid:
                continue
            rows.append({
                "sid": item.get("sid") or "",
                "created": item.get("created") or 0,
                "last_seen": item.get("last_seen") or 0,
                "ip": item.get("ip") or "",
                "ua": item.get("ua") or "",
            })
    rows.sort(key=lambda x: x.get("last_seen") or 0, reverse=True)
    return rows[:12]


def drop_session_sid(uid, sid, admin=False):
    uid = str(uid or "")
    sid = str(sid or "")
    if not sid:
        return 0
    removed = 0
    with SESSIONS_LOCK:
        for key, item in list(SESSIONS.items()):
            if not isinstance(item, dict) or item.get("sid") != sid:
                continue
            if not admin and item.get("uid") != uid:
                continue
            SESSIONS.pop(key, None)
            removed += 1
    if removed:
        save_sessions()
    return removed


def drop_other_sessions(uid, keep_sid):
    uid = str(uid or "")
    keep_sid = str(keep_sid or "")
    removed = 0
    with SESSIONS_LOCK:
        for key, item in list(SESSIONS.items()):
            if not isinstance(item, dict) or item.get("uid") != uid:
                continue
            if item.get("sid") == keep_sid:
                continue
            SESSIONS.pop(key, None)
            removed += 1
    if removed:
        save_sessions()
    return removed


# 登录失败限速：同一 IP 连错 5 次锁 10 分钟，挡掉暴力猜密码。
LOGIN_FAILS = {}
LOGIN_FAILS_LOCK = threading.Lock()


def login_wait_seconds(ip):
    now = time.time()
    with LOGIN_FAILS_LOCK:
        rec = LOGIN_FAILS.get(ip)
        if rec and rec[2] > now:
            return int(rec[2] - now)
    return 0


def note_login_failure(ip):
    now = time.time()
    with LOGIN_FAILS_LOCK:
        rec = LOGIN_FAILS.get(ip)
        if not rec or now - rec[1] > LOGIN_LOCK_SECONDS:
            LOGIN_FAILS[ip] = [1, now, 0]
            return
        rec[0] += 1
        if rec[0] >= LOGIN_MAX_FAILS:
            rec[2] = now + LOGIN_LOCK_SECONDS
            rec[0] = 0
            rec[1] = now


def note_login_success(ip):
    with LOGIN_FAILS_LOCK:
        LOGIN_FAILS.pop(ip, None)


ensure_users()
load_sessions()
AUTO_LOCK = threading.Lock()

# 风格后缀（中文，会被自动翻译）
STYLES = {
    "水彩": "水彩画风格，湿润的笔触，纸张纹理",
    "油画": "油画，厚涂笔触，画布质感",
    "像素": "像素艺术，8位像素风，复古游戏画面",
    "水墨": "中国水墨画，留白，墨色晕染",
    "吉卜力": "吉卜力动画风格，宫崎骏，柔和色彩",
    "赛博": "赛博朋克，霓虹灯，高科技，暗色调",
    "3D": "3D渲染，皮克斯风格，柔和光照，次表面散射",
    "胶片": "胶片摄影，颗粒感，复古色调，kodak portra",
    "厚涂": "日系厚涂插画，鲜艳色彩，细致光影",
    "线稿": "简洁线稿，黑白，动漫草稿",
    "国漫淡彩": "中国动画风格，淡彩色，低饱和度，柔和光线，干净线条",
    "国漫水墨": "中国动画风格，水墨淡彩，低饱和度，留白，柔和光线，干净线条",
}


# --------------------------------------------------------------------- 工具

def has_chinese(text):
    return any("一" <= ch <= "鿿" for ch in text)


def checkpoint_path(name):
    """底模文件路径；Anima 是独立的 UNET 文件，其余在 checkpoints。"""
    if name == ANIMA_MODEL:
        return os.path.join(UNET_DIR, ANIMA_MODEL)
    return os.path.join(CKPT_DIR, str(name or ""))


def translate_ready():
    """本机 Argos 中文翻译组件是否可用。"""
    try:
        import importlib.util
        return importlib.util.find_spec("argostranslate") is not None
    except Exception:
        return False


def translation_status(user=None):
    """返回 Argos 与本地大模型的状态，以及当前账号选中的方式。"""
    mode = normalize_translation_mode((user or {}).get("translation_mode"))
    cfg = local_llm.load()
    info = local_llm.public_config(cfg)
    argos = translate_ready()
    local_ok = local_llm.available(cfg)
    return {
        "mode": mode,
        "argos_ready": argos,
        "local": info,
        "local_ready": local_ok,
        "ready": bool((mode == "local" and local_ok) or argos),
    }


def translation_ready_for(user=None):
    return bool(translation_status(user).get("ready"))


def translate_text_for_user(text, user=None, mode=None):
    """按账号偏好翻译，本地模型失败时回退 Argos。

    返回 (译文, provider, error)。provider 是 local / argos / none。
    """
    text = (text or "").strip()
    if not text:
        return "", "none", ""
    mode = normalize_translation_mode(
        mode if mode is not None else (user or {}).get("translation_mode"))
    local_error = ""
    if mode == "local" and local_llm.available():
        out, local_error = local_llm.translate(text)
        if out and not has_chinese(out):
            return out, "local", ""
    argos = translate_text(text)
    if argos and not has_chinese(argos):
        return argos, "argos", local_error
    return "", "none", local_error or "翻译失败"


def model_profile(name):
    """识别模型家族并返回推荐参数、风险提示（带缓存）。"""
    return model_profiles.profile_for(
        name, checkpoint_path(name), CKPT_PRESETS.get(name) or {})


def pony_prefix_for(name, text):
    """Pony 系自动补质量标签；用户已经写了 score_9 就不重复加。"""
    p = model_profile(name)
    if p.get("family") == "pony" and "score_9" not in str(text or "").lower():
        return PONY_PREFIX
    return ""


def ckpt_kind(name):
    """判断底模类型：anime / photo / general。"""
    preset = model_profile(name)
    if preset.get("kind"):
        return preset["kind"]
    low = (name or "").lower()
    if "realvis" in low or "realistic" in low or "jugger" in low or "photo" in low:
        return "photo"
    return "anime"


def snap_dim(value, lo=256, hi=1536):
    """把画布尺寸夹到 [lo, hi] 并对齐到 16 的倍数。"""
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        v = lo
    v = max(lo, min(hi, v))
    return max(16, int(round(v / 16.0)) * 16)


def fit_size(width, height, min_side=256, max_side=1536, max_pixels=1500000):
    """规格化画幅：16 像素对齐，并按单边 / 总像素上限等比缩小。

    ComfyUI 的 VAE 下采样要求 8 的倍数；统一用 16 更稳。总像素上限比
    单边上限更贴近显存实际占用，所以两者都查。
    """
    w = snap_dim(width, min_side, max_side)
    h = snap_dim(height, min_side, max_side)
    if max_pixels and max_pixels > 0 and w * h > max_pixels:
        # 这里向下对齐，避免四舍五入后总像素又超回上限。
        for _ in range(3):
            if w * h <= max_pixels:
                break
            k = (float(max_pixels) / float(w * h)) ** 0.5
            w = max(min_side, min(max_side, int(w * k) // 16 * 16))
            h = max(min_side, min(max_side, int(h * k) // 16 * 16))
    return int(w), int(h)


def list_models():
    """扫描 checkpoints 目录，返回可用底模（含推荐步数/CFG）。"""
    names = []
    if os.path.isdir(CKPT_DIR):
        for f in os.listdir(CKPT_DIR):
            if f.lower().endswith((".safetensors", ".ckpt")):
                names.append(f)
    if anima_ready():
        names.append(ANIMA_MODEL)
    order = list(CKPT_PRESETS.keys())
    names.sort(key=lambda n: (order.index(n) if n in order else 99, n))
    out = []
    for n in names:
        p = model_profile(n)
        out.append({
            "name": n,
            "label": p.get("display") or os.path.splitext(n)[0],
            "label_en": p.get("display_en") or p.get("label_en") or "",
            "tip_en": p.get("tip_en") or "",
            "advice_en": p.get("advice_en") or [],
            "warnings_en": p.get("warnings_en") or [],
            "badges_en": p.get("badges_en") or [],
            "steps": p.get("steps", 28),
            "cfg": p.get("cfg", 6.0),
            "kind": p.get("kind") or ckpt_kind(n),
            "family": p.get("family", "unknown"),
            "sampler": p.get("sampler", DEFAULT_SAMPLER),
            "orientation": p.get("orientation", ""),
            "tip": p.get("tip", ""),
            "vpred": p.get("vpred", False),
            "recommended_size": p.get("recommended_size", "832x1216"),
            "sizes": p.get("sizes") or [],
            "max_side": int(p.get("max_side") or 1536),
            "max_pixels": int(p.get("max_pixels") or 1500000),
            "beginner": bool(p.get("beginner")),
            "supported": bool(p.get("supported", True)),
            "badges": p.get("badges") or [],
            "warnings": p.get("warnings") or [],
            "advice": p.get("advice") or [],
            "supports_lora": bool(p.get("supports_lora", True)),
            "supports_pag": bool(p.get("pag", True)),
            "supports_hires": bool(p.get("supports_hires", True)),
            "supports_negative": bool(p.get("supports_negative", True)),
            "profile": p,
        })
    return out


def list_loras(user=None):
    """扫描 loras 目录，按账号过滤训练出来的私有 LoRA。

    只隐藏内部 Anima Turbo LoRA；训练输出的 Anima LoRA 正常显示。
    没有归属元数据的历史 LoRA 继续视为共享；训练文件名在元数据丢失时
    fail-closed，普通账号看不到。
    """
    return training_manager.M.list_visible_loras(user)


def resolve_checkpoint(name):
    """校验前端传来的底模名，非法就退回默认，防止任意文件名注入。"""
    avail = [m["name"] for m in list_models()]
    if name in avail:
        return name
    if DEFAULT_CHECKPOINT in avail:
        return DEFAULT_CHECKPOINT
    return avail[0] if avail else DEFAULT_CHECKPOINT


def video_ready():
    """Wan 的三个文件齐不齐 —— 缺了直接在网页上说清楚，别跑到一半报错。"""
    return all(os.path.isfile(os.path.join(d, f)) for d, f in (
        (UNET_DIR, VIDEO_UNET),
        (TEXT_ENC_DIR, VIDEO_CLIP),
        (VAE_DIR, VIDEO_VAE),
    ))


def i2v_ready():
    """图生视频用的是 VACE 变体，额外多一个 UNet。"""
    return (video_ready()
            and os.path.isfile(os.path.join(UNET_DIR, VIDEO_VACE)))


def anima_ready():
    """Anima 的三个文件齐不齐（UNet / Qwen3 文本编码器 / Qwen-Image VAE）。"""
    return all(os.path.isfile(os.path.join(d, f)) for d, f in (
        (UNET_DIR, ANIMA_MODEL),
        (TEXT_ENC_DIR, ANIMA_CLIP),
        (VAE_DIR, ANIMA_VAE),
    ))


def anima_turbo_ready():
    """官方 Turbo LoRA 在不在（140MB，用来开 8 步极速）。"""
    return (anima_ready()
            and os.path.isfile(os.path.join(LORA_DIR, ANIMA_TURBO_LORA)))


def upscaler_for(ckpt):
    """按底模类型挑放大模型；文件不在就按顺序退回。"""
    have = []
    if os.path.isdir(UPSCALE_DIR):
        have = os.listdir(UPSCALE_DIR)
    if ckpt_kind(ckpt) == "photo":
        order = (UPSCALE_PHOTO_SHARP, UPSCALE_PHOTO, UPSCALE_ANIME)
    else:
        order = (UPSCALE_ANIME, UPSCALE_PHOTO_SHARP, UPSCALE_PHOTO)
    for name in order:
        if name in have:
            return name
    return None


def load_favorites(uid):
    uid = safe_uid(uid) or "admin"
    with FAV_LOCK:
        for path in (user_fav_file(uid),
                     FAV_FILE if uid == "admin" else ""):
            if not path:
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return set(json.load(fh) or [])
            except Exception:
                continue
    return set()


def save_favorites(uid, favs):
    uid = safe_uid(uid) or "admin"
    with FAV_LOCK:
        try:
            path = user_fav_file(uid)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(sorted(favs), fh, ensure_ascii=False)
        except Exception:
            pass


def estimate_seconds(ckpt, steps, count):
    """按历史耗时估算出图时间，用于进度条。"""
    same = [d for d in DURATIONS if d[0] == ckpt]
    if same:
        avg = sum(d[3] for d in same) / len(same)
        ref = same[-1]
        ratio = (steps * count) / max(1, ref[1] * ref[2])
        return max(5.0, avg * ratio)
    all_d = [d[3] for d in DURATIONS]
    if all_d:
        return max(5.0, (sum(all_d) / len(all_d)) * count)
    return 35.0 * count


# ComfyUI HTTP / 工作流构建在 comfy_workflows.py（在文件末尾导入）
# --------------------------------------------------------------------- 任务

def strip_png_meta(path, drop=("prompt", "workflow", "parameters", "comment")):
    """删掉 PNG 里的文本块，不动像素、不重编码。

    ComfyUI 存图时会把整条工作流（含提示词、种子）写进 PNG 的 tEXt 块，
    图片一旦发出去，别人就能原样读出你写了什么。这里只清理交付目录里的
    副本，ComfyUI/output/ 里的原始文件保持不动。
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        out = [data[:8]]
        i, changed = 8, False
        while i + 12 <= len(data):
            length = struct.unpack(">I", data[i:i + 4])[0]
            ctype = data[i + 4:i + 8]
            end = i + 12 + length
            if end > len(data):
                break
            keep = True
            if ctype in (b"tEXt", b"iTXt", b"zTXt"):
                payload = data[i + 8:i + 8 + length]
                key = payload.split(b"\x00", 1)[0].decode("latin-1", "ignore")
                if key.strip().lower() in drop:
                    keep = False
                    changed = True
            if keep:
                out.append(data[i:end])
            i = end
        if not changed:
            return False
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(b"".join(out))
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def cleanup_stage(uid, stage_id):
    """删掉一次任务临时放进 input 的图和隔离区里的上传副本。"""
    if not stage_id:
        return
    prefix = INPUT_STAGE_PREFIX + str(stage_id) + "_"
    try:
        for fn in os.listdir(INPUT_DIR):
            if fn.startswith(prefix):
                try:
                    os.remove(os.path.join(INPUT_DIR, fn))
                except OSError:
                    pass
    except OSError:
        pass
    try:
        root = user_upload_root(uid)
        shutil.rmtree(os.path.join(root, str(stage_id)),
                      ignore_errors=True)
        if root != UPLOAD_DIR and os.path.isdir(root) and not os.listdir(root):
            os.rmdir(root)
    except Exception:
        pass


def cleanup_job_stage(job_id):
    with JOBS_LOCK:
        job = dict(JOBS.get(job_id) or {})
    cleanup_stage(job.get("user_id") or "admin", job.get("stage_id"))


def stop_user_jobs(uid, reason="账号已停用"):
    """禁用/删除账号时，把它正在跑的任务标记掉并清理临时图。"""
    uid = safe_uid(uid)
    if not uid:
        return 0
    try:
        training_manager.M.cancel_user(uid, reason)
    except Exception:
        pass
    jobs = []
    with JOBS_LOCK:
        for jid, job in JOBS.items():
            if (job.get("user_id") != uid
                    or job.get("status") not in ("queued", "running")):
                continue
            job["status"] = "error"
            job["error"] = reason
            jobs.append((jid, job.get("stage_id"),
                         job.get("comfy_prompt_id"),
                         job.get("worker_id") or "local"))
    # 先把该账号还在等待队列里的任务拔掉，再处理正在跑的那个
    scheduler_cancel_user(uid)
    if not jobs:
        return 0
    current = ""
    try:
        current = comfy_current_prompt()
    except Exception:
        current = ""
    for jid, sid, cpid, worker_id in jobs:
        if worker_id not in ("", "local"):
            request_remote_cancel(jid)
            # 远端任务的临时输入由 run_job 的 finally 清
            continue
        if cpid:
            try:
                if not current or cpid == current:
                    http_json("/interrupt", {"prompt_id": cpid}, timeout=15)
                http_json("/queue", {"delete": [cpid]}, timeout=10)
            except Exception:
                pass
        cleanup_stage(uid, sid)
        # 封禁 / 删除账号属于敏感后台操作，不在任何前端做视觉播报
        activity("job", phase="cancel", job_id=jid, user_id=uid,
                 error=reason, silent=True)
    return len(jobs)


def stop_all_jobs(reason="系统维护"):
    """停掉所有账号的排队和运行任务；系统回滚 / 重置前使用。"""
    try:
        training_manager.M.stop_all(reason)
    except Exception:
        pass
    with AUTO_LOCK:
        AUTO["stop"] = True
        AUTO["running"] = False
    with JOBS_LOCK:
        uids = sorted({str(j.get("user_id") or "admin")
                       for j in JOBS.values()
                       if j.get("status") in ("queued", "running")})
    stopped = 0
    for uid in uids:
        try:
            stopped += stop_user_jobs(uid, reason)
        except Exception:
            pass
    with SCHED_LOCK:
        SCHEDULER["queues"].clear()
        for slot in SCHEDULER["slots"].values():
            slot["active"] = ""
        SCHEDULER["active"] = ""
        for ev in SCHEDULER["events"].values():
            try:
                ev.set()
            except Exception:
                pass
        SCHEDULER["events"].clear()
    with JOBS_LOCK:
        for job in JOBS.values():
            if job.get("status") in ("queued", "running"):
                job["status"] = "error"
                job["error"] = reason
                job["finished_at"] = time.time()
    persist_jobs(force=True)
    return stopped


def system_snapshot(label="手动还原点"):
    return system_state.create_snapshot(ROOT, label)


def system_rollback(name):
    """一键回滚配置；图片、模型、证书和日志保持不动。"""
    stop_all_jobs("系统回滚，任务已中断")
    result = system_state.restore_snapshot(ROOT, name)
    reload_users()
    reload_usage()
    reload_jobs_state()
    local_llm.load(force=True)
    lan_share.reload_workers()
    training_manager.M.reload()
    scheduler_kick()
    return result


def system_reset(admin_user):
    """软重置：保留当前管理员和图片，清空其他账号、任务、用量、节点。"""
    admin_user = admin_user or {}
    uid = str(admin_user.get("id") or "")
    if not is_admin(admin_user):
        raise ValueError("只有管理员可以重置系统")
    snap = system_state.create_snapshot(ROOT, "系统重置前自动备份")
    stop_all_jobs("系统重置，任务已中断")
    try:
        training_manager.M.reset_all("系统重置，训练已中断")
    except Exception:
        pass
    with USERS_LOCK:
        current = USERS.get(uid)
        if not current or current.get("role") != "admin":
            raise ValueError("当前管理员账号已不存在")
        fresh = dict(current)
        fresh["enabled"] = True
        fresh["guest"] = False
        fresh.pop("expires_at", None)
        fresh.pop("expired_at", None)
        fresh.pop("guest_expired", None)
        fresh["translation_mode"] = "argos"
        fresh["default_home"] = "flat"
        fresh["limits"] = normalize_limits(None, "admin")
        USERS.clear()
        USERS[uid] = fresh
        _save_users_locked()
        kept = dict(fresh)
    with USAGE_LOCK:
        USAGE.clear()
        USAGE.update({"version": 1, "users": {}})
        USAGE_DIRTY["v"] = True
        _save_usage_locked()
    with JOBS_LOCK:
        JOBS.clear()
    persist_jobs(force=True)
    lan_share.reset_workers()
    try:
        local_llm.save(dict(local_llm.DEFAULT_CONFIG))
    except Exception:
        pass
    try:
        disk_cleanup.save(dict(disk_cleanup.DEFAULT_SETTINGS))
    except Exception:
        pass
    try:
        queue_control.save(dict(queue_control.DEFAULT_SETTINGS))
    except Exception:
        pass
    try:
        teams.save({"version": 1, "teams": {}})
        teams.save_prompts({"version": 1, "teams": {}})
    except Exception:
        pass
    scheduler_kick()
    return {"snapshot": snap, "user": public_user(kept), "workers": 0,
            "users": len(USERS)}


def cleanup_stale_stages(max_age=1800):
    """启动时清掉上次异常退出留下的临时文件（超过 30 分钟）。"""
    now = time.time()
    try:
        for fn in os.listdir(INPUT_DIR):
            if not fn.startswith(INPUT_STAGE_PREFIX):
                continue
            path = os.path.join(INPUT_DIR, fn)
            try:
                if os.path.isfile(path) and now - os.path.getmtime(path) > max_age:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass
    try:
        for name in os.listdir(UPLOAD_DIR):
            if name.startswith("."):
                continue
            path = os.path.join(UPLOAD_DIR, name)
            if not os.path.isdir(path):
                continue
            if name in USERS:
                # 用户根目录：只清里面的任务临时目录，_legacy 保留
                try:
                    for stage in os.listdir(path):
                        if stage == "_legacy":
                            continue
                        stage_path = os.path.join(path, stage)
                        if (os.path.isdir(stage_path)
                                and now - os.path.getmtime(stage_path) > max_age):
                            shutil.rmtree(stage_path, ignore_errors=True)
                except OSError:
                    pass
            elif re.fullmatch(r"[0-9a-f]{6,32}", name):
                # 迁移前留在顶层的旧任务目录
                try:
                    if now - os.path.getmtime(path) > max_age:
                        shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


def migrate_legacy_inputs(max_age=1800):
    """把旧版网页直接丢在 ComfyUI/input 里的 ref_/mask_/up_ 文件移出并保留。"""
    legacy = os.path.join(user_upload_root("admin"), "_legacy")
    marker = os.path.join(legacy, ".migrated")
    if os.path.isfile(marker):
        return 0
    moved = 0
    skipped = 0
    try:
        os.makedirs(legacy, exist_ok=True)
        now = time.time()
        for fn in os.listdir(INPUT_DIR):
            if not re.match(r"^(ref|mask|up)_[0-9A-Za-z]+\.(png|jpg|jpeg|webp)$",
                            fn, re.I):
                continue
            src = os.path.join(INPUT_DIR, fn)
            if not os.path.isfile(src):
                continue
            if now - os.path.getmtime(src) <= max_age:
                skipped += 1
                continue
            try:
                dst = os.path.join(legacy, fn)
                if os.path.exists(dst):
                    stem, ext = os.path.splitext(fn)
                    dst = os.path.join(legacy, "%s_%s%s" % (stem, uuid.uuid4().hex[:6], ext))
                shutil.move(src, dst)
                moved += 1
            except OSError:
                skipped += 1
        # 还有没搬完的就先不写标记，下次启动再试
        if skipped == 0:
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"moved": moved,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, ensure_ascii=False)
    except Exception:
        return moved
    if moved:
        print("  [隔离] 已把 %d 张旧网页上传图移到 web_uploads\\admin\\_legacy\\" % moved)
    return moved


def _stage_to_input(stage_id, src, prefix):
    """把隔离区里的图临时复制进 ComfyUI/input，任务结束会删掉。"""
    os.makedirs(INPUT_DIR, exist_ok=True)
    ext = os.path.splitext(str(src))[1].lower()
    if ext not in IMAGE_EXT:
        ext = ".png"
    fname = "%s%s_%s%s" % (INPUT_STAGE_PREFIX, stage_id, prefix, ext)
    shutil.copy2(src, os.path.join(INPUT_DIR, fname))
    return fname


# =====================================================================
# 局域网算力共享：多槽位调度 + 远端任务状态
# =====================================================================
# 旧单槽位调度器保留在文件前部用于兼容；这里定义同名函数，模块加载后
# 以本段实现为准。SCHEDULER 数据也在启动时重置为槽位结构。

LOCAL_ALIVE = {"t": 0.0, "v": True}
REMOTE_SPOOL_DIR = os.path.join(ROOT, "remote_spool")
REMOTE_LOCK = threading.RLock()
REMOTE_JOBS = {}
WORKER_EVENTS = {}

SCHEDULER.clear()
SCHEDULER.update({
    "slots": {
        "local": {
            "id": "local", "kind": "local", "name": "本机",
            "active": "", "available": True, "last_used": 0, "policy": {},
        },
    },
    "queues": {},
    "last_served": {},
    "served_cost": {},
    "serve_seq": 0,
    "events": {},
    "seq": 0,
    "active": "",
})


def local_comfy_alive(force=False):
    """本机 ComfyUI 是否可用；缓存 5 秒，避免调度时反复探测。"""
    now = time.time()
    if not force and now - LOCAL_ALIVE["t"] < 5:
        return bool(LOCAL_ALIVE["v"])
    ok = False
    try:
        http_json("/system_stats", timeout=2)
        ok = True
    except Exception:
        ok = False
    LOCAL_ALIVE["t"] = now
    LOCAL_ALIVE["v"] = ok
    return ok


def _worker_policy(w):
    return {
        "id": w.get("id") or "",
        "name": w.get("name") or w.get("id") or "",
        "owner_id": w.get("owner_id") or "admin",
        "trusted": bool(w.get("trusted")),
        "allowed_users": tuple(w.get("allowed_users") or ()),
        "models": w.get("models") or {},
        "caps": w.get("caps") or {},
        "online": bool(w.get("online")),
        "accepting": bool(w.get("accepting")),
    }


def _sched_refresh_slots_locked(local_ok=None):
    settings = lan_share.settings()
    if local_ok is None:
        local_ok = LOCAL_ALIVE["v"]
    local = SCHEDULER["slots"].setdefault("local", {
        "id": "local", "kind": "local", "name": "本机",
        "active": "", "available": True, "last_used": 0, "policy": {},
    })
    local["kind"] = "local"
    local["name"] = "本机"
    local["available"] = bool(
        settings.get("local_enabled", True) and local_ok
        and not training_manager.M.local_gpu_blocked())
    snap = {w.get("id"): w for w in lan_share.scheduler_workers()
            if w.get("id")}
    for sid in list(SCHEDULER["slots"].keys()):
        if sid == "local":
            continue
        slot = SCHEDULER["slots"][sid]
        if sid not in snap and not slot.get("active"):
            SCHEDULER["slots"].pop(sid, None)
    for sid, w in snap.items():
        slot = SCHEDULER["slots"].setdefault(sid, {
            "id": sid, "kind": "remote", "name": w.get("name") or sid,
            "active": "", "available": False, "last_used": 0, "policy": {},
        })
        slot["kind"] = "remote"
        slot["name"] = w.get("name") or sid
        slot["policy"] = _worker_policy(w)
        slot["available"] = bool(settings.get("remote_enabled", False)
                                 and w.get("accepting"))


def _sched_update_active_locked():
    local = (SCHEDULER["slots"].get("local") or {}).get("active") or ""
    if local and (JOBS.get(local) or {}).get("status") == "running":
        SCHEDULER["active"] = local
        return
    for sid, slot in SCHEDULER["slots"].items():
        jid = slot.get("active") or ""
        if jid and (JOBS.get(jid) or {}).get("status") == "running":
            SCHEDULER["active"] = jid
            return
    SCHEDULER["active"] = ""


def _sched_user_active_locked(uid):
    n = 0
    for slot in SCHEDULER["slots"].values():
        jid = slot.get("active") or ""
        if jid:
            job = JOBS.get(jid) or {}
            if job.get("user_id") == uid and job.get("status") == "running":
                n += 1
    return n


def _models_have(models, requirements):
    models = models or {}
    aliases = {
        "diffusion_models": ("diffusion_models", "unet"),
        "text_encoders": ("text_encoders", "clip"),
    }
    for req in requirements or []:
        folder = str(req.get("folder") or "")
        name = str(req.get("name") or "").replace("\\", "/").casefold()
        if not folder or not name:
            continue
        values = []
        for f in aliases.get(folder, (folder,)):
            values.extend(models.get(f) or [])
        if name not in {str(v).replace("\\", "/").casefold() for v in values}:
            return False
    return True


def _worker_policy_can_run(policy, job):
    if not policy or not policy.get("accepting"):
        return False
    if not job.get("remote_ok") or job.get("kind") != "gen":
        return False
    excluded = job.get("exclude_workers") or []
    if (policy.get("id") in excluded
            or job.get("worker_id") in excluded):
        return False
    uid = job.get("user_id") or "admin"
    user = get_user(uid) or {}
    if is_admin(user):
        pass
    elif policy.get("owner_id") == uid:
        pass
    else:
        if not policy.get("trusted"):
            return False
        allowed = policy.get("allowed_users") or ()
        if not allowed or uid not in allowed:
            return False
    if not _models_have(policy.get("models") or {},
                        job.get("requirements") or []):
        return False
    caps = policy.get("caps") or {}
    try:
        max_pixels = int(caps.get("max_pixels") or 0)
        if max_pixels and int(job.get("pixels") or 0) > max_pixels:
            return False
        max_count = int(caps.get("max_count") or 4)
        if int(job.get("count") or 1) > max_count:
            return False
    except Exception:
        pass
    return True


def _remote_retry_available(job, failed_slot):
    """失败后是否还有别的执行器。允许忙的本机/节点排队等待。"""
    settings = lan_share.settings()
    if settings.get("local_enabled", True) and local_comfy_alive():
        return True
    if not settings.get("remote_enabled"):
        return False
    probe = dict(job)
    probe["worker_id"] = ""
    excluded = list(probe.get("exclude_workers") or [])
    if failed_slot and failed_slot not in excluded:
        excluded.append(failed_slot)
    probe["exclude_workers"] = excluded
    for w in lan_share.scheduler_workers():
        if (w.get("id") == failed_slot or not w.get("online")
                or w.get("paused")):
            continue
        policy = _worker_policy(w)
        policy["accepting"] = True
        if _worker_policy_can_run(policy, probe):
            return True
    return False


def _sched_slot_can_run_locked(slot, job):
    if not slot or slot.get("active") or not slot.get("available"):
        return False
    if slot.get("kind") == "local":
        return True
    return _worker_policy_can_run(slot.get("policy") or {}, job)


def _sched_clean_queues_locked():
    for uid in list(SCHEDULER["queues"].keys()):
        q = SCHEDULER["queues"].get(uid)
        if q is None:
            continue
        while q:
            job = JOBS.get(q[0]) or {}
            if job.get("status") == "queued":
                break
            jid = q.popleft()
            ev = SCHEDULER["events"].get(jid)
            if ev:
                ev.set()
        if not q:
            SCHEDULER["queues"].pop(uid, None)


def _sched_job_cost(job):
    """任务的预计 GPU 秒数；用于按成本加权，而不是按任务个数。"""
    try:
        return max(5.0, float(job.get("eta") or 60.0))
    except Exception:
        return 60.0


def _sched_job_priority(job, uid, now=None):
    """交互任务优先；挂机任务靠后，但等待越久优先级越高，避免饿死。"""
    now = now or time.time()
    try:
        base = int(job.get("priority",
                           10 if job.get("kind") != "auto" else 0))
    except Exception:
        base = 10
    boost = queue_control.user_boost(uid)
    waited = max(0.0, now - float(job.get("queued_at") or now))
    aging = min(3.0, waited / 300.0)
    return base + boost + aging


def _sched_norm_cost_locked():
    """累计成本太大时整体下移，避免数字无限增长。"""
    costs = SCHEDULER.setdefault("served_cost", {})
    if not costs:
        return
    low = min(costs.values())
    if low > 1000000:
        for uid in list(costs):
            costs[uid] -= low


def _sched_pick_candidate_locked(free_slots):
    best = None
    _sched_clean_queues_locked()
    for uid, q in list(SCHEDULER["queues"].items()):
        if not q:
            SCHEDULER["queues"].pop(uid, None)
            continue
        if queue_control.user_paused(uid):
            continue
        jid = q[0]
        job = JOBS.get(jid) or {}
        if job.get("status") != "queued":
            continue
        # 同一账号的运行中任务不能超过 max_concurrent；排队中的任务可以继续等。
        if _sched_user_active_locked(uid) >= _sched_user_cap(uid):
            continue
        eligible = [s for s in free_slots if _sched_slot_can_run_locked(s, job)]
        if not eligible:
            continue
        key = (-_sched_job_priority(job, uid),
               SCHEDULER.get("served_cost", {}).get(uid, 0.0),
               job.get("queue_seq") or 0)
        if best is None or key < best[0]:
            best = (key, uid, jid, eligible)
    return best


def _sched_order_locked():
    """按加权公平规则预测派发顺序：优先级 → 累计成本 → 提交顺序。"""
    tmp = {uid: deque(q) for uid, q in SCHEDULER["queues"].items()}
    costs = dict(SCHEDULER.get("served_cost") or {})
    now = time.time()
    out = []
    while True:
        best_uid = None
        best_key = None
        for uid, q in list(tmp.items()):
            if not q:
                tmp.pop(uid, None)
                continue
            if queue_control.user_paused(uid):
                continue
            job = JOBS.get(q[0]) or {}
            key = (-_sched_job_priority(job, uid, now),
                   costs.get(uid, 0.0),
                   job.get("queue_seq") or 0)
            if best_key is None or key < best_key:
                best_key = key
                best_uid = uid
        if best_uid is None:
            break
        jid = tmp[best_uid].popleft()
        job = JOBS.get(jid) or {}
        costs[best_uid] = costs.get(best_uid, 0.0) + _sched_job_cost(job)
        out.append(jid)
        if not tmp[best_uid]:
            tmp.pop(best_uid, None)
    return out


def _sched_choose_slot_locked(eligible):
    for slot in eligible:
        if slot.get("kind") == "local":
            return slot
    return min(eligible, key=lambda s: (s.get("last_used") or 0,
                                        s.get("id") or ""))


def _sched_dispatch_locked(local_ok=None):
    _sched_refresh_slots_locked(local_ok)
    _sched_clean_queues_locked()
    if queue_control.dispatch_blocked():
        _sched_update_active_locked()
        return
    while True:
        free_slots = [s for s in SCHEDULER["slots"].values()
                      if not s.get("active") and s.get("available")]
        if not free_slots:
            break
        cand = _sched_pick_candidate_locked(free_slots)
        if not cand:
            break
        _key, uid, jid, eligible = cand
        q = SCHEDULER["queues"].get(uid)
        if not q or q[0] != jid:
            continue
        q.popleft()
        if not q:
            SCHEDULER["queues"].pop(uid, None)
        slot = _sched_choose_slot_locked(eligible)
        SCHEDULER["serve_seq"] += 1
        seq = SCHEDULER["serve_seq"]
        SCHEDULER["last_served"][uid] = seq
        now = time.time()
        job = JOBS.get(jid) or {}
        costs = SCHEDULER.setdefault("served_cost", {})
        costs[uid] = costs.get(uid, 0.0) + _sched_job_cost(job)
        _sched_norm_cost_locked()
        job["status"] = "running"
        job["started"] = now
        job["dispatched_at"] = now
        job["elapsed"] = 0
        job["worker_id"] = slot.get("id") or "local"
        job["worker_name"] = slot.get("name") or "本机"
        job["worker_kind"] = slot.get("kind") or "local"
        job["attempt"] = int(job.get("attempt") or 0)
        if slot.get("kind") == "remote":
            job["attempt"] += 1
            job["dispatch_state"] = "assigned"
        else:
            job["dispatch_state"] = "local"
        slot["active"] = jid
        slot["last_used"] = seq
        _sched_update_active_locked()
        if slot.get("kind") == "remote":
            ev = WORKER_EVENTS.setdefault(slot.get("id"), threading.Event())
            ev.set()
        payload = job_activity_fields(job)
        payload["job_id"] = jid
        payload["worker_name"] = job.get("worker_name")
        payload["worker_kind"] = job.get("worker_kind")
        payload["queue_position"] = 0
        payload["queue_size"] = _sched_pending_locked()
        activity("job", phase="start", **payload)
        try:
            monitor_center.notify_job("start", dict(job, job_id=jid))
        except Exception:
            pass
        ev = SCHEDULER["events"].get(jid)
        if ev:
            ev.set()
    _sched_update_active_locked()


def _sched_slot_eligible_locked(slot, job):
    """预测用：忽略槽位当前忙闲，只看模型/权限是否匹配。"""
    if not slot or not slot.get("available"):
        return False
    if slot.get("kind") == "local":
        return True
    policy = dict(slot.get("policy") or {})
    policy["accepting"] = True
    return _worker_policy_can_run(policy, job)


def _sched_simulate_locked(jid):
    """模拟把队列里的任务依次放到最早可用的槽位，估算开始/完成时间。"""
    job = JOBS.get(jid) or {}
    slots = [s for s in SCHEDULER["slots"].values() if s.get("available")]
    if not slots:
        return None
    now = time.time()
    free_at = {}
    user_finish = {}
    for slot in slots:
        remain = 0.0
        active = JOBS.get(slot.get("active") or "") or {}
        if active and active.get("status") == "running":
            remain = max(0.0, _sched_job_cost(active)
                         - float(active.get("elapsed") or 0))
        free_at[slot.get("id")] = now + remain
        if active and active.get("status") == "running":
            uid = active.get("user_id") or "admin"
            user_finish.setdefault(uid, []).append(now + remain)

    def user_ready(uid):
        """同一账号并发已满时，要等最早一个任务结束。"""
        arr = [t for t in user_finish.get(uid, []) if t > now]
        user_finish[uid] = arr
        cap = _sched_user_cap(uid)
        if cap > 0 and len(arr) >= cap:
            return min(arr)
        return now

    for ahead_jid in _sched_order_locked():
        ahead = JOBS.get(ahead_jid) or {}
        uid = ahead.get("user_id") or "admin"
        ready = user_ready(uid)
        eligible = [s for s in slots if _sched_slot_eligible_locked(s, ahead)]
        if not eligible:
            continue
        slot = min(eligible, key=lambda s: (max(free_at.get(s.get("id"), now),
                                                ready),
                                            s.get("kind") != "local",
                                            s.get("id") or ""))
        start = max(free_at.get(slot.get("id"), now), ready)
        if ahead_jid == jid:
            return {"start_in": max(0.0, start - now),
                    "finish_in": max(0.0, start - now) + _sched_job_cost(job),
                    "slot_id": slot.get("id") or "",
                    "slot_name": slot.get("name") or ""}
        finish = start + _sched_job_cost(ahead)
        free_at[slot.get("id")] = finish
        user_finish.setdefault(uid, []).append(finish)
    return None


def _sched_info_locked(jid):
    job = JOBS.get(jid) or {}
    pending = _sched_pending_locked()
    empty = {"queue_position": 0, "queue_size": pending, "queue_eta": 0,
             "queue_eta_min": 0, "queue_eta_max": 0,
             "queue_start_in": 0, "queue_finish_in": 0,
             "queue_state": "", "queue_reason": "", "queue_slot": ""}
    if not job:
        return empty
    for slot in SCHEDULER["slots"].values():
        if slot.get("active") == jid:
            remain = max(0.0, _sched_job_cost(job)
                         - float(job.get("elapsed") or 0))
            return {"queue_position": 0, "queue_size": pending,
                    "queue_eta": 0, "queue_eta_min": 0, "queue_eta_max": 0,
                    "queue_start_in": 0, "queue_finish_in": round(remain, 1),
                    "queue_state": "running", "queue_reason": "",
                    "queue_slot": slot.get("name") or ""}
    if job.get("status") != "queued":
        out = dict(empty)
        out["queue_state"] = job.get("status") or ""
        return out
    uid = job.get("user_id") or "admin"
    state = "queued"
    reason = ""
    if queue_control.user_paused(uid):
        state = "user_paused"
        reason = "管理员暂停了这个账号的队列"
    elif queue_control.dispatch_blocked():
        if queue_control.maintenance_active():
            state = "maintenance"
            reason = "处于维护窗口，任务会保留到窗口结束"
        else:
            state = "paused"
            reason = (queue_control.load().get("pause_reason")
                      or "管理员暂停了新的出图任务")
    order = _sched_order_locked()
    try:
        idx = order.index(jid)
    except ValueError:
        idx = -1
    sim = _sched_simulate_locked(jid) if idx >= 0 else None
    if state == "queued" and sim is None:
        state = "waiting_executor"
        reason = "等待可用的模型或算力节点"
    start_in = float(sim.get("start_in") or 0) if sim else 0.0
    finish_in = float(sim.get("finish_in") or 0) if sim else 0.0
    if state != "queued":
        start_in = 0.0
        finish_in = 0.0
    eta_min = max(0.0, start_in * 0.8)
    eta_max = (start_in * 1.5 + 15.0) if start_in else 0.0
    return {"queue_position": (idx + 1) if idx >= 0 else 0,
            "queue_size": len(order) if order else pending,
            "queue_eta": round(start_in, 1),
            "queue_eta_min": round(eta_min, 1),
            "queue_eta_max": round(eta_max, 1),
            "queue_start_in": round(start_in, 1),
            "queue_finish_in": round(finish_in, 1),
            "queue_state": state,
            "queue_reason": reason,
            "queue_slot": (sim or {}).get("slot_name") or ""}


def scheduler_job_info(jid):
    with SCHED_LOCK:
        _sched_clean_queues_locked()
        return _sched_info_locked(jid)


def scheduler_active_count(uid):
    with SCHED_LOCK:
        _sched_clean_queues_locked()
        return (_sched_user_pending_locked(uid)
                + _sched_user_active_locked(uid))


def scheduler_kick():
    if queue_control.dispatch_blocked():
        return
    local_ok = local_comfy_alive()
    with SCHED_LOCK:
        _sched_dispatch_locked(local_ok=local_ok)


_QUEUE_WATCHDOG = {"started": False}
_QUEUE_WATCHDOG_LOCK = threading.Lock()


def close_queued_job(jid, status, message):
    """把仍在排队的任务直接收尾（失败/取消）；不碰正在运行的任务。"""
    status = status if status in ("error", "cancelled", "done") else "error"
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if not job or job.get("status") != "queued":
            return False
        job["status"] = status
        job["error"] = str(message or "")[:200] if status != "done" else ""
        job["finished_at"] = time.time()
        job["dispatch_state"] = status
        snapshot = dict(job)
    persist_jobs(force=True)
    try:
        monitor_center.note_job(dict(snapshot, job_id=jid))
    except Exception:
        pass
    phase = "cancel" if status == "cancelled" else (
        "done" if status == "done" else "error")
    payload = job_activity_fields(snapshot)
    payload["job_id"] = jid
    payload["error"] = snapshot.get("error") or ""
    activity("job", phase=phase, **payload)
    audit("activity", "job_" + phase,
          user_id=snapshot.get("user_id") or "admin",
          job_id=jid, kind=snapshot.get("kind"), mode=snapshot.get("mode"),
          model=snapshot.get("model"), error=snapshot.get("error") or "")
    try:
        monitor_center.notify_job(
            "error" if status == "error" else
            "done" if status == "done" else "cancelled",
            dict(snapshot, job_id=jid))
    except Exception:
        pass
    try:
        cleanup_stage(snapshot.get("user_id") or "admin",
                      snapshot.get("stage_id"))
    except Exception:
        pass
    return True


def fail_queued_job(jid, error):
    return close_queued_job(jid, "error", error)


def cancel_queued_job(jid, reason="管理员取消排队任务"):
    return close_queued_job(jid, "cancelled", reason)


def queue_watchdog_tick():
    """定期重试派发，并处理排队超时；暂停/维护期间不计算超时。"""
    control = queue_control.load()
    try:
        max_wait = int(control.get("max_wait_seconds") or 0)
    except Exception:
        max_wait = 0
    now = time.time()
    expired = []
    with SCHED_LOCK:
        _sched_clean_queues_locked()
        if max_wait > 0 and not queue_control.dispatch_blocked():
            for uid in list(SCHEDULER["queues"].keys()):
                if queue_control.user_paused(uid):
                    continue
                q = SCHEDULER["queues"].get(uid)
                if not q:
                    continue
                keep = deque()
                for jid in q:
                    job = JOBS.get(jid) or {}
                    waited = now - float(job.get("queued_at") or now)
                    if (job.get("status") == "queued"
                            and waited > max_wait):
                        expired.append(jid)
                        ev = SCHEDULER["events"].pop(jid, None)
                        if ev:
                            ev.set()
                    else:
                        keep.append(jid)
                if keep:
                    SCHEDULER["queues"][uid] = keep
                else:
                    SCHEDULER["queues"].pop(uid, None)
    for jid in expired:
        fail_queued_job(jid, "排队超时（超过 %d 分钟）"
                        % max(1, max_wait // 60))
    scheduler_kick()


def _queue_watchdog_loop():
    while True:
        try:
            queue_watchdog_tick()
        except Exception as exc:
            print("[queue] watchdog error: %s" % exc)
        time.sleep(5)


def ensure_queue_watchdog():
    with _QUEUE_WATCHDOG_LOCK:
        if _QUEUE_WATCHDOG["started"]:
            return
        _QUEUE_WATCHDOG["started"] = True
    threading.Thread(target=_queue_watchdog_loop, daemon=True,
                     name="queue-watchdog").start()


def scheduler_enqueue(jid):
    """把任务放进公平队列；返回 None 表示成功，否则返回中文拦截原因。"""
    with SCHED_LOCK:
        job = JOBS.get(jid) or {}
        if not job:
            return "任务不存在"
        uid = job.get("user_id") or "admin"
        if _sched_pending_locked() >= SCHED_MAX_QUEUE:
            return ("排队任务太多了（最多 %d 个），等前面的跑完再提交。"
                    % SCHED_MAX_QUEUE)
        cap = _sched_user_cap(uid)
        active_n = (_sched_user_pending_locked(uid)
                    + _sched_user_active_locked(uid))
        if active_n >= cap:
            return ("你已经有 %d 个任务在排队或运行，等完成再提交。"
                    % active_n)
        SCHEDULER["seq"] += 1
        job["status"] = "queued"
        job["queued_at"] = time.time()
        job["queue_seq"] = SCHEDULER["seq"]
        job.setdefault("priority", 10)
        job["worker_id"] = ""
        job["worker_name"] = ""
        SCHEDULER["queues"].setdefault(uid, deque()).append(jid)
        SCHEDULER["events"][jid] = threading.Event()
        info = _sched_info_locked(jid)
        payload = job_activity_fields(job)
        u = get_user(uid) or {}
        payload.setdefault("user_id", uid)
        payload.setdefault("username", u.get("username") or job.get("username") or "")
        payload.setdefault("user_name", u.get("name") or job.get("user_name") or "")
        payload.update({"job_id": jid,
                        "queue_position": info["queue_position"],
                        "queue_size": info["queue_size"],
                        "queue_eta": info["queue_eta"]})
        activity("job", phase="queued", **payload)
        _sched_dispatch_locked(local_ok=LOCAL_ALIVE["v"])
        persist_jobs(force=True)
        return None


def scheduler_wait(jid, timeout=86400):
    """等轮到自己；返回槽位 id（local / w_...），失败返回空串。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with SCHED_LOCK:
            job = JOBS.get(jid) or {}
            status = job.get("status")
            if status == "running" and job.get("worker_id"):
                return str(job.get("worker_id"))
            if status not in ("queued", "running"):
                return ""
            ev = SCHEDULER["events"].get(jid)
        if ev is None:
            with SCHED_LOCK:
                job = JOBS.get(jid) or {}
                if job.get("status") == "running" and job.get("worker_id"):
                    return str(job.get("worker_id"))
            return ""
        ev.wait(0.5)
    return ""


def scheduler_cancel_job(jid):
    with SCHED_LOCK:
        for uid in list(SCHEDULER["queues"].keys()):
            q = SCHEDULER["queues"].get(uid)
            if q and jid in q:
                try:
                    q.remove(jid)
                except ValueError:
                    pass
                if not q:
                    SCHEDULER["queues"].pop(uid, None)
        ev = SCHEDULER["events"].get(jid)
        if ev:
            ev.set()
        _sched_clean_queues_locked()


def scheduler_cancel_user(uid):
    with SCHED_LOCK:
        q = SCHEDULER["queues"].get(uid)
        jids = list(q or ())
        if q:
            q.clear()
            SCHEDULER["queues"].pop(uid, None)
        for jid in jids:
            ev = SCHEDULER["events"].get(jid)
            if ev:
                ev.set()
        _sched_clean_queues_locked()
        return jids


def scheduler_release(jid):
    with SCHED_LOCK:
        for slot in SCHEDULER["slots"].values():
            if slot.get("active") == jid:
                slot["active"] = ""
        _sched_update_active_locked()
        SCHEDULER["events"].pop(jid, None)
        _sched_dispatch_locked()
        persist_jobs(force=True)


def scheduler_snapshot(user=None):
    """队列概况；普通账号只看到自己的任务，管理员看全部。

    队列里包含 user_id / username / 模型等元数据，不能把其他账号的任务
    暴露给普通用户。
    """
    admin = user is None or is_admin(user)
    uid = (user or {}).get("id") or ""

    def visible(job):
        return bool(admin or job.get("user_id") == uid)

    with SCHED_LOCK:
        _sched_clean_queues_locked()
        active_job = JOBS.get(SCHEDULER["active"]) or {}
        active = {"job_id": SCHEDULER["active"]} if (
            SCHEDULER["active"] and visible(active_job)) else None
        if active:
            active.update(job_activity_fields(active_job))
            active["elapsed"] = active_job.get("elapsed", 0)
            active["worker_name"] = active_job.get("worker_name") or ""
            active["worker_kind"] = active_job.get("worker_kind") or ""
        running = []
        for slot in SCHEDULER["slots"].values():
            jid = slot.get("active") or ""
            if not jid:
                continue
            job = JOBS.get(jid) or {}
            if not visible(job):
                continue
            item = {"job_id": jid, "worker_id": slot.get("id"),
                    "worker_name": slot.get("name") or "",
                    "worker_kind": slot.get("kind") or ""}
            item.update(job_activity_fields(job))
            item["elapsed"] = job.get("elapsed", 0)
            running.append(item)
        waiting = []
        for jid in _sched_order_locked():
            job = JOBS.get(jid) or {}
            if not visible(job):
                continue
            item = {"job_id": jid}
            item.update(job_activity_fields(job))
            item.update(_sched_info_locked(jid))
            waiting.append(item)
        slots = [{
            "id": s.get("id"), "name": s.get("name"), "kind": s.get("kind"),
            "available": bool(s.get("available")),
            "active": (s.get("active") or "") if admin or visible(
                JOBS.get(s.get("active") or "") or {}) else "",
        } for s in SCHEDULER["slots"].values()]
        control = queue_control.load()
        return {"active": active, "running": running, "waiting": waiting,
                "slots": slots, "size": len(waiting), "max": SCHED_MAX_QUEUE,
                "per_user_cap": SCHED_PER_USER_CAP,
                "paused": bool(control.get("paused")),
                "pause_reason": control.get("pause_reason") or "",
                "maintenance_active": queue_control.maintenance_active(),
                "max_wait_seconds": int(control.get("max_wait_seconds") or 0),
                "training": training_manager.M.gate_snapshot(),
                "local_available": bool(
                    (SCHEDULER["slots"].get("local") or {}).get("available"))}


def scheduler_has_remote(user, requirements, pixels=0, count=1):
    if not lan_share.settings().get("remote_enabled"):
        return False
    job = {"remote_ok": True, "kind": "gen", "user_id": (user or {}).get("id") or "",
           "requirements": requirements or [], "pixels": pixels, "count": count,
           "exclude_workers": []}
    for w in lan_share.scheduler_workers():
        # 正在跑图 / 临时忙的节点也应允许排队，不能因为这一秒忙就 503。
        if not w.get("online") or w.get("paused"):
            continue
        policy = _worker_policy(w)
        policy["accepting"] = True
        if _worker_policy_can_run(policy, job):
            return True
    return False


def local_generation_running():
    """本机正在采样的生图任务数；训练闸门只拦本机，不管远端。"""
    with JOBS_LOCK:
        return sum(1 for j in JOBS.values()
                   if j.get("status") == "running"
                   and j.get("worker_kind", "local") == "local")


def comfy_free_models():
    """让 ComfyUI 释放模型/显存；/free 返回空体，不能走 http_json。"""
    try:
        data = json.dumps({"unload_models": True,
                           "free_memory": True}).encode("utf-8")
        req = urllib.request.Request(
            COMFY + "/free", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read(64)
        return True
    except Exception:
        return False


def training_limits_for(uid):
    user = get_user(uid) or {}
    return user_limits(user)


def training_usage_for(uid):
    snap = usage_snapshot(uid)
    return {
        "train_seconds_today": snap.get("train_seconds_today", 0),
        "train_seconds_month": snap.get("train_seconds_month", 0),
        "train_jobs_today": snap.get("train_jobs_today", 0),
        "train_jobs_month": snap.get("train_jobs_month", 0),
    }


def training_feature_allowed(uid):
    user = get_user(uid) or {}
    return bool(is_admin(user) or feature_allowed(user, "train"))


def training_caption_check(text):
    result = sensitive_filter.check_caption(text)
    if result.get("mode") == "block" and result.get("hit"):
        return "训练描述包含管理员禁止的内容，已拦截。"
    return ""


def training_lora_in_use(name):
    name = os.path.basename(str(name or ""))
    with JOBS_LOCK:
        for job in JOBS.values():
            if job.get("status") not in ("queued", "running"):
                continue
            if any(os.path.basename(str(x.get("name") or "")) == name
                   for x in (job.get("loras") or [])):
                return True
    return False


def _training_audit(category, action, user=None, ip="", ok=True,
                    user_id=None, **detail):
    return audit(category, action, user=user, ip=ip, ok=ok,
                 user_id=user_id, **detail)


def _training_note_usage(uid, seconds=0):
    note_training_usage(uid, seconds)


def _training_activity(event_kind, **fields):
    return activity(event_kind, **fields)


training_manager.bind_runtime(
    local_active=local_generation_running,
    gpu_snapshot=lambda: dict(LOAD_STATE),
    guard_snapshot=lambda: guard_snapshot(),
    free_comfy=comfy_free_models,
    scheduler_kick=scheduler_kick,
    audit=_training_audit,
    note_usage=_training_note_usage,
    activity=_training_activity,
    limits_for=training_limits_for,
    usage_for=training_usage_for,
    lora_in_use=training_lora_in_use,
    can_train=training_feature_allowed,
    check_caption=training_caption_check,
    ensure_sampler=ensure_load_sampler,
)


def job_requirements(ckpt, loras=None, turbo=False, kind="gen"):
    if kind != "gen":
        return []
    req = []
    if ckpt == ANIMA_MODEL:
        req.extend([
            {"folder": "diffusion_models", "name": ANIMA_MODEL},
            {"folder": "text_encoders", "name": ANIMA_CLIP},
            {"folder": "vae", "name": ANIMA_VAE},
        ])
        if turbo:
            req.append({"folder": "loras", "name": ANIMA_TURBO_LORA})
    else:
        req.append({"folder": "checkpoints", "name": os.path.basename(ckpt or "")})
    for item in loras or []:
        name = os.path.basename(str((item or {}).get("name") or ""))
        if name:
            req.append({"folder": "loras", "name": name})
    return req


# --------------------------------------------------------------------- 远端任务状态

def _remote_now():
    return time.time()


def _remote_dir(jid):
    return os.path.join(REMOTE_SPOOL_DIR, str(jid))


def remote_job_set_payload(jid, worker_id, attempt, payload, input_refs):
    with REMOTE_LOCK:
        rec = REMOTE_JOBS.get(jid) or {}
        rec.update({
            "job_id": jid,
            "worker_id": worker_id,
            "attempt": int(attempt or 1),
            "payload": payload,
            "input_refs": dict(input_refs or {}),
            "outputs": {},
            "state": "offered",
            "cancel": False,
            "cancelled": False,
            "complete": False,
            "error": "",
            "prompt_id": "",
            "event": rec.get("event") or threading.Event(),
            "created": rec.get("created") or _remote_now(),
        })
        REMOTE_JOBS[jid] = rec
    ev = WORKER_EVENTS.setdefault(worker_id, threading.Event())
    ev.set()
    return rec


def remote_claim(worker_id, wait_sec=20):
    deadline = time.time() + max(1, min(30, int(wait_sec or 20)))
    while time.time() < deadline:
        with SCHED_LOCK:
            slot = SCHEDULER["slots"].get(worker_id) or {}
            jid = slot.get("active") or ""
        if jid:
            with REMOTE_LOCK:
                rec = REMOTE_JOBS.get(jid)
                if rec and (rec.get("complete") or rec.get("error")
                            or rec.get("cancelled")):
                    return None
                if rec and rec.get("payload") is not None:
                    rec["state"] = "claimed"
                    rec["claimed_at"] = time.time()
                    payload = dict(rec["payload"])
                    payload["attempt"] = rec.get("attempt") or 1
                    payload["cancel"] = bool(rec.get("cancel"))
                    return payload
                if rec and rec.get("cancel"):
                    wait_sec = 0
        ev = WORKER_EVENTS.setdefault(worker_id, threading.Event())
        ev.wait(min(1.0, max(0.05, deadline - time.time())))
        ev.clear()
    return None


def remote_job_verify(jid, worker_id, attempt):
    with REMOTE_LOCK:
        rec = REMOTE_JOBS.get(jid)
        if not rec:
            return None, "任务不存在"
        if rec.get("worker_id") != worker_id:
            return None, "不是这个节点的任务"
        if int(rec.get("attempt") or 0) != int(attempt or 0):
            return None, "任务尝试编号已过期"
        if rec.get("complete") or rec.get("cancelled") or rec.get("error"):
            return None, "任务尝试已结束"
        return rec, ""


def remote_job_started(jid, worker_id, attempt, prompt_id):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    cpid = "w:%s:%s" % (worker_id, prompt_id)
    with REMOTE_LOCK:
        rec["prompt_id"] = prompt_id
        rec["started_at"] = _remote_now()
        rec["state"] = "running"
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if job:
            job["comfy_prompt_id"] = cpid
            job["remote_prompt_id"] = prompt_id
            job["dispatch_state"] = "running"
            job["submitted_at"] = time.time()
            job["elapsed"] = 0
    drop_job_resume(jid)
    with WS_LOCK:
        WS_PROGRESS.setdefault(cpid, {"value": 0, "max": 0})
    return {"ok": True, "cancel": bool(rec.get("cancel"))}, ""


def remote_job_progress(jid, worker_id, attempt, data):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    data = data if isinstance(data, dict) else {}
    cpid = "w:%s:%s" % (worker_id, rec.get("prompt_id") or "")
    try:
        value = int(data.get("value")) if data.get("value") is not None else None
        maximum = int(data.get("max")) if data.get("max") is not None else None
    except Exception:
        value = maximum = None
    preview = data.get("preview_b64")
    blob = None
    if isinstance(preview, str) and len(preview) <= 900000:
        try:
            blob = base64.b64decode(preview, validate=True)
        except Exception:
            blob = None
        if blob and len(blob) > 700000:
            blob = None
    with WS_LOCK:
        if value is not None:
            WS_PROGRESS[cpid] = {"value": value, "max": maximum or 0}
        if blob:
            WS_PREVIEW[cpid] = blob
    with JOBS_LOCK:
        job = JOBS.get(jid)
        if job:
            if not job.get("first_progress_at"):
                job["first_progress_at"] = time.time()
            try:
                job["elapsed"] = float(data.get("elapsed") or job.get("elapsed") or 0)
            except Exception:
                pass
    return {"ok": True, "cancel": bool(rec.get("cancel"))}, ""


def remote_job_output(jid, worker_id, attempt, index, blob):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    try:
        index = int(index)
    except Exception:
        index = -1
    if index < 0 or index > 7:
        return None, "结果序号不合法"
    if not blob or len(blob) > 40 * 1024 * 1024:
        return None, "结果文件大小不合法"
    folder = _remote_dir(jid)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%02d.png" % index)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(blob)
    os.replace(tmp, path)
    with REMOTE_LOCK:
        rec["outputs"][str(index)] = {
            "path": path,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        }
        rec["state"] = "uploading"
    return {"ok": True, "index": index, "bytes": len(blob)}, ""


def remote_job_complete(jid, worker_id, attempt, data):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    with REMOTE_LOCK:
        rec["complete"] = True
        rec["state"] = "complete"
        rec["payload"] = None
        rec["complete_data"] = data if isinstance(data, dict) else {}
        rec["event"].set()
    return {"ok": True, "final": True}, ""


def remote_job_error(jid, worker_id, attempt, data):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    data = data if isinstance(data, dict) else {}
    with REMOTE_LOCK:
        rec["error"] = str(data.get("error") or "远端执行失败")[:500]
        rec["error_kind"] = str(data.get("kind") or "")
        rec["error_status"] = data.get("status")
        rec["missing_models"] = data.get("missing_models") or []
        rec["missing_nodes"] = data.get("missing_nodes") or []
        rec["state"] = "error"
        rec["payload"] = None
        rec["event"].set()
    return {"ok": True}, ""


def remote_job_cancelled(jid, worker_id, attempt):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    with REMOTE_LOCK:
        rec["cancelled"] = True
        rec["state"] = "cancelled"
        rec["payload"] = None
        rec["event"].set()
    return {"ok": True}, ""


def remote_cancel_jobs(worker_id):
    out = []
    with REMOTE_LOCK:
        for jid, rec in REMOTE_JOBS.items():
            if (rec.get("worker_id") == worker_id and rec.get("cancel")
                    and not rec.get("cancelled")
                    and not rec.get("complete")
                    and not rec.get("error")):
                out.append(jid)
    return out


def request_remote_cancel(jid):
    with REMOTE_LOCK:
        rec = REMOTE_JOBS.get(jid)
        if rec:
            rec["cancel"] = True
            return True
    return False


def remote_job_state(jid):
    with REMOTE_LOCK:
        return dict(REMOTE_JOBS.get(jid) or {})


def remote_job_outputs(jid):
    with REMOTE_LOCK:
        rec = REMOTE_JOBS.get(jid) or {}
        outs = rec.get("outputs") or {}
        return [outs[k] for k in sorted(outs.keys(), key=lambda x: int(x))]


def remote_job_input_bytes(jid, worker_id, attempt, key):
    rec, err = remote_job_verify(jid, worker_id, attempt)
    if err:
        return None, err
    refs = rec.get("input_refs") or {}
    path = refs.get(str(key))
    if not path or not os.path.isfile(path):
        return None, "输入文件不存在"
    with open(path, "rb") as fh:
        return fh.read(), ""


def remote_job_cleanup(jid):
    with REMOTE_LOCK:
        REMOTE_JOBS.pop(jid, None)
    shutil.rmtree(_remote_dir(jid), ignore_errors=True)


def remote_spool_cleanup_startup():
    try:
        if os.path.isdir(REMOTE_SPOOL_DIR):
            for name in os.listdir(REMOTE_SPOOL_DIR):
                shutil.rmtree(os.path.join(REMOTE_SPOOL_DIR, name),
                              ignore_errors=True)
    except OSError:
        pass


def _remote_save_outputs(job_id, outputs, ckpt, user_id, prompt, prompt_en,
                         negative, width, height, steps, cfg, seed, count,
                         denoise, sampler, frames, char_tags, prompt_display,
                         update, started):
    """把 worker 上传的临时图片重新编码后存入中央图库。"""
    if not outputs:
        update(status="error", error="完成但没有输出图片")
        return False
    from PIL import Image
    os.makedirs(DELIVER_DIR, exist_ok=True)
    uid = safe_uid(user_id) or "admin"
    folder = model_folder(ckpt)
    save_dir = os.path.join(user_gallery_root(uid), folder)
    os.makedirs(save_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    saved = []
    try:
        for idx, item in enumerate(outputs):
            src = item.get("path") or ""
            if not src or not os.path.isfile(src):
                continue
            with Image.open(src) as im:
                fmt = (im.format or "").upper()
                if fmt not in ("PNG", "JPEG", "WEBP"):
                    continue
                w, h = im.size
                if w < 1 or h < 1 or w * h > UPLOAD_MAX_PIXELS or max(w, h) > UPLOAD_MAX_SIDE:
                    continue
                im.load()
                if im.mode == "P" and "transparency" in im.info:
                    im = im.convert("RGBA")
                elif im.mode not in ("RGB", "RGBA", "L"):
                    im = im.convert("RGB")
                dst_name = "%s_remote_%02d.png" % (stamp, idx)
                dest_path = os.path.join(save_dir, dst_name)
                im.save(dest_path, format="PNG")
            rel_name = uid + "/" + folder + "/" + dst_name
            strip_png_meta(dest_path)
            write_meta(rel_name, {
                "prompt": prompt_display or prompt or "",
                "prompt_en": prompt_en,
                "negative": negative,
                "width": width, "height": height, "steps": steps,
                "cfg": cfg, "seed": seed, "count": count,
                "denoise": denoise, "model": ckpt, "kind": "gen",
                "sampler": sampler, "frames": frames,
                "char_tags": char_tags or [],
                "worker": True,
            })
            saved.append(rel_name)
    except Exception as exc:
        update(status="error", error="远端结果保存失败：%s" % exc)
        return False
    if not saved:
        update(status="error", error="远端结果没有可用图片")
        return False
    secs = time.time() - started
    DURATIONS.append((ckpt, steps, count, secs))
    update(status="done", image=saved[0], images=saved,
           saved_at=time.time(),
           elapsed=round(time.time() - (JOBS.get(job_id) or {}).get("started", started), 1))
    return True


def _run_remote_job(job_id, slot, prompt, negative, width, height, steps, cfg,
                    seed, count, init_image, init_mask, denoise, ckpt, kind,
                    loras, hires, prompt_en, sampler, frames, pag, turbo,
                    char_tags, prompt_display, stage_id, user_id, update,
                    started):
    """远端分支：构建工作流，交给 worker，等待结果并写中央图库。"""
    kind_norm = kind if kind in ("gen", "video", "i2v", "upscale") else "gen"
    try:
        with JOBS_LOCK:
            job = dict(JOBS.get(job_id) or {})
        attempt = int(job.get("attempt") or 1)

        def fail(msg, retryable=False):
            """retryable 且还没有回传任何图时，交给 run_job 换节点重试。"""
            if retryable:
                rec = remote_job_state(job_id)
                if not (rec.get("outputs") or {}):
                    return ("retry", msg)
            update(status="error", error=msg)
            return ("error", msg)

        # 中文提示词在中央先翻成英文，减少对 worker 上 Argos 节点的依赖。
        text = prompt_en or prompt
        use_translate = (not prompt_en) and has_chinese(text)
        if use_translate:
            tr, _provider, _err = translate_text_for_user(
                text, get_user(user_id or "admin"))
            if tr and not has_chinese(tr):
                text = tr
                use_translate = False
        neg = negative
        if has_chinese(neg):
            trn, _provider, _err = translate_text_for_user(
                neg, get_user(user_id or "admin"))
            if trn and not has_chinese(trn):
                neg = trn
        profile = model_profile(ckpt)
        vpred = bool(profile.get("vpred"))
        pony_prefix = pony_prefix_for(ckpt, text)
        if ckpt == ANIMA_MODEL:
            wf = build_anima_workflow(text, neg, width, height, steps, cfg,
                                      seed, use_translate, count=count,
                                      init_image=init_image, init_mask=init_mask,
                                      denoise=denoise, sampler=sampler,
                                      hires=hires, turbo=turbo,
                                      char_tags=char_tags)
        else:
            wf = build_workflow(text, neg, width, height, steps, cfg, seed,
                                use_translate, count=count,
                                init_image=init_image, init_mask=init_mask,
                                denoise=denoise, ckpt=ckpt, loras=loras,
                                hires=hires, sampler=sampler, pag=pag,
                                vpred=vpred, char_tags=char_tags,
                                prefix=pony_prefix)
        remember_workflow(wf, title=os.path.basename(ckpt or "") or "出图")
        with JOBS_LOCK:
            if (JOBS.get(job_id) or {}).get("status") != "running":
                return ("cancelled", "")
            refs = dict(JOBS.get(job_id) or {}).get("input_refs") or {}
        payload_inputs = []
        for node_id, node in (wf.get("prompt") or {}).items():
            if (node or {}).get("class_type") != "LoadImage":
                continue
            value = (node.get("inputs") or {}).get("image")
            key = ""
            if init_image and value == init_image:
                key = "image"
            elif init_mask and value == init_mask:
                key = "mask"
            if key and key in refs:
                payload_inputs.append({"key": key, "node_id": str(node_id),
                                       "field": "image",
                                       "filename": os.path.basename(str(value))})
        payload = {
            "job_id": job_id,
            "attempt": attempt,
            "workflow": wf,
            "inputs": payload_inputs,
            "timeout": 900,
            "kind": kind_norm,
            "mode": job.get("mode") or "txt",
            "model": os.path.basename(ckpt or ""),
        }
        remote_job_set_payload(job_id, slot, attempt, payload, refs)
        activity_request("worker /job", "POST", job_id=job_id,
                         worker_id=slot, mode=job.get("mode"),
                         model=os.path.basename(ckpt or ""),
                         user_id=user_id or "admin")
        deadline = time.time() + 900
        cpid = ""
        while time.time() < deadline:
            with JOBS_LOCK:
                job = dict(JOBS.get(job_id) or {})
            if job.get("status") != "running":
                request_remote_cancel(job_id)
                for _ in range(30):
                    rec = remote_job_state(job_id)
                    if rec.get("cancelled") or rec.get("complete") or rec.get("error"):
                        break
                    time.sleep(0.5)
                return ("cancelled", "")
            rec = remote_job_state(job_id)
            if rec.get("complete"):
                outputs = remote_job_outputs(job_id)
                saved = _remote_save_outputs(
                    job_id, outputs, ckpt, user_id, prompt,
                    prompt_en, negative, width, height, steps,
                    cfg, seed, count, denoise, sampler,
                    frames, char_tags, prompt_display,
                    update, started)
                return ("done", "") if saved else ("error", "")
            if rec.get("error"):
                status = rec.get("error_status")
                msg = friendly_error(status) if status else rec.get("error")
                kind_name = rec.get("error_kind") or ""
                if kind_name == "incompatible":
                    miss = []
                    for m in (rec.get("missing_models") or [])[:8]:
                        miss.append(str(m.get("folder") or "") + "/" +
                                    str(m.get("name") or ""))
                    for n in (rec.get("missing_nodes") or [])[:8]:
                        miss.append(str(n))
                    if miss:
                        msg = "算力节点缺少模型或工具：" + "、".join(miss)
                retryable = kind_name not in (
                    "incompatible", "bad_workflow", "prompt_rejected",
                    "output_too_large")
                return fail(msg or "远端执行失败", retryable=retryable)
            cpid = job.get("comfy_prompt_id") or cpid
            elapsed = round(time.time() - (job.get("started") or started), 1)
            update(elapsed=elapsed)
            with WS_LOCK:
                wp = dict(WS_PROGRESS.get(cpid) or {}) if cpid else {}
            activity("job", phase="progress", job_id=job_id, elapsed=elapsed,
                     value=wp.get("value"), max=wp.get("max"),
                     throttle=1.8, throttle_key=("progress", job_id))
            worker = lan_share.get_worker(slot)
            if not worker:
                return fail("算力节点已被移除", retryable=True)
            if not lan_share._online(worker) and time.time() - float(worker.get("last_seen") or 0) > 30:
                return fail("算力节点失联", retryable=True)
            if (rec.get("claimed_at")
                    and time.time() - float(rec.get("claimed_at") or 0) > 15
                    and (worker.get("current_job") or "") != job_id
                    and not rec.get("complete") and not rec.get("error")):
                return fail("算力节点重启或任务丢失", retryable=True)
            time.sleep(1.0)
        request_remote_cancel(job_id)
        return fail("远端任务超时（15 分钟）", retryable=True)
    except Exception as exc:
        return fail("%s: %s" % (type(exc).__name__, exc))
    finally:
        remote_job_cleanup(job_id)


def run_job(job_id, prompt, negative, width, height, steps, cfg, seed,
            count=1, init_image=None, init_mask=None, denoise=1.0,
            ckpt=DEFAULT_CHECKPOINT, kind="gen", loras=None, hires=False,
            prompt_en="", sampler=DEFAULT_SAMPLER, frames=16, pag=True,
            turbo=False, char_tags=None, prompt_display="", stage_id=None,
            user_id=None):
    """后台线程：提交给 ComfyUI 并等结果。

    prompt 是用户原话（中文），只写进元数据供图库搜索用；
    prompt_en 是 optimize_prompt 转好的英文标签，真正喂给模型的它。
    """
    kind_norm = kind if kind in ("gen", "video", "i2v", "upscale") else "gen"
    if kind_norm == "upscale":
        mode = "upscale"
    elif kind_norm == "i2v":
        mode = "i2v"
    elif kind_norm == "video":
        mode = "vid"
    elif init_image:
        mode = "img"
    else:
        mode = "txt"
    job_meta = {
        "kind": kind_norm,
        "mode": mode,
        "model": os.path.basename(ckpt or ""),
        "hires": bool(hires),
        "pag": bool(pag),
        "turbo": bool(turbo),
        "loras": len(loras or []),
        "inpaint": bool(init_mask),
        "img2img": bool(init_image),
        "frames": int(frames or 0),
        "steps": int(steps or 0),
        "cfg": float(cfg or 0),
        "sampler": sampler or "",
        "user_id": user_id or "admin",
    }
    _u = get_user(user_id or "admin") or {}
    job_meta["username"] = _u.get("username") or (user_id or "admin")
    job_meta["user_name"] = _u.get("name") or ""
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(job_meta)

    # 多账号公平排队：轮到自己之前不碰 ComfyUI，也不占显存。
    slot = scheduler_wait(job_id)
    if not slot:
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job and job.get("status") == "queued":
                job["status"] = "error"
                job["error"] = "排队超时或已取消"
        scheduler_cancel_job(job_id)
        scheduler_release(job_id)
        cleanup_stage(user_id or "admin", stage_id)
        return

    started = time.time()
    finished = {"v": False}

    def update(**kw):
        with JOBS_LOCK:
            JOBS[job_id].update(kw)
            if JOBS[job_id].get("status") in ("done", "error"):
                JOBS[job_id]["dispatch_state"] = JOBS[job_id].get("status")
                JOBS[job_id].setdefault("finished_at", time.time())
            snapshot = dict(JOBS[job_id])
        persist_jobs(force=snapshot.get("status") in ("done", "error"))
        if snapshot.get("status") in ("done", "error"):
            drop_job_resume(job_id)
        if "status" in kw and snapshot.get("status") in ("done", "error",
                                                         "cancelled"):
            try:
                monitor_center.note_job(dict(snapshot, job_id=job_id))
            except Exception:
                pass
        # 任务结束 / 失败只记一次；进度事件由下面的轮询循环单独发。
        if ("status" in kw and snapshot.get("status") in ("done", "error")
                and not finished["v"]):
            finished["v"] = True
            phase = "done" if snapshot["status"] == "done" else "error"
            payload = job_activity_fields(snapshot)
            payload["job_id"] = job_id
            payload["elapsed"] = snapshot.get("elapsed", 0)
            if phase == "done":
                payload["count"] = len(snapshot.get("images") or [])
            else:
                payload["error"] = str(snapshot.get("error") or "")[:180]
            activity("job", phase=phase, **payload)
            audit("activity", "job_" + phase, user_id=user_id or "admin",
                  job_id=job_id, kind=snapshot.get("kind"),
                  mode=snapshot.get("mode"), model=snapshot.get("model"),
                  elapsed=snapshot.get("elapsed", 0),
                  count=len(snapshot.get("images") or []),
                  error=str(snapshot.get("error") or "")[:180])
            try:
                monitor_center.notify_job(phase, dict(snapshot,
                                                       job_id=job_id))
            except Exception:
                pass
            note_job_usage(user_id or "admin",
                           snapshot.get("elapsed", 0),
                           len(snapshot.get("images") or []),
                           snapshot.get("kind") or "gen")
            if snapshot.get("worker_kind") == "remote":
                lan_share.note_worker_job(
                    snapshot.get("worker_id") or "",
                    snapshot.get("elapsed", 0),
                    len(snapshot.get("images") or []),
                    phase == "done")
            cleanup_stage(user_id or "admin", stage_id)

    if slot != "local":
        while True:
            outcome, reason = "error", ""
            try:
                outcome, reason = _run_remote_job(
                    job_id, slot, prompt, negative, width, height,
                    steps, cfg, seed, count, init_image, init_mask,
                    denoise, ckpt, kind, loras, hires, prompt_en,
                    sampler, frames, pag, turbo, char_tags,
                    prompt_display, stage_id, user_id, update, started)
            except Exception as exc:
                reason = "%s: %s" % (type(exc).__name__, exc)
            finally:
                scheduler_release(job_id)

            if outcome != "retry":
                if outcome == "error" and reason:
                    with JOBS_LOCK:
                        st = (JOBS.get(job_id) or {}).get("status")
                    if st == "running":
                        update(status="error", error=reason)
                cleanup_stage(user_id or "admin", stage_id)
                return

            with JOBS_LOCK:
                job = dict(JOBS.get(job_id) or {})
            if job.get("status") != "running":
                cleanup_stage(user_id or "admin", stage_id)
                return
            if (int(job.get("retry_count") or 0) >= 1
                    or not _remote_retry_available(job, slot)):
                update(status="error", error=reason or "远端执行中断")
                cleanup_stage(user_id or "admin", stage_id)
                return

            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if not job or job.get("status") != "running":
                    cleanup_stage(user_id or "admin", stage_id)
                    return
                job["retry_count"] = int(job.get("retry_count") or 0) + 1
                excluded = list(job.get("exclude_workers") or [])
                if slot not in excluded:
                    excluded.append(slot)
                job["exclude_workers"] = excluded
                job["status"] = "queued"
                job["worker_id"] = ""
                job["worker_name"] = ""
                job["worker_kind"] = ""
                job["dispatch_state"] = "retry"
                job["error"] = ""
            audit("activity", "job_retry", user_id=user_id or "admin",
                  job_id=job_id, worker_id=slot,
                  reason=str(reason or "")[:180])
            err = scheduler_enqueue(job_id)
            if err:
                update(status="error", error=err)
                cleanup_stage(user_id or "admin", stage_id)
                return
            slot = scheduler_wait(job_id)
            if not slot:
                with JOBS_LOCK:
                    st = (JOBS.get(job_id) or {}).get("status")
                if st not in ("done", "error"):
                    update(status="error", error="重试排队失败")
                cleanup_stage(user_id or "admin", stage_id)
                return
            if slot == "local":
                break

    vpred = bool(model_profile(ckpt).get("vpred"))
    # 本机执行时，如果提示词仍是中文（例如挂机任务），先按账号偏好翻译。
    if kind not in ("upscale",) and has_chinese(prompt) and not prompt_en:
        _tr, _provider, _err = translate_text_for_user(
            prompt, get_user(user_id or "admin"))
        if _tr and not has_chinese(_tr):
            prompt_en = _tr
    if kind not in ("upscale",) and has_chinese(negative):
        _trn, _provider, _err = translate_text_for_user(
            negative, get_user(user_id or "admin"))
        if _trn and not has_chinese(_trn):
            negative = _trn
    try:
        if kind == "upscale":
            up_model = upscaler_for(ckpt)
            if not up_model:
                update(status="error", error="没有可用的放大模型")
                return
            wf = build_upscale_workflow(init_image, up_model, count)
        elif kind == "i2v":
            text = prompt_en or prompt
            wf = build_i2v_workflow(text, negative, width, height, frames,
                                    seed, init_image,
                                    use_translate=has_chinese(text))
        elif kind == "video":
            text = prompt_en or prompt
            wf = build_video_workflow(text, negative, width, height,
                                      frames, seed,
                                      use_translate=has_chinese(text))
        else:
            # prompt_en 已经转成英文标签，就不再走 ComfyUI 里的翻译节点
            text = prompt_en or prompt
            use_translate = (not prompt_en) and has_chinese(text)
            profile = model_profile(ckpt)
            pony_prefix = pony_prefix_for(ckpt, text)
            if ckpt == ANIMA_MODEL:
                wf = build_anima_workflow(
                    text, negative, width, height, steps, cfg, seed,
                    use_translate, count=count, init_image=init_image,
                    init_mask=init_mask, denoise=denoise,
                    sampler=sampler, hires=hires, turbo=turbo,
                    char_tags=char_tags, loras=loras)
            else:
                wf = build_workflow(text, negative, width, height, steps, cfg,
                                    seed, use_translate, count=count,
                                    init_image=init_image, init_mask=init_mask,
                                    denoise=denoise, ckpt=ckpt,
                                    loras=loras, hires=hires, sampler=sampler,
                                    pag=pag, vpred=vpred,
                                    char_tags=char_tags, prefix=pony_prefix)

        # 构建工作流期间可能已经被取消：不要再把任务提交给 ComfyUI
        with JOBS_LOCK:
            if (JOBS.get(job_id) or {}).get("status") != "running":
                return
        resp = http_json("/prompt", wf)
        pid = resp.get("prompt_id")
        if not pid:
            update(status="error", error="提交失败：%s" % resp)
            return
        # 提交和取消撞车：把自己刚塞进 ComfyUI 队列的 prompt 删掉
        with JOBS_LOCK:
            still_running = ((JOBS.get(job_id) or {}).get("status") == "running")
        if not still_running:
            try:
                http_json("/queue", {"delete": [pid]}, timeout=10)
            except Exception:
                pass
            return
        wf_title = ("图生视频" if kind_norm == "i2v" else
                    "文生视频" if kind_norm == "video" else
                    "放大" if kind_norm == "upscale" else
                    (os.path.basename(ckpt or "") or "出图"))
        remember_workflow(wf, title=wf_title)
        update(comfy_prompt_id=pid, submitted_at=time.time())
        # 已经提交给 ComfyUI，不能再自动重试，否则可能重复出图。
        drop_job_resume(job_id)
        activity_request("ComfyUI /prompt", "POST", job_id=job_id,
                         mode=job_meta["mode"], model=job_meta["model"],
                         user_id=user_id or "admin",
                         user=job_meta.get("username") or "")

        def _queue_has_pid(queue, prompt_id):
            for key in ("queue_running", "queue_pending"):
                for item in (queue or {}).get(key) or []:
                    if (isinstance(item, (list, tuple)) and len(item) > 1
                            and str(item[1]) == prompt_id):
                        return True
            return False

        deadline = time.time() + 900
        comfy_fail = 0
        queue_missing = 0
        while time.time() < deadline:
            time.sleep(2)
            with JOBS_LOCK:
                if JOBS[job_id]["status"] != "running":
                    return  # 已被取消
            elapsed = round(time.time() - JOBS[job_id]["started"], 1)
            update(elapsed=elapsed)
            with WS_LOCK:
                wp = dict(WS_PROGRESS.get(pid) or {})
            if wp.get("value") is not None and not JOBS[job_id].get("first_progress_at"):
                update(first_progress_at=time.time())
            activity("job", phase="progress", job_id=job_id, elapsed=elapsed,
                     value=wp.get("value"), max=wp.get("max"),
                     throttle=1.8, throttle_key=("progress", job_id))
            try:
                hist = http_json("/history/" + pid, timeout=5)
            except Exception:
                # ComfyUI 被关掉/重启时 /history 会连续连接失败。不要傻等
                # 15 分钟，连续 6 次（约 12 秒）就明确失败并释放队列槽位。
                comfy_fail += 1
                if comfy_fail >= 6:
                    update(status="error",
                           error="ComfyUI 连接中断，任务已中断；"
                                 "请确认 ComfyUI 恢复后重新提交。")
                    return
                continue
            comfy_fail = 0
            if pid not in hist:
                # ComfyUI 重启后内存队列会清空，旧 prompt_id 永远不会再出现。
                # 运行中的任务一定在 /queue 里；连续 5 次（约 10 秒）都找不到
                # 就判定任务已被 ComfyUI 丢失。
                if elapsed > 10:
                    try:
                        queue = http_json("/queue", timeout=5)
                        queue_missing = (0 if _queue_has_pid(queue, pid)
                                         else queue_missing + 1)
                    except Exception:
                        queue_missing += 1
                    if queue_missing >= 5:
                        update(status="error",
                               error="ComfyUI 已重启或丢失该任务；"
                                     "请重新提交。")
                        return
                continue
            queue_missing = 0
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                update(status="error", error=friendly_error(status))
                return

            found = []
            for out in (entry.get("outputs") or {}).values():
                for im in (out.get("images") or []):
                    found.append(im)
            if found:
                os.makedirs(DELIVER_DIR, exist_ok=True)
                uid = safe_uid(user_id) or "admin"
                folder = model_folder(ckpt)
                save_dir = os.path.join(user_gallery_root(uid), folder)
                os.makedirs(save_dir, exist_ok=True)
                stamp = time.strftime("%Y%m%d-%H%M%S")
                saved = []
                for idx, im in enumerate(found):
                    name = im.get("filename")
                    if not name:
                        continue
                    src = os.path.join(OUTPUT_DIR,
                                       im.get("subfolder") or "", name)
                    stem, ext = os.path.splitext(name)
                    dst_name = "%s_%s_%02d%s" % (stamp, stem, idx,
                                                 ext or ".png")
                    dest_path = os.path.join(save_dir, dst_name)
                    copied = False
                    try:
                        shutil.copy2(src, dest_path)
                        copied = True
                    except Exception:
                        dst_name = name
                        dest_path = os.path.join(save_dir, dst_name)
                    rel_name = uid + "/" + folder + "/" + dst_name
                    # 交付副本抹掉提示词元数据；原件仍在 ComfyUI/output/
                    if copied:
                        strip_png_meta(dest_path)
                    meta_prompt = (prompt_display or prompt
                                   or (JOBS[job_id].get("prompt") or ""))
                    write_meta(rel_name, {
                        "prompt": meta_prompt, "prompt_en": prompt_en,
                        "negative": negative,
                        "width": width, "height": height, "steps": steps,
                        "cfg": cfg, "seed": seed, "count": count,
                        "denoise": denoise, "model": ckpt, "kind": kind,
                        "sampler": sampler, "frames": frames,
                        "char_tags": char_tags or [],
                    })
                    saved.append(rel_name)
                if saved:
                    secs = time.time() - started
                    if kind == "gen":
                        DURATIONS.append((ckpt, steps, count, secs))
                    update(status="done", image=saved[0], images=saved,
                           saved_at=time.time(),
                           elapsed=round(time.time() - JOBS[job_id]["started"], 1))
                    return
            update(status="error", error="完成但没找到输出图片")
            return
        update(status="error", error="超时（15 分钟）")
    except Exception as e:
        update(status="error", error="%s: %s" % (type(e).__name__, e))
    finally:
        scheduler_release(job_id)
        cleanup_stage(user_id or "admin", stage_id)


# --------------------------------------------------------------------- 图库

def write_meta(name, meta):
    """给图片写一份同名 .json；name 可以是 模型目录/文件名.png。"""
    try:
        path = media_path(name)
        if not path:
            return
        meta = dict(meta or {})
        meta["saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
    except Exception:
        pass


def read_meta(name):
    try:
        path = media_path(name)
        if not path:
            return {}
        with open(path + ".json", "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def migrate_gallery_to_model_folders():
    """旧版平铺图库 → 按底模分目录；只移动文件，不删除。"""
    marker = os.path.join(DELIVER_DIR, ".model_isolation_v1")
    if os.path.isfile(marker) or not os.path.isdir(DELIVER_DIR):
        return 0
    favs = load_favorites("admin")
    fav_changed = False
    moved = 0
    failed = 0
    for name in list(os.listdir(DELIVER_DIR)):
        src = os.path.join(DELIVER_DIR, name)
        if name.startswith(".") or not os.path.isfile(src):
            continue
        if not name.lower().endswith(MEDIA_EXT):
            continue
        meta = read_meta(name)
        folder = model_folder(meta.get("model")) if meta.get("model") else "misc"
        dest_dir = os.path.join(DELIVER_DIR, folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest_name = name
        dst = os.path.join(dest_dir, dest_name)
        if os.path.exists(dst):
            stem, ext = os.path.splitext(name)
            dest_name = "%s_%s%s" % (stem, uuid.uuid4().hex[:6], ext)
            dst = os.path.join(dest_dir, dest_name)
        try:
            shutil.move(src, dst)
            jp = src + ".json"
            if os.path.isfile(jp):
                shutil.move(jp, dst + ".json")
            rel = folder + "/" + dest_name
            if name in favs:
                favs.discard(name)
                favs.add(rel)
                fav_changed = True
            moved += 1
        except Exception:
            failed += 1
    if fav_changed:
        save_favorites("admin", favs)
    # 缩略图是派生缓存，文件名换了以后清掉重生成
    if moved:
        try:
            for fn in os.listdir(THUMB_DIR):
                if fn.lower().endswith(".jpg"):
                    os.remove(os.path.join(THUMB_DIR, fn))
        except Exception:
            pass
    # 有文件没搬成功就先不写标记，下次启动再试
    if failed == 0:
        try:
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"moved": moved,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, ensure_ascii=False)
        except Exception:
            pass
    if moved:
        print("  [图库] 已按模型分目录整理 %d 张图" % moved)
    return moved


def migrate_users_v1():
    """旧图库/旧上传 → 管理员目录，给多用户让出独立根目录。"""
    marker = os.path.join(DELIVER_DIR, ".users_v1")
    if os.path.isfile(marker) or not os.path.isdir(DELIVER_DIR):
        return 0
    admin_root = user_gallery_root("admin")
    os.makedirs(admin_root, exist_ok=True)
    moved = 0
    failed = 0

    # 1) 顶层的模型目录 / misc → generated/admin/
    for name in list(os.listdir(DELIVER_DIR)):
        src = os.path.join(DELIVER_DIR, name)
        if name.startswith("."):
            continue
        if os.path.isfile(src):
            if not name.lower().endswith(MEDIA_EXT):
                continue
            meta = read_meta(name)
            folder = (model_folder(meta.get("model"))
                      if meta.get("model") else "misc")
            dest_dir = os.path.join(admin_root, folder)
            os.makedirs(dest_dir, exist_ok=True)
            dst = os.path.join(dest_dir, name)
            if os.path.exists(dst):
                stem, ext = os.path.splitext(name)
                dst = os.path.join(dest_dir, "%s_%s%s" % (
                    stem, uuid.uuid4().hex[:6], ext))
            try:
                shutil.move(src, dst)
                jp = src + ".json"
                if os.path.isfile(jp):
                    shutil.move(jp, dst + ".json")
                moved += 1
            except Exception:
                failed += 1
            continue
        if safe_uid(name) and name in USERS:
            continue
        dest = os.path.join(admin_root, name)
        try:
            if os.path.exists(dest):
                for fn in os.listdir(src):
                    s = os.path.join(src, fn)
                    d = os.path.join(dest, fn)
                    if os.path.exists(d):
                        stem, ext = os.path.splitext(fn)
                        d = os.path.join(dest, "%s_%s%s" % (
                            stem, uuid.uuid4().hex[:6], ext))
                    shutil.move(s, d)
                os.rmdir(src)
            else:
                shutil.move(src, dest)
            moved += 1
        except Exception:
            failed += 1

    # 2) 旧收藏 → generated/admin/.favorites.json
    if os.path.isfile(FAV_FILE):
        dest = user_fav_file("admin")
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            old = set()
            new = set()
            try:
                with open(FAV_FILE, "r", encoding="utf-8") as fh:
                    old = set(json.load(fh) or [])
            except Exception:
                pass
            if os.path.isfile(dest):
                try:
                    with open(dest, "r", encoding="utf-8") as fh:
                        new = set(json.load(fh) or [])
                except Exception:
                    pass
                os.remove(FAV_FILE)
                if old - new:
                    with open(dest, "w", encoding="utf-8") as fh:
                        json.dump(sorted(old | new), fh, ensure_ascii=False)
            else:
                shutil.move(FAV_FILE, dest)
        except Exception:
            failed += 1

    # 3) web_uploads 顶层旧文件 → web_uploads/admin/
    src_up = UPLOAD_DIR
    dst_up = user_upload_root("admin")
    try:
        os.makedirs(dst_up, exist_ok=True)
        if os.path.isdir(src_up):
            for name in list(os.listdir(src_up)):
                if name in USERS:
                    continue
                src = os.path.join(src_up, name)
                dst = os.path.join(dst_up, name)
                if os.path.exists(dst):
                    continue
                try:
                    shutil.move(src, dst)
                    moved += 1
                except Exception:
                    failed += 1
    except Exception:
        failed += 1

    if moved:
        try:
            for fn in os.listdir(THUMB_DIR):
                if fn.lower().endswith(".jpg"):
                    os.remove(os.path.join(THUMB_DIR, fn))
        except Exception:
            pass
    if failed == 0:
        try:
            with open(marker, "w", encoding="utf-8") as fh:
                json.dump({"moved": moved,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                          fh, ensure_ascii=False)
        except Exception:
            pass
    if moved:
        print("  [账号] 已把旧图库/上传整理到管理员目录（%d 项）" % moved)
    return moved


def gallery_folders(uid=None, scope_uids=None):
    """模型目录的图片数量；uid 为空时统计所有用户。"""
    scope = safe_uid(uid)
    uids = None
    if scope_uids is not None:
        uids = {safe_uid(x) for x in scope_uids if safe_uid(x)}
    counts = {}
    if not os.path.isdir(DELIVER_DIR):
        return []
    base = os.path.abspath(DELIVER_DIR)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.startswith(".") or not fn.lower().endswith(MEDIA_EXT):
                continue
            rel = os.path.relpath(os.path.join(root, fn), base)
            rel = rel.replace(os.sep, "/")
            owner, model, _fname = split_media_rel(rel)
            if scope and owner != scope:
                continue
            if uids is not None and owner not in uids:
                continue
            key = model or "misc"
            counts[key] = counts.get(key, 0) + 1
    out = [{"name": k, "count": v} for k, v in counts.items()]
    out.sort(key=lambda x: (x["name"] != "", -x["count"], x["name"].lower()))
    return out


def gallery_users():
    """管理员用：每个用户目录的图片数量和占用。"""
    counts = {}
    if not os.path.isdir(DELIVER_DIR):
        return []
    base = os.path.abspath(DELIVER_DIR)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.startswith(".") or not fn.lower().endswith(MEDIA_EXT):
                continue
            rel = os.path.relpath(os.path.join(root, fn), base)
            rel = rel.replace(os.sep, "/")
            owner, _model, _fname = split_media_rel(rel)
            if not owner:
                continue
            rec = counts.setdefault(owner, {"count": 0, "bytes": 0})
            rec["count"] += 1
            try:
                rec["bytes"] += os.path.getsize(os.path.join(root, fn))
            except Exception:
                pass
    out = []
    for uid, rec in counts.items():
        user = get_user(uid)
        out.append({
            "id": uid,
            "username": (user or {}).get("username", uid),
            "name": (user or {}).get("name", uid),
            "role": (user or {}).get("role", "user"),
            "enabled": bool((user or {}).get("enabled", False)),
            "count": rec["count"],
            "mb": round(rec["bytes"] / 1048576, 1),
        })
    out.sort(key=lambda x: (-x["count"], x["id"]))
    return out


def list_gallery(offset=0, limit=60, kind=None, fav_only=False, q=None,
                 folder=None, scope_uid=None, user_filter=None,
                 fav_uid="admin", scope_uids=None):
    """列出图片（新→旧）。

    scope_uid   : 普通用户只看自己的目录；None 表示管理员看全部。
    user_filter : 管理员按用户筛选。
    folder      : 按模型目录筛选。
    fav_uid     : 收藏夹属于当前登录用户。
    """
    scope_uid = safe_uid(scope_uid) if scope_uid else ""
    user_filter = safe_uid(user_filter) if user_filter else ""
    uids = None
    if scope_uids is not None:
        uids = {safe_uid(x) for x in scope_uids if safe_uid(x)}
    favs = load_favorites(fav_uid)
    needle = (q or "").strip().lower()
    items = []
    if not os.path.isdir(DELIVER_DIR):
        return items, 0
    base = os.path.abspath(DELIVER_DIR)
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in files:
            if fn.startswith(".") or not fn.lower().endswith(MEDIA_EXT):
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, base).replace(os.sep, "/")
            owner, model, _fname = split_media_rel(rel)
            if scope_uid and owner != scope_uid:
                continue
            if uids is not None and owner not in uids:
                continue
            if user_filter and owner != user_filter:
                continue
            if folder is not None and (model or "misc") != folder:
                continue
            meta = read_meta(rel)
            # 关键词搜索：中文原话、英文标签、负面提示词都能搜
            if needle:
                hay = ((meta.get("prompt") or "") + " " +
                       (meta.get("prompt_en") or "") + " " +
                       (meta.get("negative") or "")).lower()
                if needle not in hay:
                    continue
            if kind in ("anime", "photo"):
                if ckpt_kind(meta.get("model")) != kind:
                    continue
            is_fav = rel in favs or os.path.basename(rel) in favs
            if fav_only and not is_fav:
                continue
            w, h = meta.get("width"), meta.get("height")
            owner_user = get_user(owner) if owner else None
            items.append({
                "name": rel,
                "folder": model or "misc",
                "user": owner,
                "user_name": ((owner_user or {}).get("name")
                              or (owner_user or {}).get("username")
                              or owner),
                "media": "video" if rel.lower().endswith(VIDEO_EXT) else "image",
                "prompt": meta.get("prompt", ""),
                "prompt_en": meta.get("prompt_en", ""),
                "negative": meta.get("negative", ""),
                "model": meta.get("model", ""),
                "kind": ckpt_kind(meta.get("model")),
                "steps": meta.get("steps"),
                "cfg": meta.get("cfg"),
                "seed": meta.get("seed"),
                "denoise": meta.get("denoise"),
                "frames": meta.get("frames"),
                "count": meta.get("count"),
                "size": ("%sx%s" % (w, h)) if (w and h) else "",
                "saved": meta.get("saved", ""),
                "fav": is_fav,
                "mtime": os.path.getmtime(fp),
            })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    total = len(items)
    return items[offset:offset + limit], total


def delete_images(names, user=None):
    """删除图片及其元数据、缩略图；普通用户只能删自己的。"""
    removed = []
    admin = user is None or is_admin(user)
    uid = (user or {}).get("id") or "admin"
    favs = load_favorites(uid)
    other_favs = {}
    for raw in names or []:
        n = safe_media_rel(raw)
        if not n:
            continue
        owner, _model, _fname = split_media_rel(n)
        if not admin and owner != uid:
            continue
        if not owner and not admin:
            continue
        p = media_path(n)
        if not p or not os.path.isfile(p):
            continue
        for f in (p, p + ".json",
                  os.path.join(THUMB_DIR, thumb_key(n) + ".jpg")):
            try:
                if os.path.isfile(f):
                    os.remove(f)
            except Exception:
                pass
        favs.discard(n)
        favs.discard(os.path.basename(n))
        if admin and owner and owner != uid:
            ofav = other_favs.get(owner)
            if ofav is None:
                ofav = load_favorites(owner)
                other_favs[owner] = ofav
            ofav.discard(n)
        removed.append(n)
        try:
            parent = os.path.dirname(p)
            protected = (os.path.abspath(DELIVER_DIR),
                         os.path.abspath(user_gallery_root(owner or "admin")))
            if (parent not in protected and not os.listdir(parent)):
                os.rmdir(parent)
        except Exception:
            pass
    if removed:
        save_favorites(uid, favs)
        for owner, ofav in other_favs.items():
            save_favorites(owner, ofav)
    return removed


def _archive_meta_path(token):
    return os.path.join(ARCHIVE_DIR, token + ".json")


def cleanup_archives(now=None):
    """删除过期的打包 ZIP 和残留的 .part 文件。"""
    now = float(now or time.time())
    try:
        names = os.listdir(ARCHIVE_DIR)
    except OSError:
        return 0
    removed = 0
    for fn in names:
        path = os.path.join(ARCHIVE_DIR, fn)
        try:
            if fn.endswith(".part") or now - os.path.getmtime(path) > ARCHIVE_TTL:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed


def make_archive(names, user=None):
    """把选中的图库文件打包成 ZIP；返回下载 token 和大小。

    只接受当前用户自己的文件（管理员可用全部），最多 200 个 / 4GB。
    图片本身已压缩，使用 ZIP_STORED 避免额外 CPU 和临时内存。
    """
    admin = user is None or is_admin(user)
    uid = (user or {}).get("id") or "admin"
    picked = []
    total = 0
    seen = set()
    for raw in names or []:
        rel = safe_media_rel(raw)
        if not rel or rel in seen:
            continue
        owner, _model, _fname = split_media_rel(rel)
        if (not admin and owner != uid
                and not teams.share_owner(uid, owner)):
            continue
        path = media_path(rel)
        if not path or not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if total + size > ARCHIVE_MAX_BYTES:
            break
        seen.add(rel)
        picked.append((rel, path, size))
        total += size
        if len(picked) >= ARCHIVE_MAX_FILES:
            break
    if not picked:
        return None, "没有可打包的文件"
    try:
        free = shutil.disk_usage(ARCHIVE_DIR if os.path.isdir(ARCHIVE_DIR)
                                 else DELIVER_DIR).free
    except OSError:
        free = total
    if free < total + 64 * 1024 * 1024:
        return None, "磁盘剩余空间不足，无法生成压缩包"
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    cleanup_archives()
    token = secrets.token_urlsafe(18)
    zip_path = os.path.join(ARCHIVE_DIR, token + ".zip")
    part_path = zip_path + ".part"
    display = "mobile-studio-%s.zip" % time.strftime("%Y%m%d-%H%M%S")
    try:
        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_STORED,
                             allowZip64=True) as zf:
            for rel, path, _size in picked:
                zf.write(path, arcname=rel)
        os.replace(part_path, zip_path)
    except Exception as exc:
        try:
            if os.path.isfile(part_path):
                os.remove(part_path)
        except OSError:
            pass
        return None, "打包失败：%s" % exc
    meta = {"token": token, "uid": uid, "created": time.time(),
            "display": display, "files": len(picked), "bytes": total}
    try:
        with open(_archive_meta_path(token), "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False)
    except Exception:
        pass
    return {
        "token": token,
        "url": "/archive/" + token,
        "name": display,
        "count": len(picked),
        "size": total,
    }, ""


def archive_download(token, user=None):
    """校验 token 和所有者，返回 (path, display_name)。"""
    token = str(token or "")
    if not ARCHIVE_TOKEN_RE.match(token):
        return None, None
    path = os.path.join(ARCHIVE_DIR, token + ".zip")
    if not os.path.isfile(path):
        return None, None
    try:
        with open(_archive_meta_path(token), "r", encoding="utf-8") as fh:
            meta = json.load(fh) or {}
    except Exception:
        meta = {}
    if not (user is None or is_admin(user)
            or meta.get("uid") == (user or {}).get("id")):
        return None, None
    return path, meta.get("display") or "mobile-studio.zip"


def find_image(name, user=None):
    """找原图；普通用户只能访问自己目录，管理员可以访问全部。"""
    rel = safe_media_rel(name)
    if not rel:
        return None
    admin = user is None or is_admin(user)
    owner, _model, _fname = split_media_rel(rel)
    viewer = (user or {}).get("id") or ""
    if not admin and owner != viewer and not teams.share_owner(viewer, owner):
        return None
    path = media_path(rel)
    if path and os.path.isfile(path):
        return path
    if admin:
        # 兼容 ComfyUI/output 里的原始文件（通常是平铺的文件名）
        fp = os.path.join(OUTPUT_DIR, os.path.basename(rel))
        if os.path.isfile(fp):
            return fp
    return None


def thumb_key(name):
    return hashlib.sha1(str(name).encode("utf-8")).hexdigest()[:20]


def video_first_frame(path):
    """取视频第一帧当缩略图（PyAV 随 ComfyUI 自带，不需要 ffmpeg.exe）。"""
    try:
        import av
        with av.open(path) as container:
            for frame in container.decode(video=0):
                return frame.to_image().convert("RGB")
    except Exception:
        pass
    return None


def thumb_path(name, user=None):
    """返回缩略图路径，没有就现生成并缓存。失败返回 None。"""
    rel = safe_media_rel(name)
    if not rel:
        return None
    src = find_image(rel, user)
    if not src:
        return None
    try:
        os.makedirs(THUMB_DIR, exist_ok=True)
        dst = os.path.join(THUMB_DIR, thumb_key(rel) + ".jpg")
        if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst
        from PIL import Image
        if os.path.splitext(rel)[1].lower() in VIDEO_EXT:
            im = video_first_frame(src)
            if im is None:
                return None
        else:
            im = Image.open(src).convert("RGB")
        if im.width > THUMB_WIDTH:
            ratio = THUMB_WIDTH / float(im.width)
            im = im.resize((THUMB_WIDTH, max(1, int(im.height * ratio))),
                           Image.LANCZOS)
        im.save(dst, "JPEG", quality=82, optimize=True)
        return dst
    except Exception:
        return None


def app_icon(size):
    """生成 PWA 图标（缓存到 .thumbs 里，不会被当成图片列出）。"""
    try:
        os.makedirs(THUMB_DIR, exist_ok=True)
        path = os.path.join(THUMB_DIR, "icon_%d.png" % size)
        if os.path.isfile(path):
            return path
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (size, size), (20, 22, 26))
        d = ImageDraw.Draw(im)
        m = int(size * 0.16)
        d.rounded_rectangle([m, m, size - m, size - m],
                            radius=int(size * 0.14), fill=(74, 124, 247))
        r = int(size * 0.17)
        cx, cy = size // 2, int(size * 0.52)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(20, 22, 26))
        d.ellipse([cx - int(r * 0.5), cy - int(r * 0.5),
                   cx + int(r * 0.5), cy + int(r * 0.5)], fill=(122, 162, 255))
        d.rounded_rectangle([int(size * 0.30), int(size * 0.22),
                             int(size * 0.48), int(size * 0.30)],
                            radius=int(size * 0.02), fill=(20, 22, 26))
        im.save(path, "PNG")
        return path
    except Exception:
        return None


# 提示词相关逻辑在 prompt_engine.py（翻译 / 角色词典 / 标签优化）
from prompt_engine import (
    translate_text, extract_char_tags, optimize_prompt,
    CHAR_ALIASES, CHAR_SERIES,
)


# --------------------------------------------------------------------- 图片加工

def _font(size):
    from PIL import ImageFont
    for f in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf",
              r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_collage(names, cols=2, user=None):
    """把若干张图拼成一张网格图（存到当前用户目录）。"""
    from PIL import Image
    imgs = []
    for n in (names or [])[:9]:
        p = find_image(n, user)
        if not p:
            continue
        try:
            imgs.append(Image.open(p).convert("RGB"))
        except Exception:
            continue
    if not imgs:
        return None
    cols = max(1, min(3, int(cols or 2)))
    rows = (len(imgs) + cols - 1) // cols
    cw, ch = 520, 730
    canvas = Image.new("RGB", (cw * cols, ch * rows), (18, 20, 24))
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        t = im.copy()
        t.thumbnail((cw - 10, ch - 10), Image.LANCZOS)
        x = c * cw + (cw - t.width) // 2
        y = r * ch + (ch - t.height) // 2
        canvas.paste(t, (x, y))
    uid = (user or {}).get("id") or "admin"
    name = "collage_%s_%d.png" % (time.strftime("%Y%m%d-%H%M%S"), len(imgs))
    rel = uid + "/misc/" + name
    path = media_path(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    canvas.save(path, "PNG")
    write_meta(rel, {"prompt": "拼图 · %d 张" % len(imgs), "kind": "collage"})
    return rel


def export_tagged(name, user=None):
    """导出带参数说明的图片（底部加一条信息栏）。"""
    from PIL import Image, ImageDraw
    src = find_image(name, user)
    if not src:
        return None
    try:
        im = Image.open(src).convert("RGB")
    except Exception:
        return None
    meta = read_meta(name)

    lines = []
    if meta.get("prompt"):
        lines.append(meta["prompt"])
    if meta.get("negative"):
        lines.append("负面: " + meta["negative"])
    bits = []
    if meta.get("model"):
        bits.append(meta["model"])
    if meta.get("steps"):
        bits.append("%s 步" % meta["steps"])
    if meta.get("cfg"):
        bits.append("CFG %s" % meta["cfg"])
    if meta.get("seed") is not None:
        bits.append("种子 %s" % meta["seed"])
    if meta.get("denoise") and meta["denoise"] < 1:
        bits.append("重绘 %s" % meta["denoise"])
    if bits:
        lines.append(" · ".join(bits))
    if not lines:
        return None

    fs = max(14, im.width // 46)
    font = _font(fs)
    pad = max(12, im.width // 50)
    # 粗略换行：中文按字数，英文按字符
    wrapped = []
    per = max(10, int(im.width / (fs * 1.05)))
    for ln in lines:
        while len(ln) > per:
            wrapped.append(ln[:per])
            ln = ln[per:]
        wrapped.append(ln)
    bar = int(fs * 1.6 * len(wrapped)) + pad * 2
    canvas = Image.new("RGB", (im.width, im.height + bar), (16, 18, 22))
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas)
    y = im.height + pad
    for ln in wrapped:
        d.text((pad, y), ln, fill=(198, 205, 214), font=font)
        y += int(fs * 1.6)
    uid = (user or {}).get("id") or "admin"
    out = "tagged_%s.png" % os.path.splitext(os.path.basename(name))[0]
    rel = uid + "/misc/" + out
    path = media_path(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    canvas.save(path, "PNG")
    write_meta(rel, dict(meta, kind="tagged",
                         prompt=(meta.get("prompt") or "") + "（带参数导出）"))
    return rel


def gallery_stats(user=None):
    """图库统计；普通用户只统计自己，管理员统计全部并附每人用量。"""
    user = user or {"id": "admin", "role": "admin"}
    admin = is_admin(user)
    uid = user.get("id") or "admin"
    items, total = list_gallery(0, 100000,
                                scope_uid=None if admin else uid,
                                fav_uid=uid)
    by_kind = {}
    for it in items:
        k = it.get("kind") or "anime"
        by_kind[k] = by_kind.get(k, 0) + 1
    folders = gallery_folders(None if admin else uid)
    by_folder = {}
    for f in folders:
        label = f["name"] if f["name"] not in ("", "misc") else "未分类"
        by_folder[label] = by_folder.get(label, 0) + f["count"]
    by_user = {}
    users_info = []
    if admin:
        users_info = gallery_users()
        for u in users_info:
            by_user[u.get("name") or u.get("username") or u["id"]] = u["count"]
    disk = 0
    roots = [DELIVER_DIR] if admin else [user_gallery_root(uid)]
    for root_base in roots:
        if not os.path.isdir(root_base):
            continue
        for root, dirs, files in os.walk(root_base):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                if fn.startswith(".") or not fn.lower().endswith(MEDIA_EXT):
                    continue
                try:
                    disk += os.path.getsize(os.path.join(root, fn))
                except Exception:
                    pass
    isolation_mb = 0
    isolation_files = 0
    isolation_pending = 0
    isolation_legacy = 0
    iso_roots = [UPLOAD_DIR] if admin else [user_upload_root(uid)]
    for iso_root in iso_roots:
        if not os.path.isdir(iso_root):
            continue
        for root, _dirs, files in os.walk(iso_root):
            rel = os.path.relpath(root, iso_root)
            is_legacy = "_legacy" in rel.split(os.sep)
            for fn in files:
                if fn.startswith("."):
                    continue
                try:
                    isolation_mb += os.path.getsize(os.path.join(root, fn))
                    isolation_files += 1
                    if is_legacy:
                        isolation_legacy += 1
                    else:
                        isolation_pending += 1
                except Exception:
                    pass
    staged_input = 0
    try:
        staged_input = sum(1 for fn in os.listdir(INPUT_DIR)
                           if fn.startswith(INPUT_STAGE_PREFIX))
    except OSError:
        pass
    durs = [round(d[3], 1) for d in DURATIONS]
    models = list_models()
    if not admin:
        allowed = user_limits(user).get("allowed_models") or []
        if allowed:
            models = [m for m in models
                      if m.get("name") in allowed
                      or os.path.splitext(str(m.get("name")))[0] in allowed]
    return {
        "total": total,
        "by_kind": by_kind,
        "by_folder": by_folder,
        "by_user": by_user,
        "folders": folders,
        "users": users_info,
        "disk_mb": round(disk / 1048576, 1),
        "isolation_mb": round(isolation_mb / 1048576, 2),
        "isolation_files": isolation_files,
        "isolation_pending": isolation_pending,
        "isolation_legacy": isolation_legacy,
        "staged_input": staged_input,
        "avg_seconds": round(sum(durs) / len(durs), 1) if durs else None,
        "recent_seconds": durs[-8:],
        "models": [{"label": m["label"], "name": m["name"]} for m in models],
    }


# --------------------------------------------------------------------- 监控中心

_STORAGE_CACHE = {"t": 0.0, "data": None}
_STORAGE_LOCK = threading.Lock()


def storage_forecast(force=False):
    """图库增长与磁盘余量预测；60 秒缓存。"""
    now = time.time()
    with _STORAGE_LOCK:
        if (not force and _STORAGE_CACHE["data"] is not None
                and now - _STORAGE_CACHE["t"] < 60):
            return dict(_STORAGE_CACHE["data"])
    day_keys = []
    for i in range(6, -1, -1):
        day_keys.append(time.strftime("%Y-%m-%d",
                                      time.localtime(now - i * 86400)))
    day_bytes = {k: 0 for k in day_keys}
    total_bytes = 0
    total_images = 0
    newest = 0.0
    try:
        for root, dirs, files in os.walk(DELIVER_DIR):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                if fn.startswith(".") or not fn.lower().endswith(MEDIA_EXT):
                    continue
                path = os.path.join(root, fn)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                total_bytes += st.st_size
                total_images += 1
                newest = max(newest, st.st_mtime)
                key = time.strftime("%Y-%m-%d", time.localtime(st.st_mtime))
                if key in day_bytes:
                    day_bytes[key] += st.st_size
    except OSError:
        pass
    try:
        usage = shutil.disk_usage(DELIVER_DIR)
        free_bytes, total_disk = usage.free, usage.total
    except OSError:
        free_bytes = total_disk = 0
    avg_bytes = sum(day_bytes.values()) / max(1, len(day_bytes))
    days_left = (free_bytes / avg_bytes) if avg_bytes > 0 else None
    if days_left is not None:
        days_left = round(days_left, 1)
    top_users = []
    try:
        for u in gallery_users()[:5]:
            top_users.append({"name": u.get("name") or u.get("username")
                              or u.get("id"), "count": u.get("count", 0),
                              "mb": round((u.get("bytes") or 0) / 1048576, 1)})
    except Exception:
        pass
    data = {
        "total_images": total_images,
        "total_mb": round(total_bytes / 1048576, 1),
        "free_gb": round(free_bytes / 1073741824, 2),
        "disk_total_gb": round(total_disk / 1073741824, 2),
        "avg_mb_per_day": round(avg_bytes / 1048576, 1),
        "days_left": days_left,
        "top_users": top_users,
        "daily": [{"date": k, "mb": round(day_bytes[k] / 1048576, 1)}
                  for k in day_keys],
        "newest": newest,
        "updated": round(now, 3),
    }
    with _STORAGE_LOCK:
        _STORAGE_CACHE.update(t=now, data=data)
    return dict(data)


CLEANUP_LOCK = threading.Lock()
CLEANUP_AUTO = {"last_check": 0.0}


def cleanup_overview():
    """管理员清理面板用的实时概况。"""
    cfg = disk_cleanup.load()
    storage = storage_forecast(force=True)
    candidates = disk_cleanup.gallery_candidates(
        DELIVER_DIR, cfg.get("retention_days"),
        cfg.get("max_files_per_run"), cfg.get("include_videos"))
    out_bytes = 0
    if cfg.get("include_comfy_output"):
        out_bytes = sum(x.get("size") or 0 for x in
                        disk_cleanup.output_candidates(
                            OUTPUT_DIR, cfg.get("retention_days"),
                            cfg.get("max_files_per_run"),
                            cfg.get("include_videos")))
    return {
        "settings": disk_cleanup.public_settings(cfg),
        "storage": storage,
        "candidate_count": len(candidates),
        "candidate_mb": round(sum(x.get("size") or 0 for x in candidates)
                              / 1048576, 1),
        "output_candidate_mb": round(out_bytes / 1048576, 1),
    }


def run_disk_cleanup(trigger="manual", free_bytes=None, user=None):
    """执行一次清理；trigger=auto 时只在低于 min_free_gb 才动手。"""
    with CLEANUP_LOCK:
        cfg = disk_cleanup.load(force=True)
        try:
            usage = shutil.disk_usage(DELIVER_DIR)
            free = float(free_bytes if free_bytes is not None else usage.free)
        except OSError:
            free = float(free_bytes or 0)
        now = time.time()
        free_gb = free / 1073741824.0
        target_gb = float(cfg.get("target_free_gb") or 20)
        min_gb = float(cfg.get("min_free_gb") or 10)

        def done(result):
            result.setdefault("time", now)
            result.setdefault("trigger", trigger)
            result.setdefault("free_before_gb", round(free_gb, 2))
            result.setdefault("free_after_gb", round(free_gb, 2))
            result.setdefault("target_gb", target_gb)
            result.setdefault("retention_days", cfg.get("retention_days"))
            result.setdefault("deleted_images", 0)
            result.setdefault("deleted_outputs", 0)
            result.setdefault("freed_mb", 0)
            disk_cleanup.save({"last_run": now, "last_result": result})
            return result

        if trigger == "auto" and not cfg.get("enabled"):
            return {"skipped": "disabled"}
        if trigger == "auto" and free_gb >= min_gb:
            return done({"skipped": "space_ok"})
        if trigger != "auto" and free_gb >= target_gb:
            return done({"skipped": "space_ok"})
        need = max(0, int(target_gb * 1073741824 - free))
        if need <= 0:
            return done({"skipped": "space_ok"})
        max_files = int(cfg.get("max_files_per_run") or 500)
        gallery = disk_cleanup.gallery_candidates(
            DELIVER_DIR, cfg.get("retention_days"), max_files,
            cfg.get("include_videos"), now)
        outputs = []
        if cfg.get("include_comfy_output"):
            outputs = disk_cleanup.output_candidates(
                OUTPUT_DIR, cfg.get("retention_days"), max_files,
                cfg.get("include_videos"), now)
        combined = sorted(gallery + outputs,
                          key=lambda x: x.get("mtime") or 0)
        picked, planned = disk_cleanup.plan(need, combined)
        gallery_picked = [x for x in picked
                          if x.get("source") != "output"]
        output_picked = [x for x in picked if x.get("source") == "output"]
        names = [x["rel"] for x in gallery_picked]
        removed = delete_images(names, None) if names else []
        removed_set = set(removed)
        freed = sum(x.get("size") or 0 for x in gallery_picked
                    if x["rel"] in removed_set)
        removed_outputs = 0
        for item in output_picked:
            path = os.path.join(OUTPUT_DIR, item["rel"])
            try:
                if os.path.isfile(path):
                    os.remove(path)
                    removed_outputs += 1
                    freed += int(item.get("size") or 0)
            except OSError:
                pass
        if free_bytes is None:
            try:
                free_after = shutil.disk_usage(DELIVER_DIR).free
            except OSError:
                free_after = free + freed
        else:
            free_after = free + freed
        result = {
            "time": now,
            "trigger": trigger,
            "free_before_gb": round(free_gb, 2),
            "free_after_gb": round(free_after / 1073741824.0, 2),
            "target_gb": target_gb,
            "retention_days": cfg.get("retention_days"),
            "deleted_images": len(removed),
            "deleted_outputs": removed_outputs,
            "freed_mb": round(freed / 1048576.0, 1),
            "candidate_count": len(combined),
            "planned_mb": round(planned / 1048576.0, 1),
            "skipped": "",
        }
        if not picked:
            result["note"] = "没有符合条件的旧文件"
        disk_cleanup.save({"last_run": now, "last_result": result})
        try:
            audit("activity", "disk_cleanup", user=user, trigger=trigger,
                  deleted=len(removed) + removed_outputs,
                  freed_mb=result["freed_mb"])
        except Exception:
            pass
        return result


def ensure_cleanup_thread():
    """后台清理线程；默认关闭，只有管理员开启后才会真正删除。"""
    def loop():
        while True:
            try:
                cfg = disk_cleanup.load()
                if cfg.get("enabled"):
                    now = time.time()
                    if now - float(cfg.get("last_run") or 0) >= 6 * 3600:
                        run_disk_cleanup("auto")
            except Exception:
                pass
            time.sleep(900)

    threading.Thread(target=loop, daemon=True,
                     name="disk-cleanup").start()


def monitor_snapshot():
    """给告警 / 健康分 / Prometheus 用的安全快照。"""
    now = time.time()
    with LOAD_LOCK:
        load = dict(LOAD_STATE)
    with JOBS_LOCK:
        jobs = [dict(j, job_id=jid) for jid, j in JOBS.items()]
    workers = []
    for w in lan_share.list_workers():
        workers.append({
            "id": w.get("id") or "",
            "name": w.get("name") or w.get("id") or "",
            "status": w.get("status") or "",
            "owner_id": w.get("owner_id") or "",
            "last_seen": w.get("last_seen") or 0,
            "current_job": w.get("current_job") or "",
            "online": bool(lan_share._online(w)),
            "comfy_busy": bool(w.get("comfy_busy")),
        })
    approved = [w for w in workers if w.get("status") == "approved"]
    recent = [j for j in jobs
              if float(j.get("finished_at") or j.get("started") or
                       j.get("queued_at") or 0) >= now - 600]
    terminal = [j for j in recent
                if j.get("status") in ("done", "error", "cancelled")]
    errors = [j for j in terminal if j.get("status") == "error"]
    try:
        q = scheduler_snapshot()
        queue_size = int(q.get("size") or 0)
        running_count = len(q.get("running") or [])
    except Exception:
        queue_size = sum(1 for j in jobs if j.get("status") == "queued")
        running_count = sum(1 for j in jobs if j.get("status") == "running")
    storage = storage_forecast()
    try:
        comfy_ready = local_comfy_alive()
    except Exception:
        comfy_ready = False
    return {
        "now": now,
        "gpu_util": load.get("gpu"),
        "vram_used_mb": load.get("vram_used"),
        "vram_total_mb": load.get("vram_total"),
        "gpu_temp_c": load.get("gpu_temp"),
        "cpu_percent": load.get("cpu"),
        "ram_percent": load.get("ram_percent"),
        "queue_size": queue_size,
        "running_count": running_count,
        "comfy_ready": comfy_ready,
        "local_enabled": bool(lan_share.settings().get("local_enabled", True)),
        "workers": workers,
        "workers_total": len(approved),
        "workers_online": sum(1 for w in approved if w.get("online")),
        "jobs": [{"job_id": j.get("job_id"), "status": j.get("status"),
                  "started": j.get("started"),
                  "queued_at": j.get("queued_at"),
                  "user_id": j.get("user_id")}
                 for j in jobs if j.get("status") == "running"][:30],
        "job_count_10m": len(terminal),
        "error_count_10m": len(errors),
        "disk_free_gb": storage.get("free_gb"),
        "gallery_images": storage.get("total_images"),
        "cert_days": certificate_days_left(),
        "storage": storage,
    }


def _version_lock_info():
    lock_paths = (os.path.join(ROOT, "installer", "versions.lock.json"),
                  os.path.join(ROOT, "versions.lock.json"))
    lock = {}
    for p in lock_paths:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    lock = json.load(fh) or {}
            except Exception:
                lock = {}
            break
    actual = ""
    try:
        with open(os.path.join(ROOT, "ComfyUI", "comfyui_version.py"),
                  "r", encoding="utf-8") as fh:
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", fh.read())
            actual = m.group(1) if m else ""
    except Exception:
        pass
    want = str((lock.get("comfyui") or {}).get("version") or "")
    return {"lock": lock, "expected": want, "actual": actual}


def diagnose_system():
    """管理员一键诊断；只返回检查结果，不改任何东西。"""
    checks = []
    now = time.time()

    def add(name, level, title, detail, hint="", title_en="",
            detail_en="", hint_en=""):
        checks.append({
            "id": name, "level": level, "title": title,
            "detail": detail, "hint": hint,
            "title_en": title_en or title,
            "detail_en": detail_en or detail,
            "hint_en": hint_en or hint,
        })

    try:
        comfy = local_comfy_alive(force=True)
    except Exception:
        comfy = False
    add("comfy", "ok" if comfy else "error", "ComfyUI 连接",
        "本机 ComfyUI 正常响应。" if comfy else "本机 ComfyUI 没有响应。",
        "" if comfy else "检查 8188 端口和 ComfyUI 窗口。",
        "ComfyUI connection",
        "Local ComfyUI responded normally." if comfy
        else "Local ComfyUI is not responding.",
        "" if comfy else "Check port 8188 and the ComfyUI window.")
    models = list_models()
    add("models", "ok" if models else "error", "底模文件",
        "发现 %d 个可用底模。" % len(models) if models else "没有找到可用底模。",
        "运行模型下载.bat。" if not models else "",
        "Checkpoint files",
        ("%d usable checkpoints found." % len(models)) if models
        else "No usable checkpoints found.",
        "Run 模型下载.bat." if not models else "")
    if models:
        add("anima", "ok" if anima_ready() else "warn", "Anima 三件套",
            "Anima UNet / 文本编码器 / VAE 齐全。" if anima_ready()
            else "Anima 组件不完整。",
            "" if anima_ready()
            else "检查 diffusion_models、text_encoders、vae。",
            "Anima components",
            "Anima UNet / text encoder / VAE are present."
            if anima_ready() else "Anima components are incomplete.",
            "" if anima_ready()
            else "Check diffusion_models, text_encoders and vae.")
    if video_ready() or i2v_ready():
        add("video", "ok", "Wan 视频模型",
            "文生视频 / 图生视频组件已就绪。", "",
            "Wan video models",
            "Text-to-video / image-to-video components are ready.", "")
    else:
        add("video", "info", "Wan 视频模型",
            "没有检测到完整的 Wan 视频组件。", "不跑视频可以忽略。",
            "Wan video models",
            "No complete Wan video components found.",
            "Ignore this if you do not use video.")
    node_dirs = []
    try:
        node_dirs = [d for d in os.listdir(os.path.join(ROOT, "ComfyUI",
                                                        "custom_nodes"))
                     if os.path.isdir(os.path.join(ROOT, "ComfyUI",
                                                   "custom_nodes", d))
                     and not d.startswith("__")]
    except OSError:
        pass
    add("nodes", "ok" if node_dirs else "warn", "自定义节点",
        "已安装 %d 个自定义节点目录。" % len(node_dirs) if node_dirs
        else "没有检测到自定义节点。",
        "至少需要 UltimateSDUpscale / AlekPet。" if not node_dirs else "",
        "Custom nodes",
        ("%d custom node folders installed." % len(node_dirs))
        if node_dirs else "No custom nodes detected.",
        "UltimateSDUpscale / AlekPet are recommended."
        if not node_dirs else "")
    workers = lan_share.admin_payload().get("workers") or []
    approved = [w for w in workers if w.get("status") == "approved"]
    offline = [w for w in approved if not w.get("online")]
    pending = [w for w in workers if w.get("status") == "pending"]
    if offline:
        add("workers", "warn" if len(offline) < len(approved) else "error",
            "算力节点",
            "%d 台已批准节点中 %d 台离线。" % (len(approved), len(offline)),
            "检查节点电脑、热点和 worker 窗口。",
            "Compute nodes",
            "%d of %d approved nodes are offline." %
            (len(offline), len(approved)),
            "Check the worker PC, hotspot and worker window.")
    elif approved:
        add("workers", "ok", "算力节点",
            "%d 台已批准节点在线。" % len(approved), "",
            "Compute nodes",
            "%d approved nodes online." % len(approved), "")
    else:
        add("workers", "info", "算力节点",
            "没有局域网节点；当前只使用本机。" +
            (" 另有 %d 台待审批。" % len(pending) if pending else ""), "",
            "Compute nodes",
            "No LAN nodes; using this PC only." +
            (" %d pending approval." % len(pending) if pending else ""), "")
    with JOBS_LOCK:
        jobs = [dict(j, job_id=jid) for jid, j in JOBS.items()]
    running = [j for j in jobs if j.get("status") == "running"]
    stuck = [j for j in running
             if now - float(j.get("started") or now) > 20 * 60]
    queued = sum(1 for j in jobs if j.get("status") == "queued")
    add("queue", "warn" if stuck else "ok", "任务队列",
        "运行 %d 个，排队 %d 个%s。" %
        (len(running), queued,
         "，其中 %d 个运行超过 20 分钟" % len(stuck) if stuck else ""),
        "卡住时可查看任务时间线或取消任务。" if stuck else "",
        "Job queue",
        "Running %d, queued %d%s." %
        (len(running), queued,
         ", %d running over 20 minutes" % len(stuck) if stuck else ""),
        "Check the job timeline or cancel a stuck job." if stuck else "")
    storage = storage_forecast(force=True)
    free_gb = float(storage.get("free_gb") or 0)
    total_mb = float(storage.get("total_mb") or 0)
    size_text = ("%.0f MB" % total_mb) if total_mb < 1024 \
        else ("%.1f GB" % (total_mb / 1024))
    days_left = storage.get("days_left")
    days_text = "空间充足" if days_left is None or days_left > 3650 \
        else ("还能用 %.1f 天" % days_left)
    days_text_en = "plenty of space" if days_left is None or days_left > 3650 \
        else ("about %.1f days left" % days_left)
    level = "critical" if free_gb < 5 else "warn" if free_gb < 10 else "ok"
    add("storage", level, "磁盘空间",
        "图库占用 %s，磁盘剩余 %.1f GB，预计%s。" %
        (size_text, free_gb, days_text),
        "清理旧图或扩容。" if level != "ok" else "",
        "Disk space",
        "Gallery uses %s, %.1f GB free, %s." %
        (size_text, free_gb, days_text_en),
        "Clean old images or add storage." if level != "ok" else "")
    days = certificate_days_left()
    level = "critical" if days is not None and days < 7 else \
        "warn" if days is not None and days < 30 else "ok"
    add("cert", level, "HTTPS 证书",
        ("证书还剩 %.0f 天。" % days) if days is not None
        else "没有解析到证书有效期。",
        "运行 安全设置.bat 选 3 重新生成。" if level != "ok" else "",
        "HTTPS certificate",
        ("Certificate has %.0f days left." % days) if days is not None
        else "Could not read certificate validity.",
        "Run 安全设置.bat and choose 3 to regenerate."
        if level != "ok" else "")
    temp_files = 0
    try:
        temp_files = sum(1 for fn in os.listdir(INPUT_DIR)
                         if fn.startswith(INPUT_STAGE_PREFIX))
    except OSError:
        pass
    add("temp", "warn" if temp_files > 20 else "ok", "临时上传文件",
        "ComfyUI/input 里还有 %d 个临时文件。" % temp_files,
        "任务结束后会自动清理；持续堆积可重启服务。" if temp_files > 20 else "",
        "Temporary uploads",
        "%d temporary files remain in ComfyUI/input." % temp_files,
        "They are cleaned after jobs; restart the service if they accumulate."
        if temp_files > 20 else "")
    tr = translation_status()
    add("translate", "ok" if tr.get("ready") else "info", "翻译组件",
        "Argos %s，本地模型 %s。" %
        ("可用" if tr.get("argos_ready") else "不可用",
         "已启用" if tr.get("local_ready") else "未启用"),
        "中文提示词需要其中之一。" if not tr.get("ready") else "",
        "Translation components",
        "Argos %s, local model %s." %
        ("available" if tr.get("argos_ready") else "unavailable",
         "enabled" if tr.get("local_ready") else "disabled"),
        "Chinese prompts need one of them." if not tr.get("ready") else "")
    ver = _version_lock_info()
    if ver["expected"]:
        same = bool(ver["actual"]) and (
            ver["actual"].startswith(ver["expected"]) or
            ver["expected"].startswith(ver["actual"]))
        add("version", "ok" if same else "warn", "ComfyUI 版本",
            "锁定 %s，当前 %s。" % (ver["expected"],
                                   ver["actual"] or "未知"),
            "版本不一致时先看 VERSION_LOCK.md。" if not same else "",
            "ComfyUI version",
            "Locked %s, current %s." % (ver["expected"],
                                        ver["actual"] or "unknown"),
            "See VERSION_LOCK.md if versions differ." if not same else "")
    summary = {"ok": 0, "info": 0, "warn": 0, "error": 0, "critical": 0}
    for c in checks:
        summary[c["level"]] = summary.get(c["level"], 0) + 1
    return {"generated": now, "checks": checks, "summary": summary,
            "version": ver["actual"], "version_lock": ver["expected"]}


def app_version():
    for name in ("VERSION", "VERSION.txt"):
        try:
            with open(os.path.join(ROOT, name), "r", encoding="utf-8") as fh:
                value = (fh.read() or "").strip()
            if value:
                return value
        except OSError:
            continue
    return "dev"


def collect_health_report():
    """采集一键体检数据；不读取密码哈希、API Key 或授权码原文。"""
    now = time.time()
    snap = monitor_snapshot()
    diag = diagnose_system()
    storage = storage_forecast(force=True)
    cleanup = cleanup_overview()
    lic = license_guard.status(force=True)
    try:
        worker_payload = lan_share.admin_payload()
        workers = []
        for w in worker_payload.get("workers") or []:
            workers.append({
                "id": w.get("id") or "",
                "name": w.get("name") or "",
                "status": w.get("status") or "",
                "online": bool(w.get("online")),
                "gpu_name": w.get("gpu_name") or "",
                "gpu_util": w.get("gpu_util"),
                "vram_used_mb": w.get("vram_used_mb"),
                "gpu_temp_c": w.get("gpu_temp_c"),
                "current_job": w.get("current_job") or "",
                "comfy_ready": bool(w.get("comfy_ready")),
            })
    except Exception:
        workers = []
    with LOAD_LOCK:
        load = dict(LOAD_STATE)
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        started = proc.create_time()
        cpu_count = psutil.cpu_count() or 0
    except Exception:
        started = 0
        cpu_count = 0
    safe_snap = {
        "cpu_percent": snap.get("cpu_percent"),
        "cpu_count": cpu_count,
        "ram_percent": snap.get("ram_percent"),
        "gpu_name": load.get("gpu_name") or "",
        "gpu_util": snap.get("gpu_util"),
        "vram_used_mb": snap.get("vram_used_mb"),
        "vram_total_mb": snap.get("vram_total_mb"),
        "gpu_temp_c": snap.get("gpu_temp_c"),
        "queue_size": snap.get("queue_size"),
        "running_count": snap.get("running_count"),
        "comfy_ready": snap.get("comfy_ready"),
        "workers_total": snap.get("workers_total"),
        "workers_online": snap.get("workers_online"),
        "disk_free_gb": snap.get("disk_free_gb"),
        "cert_days": snap.get("cert_days"),
        "job_count_10m": snap.get("job_count_10m"),
        "error_count_10m": snap.get("error_count_10m"),
        "gallery_images": snap.get("gallery_images"),
    }
    logs = {}
    for category in ("activity", "security"):
        try:
            rows = read_audit(category, 200)
            logs[category] = [
                json.dumps(x, ensure_ascii=False, default=str) for x in rows
            ]
        except Exception:
            logs[category] = []
    with USERS_LOCK:
        user_count = len(USERS)
        guest_count = sum(1 for u in USERS.values() if u.get("guest"))
    return {
        "generated": now,
        "app": {
            "version": app_version(),
            "edition": license_guard.edition(),
            "pid": os.getpid(),
            "started": started,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "health": monitor_center.health(snap),
        "diagnostics": diag,
        "snapshot": safe_snap,
        "storage": storage,
        "cleanup": {
            "settings": cleanup.get("settings") or {},
            "candidate_count": cleanup.get("candidate_count") or 0,
            "candidate_mb": cleanup.get("candidate_mb") or 0,
        },
        "license": lic,
        "models": model_manager.list_all(),
        "workers": workers,
        "jobs": monitor_recent_jobs(
            {"id": "admin", "role": "admin", "enabled": True}, 20),
        "alerts": monitor_center.active_alerts(),
        "counts": {"users": user_count, "guests": guest_count},
        "config": {
            "monitor": monitor_center.public_settings(),
            "translation": local_llm.public_config(),
        },
        "logs": logs,
    }


def build_health_report():
    data = collect_health_report()
    filename = "health-report-%s.zip" % time.strftime("%Y%m%d-%H%M%S")
    return health_report.build_zip(data), filename


def job_timeline(jid, user):
    """任务阶段耗时；普通账号只能看自己的任务。"""
    jid = str(jid or "")
    with JOBS_LOCK:
        job = dict(JOBS.get(jid) or {})
    if not job:
        return None
    if not is_admin(user) and job.get("user_id") != (user or {}).get("id"):
        return None
    now = time.time()
    queued = float(job.get("queued_at") or 0)
    dispatched = float(job.get("dispatched_at") or job.get("started") or 0)
    submitted = float(job.get("submitted_at") or 0)
    finished = float(job.get("finished_at") or 0)
    saved = float(job.get("saved_at") or 0)
    stages = []
    def stage(key, label, a, b, status="ok"):
        if not a:
            return
        end = b or now
        stages.append({"key": key, "label": label,
                       "seconds": round(max(0, end - a), 1),
                       "status": status})
    stage("queue", "排队", queued, dispatched or submitted)
    stage("dispatch", "派发 / 准备", dispatched, submitted)
    stage("sample", "采样 / 执行", submitted,
          finished or (saved or now),
          "error" if job.get("status") == "error" else "ok")
    if finished or saved:
        stage("save", "保存图库", finished or submitted, saved or finished)
    return {
        "job_id": jid,
        "status": job.get("status") or "",
        "kind": job.get("kind") or "",
        "mode": job.get("mode") or "",
        "model": os.path.basename(job.get("model") or ""),
        "worker_name": job.get("worker_name") or "本机",
        "worker_kind": job.get("worker_kind") or "local",
        "attempt": int(job.get("attempt") or 0),
        "retry_count": int(job.get("retry_count") or 0),
        "elapsed": round(float(job.get("elapsed") or 0), 1),
        "total": round(max(0, (saved or finished or now) - (queued or now)), 1),
        "stages": stages,
        "error": str(job.get("error") or "")[:240],
        "images": len(job.get("images") or []),
        "started": job.get("started") or 0,
        "finished": job.get("finished_at") or 0,
        "user": job.get("username") or "",
        "user_name": job.get("user_name") or "",
    }


def monitor_recent_jobs(user, limit=20):
    admin = is_admin(user)
    uid = (user or {}).get("id") or ""
    with JOBS_LOCK:
        rows = [dict(j, job_id=jid) for jid, j in JOBS.items()
                if admin or j.get("user_id") == uid]
    rows.sort(key=lambda j: float(j.get("started") or
                                  j.get("queued_at") or 0), reverse=True)
    out = []
    for j in rows[:max(1, min(50, int(limit or 20)))]:
        out.append({
            "job_id": j.get("job_id"),
            "status": j.get("status") or "",
            "kind": j.get("kind") or "",
            "model": os.path.basename(j.get("model") or ""),
            "worker_name": j.get("worker_name") or "",
            "elapsed": round(float(j.get("elapsed") or 0), 1),
            "started": j.get("started") or 0,
            "error": str(j.get("error") or "")[:160],
            "user": j.get("username") or "",
        })
    return out


# --------------------------------------------------------------------- 用户配额

def user_usage(uid):
    """用户图库用量：图片数、占用字节、今天新增、正在跑的任务数。"""
    uid = safe_uid(uid) or "admin"
    root = user_gallery_root(uid)
    today = trusted_time.strftime("%Y-%m-%d")
    images = 0
    total = 0
    today_count = 0
    if os.path.isdir(root):
        for walk_root, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fn in files:
                if fn.startswith(".") or not fn.lower().endswith(MEDIA_EXT):
                    continue
                fp = os.path.join(walk_root, fn)
                images += 1
                try:
                    total += os.path.getsize(fp)
                    if time.strftime("%Y-%m-%d",
                                     time.localtime(os.path.getmtime(fp))) == today:
                        today_count += 1
                except Exception:
                    pass
    running = 0
    queued = 0
    with JOBS_LOCK:
        for job in JOBS.values():
            if job.get("user_id") != uid:
                continue
            if job.get("status") == "running":
                running += 1
            elif job.get("status") == "queued":
                queued += 1
    snap = usage_snapshot(uid)
    # 文件 mtime 会被系统时间影响；用量账本按可信时间记账，取两者较大值，
    # 防止把时钟往回拨后“今天”的图片数突然归零。
    today_count = max(today_count, int(snap["today"].get("images") or 0))
    return {
        "images": images, "bytes": total, "today": today_count,
        "running": running, "queued": queued, "active": running + queued,
        "traffic_today": snap["traffic_today"],
        "traffic_month": snap["traffic_month"],
        "traffic_total": snap["traffic_total"],
        "traffic_today_mb": round(snap["traffic_today"] / 1048576, 2),
        "traffic_month_mb": round(snap["traffic_month"] / 1048576, 2),
        "requests_today": snap["today"].get("requests", 0),
        "gpu_seconds_today": round(snap["today"].get("gpu_seconds", 0), 1),
        "gpu_seconds_month": round(snap["month"].get("gpu_seconds", 0), 1),
        "images_month": snap["month"].get("images", 0),
        "jobs_month": snap["month"].get("jobs", 0),
        "train_seconds_today": snap.get("train_seconds_today", 0),
        "train_seconds_month": snap.get("train_seconds_month", 0),
        "train_jobs_today": snap.get("train_jobs_today", 0),
        "train_jobs_month": snap.get("train_jobs_month", 0),
    }


def user_limits(user):
    if is_admin(user):
        return dict(ADMIN_DEFAULT_LIMITS)
    return normalize_limits((user or {}).get("limits"), "user")


def feature_allowed(user, key):
    """管理员或未被关闭该功能的普通账号。"""
    if is_admin(user):
        return True
    return bool(user_limits(user).get("features", {}).get(key, True))


def check_feature(user, key):
    if feature_allowed(user, key):
        return None
    return "管理员暂时关闭了你的「%s」功能。" % FEATURE_LABELS.get(key, key)


def _quota(kind, label, used, limit, unit, reset=None, action=None):
    return {
        "kind": kind, "label": label,
        "used": round(float(used), 2) if isinstance(used, float) else int(used),
        "limit": int(limit), "unit": unit,
        "reset": reset, "action": action,
    }


def traffic_quota_detail(user):
    """普通账号的每日 / 每月流量额度；返回 (提示, 结构化配额)。"""
    if is_admin(user):
        return None, None
    uid = (user or {}).get("id") or ""
    lim = user_limits(user)
    snap = usage_snapshot(uid)
    daily = int(lim.get("daily_traffic_mb") or 0)
    used_mb = snap["traffic_today"] / 1048576.0
    if daily > 0 and snap["traffic_today"] >= daily * 1048576:
        return ("今天的流量额度用完了（每天 %d MB）。" % daily,
                _quota("daily_traffic_mb", "今日流量", used_mb, daily, "MB",
                       reset="daily"))
    monthly = int(lim.get("monthly_traffic_mb") or 0)
    used_month = snap["traffic_month"] / 1048576.0
    if monthly > 0 and snap["traffic_month"] >= monthly * 1048576:
        return ("本月流量额度用完了（每月 %d MB）。" % monthly,
                _quota("monthly_traffic_mb", "本月流量", used_month, monthly,
                       "MB", reset="monthly"))
    return None, None


def traffic_quota_message(user):
    return traffic_quota_detail(user)[0]


def check_user_limits_detail(user, ckpt, is_video=False, steps=0, count=1,
                             kind="gen", eta=0):
    """返回 (中文拦截原因, 结构化配额)；放行时返回 (None, None)。

    eta 是本次任务的预计 GPU 秒数；用于按 GPU 时间配额预检查。
    """
    if is_admin(user):
        return None, None
    lim = user_limits(user)
    if kind == "upscale" and not feature_allowed(user, "upscale"):
        return "管理员暂时关闭了你的「放大」功能。", None
    if is_video and not feature_allowed(user, "video"):
        return "管理员暂时关闭了你的「视频生成」功能。", None
    if kind == "auto" and not feature_allowed(user, "auto"):
        return "管理员暂时关闭了你的「挂机造图」功能。", None
    allowed = (lim.get("allowed_models") or []) if not is_video else []
    if allowed:
        base = os.path.basename(str(ckpt or ""))
        if base not in allowed and os.path.splitext(base)[0] not in allowed:
            return "当前底模不在管理员允许的模型列表里。", None
    max_steps = int(lim.get("max_steps") or 0)
    if max_steps > 0 and steps > max_steps:
        return ("步数超过上限（管理员限制 %d 步）。" % max_steps,
                _quota("max_steps", "单次步数", steps, max_steps, "步",
                       action="settings"))
    max_count = int(lim.get("max_count") or 0)
    if kind == "gen" and max_count > 0 and count > max_count:
        return ("一次生成张数超过上限（管理员限制 %d 张）。" % max_count,
                _quota("max_count", "单次张数", count, max_count, "张",
                       action="settings"))
    usage = user_usage(user.get("id"))
    max_concurrent = int(lim.get("max_concurrent") or 0)
    active_jobs = usage.get("active", usage.get("running", 0))
    if max_concurrent > 0 and active_jobs >= max_concurrent:
        return ("你已经有 %d 个任务在排队或运行，等完成再提交。" % active_jobs,
                _quota("max_concurrent", "同时任务", active_jobs,
                       max_concurrent, "个", reset="active"))
    daily = int(lim.get("daily_images") or 0)
    if daily > 0 and usage["today"] + count > daily:
        return ("今天的出图额度用完了（每天 %d 张）。" % daily,
                _quota("daily_images", "今日出图", usage["today"], daily,
                       "张", reset="daily", action="gallery"))
    max_images = int(lim.get("max_images") or 0)
    if max_images > 0 and usage["images"] + count > max_images:
        return ("图库数量到上限了（最多 %d 张），先删一些旧图。" % max_images,
                _quota("max_images", "图库数量", usage["images"], max_images,
                       "张", action="gallery"))
    max_storage = int(lim.get("max_storage_mb") or 0)
    if max_storage > 0 and usage["bytes"] >= max_storage * 1048576:
        return ("占用空间到上限了（最多 %d MB），先清理旧图。" % max_storage,
                _quota("max_storage_mb", "图库空间",
                       usage["bytes"] / 1048576.0, max_storage, "MB",
                       action="gallery"))
    try:
        eta = max(0.0, float(eta or 0))
    except Exception:
        eta = 0.0
    daily_gpu = int(lim.get("daily_gpu_seconds") or 0)
    if daily_gpu > 0 and usage["gpu_seconds_today"] + eta > daily_gpu:
        return ("今天的 GPU 时间额度用完了（每天 %d 秒）。" % daily_gpu,
                _quota("daily_gpu_seconds", "今日 GPU 时间",
                       usage["gpu_seconds_today"], daily_gpu, "秒",
                       reset="daily"))
    monthly_gpu = int(lim.get("monthly_gpu_seconds") or 0)
    if monthly_gpu > 0 and usage["gpu_seconds_month"] + eta > monthly_gpu:
        return ("本月的 GPU 时间额度用完了（每月 %d 秒）。" % monthly_gpu,
                _quota("monthly_gpu_seconds", "本月 GPU 时间",
                       usage["gpu_seconds_month"], monthly_gpu, "秒",
                       reset="monthly"))
    traffic_msg, traffic_info = traffic_quota_detail(user)
    if traffic_msg:
        return traffic_msg, traffic_info
    return None, None


def check_user_limits(user, ckpt, is_video=False, steps=0, count=1,
                      kind="gen", eta=0):
    return check_user_limits_detail(
        user, ckpt, is_video, steps, count, kind, eta)[0]


# --------------------------------------------------------------------- 实时进度

def _ws_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise IOError("连接已关闭")
        buf += chunk
    return buf


def _ws_handshake(sock):
    key = base64.b64encode(os.urandom(16)).decode()
    req = ("GET /ws?clientId=mobile_web HTTP/1.1\r\n"
           "Host: 127.0.0.1:8188\r\n"
           "Upgrade: websocket\r\n"
           "Connection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\n"
           "Sec-WebSocket-Version: 13\r\n\r\n") % key
    sock.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise IOError("握手无响应")
        buf += chunk
        if len(buf) > 65536:
            raise IOError("握手响应异常")
    if b"101" not in buf.split(b"\r\n")[0]:
        raise IOError("握手被拒绝")


def _ws_read_frame(sock):
    hdr = _ws_exact(sock, 2)
    opcode = hdr[0] & 0x0F
    masked = hdr[1] & 0x80
    length = hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _ws_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _ws_exact(sock, 8))[0]
    mask = _ws_exact(sock, 4) if masked else None
    payload = _ws_exact(sock, length) if length else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _ws_handle_text(payload):
    try:
        msg = json.loads(payload.decode("utf-8"))
    except Exception:
        return
    t = msg.get("type")
    data = msg.get("data") or {}
    pid = data.get("prompt_id")
    if t == "execution_start" and pid:
        WS_CURRENT["pid"] = pid
        with WS_LOCK:
            WS_PROGRESS.setdefault(pid, {"value": 0, "max": 0})
    elif t == "progress" and pid:
        WS_CURRENT["pid"] = pid
        with WS_LOCK:
            WS_PROGRESS[pid] = {"value": data.get("value"), "max": data.get("max")}
    elif t == "executing" and pid:
        WS_CURRENT["pid"] = pid
    elif t in ("execution_success", "execution_error") and pid:
        with WS_LOCK:
            WS_PROGRESS.pop(pid, None)
            WS_PREVIEW.pop(pid, None)


def _ws_handle_binary(payload):
    # 前 4 字节事件类型，接着 4 字节格式（1=jpeg, 2=png），其后是图像数据
    if len(payload) < 9:
        return
    try:
        fmt = struct.unpack(">I", payload[4:8])[0]
    except Exception:
        return
    if fmt not in (1, 2):
        return
    pid = WS_CURRENT.get("pid")
    if not pid:
        return
    with WS_LOCK:
        WS_PREVIEW[pid] = payload[8:]


def ws_listener():
    """连 ComfyUI 的 WebSocket 拿实时进度和预览图，断了自动重连。"""
    while True:
        sock = None
        try:
            sock = socket.create_connection(("127.0.0.1", 8188), timeout=10)
            sock.settimeout(90)
            _ws_handshake(sock)
            while True:
                opcode, payload = _ws_read_frame(sock)
                if opcode == 0x8:
                    raise IOError("服务端关闭")
                elif opcode == 0x9:
                    continue
                elif opcode == 0x1:
                    _ws_handle_text(payload)
                elif opcode == 0x2:
                    _ws_handle_binary(payload)
        except Exception:
            time.sleep(3)
        finally:
            try:
                if sock:
                    sock.close()
            except Exception:
                pass


# --------------------------------------------------------------------- 挂机造图

def auto_loop(params, count, interval, uid="admin"):
    """连续出图，直到轮数用完或被叫停。"""
    prompt_model, char_tags = extract_char_tags(params["prompt"])
    try:
        for i in range(count):
            with AUTO_LOCK:
                if AUTO["stop"]:
                    break
                AUTO["done"] = i
            # LoRA 训练占用本机显卡时，挂机造图跟着暂停，训练结束再继续。
            while training_manager.M.local_gpu_blocked():
                with AUTO_LOCK:
                    if AUTO["stop"]:
                        break
                time.sleep(2)
            with AUTO_LOCK:
                if AUTO["stop"]:
                    break
            user = get_user(uid)
            eta = round(estimate_seconds(params["ckpt"], params["steps"], 1), 1)
            if user:
                msg = check_user_limits(user, params["ckpt"], False,
                                        params["steps"], 1, "auto", eta=eta)
                if msg:
                    with AUTO_LOCK:
                        AUTO["stop"] = True
                    break
            jid = uuid.uuid4().hex[:12]
            prompt_en = params.get("prompt_en") or ""
            reqs = job_requirements(params["ckpt"], [],
                                    bool(params.get("turbo")), "gen")
            with JOBS_LOCK:
                JOBS[jid] = {"status": "queued", "started": 0,
                             "queued_at": time.time(), "elapsed": 0,
                             "prompt": params["prompt"],
                             "prompt_en": prompt_en,
                             "kind": "gen", "mode": "txt",
                             "model": os.path.basename(params["ckpt"]),
                             "turbo": bool(params.get("turbo")),
                             "pag": bool(params.get("pag", True)),
                             "steps": params["steps"], "cfg": params["cfg"],
                             "sampler": params.get("sampler") or DEFAULT_SAMPLER,
                             "user_id": uid,
                             "username": (user or {}).get("username") or uid,
                             "user_name": (user or {}).get("name") or "",
                             "eta": eta, "priority": 0,
                             "requirements": reqs,
                             "remote_ok": True,
                             "pixels": int(params["w"] * params["h"]),
                             "count": 1,
                             "input_refs": {},
                             "attempt": 0,
                             "retry_count": 0,
                             "exclude_workers": [],
                             "worker_id": "",
                             "worker_name": "",
                             "worker_kind": "",
                             "dispatch_state": ""}
            queue_err = scheduler_enqueue(jid)
            if queue_err:
                with JOBS_LOCK:
                    JOBS.pop(jid, None)
                with AUTO_LOCK:
                    AUTO["stop"] = True
                break
            run_job(jid, prompt_model, params["negative"],
                    params["w"], params["h"], params["steps"], params["cfg"],
                    params["seed"] + i * 7919, 1, None, None, 1.0,
                    params["ckpt"], "gen", None, False, prompt_en,
                    params.get("sampler") or DEFAULT_SAMPLER, 16,
                    params.get("pag", True), params.get("turbo", False),
                    char_tags, params["prompt"],
                    user_id=uid)
            with AUTO_LOCK:
                AUTO["done"] = i + 1
            if interval and i < count - 1:
                # 分段睡眠，方便随时叫停
                left = float(interval)
                while left > 0:
                    with AUTO_LOCK:
                        if AUTO["stop"]:
                            break
                    time.sleep(min(1.0, left))
                    left -= 1.0
    finally:
        with AUTO_LOCK:
            AUTO["running"] = False


# --------------------------------------------------------------------- 前端

TEMPLATE_DIR = os.path.join(ROOT, "webapp_templates")


def load_template(name):
    with open(os.path.join(TEMPLATE_DIR, name), "r", encoding="utf-8") as fh:
        return fh.read()


PAGE = load_template("page.html")
LOGIN_PAGE = load_template("login.html")
LICENSE_PAGE = load_template("license.html")
SW_JS = load_template("sw.js")


MANIFEST = {
    "name": "手机出图",
    "short_name": "出图",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#14161a",
    "theme_color": "#14161a",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}



# ComfyUI 工作流模块（放在文件末尾导入，确保常量已经定义）
from comfy_workflows import (
    http_json, comfy_current_prompt, source_megapixels,
    build_workflow, build_anima_workflow, build_video_workflow,
    build_i2v_workflow, build_upscale_workflow, friendly_error,
)
