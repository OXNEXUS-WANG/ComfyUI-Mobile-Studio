# -*- coding: utf-8 -*-
"""监控中心：告警、健康分、趋势、worker 遥测和外部通知。

独立于 app_core，只依赖标准库；调用方把当前的负载 / 队列 / worker / 任务
快照传进来，这里负责判断、去重、保存和输出。所有内容都不含提示词正文。
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections import deque

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ROOT, "monitor.json")
ALERTS_FILE = os.path.join(ROOT, "monitor_alerts.json")
TRENDS_FILE = os.path.join(ROOT, "monitor_trends.json")

DEFAULT_SETTINGS = {
    "alerts_enabled": True,
    "gpu_high": 97,
    "gpu_temp_high": 85,
    "queue_warn": 10,
    "worker_offline_sec": 30,
    "worker_critical_sec": 120,
    "error_rate_pct": 25,
    "error_min_jobs": 5,
    "disk_free_gb": 10,
    "cert_days": 30,
    "job_stuck_min": 20,
    "webhook_enabled": False,
    "webhook_url": "",
    "webhook_cooldown": 300,
    "job_notify": True,
    "job_notify_start": False,
    "job_notify_done": True,
    "job_notify_error": True,
    "metrics_enabled": False,
    "metrics_token": "",
}

_LOCK = threading.RLock()
_CACHE = {"mtime": 0.0, "settings": None}
_ALERTS = {}
_HISTORY = []
_ALERT_SEEN = {"loaded": False, "last_save": 0.0}
_WEBHOOK_LAST = {}
_TELEMETRY = {}
_TELEMETRY_LOCK = threading.Lock()
_TRENDS = None
_TRENDS_LOCK = threading.Lock()
_TRENDS_LAST_SAVE = {"t": 0.0}
_NOTED_JOBS = set()
_SEVERITY_RANK = {"critical": 0, "warn": 1, "info": 2}


def _now():
    return time.time()


def _iso(ts=None):
    return time.strftime("%Y-%m-%d %H:%M:%S",
                         time.localtime(ts if ts is not None else _now()))


def _clamp_int(value, lo, hi, default):
    try:
        n = int(value)
    except Exception:
        return default
    return max(lo, min(hi, n))


def _clean_settings(raw):
    src = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_SETTINGS)
    for key in ("alerts_enabled", "webhook_enabled", "metrics_enabled",
                "job_notify", "job_notify_start", "job_notify_done",
                "job_notify_error"):
        out[key] = bool(src.get(key, out[key]))
    for key, hi in (("gpu_high", 100), ("gpu_temp_high", 120),
                    ("queue_warn", 500), ("worker_offline_sec", 600),
                    ("worker_critical_sec", 3600), ("error_rate_pct", 100),
                    ("error_min_jobs", 100), ("disk_free_gb", 10000),
                    ("cert_days", 3650), ("job_stuck_min", 1440),
                    ("webhook_cooldown", 86400)):
        out[key] = _clamp_int(src.get(key), 1, hi, out[key])
    url = str(src.get("webhook_url") or "").strip()
    if len(url) > 500 or (url and not re.match(r"^https?://", url)):
        url = ""
    out["webhook_url"] = url
    out["metrics_token"] = str(src.get("metrics_token") or "")[:120]
    return out


def load_settings(force=False):
    try:
        mtime = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if (not force and _CACHE["settings"] is not None
                and mtime == _CACHE["mtime"]):
            return dict(_CACHE["settings"])
        data = {}
        if mtime:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
            except Exception:
                data = {}
        cfg = _clean_settings(data)
        _CACHE.update({"mtime": mtime, "settings": cfg})
        return dict(cfg)


def save_settings(patch):
    with _LOCK:
        cfg = load_settings(force=True)
        src = dict(patch) if isinstance(patch, dict) else {}
        if src.pop("clear_metrics_token", False):
            cfg["metrics_token"] = ""
        if "metrics_token" in src and not str(src.get("metrics_token") or "").strip():
            src.pop("metrics_token", None)
        cfg.update(src)
        cfg = _clean_settings(cfg)
        tmp = SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
        _CACHE.update({"mtime": os.path.getmtime(SETTINGS_FILE),
                       "settings": cfg})
        return dict(cfg)


def public_settings(cfg=None):
    cfg = dict(cfg or load_settings())
    return {
        "alerts_enabled": bool(cfg.get("alerts_enabled")),
        "gpu_high": cfg.get("gpu_high"),
        "gpu_temp_high": cfg.get("gpu_temp_high"),
        "queue_warn": cfg.get("queue_warn"),
        "worker_offline_sec": cfg.get("worker_offline_sec"),
        "worker_critical_sec": cfg.get("worker_critical_sec"),
        "error_rate_pct": cfg.get("error_rate_pct"),
        "error_min_jobs": cfg.get("error_min_jobs"),
        "disk_free_gb": cfg.get("disk_free_gb"),
        "cert_days": cfg.get("cert_days"),
        "job_stuck_min": cfg.get("job_stuck_min"),
        "webhook_enabled": bool(cfg.get("webhook_enabled")),
        "webhook_url": cfg.get("webhook_url") or "",
        "webhook_cooldown": cfg.get("webhook_cooldown"),
        "metrics_enabled": bool(cfg.get("metrics_enabled")),
        "metrics_token_set": bool(cfg.get("metrics_token")),
    }


# ------------------------------------------------------------------ 告警
def _alert_id(key):
    return hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]


def _load_alerts():
    if _ALERT_SEEN["loaded"]:
        return
    _ALERT_SEEN["loaded"] = True
    try:
        with open(ALERTS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except Exception:
        return
    with _LOCK:
        for item in data.get("active") or []:
            if isinstance(item, dict) and item.get("key"):
                item["status"] = "active"
                _ALERTS[item["key"]] = item
        for item in data.get("history") or []:
            if isinstance(item, dict):
                _HISTORY.append(item)
        del _HISTORY[:-200]


def _save_alerts(force=False):
    now = _now()
    if not force and now - _ALERT_SEEN["last_save"] < 10:
        return
    _ALERT_SEEN["last_save"] = now
    with _LOCK:
        active = [dict(v) for v in _ALERTS.values()
                  if v.get("status") == "active"]
        payload = {"version": 1, "saved_at": now,
                   "active": active[-100:], "history": _HISTORY[-200:]}
    tmp = ALERTS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, ALERTS_FILE)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def _post_webhook(alert):
    cfg = load_settings()
    if not cfg.get("webhook_enabled") or not cfg.get("webhook_url"):
        return
    key = alert.get("key") or alert.get("id")
    now = _now()
    cooldown = int(cfg.get("webhook_cooldown") or 300)
    if now - float(_WEBHOOK_LAST.get(key) or 0) < cooldown:
        return
    _WEBHOOK_LAST[key] = now
    body = json.dumps({
        "product": "Nexus",
        "event": "monitor_alert",
        "id": alert.get("id"),
        "severity": alert.get("severity"),
        "title": alert.get("title"),
        "detail": alert.get("detail"),
        "first_seen": alert.get("first_seen"),
        "last_seen": alert.get("last_seen"),
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        cfg["webhook_url"], data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")

    def run():
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                resp.read(2048)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name="monitor-webhook").start()


def notify_job(event, job):
    """任务开始/完成/失败时发一条状态通知；不含提示词和图片。"""
    cfg = load_settings()
    if not cfg.get("webhook_enabled") or not cfg.get("webhook_url"):
        return False
    if not cfg.get("job_notify"):
        return False
    if event == "start" and not cfg.get("job_notify_start"):
        return False
    if event == "done" and not cfg.get("job_notify_done"):
        return False
    if event == "error" and not cfg.get("job_notify_error"):
        return False
    job = job or {}
    body = json.dumps({
        "product": "Nexus",
        "event": "job_" + str(event),
        "job_id": job.get("job_id") or job.get("id") or "",
        "status": job.get("status") or event,
        "kind": job.get("kind") or "",
        "mode": job.get("mode") or "",
        "model": os.path.basename(str(job.get("model") or "")),
        "user": job.get("username") or job.get("user") or "",
        "user_name": job.get("user_name") or "",
        "elapsed": round(float(job.get("elapsed") or 0), 1),
        "images": len(job.get("images") or []),
        "error": str(job.get("error") or "")[:200],
        "time": _iso(),
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        cfg["webhook_url"], data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")

    def run():
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                resp.read(1024)
        except Exception:
            pass

    threading.Thread(target=run, daemon=True, name="job-webhook").start()
    return True


def send_test_webhook():
    cfg = load_settings()
    url = str(cfg.get("webhook_url") or "").strip()
    if not url:
        return False, "请先填写 Webhook 地址"
    body = json.dumps({
        "product": "Nexus",
        "event": "test",
        "severity": "info",
        "title": "测试告警",
        "detail": "如果你看到这条消息，说明 Webhook 配置成功。",
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            resp.read(2048)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def new_metrics_token():
    return secrets.token_urlsafe(24)


def _raise_alert(key, severity, title, detail, source="", now=None,
                 title_en="", detail_en=""):
    now = now or _now()
    with _LOCK:
        cur = _ALERTS.get(key)
        if cur and cur.get("status") == "active":
            cur["last_seen"] = now
            cur["count"] = int(cur.get("count") or 1) + 1
            cur["severity"] = severity
            cur["title"] = title
            cur["detail"] = detail
            cur["title_en"] = title_en or title
            cur["detail_en"] = detail_en or detail
            cur["source"] = source
            return False
        item = {
            "id": _alert_id(key), "key": key, "severity": severity,
            "title": title, "detail": detail,
            "title_en": title_en or title, "detail_en": detail_en or detail,
            "source": source,
            "first_seen": now, "last_seen": now, "count": 1,
            "status": "active", "ack": False,
        }
        _ALERTS[key] = item
        _HISTORY.append(dict(item, action="open", time=now))
        del _HISTORY[:-200]
    _post_webhook(item)
    return True


def _resolve_alert(key, now=None):
    now = now or _now()
    with _LOCK:
        cur = _ALERTS.get(key)
        if not cur or cur.get("status") != "active":
            return False
        cur["status"] = "resolved"
        cur["resolved_at"] = now
        _HISTORY.append(dict(cur, action="resolve", time=now))
        del _HISTORY[:-200]
        _ALERTS.pop(key, None)
    _save_alerts(force=True)
    return True


def evaluate(snapshot):
    """根据当前快照更新告警；snapshot 由 web_server 组装。"""
    _load_alerts()
    cfg = load_settings()
    now = float(snapshot.get("now") or _now())
    wanted = set()
    if not cfg.get("alerts_enabled"):
        for key in list(_ALERTS.keys()):
            _resolve_alert(key, now)
        return active_alerts()

    def want(key, severity, title, detail, source="", title_en="", detail_en=""):
        wanted.add(key)
        _raise_alert(key, severity, title, detail, source, now,
                     title_en=title_en, detail_en=detail_en)

    gpu = snapshot.get("gpu_util")
    running = int(snapshot.get("running_count") or 0)
    if gpu is not None and running == 0 and float(gpu) >= cfg["gpu_high"]:
        want("gpu_external", "warn", "GPU 被其他程序占用",
             "GPU 利用率 %s%%，当前没有本平台任务在跑。" % gpu, "load",
             "GPU busy outside this app",
             "GPU utilization is %s%% and no job from this platform is running."
             % gpu)
    temp = snapshot.get("gpu_temp_c")
    if temp is not None and float(temp) >= cfg["gpu_temp_high"]:
        want("gpu_temp", "critical" if float(temp) >= 95 else "warn",
             "GPU 温度过高", "当前 GPU 温度 %s°C。" % temp, "load",
             "GPU temperature high", "Current GPU temperature is %s°C." % temp)
    queue = int(snapshot.get("queue_size") or 0)
    if queue >= cfg["queue_warn"]:
        sev = "critical" if queue >= cfg["queue_warn"] * 2 else "warn"
        want("queue_backlog", sev, "任务队列积压",
             "当前有 %d 个任务在排队。" % queue, "queue",
             "Job queue backlog", "%d jobs are queued." % queue)
    if snapshot.get("comfy_ready") is False:
        want("comfy_offline", "warn", "ComfyUI 不在线",
             "本机 ComfyUI 没有响应，本机槽位无法接单。", "comfy",
             "ComfyUI offline",
             "Local ComfyUI is not responding; the local slot cannot take jobs.")
    for w in snapshot.get("workers") or []:
        if not isinstance(w, dict) or w.get("status") != "approved":
            continue
        last = float(w.get("last_seen") or 0)
        if not last:
            continue
        age = now - last
        wname = w.get("name") or w.get("id")
        if age > cfg["worker_critical_sec"]:
            want("worker:" + str(w.get("id")), "critical",
                 "算力节点离线", "%s 已 %d 秒没有心跳。" %
                 (wname, int(age)), "worker",
                 "Compute node offline",
                 "%s has not sent a heartbeat for %d seconds." %
                 (wname, int(age)))
        elif age > cfg["worker_offline_sec"]:
            want("worker:" + str(w.get("id")), "warn",
                 "算力节点心跳变慢", "%s 已 %d 秒没有心跳。" %
                 (wname, int(age)), "worker",
                 "Compute node heartbeat late",
                 "%s has not sent a heartbeat for %d seconds." %
                 (wname, int(age)))
    jobs = snapshot.get("jobs") or []
    stuck_sec = cfg["job_stuck_min"] * 60
    for j in jobs:
        if not isinstance(j, dict) or j.get("status") != "running":
            continue
        started = float(j.get("started") or j.get("queued_at") or 0)
        if started and now - started > stuck_sec:
            minutes = int((now - started) / 60)
            want("stuck:" + str(j.get("job_id")), "warn",
                 "任务运行时间过长", "%s 已运行 %d 分钟。" %
                 (j.get("job_id"), minutes), "job",
                 "Job running too long",
                 "%s has been running for %d minutes." %
                 (j.get("job_id"), minutes))
    total = int(snapshot.get("job_count_10m") or 0)
    errors = int(snapshot.get("error_count_10m") or 0)
    if total >= cfg["error_min_jobs"] and total:
        rate = errors * 100.0 / total
        if rate >= cfg["error_rate_pct"]:
            want("error_rate", "warn", "任务失败率偏高",
                 "最近 10 分钟 %d/%d 个任务失败（%.0f%%）。" %
                 (errors, total, rate), "job",
                 "High job failure rate",
                 "%d/%d jobs failed in the last 10 minutes (%.0f%%)." %
                 (errors, total, rate))
    disk = snapshot.get("disk_free_gb")
    if disk is not None and float(disk) < cfg["disk_free_gb"]:
        want("disk_low", "critical" if float(disk) < cfg["disk_free_gb"] / 2
             else "warn", "磁盘空间不足",
             "图库所在磁盘剩余 %.1f GB。" % float(disk), "storage",
             "Low disk space",
             "Gallery disk has %.1f GB free." % float(disk))
    cert = snapshot.get("cert_days")
    if cert is not None and float(cert) < cfg["cert_days"]:
        want("cert_expiry", "warn", "HTTPS 证书即将过期",
             "证书还剩 %.0f 天。" % float(cert), "security",
             "HTTPS certificate expiring",
             "Certificate has %.0f days left." % float(cert))
    for key in list(_ALERTS.keys()):
        if key not in wanted:
            _resolve_alert(key, now)
    _save_alerts()
    return active_alerts()


def active_alerts():
    _load_alerts()
    with _LOCK:
        rows = [dict(v) for v in _ALERTS.values()
                if v.get("status") == "active"]
    rows.sort(key=lambda x: (_SEVERITY_RANK.get(x.get("severity"), 9),
                             -(x.get("last_seen") or 0)))
    return rows


def alert_history(limit=100):
    _load_alerts()
    with _LOCK:
        return [dict(x) for x in _HISTORY[-max(1, min(200, limit)):]][::-1]


def ack_alert(alert_id):
    with _LOCK:
        for item in _ALERTS.values():
            if item.get("id") == alert_id:
                item["ack"] = True
                _save_alerts(force=True)
                return True
    return False


def alert_summary():
    rows = active_alerts()
    return {
        "total": len(rows),
        "critical": sum(1 for x in rows if x.get("severity") == "critical"),
        "warn": sum(1 for x in rows if x.get("severity") == "warn"),
        "info": sum(1 for x in rows if x.get("severity") == "info"),
        "rows": rows,
    }


def health(snapshot):
    alerts = active_alerts()
    score = 100
    reasons = []
    reasons_en = []
    for a in alerts:
        sev = a.get("severity")
        score -= 25 if sev == "critical" else 10 if sev == "warn" else 2
        reasons.append("%s：%s" % (a.get("title"), a.get("detail")))
        reasons_en.append("%s: %s" % (
            a.get("title_en") or a.get("title"),
            a.get("detail_en") or a.get("detail")))
    queue = int(snapshot.get("queue_size") or 0)
    if queue > 5:
        score -= min(10, queue // 5)
    if snapshot.get("comfy_ready") is False:
        score -= 10
    disk = snapshot.get("disk_free_gb")
    if disk is not None and float(disk) < 5:
        score -= 10
    score = max(0, min(100, score))
    if score >= 90:
        grade, label, label_en = "healthy", "健康", "Healthy"
    elif score >= 70:
        grade, label, label_en = "attention", "注意", "Attention"
    elif score >= 40:
        grade, label, label_en = "degraded", "异常", "Degraded"
    else:
        grade, label, label_en = "critical", "严重", "Critical"
    return {"score": score, "grade": grade, "label": label,
            "label_en": label_en, "reasons": reasons[:6],
            "reasons_en": reasons_en[:6], "alerts": len(alerts)}


# --------------------------------------------------------------- worker 遥测
def note_worker(wid, sample):
    wid = str(wid or "")
    if not wid or not isinstance(sample, dict):
        return
    item = {
        "t": round(float(sample.get("t") or _now()), 3),
        "gpu_util": sample.get("gpu_util"),
        "vram_used_mb": sample.get("vram_used_mb"),
        "vram_total_mb": sample.get("vram_total_mb"),
        "temp_c": sample.get("temp_c"),
        "busy": bool(sample.get("busy")),
        "online": bool(sample.get("online")),
        "current_job": str(sample.get("current_job") or "")[:64],
    }
    with _TELEMETRY_LOCK:
        q = _TELEMETRY.get(wid)
        if q is None:
            q = deque(maxlen=120)
            _TELEMETRY[wid] = q
        q.append(item)


def worker_series(wid, limit=60):
    with _TELEMETRY_LOCK:
        q = list(_TELEMETRY.get(str(wid or "")) or ())
    return q[-max(1, min(120, int(limit or 60))):]


def all_worker_series(limit=60):
    with _TELEMETRY_LOCK:
        ids = list(_TELEMETRY.keys())
    return {wid: worker_series(wid, limit) for wid in ids}


# ------------------------------------------------------------------ 趋势
def _trend_data():
    global _TRENDS
    with _TRENDS_LOCK:
        if _TRENDS is not None:
            return _TRENDS
        try:
            with open(TRENDS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception:
            data = {}
        if not isinstance(data.get("hours"), dict):
            data["hours"] = {}
        if not isinstance(data.get("days"), dict):
            data["days"] = {}
        _TRENDS = data
        return _TRENDS


def _save_trends(force=False):
    now = _now()
    if not force and now - _TRENDS_LAST_SAVE["t"] < 20:
        return
    _TRENDS_LAST_SAVE["t"] = now
    data = _trend_data()
    cutoff_h = time.strftime("%Y-%m-%dT%H", time.localtime(now - 8 * 86400))
    cutoff_d = time.strftime("%Y-%m-%d", time.localtime(now - 31 * 86400))
    data["hours"] = {k: v for k, v in data["hours"].items() if k >= cutoff_h}
    data["days"] = {k: v for k, v in data["days"].items() if k >= cutoff_d}
    tmp = TRENDS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, TRENDS_FILE)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def note_job(job):
    if not isinstance(job, dict):
        return
    jid = str(job.get("job_id") or job.get("id") or "")
    status = str(job.get("status") or "")
    if not jid or status not in ("done", "error", "cancelled"):
        return
    with _TRENDS_LOCK:
        if jid in _NOTED_JOBS:
            return
        _NOTED_JOBS.add(jid)
    ts = float(job.get("finished_at") or _now())
    hour = time.strftime("%Y-%m-%dT%H", time.localtime(ts))
    day = time.strftime("%Y-%m-%d", time.localtime(ts))
    elapsed = float(job.get("elapsed") or 0)
    images = len(job.get("images") or [])
    data = _trend_data()
    for bucket_name, key in (("hours", hour), ("days", day)):
        bucket = data[bucket_name].setdefault(key, {
            "jobs": 0, "done": 0, "error": 0, "cancelled": 0,
            "seconds": 0.0, "images": 0,
        })
        bucket["jobs"] += 1
        bucket[status] = bucket.get(status, 0) + 1
        bucket["seconds"] = round(float(bucket.get("seconds") or 0) + elapsed, 1)
        bucket["images"] = int(bucket.get("images") or 0) + images
    _save_trends()


def trends(hours=24):
    data = _trend_data()
    now = time.time()
    n = max(1, min(168, int(hours or 24)))
    rows = []
    for i in range(n - 1, -1, -1):
        ts = now - i * 3600
        key = time.strftime("%Y-%m-%dT%H", time.localtime(ts))
        b = data["hours"].get(key) or {}
        rows.append({
            "key": key,
            "label": time.strftime("%H:00", time.localtime(ts)),
            "jobs": int(b.get("jobs") or 0),
            "done": int(b.get("done") or 0),
            "error": int(b.get("error") or 0),
            "cancelled": int(b.get("cancelled") or 0),
            "seconds": round(float(b.get("seconds") or 0), 1),
            "images": int(b.get("images") or 0),
        })
    days = []
    for i in range(6, -1, -1):
        ts = now - i * 86400
        key = time.strftime("%Y-%m-%d", time.localtime(ts))
        b = data["days"].get(key) or {}
        days.append({
            "key": key,
            "label": time.strftime("%m-%d", time.localtime(ts)),
            "jobs": int(b.get("jobs") or 0),
            "done": int(b.get("done") or 0),
            "error": int(b.get("error") or 0),
            "cancelled": int(b.get("cancelled") or 0),
            "seconds": round(float(b.get("seconds") or 0), 1),
            "images": int(b.get("images") or 0),
        })
    return {"hours": rows, "days": days}


# ------------------------------------------------------------------ metrics
def metrics_text(snapshot, alerts=None):
    alerts = alerts if alerts is not None else active_alerts()
    lines = [
        "# HELP mgs_up Service is running",
        "# TYPE mgs_up gauge",
        "mgs_up 1",
    ]
    def gauge(name, help_text, value):
        lines.extend(["# HELP %s %s" % (name, help_text),
                      "# TYPE %s gauge" % name, "%s %s" % (name, value)])
    gauge("mgs_jobs_running", "Running jobs", int(snapshot.get("running_count") or 0))
    gauge("mgs_jobs_queued", "Queued jobs", int(snapshot.get("queue_size") or 0))
    gauge("mgs_workers_online", "Online workers", int(snapshot.get("workers_online") or 0))
    gauge("mgs_workers_total", "Total workers", int(snapshot.get("workers_total") or 0))
    gauge("mgs_gpu_util_percent", "GPU utilization", snapshot.get("gpu_util") or 0)
    gauge("mgs_vram_used_mb", "VRAM used", snapshot.get("vram_used_mb") or 0)
    gauge("mgs_queue_size", "Queue size", int(snapshot.get("queue_size") or 0))
    gauge("mgs_errors_10m", "Errors in last 10 minutes",
          int(snapshot.get("error_count_10m") or 0))
    gauge("mgs_gallery_images", "Gallery images", int(snapshot.get("gallery_images") or 0))
    gauge("mgs_disk_free_mb", "Disk free MB", int(float(snapshot.get("disk_free_gb") or 0) * 1024))
    lines.extend([
        "# HELP mgs_alerts Active alerts",
        "# TYPE mgs_alerts gauge",
    ])
    for sev in ("critical", "warn", "info"):
        n = sum(1 for a in alerts if a.get("severity") == sev)
        lines.append('mgs_alerts{severity="%s"} %d' % (sev, n))
    return "\n".join(lines) + "\n"


def metrics_token_ok(token):
    cfg = load_settings()
    want = str(cfg.get("metrics_token") or "")
    return bool(cfg.get("metrics_enabled") and want and
                hmac.compare_digest(str(token or ""), want))
