# -*- coding: utf-8 -*-
"""手机出图 HTTP 服务层：路由、页面响应、启动。

后端逻辑在 app_core.py；这里只负责 HTTP 和进程启动。
"""
import base64
import csv
import hashlib
import io
import json
import os
import queue
import re
import select
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app_core import *
# 星号导入不会带下划线开头的内部函数，单独补一个
from app_core import _stage_to_input
import lan_share
import license_guard
import model_manager
import input_guard
import runtime_settings
import trusted_time
import edition_policy
import node_manager
import plugin_manager
import workflow_manager
import worker_bundle


_OBJECT_INFO_CACHE = {"t": 0.0, "v": None}


def comfy_object_info_cached(max_age=30):
    """读取 ComfyUI 节点定义；缓存 30 秒，避免体检时反复拉几 MB JSON。"""
    now = time.time()
    if (_OBJECT_INFO_CACHE["v"] is not None
            and now - float(_OBJECT_INFO_CACHE["t"] or 0) < max_age):
        return _OBJECT_INFO_CACHE["v"]
    try:
        info = http_json("/object_info", timeout=20)
        if isinstance(info, dict):
            _OBJECT_INFO_CACHE["v"] = info
            _OBJECT_INFO_CACHE["t"] = now
            return info
    except Exception:
        pass
    return _OBJECT_INFO_CACHE["v"]


def plugin_styles_for(user):
    """内置风格 + 当前账号启用的安全插件包风格。"""
    merged = dict(STYLES)
    try:
        extra = plugin_manager.styles_for_user((user or {}).get("id") or "")
    except Exception:
        extra = {}
    for name, suffix in extra.items():
        key = name
        while key in merged:
            key = "插件·" + key
        merged[key] = suffix
    return merged


def _models_payload():
    """模型列表 + 正在被排队/运行任务使用的文件名。"""
    data = model_manager.list_all()
    busy = set()
    with JOBS_LOCK:
        for job in JOBS.values():
            if job.get("status") not in ("queued", "running"):
                continue
            for raw in [job.get("model")] + list(job.get("loras") or []):
                name = os.path.basename(str(raw or ""))
                if name:
                    busy.add(name)
    data["busy_models"] = sorted(busy)
    return data


def is_mobile_ua(ua):
    """手机 UA。iPad/桌面 UA 不算，保留桌面星图。"""
    s = str(ua or "").lower()
    if not s or "ipad" in s:
        return False
    return any(k in s for k in (
        "iphone", "ipod", "android", "windows phone", "harmonyos"))


# --------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "MobileWeb"
    sys_version = ""            # 不把 Python 版本号广播给任何人

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if https_enabled():
                self.send_header("Strict-Transport-Security",
                                 "max-age=15552000")
            items = headers.items() if isinstance(headers, dict) else (headers or [])
            for k, v in items:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)
            note_traffic(activity_user_id(), tx=len(body), requests=1)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    # ------------------------------------------------------------ 登录态
    def _is_mobile(self):
        ua = self.headers.get("User-Agent") or ""
        hint = (self.headers.get("Sec-CH-UA-Mobile") or "").strip()
        return hint == "?1" or is_mobile_ua(ua)

    def _cookie(self, name):
        raw = self.headers.get("Cookie") or ""
        if not raw:
            return ""
        try:
            c = SimpleCookie()
            c.load(raw)
            m = c.get(name)
            return m.value if m else ""
        except Exception:
            return ""

    def _current_user(self):
        if not auth_enabled():
            user = {"id": "admin", "username": "admin", "name": "管理员",
                    "role": "admin", "enabled": True,
                    "limits": dict(ADMIN_DEFAULT_LIMITS)}
        else:
            user = session_user(self._cookie(COOKIE_NAME))
            if not user:
                user = proxy_auth_user(
                    self.headers.get(proxy_auth_header()),
                    self.client_address[0])
        if user:
            note_user_presence(user, self.path.split("?")[0],
                               self.client_address[0])
        set_activity_user(user, self.client_address[0])
        return user

    def _authed(self):
        """没设账号时一律放行；设了就必须带有效会话 cookie。"""
        return self._current_user() is not None

    def _deny(self):
        route = self.path.split("?")[0]
        if route.startswith(("/api/", "/img/", "/thumb/", "/preview/")):
            audit("security", "unauthorized", ip=self.client_address[0],
                  ok=False, method=self.command, route=route)
        self._json({"error": "需要登录", "need_login": True}, 401)

    def _require_feature(self, user, key):
        msg = check_feature(user, key)
        if not msg:
            return True
        audit("security", "feature_denied", user=user,
              ip=self.client_address[0], ok=False, feature=key,
              error=msg, route=self.path.split("?")[0])
        self._json({"error": msg, "feature": key}, 403)
        return False

    def _require_traffic(self, user):
        msg, quota = traffic_quota_detail(user)
        if not msg:
            return True
        audit("security", "limit_denied", user=user,
              ip=self.client_address[0], ok=False, operation="traffic",
              error=msg, route=self.path.split("?")[0])
        self._json({"error": msg, "traffic": True,
                    "code": "quota_exhausted", "quota": quota}, 403)
        return False

    def _set_cookie_header(self, tok, max_age):
        # 开了 HTTPS 时加 Secure，浏览器不会再从明文连接带上会话。
        flags = "Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % max_age
        if https_enabled():
            flags += "; Secure"
        return ("Set-Cookie", "%s=%s; %s" % (COOKIE_NAME, tok, flags))

    # ------------------------------------------------------------ 局域网算力节点
    def _worker_ip(self):
        return lan_share.normalize_ip(self.client_address[0])

    def _worker_ip_ok(self):
        return lan_share.worker_ip_allowed(self._worker_ip())

    def _worker_https_ok(self):
        ip = self._worker_ip()
        if lan_share.is_loopback_ip(ip):
            return True
        return https_enabled()

    def _worker_deny(self, message, code=403, action="worker_denied"):
        audit("security", action, ip=self._worker_ip(), ok=False,
              route=self.path.split("?")[0], error=str(message)[:160])
        self._json({"error": message}, code)

    def _worker_protocol_ok(self, data=None):
        data = data if isinstance(data, dict) else {}
        raw = (self.headers.get("X-Protocol")
               or self.headers.get("X-Protocol-Version")
               or data.get("protocol") or data.get("protocol_version") or 0)
        try:
            value = int(raw)
        except Exception:
            value = 0
        if value == int(lan_share.SETTINGS.get("protocol") or 1):
            return True
        self._json({"error": "worker 协议版本不一致",
                    "central_protocol": int(lan_share.SETTINGS.get("protocol") or 1),
                    "min_agent_version": "1.0"}, 426)
        return False

    def _worker_read_body(self, limit):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            self._json({"error": "Content-Length 无效"}, 400)
            return None
        if n < 0 or n > limit:
            self._json({"error": "请求体太大"}, 413)
            return None
        try:
            return self.rfile.read(n) if n else b"{}"
        except Exception:
            self._json({"error": "请求体读取失败"}, 400)
            return None

    def _worker_json_body(self, data):
        try:
            return json.loads((data or b"{}").decode("utf-8"))
        except Exception:
            self._json({"error": "请求格式错误"}, 400)
            return None

    def _serve_cert(self):
        try:
            with open(CERT_FILE, "rb") as fh:
                body = fh.read()
        except Exception:
            self._send(404, "not found", "text/plain; charset=utf-8")
            return
        self._send(200, body, "application/x-pem-file")

    def _cert_fingerprint(self):
        try:
            with open(CERT_FILE, "r", encoding="ascii") as fh:
                pem = fh.read()
            der = ssl.PEM_cert_to_DER_cert(pem)
            return ":".join("%02X" % b for b in hashlib.sha256(der).digest())
        except Exception:
            return ""

    def _handle_worker_get(self, path, q):
        if not self._worker_ip_ok():
            self._worker_deny("这个来源地址不允许接入算力节点", action="worker_ip_denied")
            return
        if not self._worker_https_ok():
            self._worker_deny("非本机 worker 必须使用 HTTPS", action="worker_https_required")
            return
        if path == "/api/worker/ping":
            self._json({
                "ok": True,
                "service": "mobile-web",
                "protocol": int(lan_share.SETTINGS.get("protocol") or 1),
                "min_agent_version": "1.0",
                "https": https_enabled(),
                "join_required": True,
                "cert_fingerprint_sha256": self._cert_fingerprint(),
                "server_time": time.time(),
            })
            return
        m = re.match(r"^/api/worker/job/([0-9A-Za-z]+)/input/([^/]+)$", path)
        if m:
            if not self._worker_protocol_ok({}):
                return
            worker = lan_share.worker_auth(self.headers.get("Authorization") or "",
                                           self._worker_ip())
            if not worker:
                self._json({"error": "worker 身份无效"}, 401)
                return
            try:
                attempt = int(self.headers.get("X-Attempt") or 0)
            except Exception:
                attempt = 0
            key = urllib.parse.unquote(m.group(2))
            blob, err = remote_job_input_bytes(m.group(1), worker.get("id"),
                                               attempt, key)
            if err:
                self._json({"error": err}, 409 if "过期" in err else 404)
                return
            self._send(200, blob, "image/png")
            return
        self._json({"error": "not found"}, 404)

    def _handle_worker_post(self, route):
        if not self._worker_ip_ok():
            self._worker_deny("这个来源地址不允许接入算力节点", action="worker_ip_denied")
            return
        if not self._worker_https_ok():
            self._worker_deny("非本机 worker 必须使用 HTTPS", action="worker_https_required")
            return

        if route == "/api/worker/join":
            raw = self._worker_read_body(2 * 1024 * 1024)
            if raw is None:
                return
            data = self._worker_json_body(raw)
            if data is None:
                return
            if not self._worker_protocol_ok(data):
                audit("security", "worker_protocol_mismatch", ip=self._worker_ip(),
                      ok=False, route=route)
                return
            worker, secret, err = lan_share.redeem_join_code(
                data.get("code") or "", self._worker_ip(),
                data.get("name") or "", data.get("probe") or {},
                data.get("agent_version") or "")
            if err:
                audit("security", "worker_join_denied", ip=self._worker_ip(),
                      ok=False, route=route, error=err)
                self._json({"error": err}, 403)
                return
            audit("security", "worker_join", ip=self._worker_ip(), ok=True,
                  worker_id=worker.get("id"), name=worker.get("name"))
            self._json({
                "ok": True,
                "worker_id": worker.get("id"),
                "secret": secret,
                "status": worker.get("status"),
                "approved": False,
                "protocol": int(lan_share.SETTINGS.get("protocol") or 1),
                "heartbeat_ttl": int(lan_share.SETTINGS.get("heartbeat_ttl") or 20),
                "server_time": time.time(),
            })
            return

        if route == "/api/worker/heartbeat":
            raw = self._worker_read_body(1024 * 1024)
            if raw is None:
                return
            data = self._worker_json_body(raw)
            if data is None:
                return
            if not self._worker_protocol_ok(data):
                audit("security", "worker_protocol_mismatch", ip=self._worker_ip(),
                      ok=False, route=route)
                return
            worker = lan_share.worker_auth(self.headers.get("Authorization") or "",
                                           self._worker_ip())
            if not worker:
                audit("security", "worker_auth_failed", ip=self._worker_ip(),
                      ok=False, route=route)
                self._json({"error": "worker 身份无效"}, 401)
                return
            result = lan_share.heartbeat(worker.get("id"), data, self._worker_ip())
            if not result:
                self._json({"error": "worker 不存在"}, 404)
                return
            if result.get("online") and not result.get("was_online"):
                audit("security", "worker_online", ip=self._worker_ip(), ok=True,
                      worker_id=worker.get("id"), name=worker.get("name"))
                activity("worker", phase="online", silent=True,
                         worker_id=worker.get("id"), name=worker.get("name"))
            result["cancel_jobs"] = remote_cancel_jobs(worker.get("id"))
            scheduler_kick()
            self._json(result)
            return

        if route == "/api/worker/poll":
            if not self._worker_protocol_ok({}):
                return
            worker = lan_share.worker_auth(self.headers.get("Authorization") or "",
                                           self._worker_ip())
            if not worker:
                audit("security", "worker_auth_failed", ip=self._worker_ip(),
                      ok=False, route=route)
                self._json({"error": "worker 身份无效"}, 401)
                return
            raw = self._worker_read_body(1024 * 1024)
            if raw is None:
                return
            data = self._worker_json_body(raw) or {}
            wid = worker.get("id") or ""
            with SCHED_LOCK:
                has_active = bool((SCHEDULER["slots"].get(wid) or {}).get("active"))
            if not has_active and not lan_share.worker_accepting(worker):
                self._send(204, b"", "application/json")
                return
            scheduler_kick()
            try:
                wait_sec = int(data.get("wait_sec") or 20)
            except Exception:
                wait_sec = 20
            job = remote_claim(wid, wait_sec)
            if job:
                self._json(job)
            else:
                self._send(204, b"", "application/json")
            return

        m = re.match(
            r"^/api/worker/job/([0-9A-Za-z]+)/"
            r"(started|progress|output|complete|error|cancelled)$", route)
        if m:
            if not self._worker_protocol_ok({}):
                return
            worker = lan_share.worker_auth(self.headers.get("Authorization") or "",
                                           self._worker_ip())
            if not worker:
                audit("security", "worker_auth_failed", ip=self._worker_ip(),
                      ok=False, route=route)
                self._json({"error": "worker 身份无效"}, 401)
                return
            jid, action = m.group(1), m.group(2)
            wid = worker.get("id") or ""
            try:
                attempt = int(self.headers.get("X-Attempt") or 0)
            except Exception:
                attempt = 0
            q = self._query() or {}
            if action == "output":
                raw = self._worker_read_body(40 * 1024 * 1024)
                if raw is None:
                    return
                try:
                    index = int(q.get("index") or 0)
                except Exception:
                    index = -1
                data, err = remote_job_output(jid, wid, attempt, index, raw)
            else:
                raw = self._worker_read_body(1024 * 1024)
                if raw is None:
                    return
                body = self._worker_json_body(raw)
                if body is None:
                    return
                try:
                    attempt = int(body.get("attempt") or attempt)
                except Exception:
                    attempt = 0
                if action == "started":
                    data, err = remote_job_started(
                        jid, wid, attempt, body.get("prompt_id") or "")
                elif action == "progress":
                    data, err = remote_job_progress(jid, wid, attempt, body)
                elif action == "complete":
                    data, err = remote_job_complete(jid, wid, attempt, body)
                elif action == "error":
                    data, err = remote_job_error(jid, wid, attempt, body)
                else:
                    data, err = remote_job_cancelled(jid, wid, attempt)
            if err:
                self._json({"error": err}, 409)
                return
            self._json(data or {"ok": True})
            return

        self._json({"error": "not found"}, 404)

    def _local_model_inventory(self):
        def scan(path, exts):
            try:
                return sorted(
                    f for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f))
                    and f.lower().endswith(exts))
            except OSError:
                return []

        models = {
            "checkpoints": scan(CKPT_DIR, (".safetensors", ".ckpt")),
            "diffusion_models": scan(UNET_DIR, (".safetensors", ".ckpt", ".sft")),
            "text_encoders": scan(TEXT_ENC_DIR, (".safetensors", ".ckpt", ".sft")),
            "vae": scan(VAE_DIR, (".safetensors", ".ckpt", ".pt", ".sft")),
            "loras": scan(LORA_DIR, (".safetensors", ".pt", ".ckpt")),
            "upscale_models": scan(UPSCALE_DIR, (".pth", ".safetensors", ".ckpt")),
        }
        return models

    def _local_worker_payload(self):
        settings = lan_share.settings()
        stats = {}
        gpu_name = ""
        vram_mb = 0
        comfy_version = ""
        try:
            stats = http_json("/system_stats", timeout=2)
            dev = (stats.get("devices") or [{}])[0]
            gpu_name = dev.get("name") or ""
            vram_mb = round(float(dev.get("vram_total") or 0) / 1048576.0, 1)
            comfy_version = ((stats.get("system") or {}).get("comfyui_version")
                             or "")
        except Exception:
            stats = {}
        active = SCHEDULER.get("active") or ""
        return {
            "id": "local",
            "name": "本机",
            "kind": "local",
            "status": "approved",
            "enabled": bool(settings.get("local_enabled", True)),
            "online": bool(stats),
            "accepting": bool(settings.get("local_enabled", True) and stats),
            "comfy_ready": bool(stats),
            "comfy_version": comfy_version,
            "gpu_name": gpu_name,
            "vram_mb": vram_mb,
            "models": self._local_model_inventory(),
            "current_job": active,
            "paused": False,
            "trusted": True,
            "owner_id": "admin",
            "allowed_users": [],
        }

    def _handle_model_chunk(self):
        """模型分块上传：原始字节，不走通用 JSON 解析。"""
        user = self._current_user()
        if not is_admin(user):
            self._json({"error": "只有管理员可以上传模型"}, 403)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            self._json({"error": "Content-Length 无效"}, 400)
            return
        if n <= 0 or n > model_manager.CHUNK_MAX_BYTES:
            self._json({"error": "分块大小不合法"}, 413)
            return
        q = self._query()
        try:
            raw = self.rfile.read(n)
            note_traffic(activity_user_id(), rx=n)
        except Exception:
            self._json({"error": "读取上传内容失败"}, 400)
            return
        try:
            result = model_manager.upload_chunk(
                q.get("upload_id"), q.get("offset"), raw)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        self._json(result)

    def _handle_node_chunk(self):
        """自定义节点 ZIP 分块上传：原始字节，不走通用 JSON 解析。"""
        user = self._current_user()
        if not is_admin(user):
            self._json({"error": "只有管理员可以导入自定义节点"}, 403)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            self._json({"error": "Content-Length 无效"}, 400)
            return
        if n <= 0 or n > node_manager.CHUNK_MAX_BYTES:
            self._json({"error": "分块大小不合法"}, 413)
            return
        q = self._query()
        try:
            raw = self.rfile.read(n)
            note_traffic(activity_user_id(), rx=n)
        except Exception:
            self._json({"error": "读取上传内容失败"}, 400)
            return
        try:
            result = node_manager.upload_chunk(
                q.get("upload_id"), q.get("offset"), raw)
        except ValueError as exc:
            self._json({"error": str(exc)}, 400)
            return
        self._json(result)

    def _handle_workers_admin(self, data):
        user = self._current_user()
        if not is_admin(user):
            self._json({"error": "只有管理员可以管理算力节点"}, 403)
            return
        data = data if isinstance(data, dict) else {}
        action = str(data.get("action") or "")
        ip = self.client_address[0]
        wid = str(data.get("id") or "")
        result = {}

        if action == "join_code":
            if lan_share.worker_quota().get("reached"):
                self._json({"error": edition_policy.quota_message("workers")}, 403)
                return
            info = lan_share.create_join_code(
                created_by=(user or {}).get("username") or "admin",
                note=data.get("note") or "")
            scheme = "https" if https_enabled() else "http"
            command = ('python worker_agent.py join --server %s://%s:%d '
                       '--code %s --name "My Worker"' %
                       (scheme, HOTSPOT_IP, PORT, info["code"]))
            if https_enabled():
                command += " --ca cert.pem"
            info.update({"server": "%s://%s:%d" % (scheme, HOTSPOT_IP, PORT),
                         "command": command,
                         "cert_fingerprint_sha256": self._cert_fingerprint()})
            result = info
            audit("security", "worker_join_code_created", user=user, ip=ip,
                  ok=True, note=data.get("note") or "")
        elif action == "settings":
            result = lan_share.set_settings(data)
            audit("security", "worker_settings", user=user, ip=ip, ok=True,
                  remote_enabled=result.get("remote_enabled"),
                  local_enabled=result.get("local_enabled"))
        elif action in ("approve", "update"):
            owner = str(data.get("owner_id") or "admin")
            if owner not in (None, "") and not get_user(owner):
                self._json({"error": "owner 账号不存在"}, 400)
                return
            allowed = []
            for uid in (data.get("allowed_users") or []):
                uid = str(uid or "")
                if uid and get_user(uid):
                    allowed.append(uid)
            if action == "approve":
                worker, err = lan_share.approve_worker(
                    wid, owner_id=owner or "admin",
                    trusted=bool(data.get("trusted")),
                    allowed_users=allowed,
                    name=data.get("name") or "",
                    by=(user or {}).get("username") or "admin")
                audit_action = "worker_approve"
            else:
                worker, err = lan_share.update_worker(wid, {
                    "owner_id": owner or "admin",
                    "trusted": bool(data.get("trusted")),
                    "allowed_users": allowed,
                    "name": data.get("name") or None,
                }, by=(user or {}).get("username") or "admin")
                audit_action = "worker_update"
            if err:
                self._json({"error": err}, 404)
                return
            audit("security", audit_action, user=user, ip=ip, ok=True,
                  worker_id=wid, name=worker.get("name"),
                  owner_id=worker.get("owner_id"),
                  trusted=bool(worker.get("trusted")))
        elif action in ("pause", "resume"):
            worker, err = lan_share.update_worker(
                wid, {"pause_admin": action == "pause"},
                by=(user or {}).get("username") or "admin")
            if err:
                self._json({"error": err}, 404)
                return
            audit("security", "worker_pause" if action == "pause" else "worker_resume",
                  user=user, ip=ip, ok=True, worker_id=wid)
        elif action in ("reject", "revoke"):
            worker, err = lan_share.update_worker(
                wid, {"status": "rejected" if action == "reject" else "revoked"},
                by=(user or {}).get("username") or "admin")
            if err:
                self._json({"error": err}, 404)
                return
            audit("security", "worker_" + action, user=user, ip=ip, ok=True,
                  worker_id=wid)
        elif action == "remove":
            ok = lan_share.remove_worker(wid)
            if not ok:
                self._json({"error": "节点不存在"}, 404)
                return
            audit("security", "worker_remove", user=user, ip=ip, ok=True,
                  worker_id=wid)
        elif action == "refresh":
            worker, err = lan_share.update_worker(wid, {"refresh_inventory": True},
                                                  by=(user or {}).get("username") or "admin")
            if err:
                self._json({"error": err}, 404)
                return
            audit("security", "worker_refresh", user=user, ip=ip, ok=True,
                  worker_id=wid)
        elif action == "rotate":
            worker, secret = lan_share.rotate_secret(wid)
            if not worker:
                self._json({"error": "节点不存在"}, 404)
                return
            result = {"secret": secret}
            audit("security", "worker_secret_rotated", user=user, ip=ip,
                  ok=True, worker_id=wid)
        else:
            self._json({"error": "未知操作"}, 400)
            return

        scheduler_kick()
        payload = lan_share.admin_payload()
        payload["local"] = self._local_worker_payload()
        payload.update(result)
        self._json(payload)

    def _handle_workers_mine(self, data=None):
        user = self._current_user()
        if not user:
            self._json({"error": "需要登录"}, 401)
            return
        data = data if isinstance(data, dict) else {}
        action = str(data.get("action") or "")
        if action in ("pause", "resume"):
            wid = str(data.get("id") or "")
            worker = lan_share.get_worker(wid)
            if not worker:
                self._json({"error": "节点不存在"}, 404)
                return
            if worker.get("owner_id") != user.get("id") and not is_admin(user):
                self._json({"error": "不是你的节点"}, 403)
                return
            lan_share.update_worker(wid, {"pause_owner": action == "pause"},
                                    by=user.get("username") or "user")
            audit("security", "worker_owner_pause" if action == "pause"
                  else "worker_owner_resume", user=user,
                  ip=self.client_address[0], ok=True, worker_id=wid)
        elif action:
            self._json({"error": "未知操作"}, 400)
            return
        scheduler_kick()
        payload = lan_share.owner_payload(user.get("id") or "")
        try:
            payload["telemetry"] = {
                w.get("id"): monitor_center.worker_series(w.get("id"), 60)
                for w in payload.get("workers") or []
            }
        except Exception:
            payload["telemetry"] = {}
        self._json(payload)

    # ------------------------------------------------------------ 管理员活动 WebSocket
    # 只用于管理员后台的私有状态事件。普通账号没有这个连接，也拿不到这些事件。
    WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def _ws_send_frame(self, opcode, payload=b""):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        n = len(payload)
        head = bytearray([0x80 | (opcode & 0x0F)])
        if n < 126:
            head.append(n)
        elif n < 65536:
            head.append(126)
            head.extend(struct.pack(">H", n))
        else:
            head.append(127)
            head.extend(struct.pack(">Q", n))
        try:
            self.connection.sendall(bytes(head) + payload)
        except Exception:
            raise

    def _ws_read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.connection.recv(n - len(buf))
            if not chunk:
                raise IOError("closed")
            buf += chunk
        return buf

    def _ws_read_frame(self):
        hdr = self._ws_read_exact(2)
        opcode = hdr[0] & 0x0F
        masked = bool(hdr[1] & 0x80)
        length = hdr[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._ws_read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._ws_read_exact(8))[0]
        if length > 1_000_000:
            raise IOError("frame too large")
        mask = self._ws_read_exact(4) if masked else b""
        payload = self._ws_read_exact(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _serve_activity_ws(self, user):
        key = (self.headers.get("Sec-WebSocket-Key") or "").strip()
        if not key or "websocket" not in (
                self.headers.get("Upgrade") or "").lower():
            self._json({"error": "需要 WebSocket 升级"}, 400)
            return
        accept = base64.b64encode(hashlib.sha1(
            (key + self.WS_GUID).encode("ascii")).digest()).decode()
        try:
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.flush()
        except Exception:
            return
        uid = (user or {}).get("id") or ""
        q = subscribe_activity(uid)
        self.close_connection = True
        try:
            self.connection.settimeout(0.6)
            while True:
                try:
                    ev = q.get(timeout=0.6)
                    self._ws_send_frame(
                        0x1, json.dumps(ev, ensure_ascii=False))
                except queue.Empty:
                    pass
                try:
                    ready, _, _ = select.select([self.connection], [], [], 0)
                except Exception:
                    break
                if ready:
                    opcode, payload = self._ws_read_frame()
                    if opcode == 0x8:
                        break
                    if opcode == 0x9:
                        self._ws_send_frame(0xA, payload)
        except Exception:
            pass
        finally:
            unsubscribe_activity(uid, q)
            try:
                self.connection.close()
            except Exception:
                pass

    def _handle_login(self, data):
        if not auth_enabled():
            self._json({"ok": True})
            return
        ip = self.client_address[0]
        attempted = str(data.get("username") or "admin").strip()[:64]
        wait = login_wait_seconds(ip)
        if wait:
            set_activity_user({"username": attempted}, ip)
            activity_request("/api/login", "POST", throttle=1.0,
                             ok=False, reason="locked")
            audit("security", "login_locked", ip=ip, ok=False,
                  user={"username": attempted},
                  reason="too_many_failures", wait=wait)
            self._json({"error": "错误次数太多，%d 秒后再试" % wait}, 429)
            return
        # 截断到 512 字符，防止有人用超长密码消耗 PBKDF2
        username = attempted
        user = find_user(username)
        ok = bool(user_is_active(user)
                  and verify_user_password(user,
                                           str(data.get("password") or "")[:512]))
        if not ok:
            note_login_failure(ip)
            set_activity_user({"username": username}, ip)
            activity_request("/api/login", "POST", throttle=1.0,
                             ok=False, reason="bad_password")
            audit("security", "login_failed", ip=ip, ok=False,
                  user={"username": username},
                  reason="bad_password")
            self.log_message("登录失败 %s", ip)
            self._json({"error": "用户名或密码不对"}, 401)
            return
        note_login_success(ip)
        set_activity_user(user, ip)
        activity_request("/api/login", "POST", ok=True,
                         user=user.get("username"))
        audit("security", "login_ok", user=user, ip=ip)
        audit("activity", "login", user=user, ip=ip)
        user["last_login"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_users()
        tok = new_session(user["id"], ip=ip,
                          ua=self.headers.get("User-Agent") or "")
        home = normalize_home(user.get("default_home"))
        redirect = ("/universe" if home == "star" and not self._is_mobile()
                    else "/")
        if license_guard.license_required():
            redirect = "/license"
        self.log_message("登录成功 %s (%s)", ip, user.get("username"))
        self._send(200, json.dumps({"ok": True,
                                    "default_home": home,
                                    "redirect": redirect,
                                    "user": public_user(user)},
                                   ensure_ascii=False),
                   headers=[self._set_cookie_header(tok, SESSION_TTL)])

    def _file(self, path, ctype):
        """发文件；支持 Range，视频才能拖进度条 / 边下边播。"""
        try:
            size = os.path.getsize(path)
        except Exception:
            return False
        start, end, partial = 0, max(0, size - 1), False
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes=") and size > 0:
            a, _, b = rng[6:].split(",")[0].partition("-")
            try:
                if a.strip():
                    start = int(a)
                    end = int(b) if b.strip() else size - 1
                elif b.strip():
                    start = max(0, size - int(b))
                else:
                    raise ValueError
            except Exception:
                start, end = 0, size - 1
            start = max(0, min(start, size - 1))
            end = max(start, min(end, size - 1))
            partial = True
        try:
            with open(path, "rb") as f:
                f.seek(start)
                data = f.read(end - start + 1)
        except Exception:
            return False
        try:
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                self.send_header("Content-Range",
                                 "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if https_enabled():
                self.send_header("Strict-Transport-Security",
                                 "max-age=15552000")
            self.end_headers()
            self.wfile.write(data)
            note_traffic(activity_user_id(), tx=len(data), requests=1)
        except Exception:
            pass
        return True

    def _stream_file(self, path, ctype, download_name=""):
        """分块发送大文件（如 ZIP），避免把整个压缩包读进内存。"""
        try:
            size = os.path.getsize(path)
        except Exception:
            return False
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            if download_name:
                safe = re.sub(r"[^A-Za-z0-9._-]", "-", download_name)[:120]
                self.send_header("Content-Disposition",
                                 'attachment; filename="%s"' % safe)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if https_enabled():
                self.send_header("Strict-Transport-Security",
                                 "max-age=15552000")
            self.end_headers()
        except Exception:
            return False
        sent = 0
        try:
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
        except Exception:
            pass
        note_traffic(activity_user_id(), tx=sent, requests=1)
        return True

    def _query(self):
        if "?" not in self.path:
            return {}
        out = {}
        for part in self.path.split("?", 1)[1].split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k] = urllib.request.unquote(v)
        return out

    # ------------------------------------------------------------ GET
    LICENSE_BYPASS_GET = {
        "/license", "/api/license", "/api/session", "/i18n.js", "/sw.js",
        "/favicon.ico", "/comfyui.ico", "/manifest.json", "/cert.pem",
    }

    def do_GET(self):
        set_activity_user(None)
        path = self.path.split("?")[0]
        q = self._query()
        if (license_guard.license_required()
                and path not in self.LICENSE_BYPASS_GET):
            if path == "/":
                if not self._authed():
                    self._send(200, LOGIN_PAGE, "text/html; charset=utf-8")
                else:
                    self._send(302, b"", headers={"Location": "/license"})
                return
            if path.startswith("/api/"):
                self._json({"error": "商用版尚未激活", "code": "license_required"}, 403)
                return
            self._send(302, b"", headers={"Location": "/license"})
            return
        if path == "/license":
            self._send(200, LICENSE_PAGE, "text/html; charset=utf-8")
            return
        if path == "/api/license":
            self._json(license_guard.status(force=True))
            return
        if path in ("/universe", "/universe.html") and not self._authed():
            self._send(302, b"", headers={"Location": "/"})
            return
        # worker 路由和证书必须在登录 cookie 校验之前处理
        if path.startswith("/api/worker/"):
            self._handle_worker_get(path, q)
            return
        if path == "/cert.pem":
            self._serve_cert()
            return
        if path == "/metrics":
            token = q.get("token") or ""
            auth = self.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
            if not monitor_center.metrics_token_ok(token):
                self._json({"error": "metrics 未启用或 token 不正确"}, 404)
                return
            snap = monitor_snapshot()
            text = monitor_center.metrics_text(
                snap, monitor_center.evaluate(snap))
            self._send(200, text, "text/plain; version=0.0.4; charset=utf-8")
            return
        authed = self._authed()
        # 认证通过后先建立用户上下文，后面所有 activity_request 都会带 uid，
        # 避免管理员请求被当成匿名全局事件广播给普通账号。
        if authed:
            self._current_user()

        if path in ("/", "/index.html"):
            self._send(200, PAGE if authed else LOGIN_PAGE,
                       "text/html; charset=utf-8")
            return

        if path == "/api/session":
            user = self._current_user() if authed else None
            self._json({"authed": bool(user), "need_login": auth_enabled(),
                        "https": https_enabled(), "auth": auth_enabled(),
                        "user": public_user(user) if user else None})
            return

        if path == "/api/preferences":
            user = self._current_user()
            self._json({
                "default_home": normalize_home(
                    (user or {}).get("default_home")),
                "translation_mode": normalize_translation_mode(
                    (user or {}).get("translation_mode")),
                "translation": translation_status(user),
            })
            return

        # 语言包登录页也要用，放在鉴权之前
        if path == "/i18n.js":
            try:
                with open(os.path.join(ROOT, "i18n.js"), "r",
                          encoding="utf-8") as fh:
                    self._send(200, fh.read(),
                               "application/javascript; charset=utf-8")
            except Exception:
                self._send(404, "not found", "text/plain; charset=utf-8")
            return

        # 其余一切（图库、图片、缩略图、接口）都必须先登录
        if not authed:
            self._deny()
            return

        if path == "/ws/activity":
            user = self._current_user()
            if not is_admin(user):
                audit("security", "admin_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      route="/ws/activity", method="GET")
                self._json({"error": "只有管理员可以连接"}, 403)
                return
            self._serve_activity_ws(user)
            return

        if path in ("/universe", "/universe.html"):
            # 手机端不再提供 3D 星图，直接回平面工作台；桌面/平板不受影响。
            if self._is_mobile():
                self._send(302, "", "text/plain; charset=utf-8",
                           headers=[("Location", "/")])
                return
            try:
                with open(os.path.join(ROOT, "宇宙接口图.html"), "r",
                          encoding="utf-8") as fh:
                    self._send(200, fh.read(), "text/html; charset=utf-8")
            except Exception:
                self._send(404, "not found", "text/plain; charset=utf-8")
            return

        if path == "/manifest.webmanifest":
            self._send(200, json.dumps(MANIFEST, ensure_ascii=False),
                       "application/manifest+json; charset=utf-8")
            return

        if path == "/sw.js":
            self._send(200, SW_JS, "application/javascript; charset=utf-8")
            return

        if path in ("/icon-192.png", "/icon-512.png"):
            size = 192 if "192" in path else 512
            p = app_icon(size)
            if p and self._file(p, "image/png"):
                return
            self._send(404, "no icon", "text/plain; charset=utf-8")
            return

        if path.startswith("/api/status/"):
            jid = path.rsplit("/", 1)[-1]
            user = self._current_user()
            with JOBS_LOCK:
                job = JOBS.get(jid)
            if (job and not is_admin(user)
                    and job.get("user_id") != (user or {}).get("id")):
                job = None
            if not job:
                self._json({"status": "error", "error": "任务不存在"}, 404)
            else:
                cpid = job.get("comfy_prompt_id")
                with WS_LOCK:
                    prog = dict(WS_PROGRESS.get(cpid) or {}) if cpid else {}
                    has_prev = bool(cpid and cpid in WS_PREVIEW)
                qinfo = scheduler_job_info(jid)
                queued_for = 0
                if job.get("status") == "queued" and job.get("queued_at"):
                    queued_for = round(time.time() - job["queued_at"], 1)
                self._json({
                    "status": job["status"],
                    "elapsed": job.get("elapsed", 0),
                    "image": job.get("image"),
                    "images": job.get("images") or (
                        [job["image"]] if job.get("image") else []),
                    "error": job.get("error"),
                    "seed": job.get("seed"),
                    "progress": prog,
                    "preview": has_prev,
                    "kind": job.get("kind"),
                    "mode": job.get("mode"),
                    "model": job.get("model"),
                    "worker_id": job.get("worker_id") or "",
                    "worker_name": job.get("worker_name") or "",
                    "worker_kind": job.get("worker_kind") or "",
                    "retry_count": int(job.get("retry_count") or 0),
                    "dispatch_state": job.get("dispatch_state") or "",
                    "started": job.get("started"),
                    "queued_at": job.get("queued_at"),
                    "queued_for": queued_for,
                    "queue_position": qinfo.get("queue_position"),
                    "queue_size": qinfo.get("queue_size"),
                    "queue_eta": qinfo.get("queue_eta"),
                    "queue_eta_min": qinfo.get("queue_eta_min"),
                    "queue_eta_max": qinfo.get("queue_eta_max"),
                    "queue_start_in": qinfo.get("queue_start_in"),
                    "queue_finish_in": qinfo.get("queue_finish_in"),
                    "queue_state": qinfo.get("queue_state"),
                    "queue_reason": qinfo.get("queue_reason"),
                    "queue_slot": qinfo.get("queue_slot"),
                })
            return

        if path == "/api/load":
            touch_presence()
            ensure_load_sampler()
            ensure_guard()
            with LOAD_LOCK:
                snap = dict(LOAD_STATE)
            snap["ts"] = round(time.time(), 3)
            snap["guard"] = guard_snapshot()
            self._json(snap)
            return

        if path == "/api/guard":
            # 主页面用它做心跳 + 读取“是否该暂停生图”
            touch_presence()
            ensure_guard()
            self._json(guard_snapshot())
            return

        if path == "/api/workflow":
            touch_presence()
            self._json(workflow_snapshot())
            return

        if path == "/api/activity":
            touch_presence()
            ensure_guard()
            user = self._current_user()
            admin = is_admin(user)
            uid = (user or {}).get("id") or ""
            uname = (user or {}).get("username") or ""
            try:
                since = max(0, int(q.get("since", 0)))
            except Exception:
                since = 0
            now = time.time()
            with ACTIVITY_LOCK:
                events = []
                for e in ACTIVITY:
                    if not (e["seq"] > since and now - e["t"] <= 45):
                        continue
                    # 敏感操作静默；私有后台事件只走定向 WebSocket
                    if e.get("silent") or e.get("private_user_id"):
                        continue
                    if not admin and e.get("user") not in ("", None, uname):
                        continue
                    if not admin and e.get("user_id") not in ("", None, uid):
                        continue
                    item = dict(e)
                    item["mine"] = (e.get("user_id") == uid)
                    events.append(item)
                last = ACTIVITY_SEQ
            running = []
            with JOBS_LOCK:
                raw_running = [(jid, dict(job)) for jid, job in JOBS.items()
                               if job.get("status") in ("queued", "running")
                               and (admin or job.get("user_id") == uid)]
            for jid, job in raw_running:
                cpid = job.get("comfy_prompt_id")
                with WS_LOCK:
                    prog = dict(WS_PROGRESS.get(cpid) or {}) if cpid else {}
                    has_prev = bool(cpid and cpid in WS_PREVIEW)
                qinfo = scheduler_job_info(jid)
                queued_for = 0
                if job.get("status") == "queued" and job.get("queued_at"):
                    queued_for = round(now - job["queued_at"], 1)
                item = {"job_id": jid,
                        "status": job.get("status"),
                        "started": job.get("started"),
                        "queued_at": job.get("queued_at"),
                        "queued_for": queued_for,
                        "elapsed": job.get("elapsed", 0),
                        "value": prog.get("value"),
                        "max": prog.get("max"),
                        "preview": has_prev,
                        "queue_position": qinfo.get("queue_position"),
                        "queue_size": qinfo.get("queue_size"),
                        "queue_eta": qinfo.get("queue_eta"),
                        "queue_eta_min": qinfo.get("queue_eta_min"),
                        "queue_eta_max": qinfo.get("queue_eta_max"),
                        "queue_start_in": qinfo.get("queue_start_in"),
                        "queue_finish_in": qinfo.get("queue_finish_in"),
                        "queue_state": qinfo.get("queue_state"),
                        "queue_reason": qinfo.get("queue_reason"),
                        "queue_slot": qinfo.get("queue_slot"),
                        "worker_id": job.get("worker_id") or "",
                        "worker_name": job.get("worker_name") or "",
                        "worker_kind": job.get("worker_kind") or "",
                        "mine": job.get("user_id") == uid}
                item.update(job_activity_fields(job))
                running.append(item)
            # 正在采样的排最前；同状态按入队/开始时间从新到旧。
            # 主页面和星图优先接管自己的任务，避免管理员误接别人的。
            running.sort(key=lambda x: (
                0 if x.get("status") == "running" else 1,
                -(x.get("started") or x.get("queued_at") or 0)))
            with AUTO_LOCK:
                auto = dict(AUTO)
                if not admin and auto.get("user_id") not in (None, uid):
                    auto = {"running": False, "done": 0, "target": 0}
            online = presence_snapshot()
            if not admin:
                # 普通账号不暴露其他在线用户；管理员才看全部
                online = [x for x in online if x.get("id") == uid]
            self._json({"seq": last, "now": round(now, 3),
                        "events": events[-140:], "running": running,
                        "auto": auto,
                        "online": online})
            return

        if path == "/api/logs":
            user = self._current_user()
            admin = is_admin(user)
            uid = (user or {}).get("id") or ""
            category = (q.get("category") or "activity").strip().lower()
            if category not in ("activity", "security"):
                category = "activity"
            if category == "security" and not admin:
                self._json({"error": "只有管理员能看安全日志"}, 403)
                return
            try:
                limit = int(q.get("limit") or 100)
            except Exception:
                limit = 100
            scope_uid = None if (admin and q.get("scope") != "me") else uid
            rows = read_audit(category, limit=limit, user_id=scope_uid,
                              q=q.get("q") or "")
            self._json({"logs": rows, "category": category,
                        "scope": "all" if scope_uid is None else "me",
                        "count": len(rows)})
            return

        if path == "/api/usage/export":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            target = str(q.get("uid") or "")
            uid = (target if admin and target else user.get("id")) or ""
            if not admin and uid != user.get("id"):
                self._json({"error": "只能导出自己的用量"}, 403)
                return
            fmt = str(q.get("format") or "csv").lower()
            rows = usage_export_rows(uid if (target or not admin) else None)
            audit("activity", "usage_export", user=user,
                  ip=self.client_address[0], target=uid, format=fmt,
                  rows=len(rows))
            if fmt == "json":
                body = json.dumps({"rows": rows, "exported": time.time()},
                                  ensure_ascii=False, indent=1)
                self._send(200, body, "application/json; charset=utf-8",
                           headers={"Content-Disposition":
                                    'attachment; filename="usage.json"'})
            else:
                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(["date", "user_id", "username", "name",
                                 "role", "requests", "rx_bytes", "tx_bytes",
                                 "images", "gpu_seconds", "jobs", "kinds"])
                for r in rows:
                    writer.writerow([
                        r["date"], r["user_id"], r["username"], r["name"],
                        r["role"], r["requests"], r["rx_bytes"],
                        r["tx_bytes"], r["images"], r["gpu_seconds"],
                        r["jobs"], json.dumps(r["kinds"], ensure_ascii=False),
                    ])
                self._send(200, buf.getvalue(), "text/csv; charset=utf-8",
                           headers={"Content-Disposition":
                                    'attachment; filename="usage.csv"'})
            return

        if path == "/api/usage":
            user = self._current_user()
            admin = is_admin(user)
            if admin:
                rows = admin_users_payload()
                scope = "all"
            else:
                item = public_user(user)
                if item:
                    item["usage"] = user_usage((user or {}).get("id"))
                    item["usage_mb"] = round(
                        item["usage"].get("bytes", 0) / 1048576, 1)
                rows = [item] if item else []
                scope = "me"
            self._json({"users": rows, "scope": scope,
                        "you": public_user(user)})
            return

        if path == "/api/plugins":
            activity_request("/api/plugins", "GET", throttle=1.0, silent=True)
            user = self._current_user()
            uid = (user or {}).get("id") or "admin"
            try:
                payload = plugin_manager.user_center(uid)
            except Exception as exc:
                self._json({"error": "读取插件中心失败：%s" % exc}, 500)
                return
            lim = user_limits(user)
            feats = lim.get("features") or {}
            payload["features"] = {
                "plugin_pack": feature_allowed(user, "plugin_pack"),
                "plugin_submit": feature_allowed(user, "plugin_submit"),
            }
            payload["is_admin"] = is_admin(user)
            payload["restart_required"] = plugin_manager.restart_required()
            self._json(payload)
            return

        if path.startswith("/api/admin/plugins/submission/"):
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以下载待审批插件"}, 403)
                return
            sid = urllib.request.unquote(
                path[len("/api/admin/plugins/submission/"):])
            try:
                zip_path, name = plugin_manager.submission_zip(sid)
            except ValueError as exc:
                self._json({"error": str(exc)}, 404)
                return
            if not self._stream_file(zip_path, "application/zip", name):
                self._json({"error": "文件不存在"}, 404)
            return

        if path == "/api/admin/plugins":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理插件"}, 403)
                return
            try:
                self._json(plugin_manager.admin_snapshot())
            except Exception:
                self._json({"error": "读取插件注册表失败，请查看服务日志"}, 500)
            return

        if path == "/api/models":
            activity_request("/api/models", "GET", throttle=6.0, silent=True)
            user = self._current_user()
            models = list_models()
            if not is_admin(user):
                allowed = user_limits(user).get("allowed_models") or []
                if allowed:
                    models = [m for m in models
                              if m.get("name") in allowed
                              or os.path.splitext(str(m.get("name")))[0]
                              in allowed]
            self._json({"models": models,
                        "default": (models[0]["name"] if models else None),
                        "negative": DEFAULT_NEGATIVE,
                        "upscalers": [UPSCALE_ANIME, UPSCALE_PHOTO_SHARP,
                                      UPSCALE_PHOTO],
                        "loras": list_loras(),
                        "styles": plugin_styles_for(user),
                        "samplers": [{"key": k, "label": v["label"]}
                                     for k, v in SAMPLERS.items()],
                        "default_sampler": DEFAULT_SAMPLER,
                        "video_ready": video_ready(),
                        "video_model": VIDEO_UNET,
                        "video_sizes": list(VIDEO_SIZES),
                        "video_min_seconds": VIDEO_MIN_SECONDS,
                        "video_max_seconds": VIDEO_MAX_SECONDS,
                        "translate_ready": translation_ready_for(user),
                        "translation": translation_status(user),
                        "auth": auth_enabled(),
                        "https": https_enabled(),
                        "user": public_user(user)})
            return

        if path == "/api/stats":
            activity_request("/api/stats", "GET", throttle=2.0, silent=True)
            self._json(gallery_stats(self._current_user()))
            return

        if path == "/api/jobstats":
            user = self._current_user()
            admin = is_admin(user)
            uid = (user or {}).get("id") or ""
            with JOBS_LOCK:
                jobs = [dict(j) for j in JOBS.values()
                        if admin or j.get("user_id") == uid]
            counts = {"total": len(jobs), "running": 0, "queued": 0,
                      "done": 0, "error": 0, "cancelled": 0}
            by_model = {}
            for job in jobs:
                st = job.get("status")
                if st in counts:
                    counts[st] += 1
                if st == "done":
                    model = os.path.basename(job.get("model") or "未知")
                    by_model[model] = by_model.get(model, 0) + 1
            # 从当前账号可见的任务里重建耗时：服务重启后 DURATIONS 会清空，
            # 而且全局 DURATIONS 会把其他账号的模型名和耗时段泄露给普通账号。
            done = [j for j in jobs if j.get("status") == "done"
                    and isinstance(j.get("elapsed"), (int, float))
                    and float(j.get("elapsed")) > 0]
            done.sort(key=lambda j: (j.get("finished_at") or j.get("saved_at")
                                     or j.get("started") or 0))
            durs = [(str(j.get("model") or "未知"), j.get("steps") or 0,
                     j.get("count") or 1, float(j.get("elapsed") or 0))
                    for j in done]
            avg = round(sum(d[3] for d in durs) / len(durs), 1) if durs else None
            self._json({"counts": counts, "avg_seconds": avg,
                        "by_model": by_model,
                        "recent": [{"model": os.path.basename(str(d[0])),
                                    "seconds": round(d[3], 1)}
                                   for d in durs[-10:]]})
            return

        if path == "/api/errors":
            user = self._current_user()
            admin = is_admin(user)
            uid = (user or {}).get("id") or ""
            with JOBS_LOCK:
                items = []
                for jid, job in JOBS.items():
                    if not admin and job.get("user_id") != uid:
                        continue
                    st = job.get("status")
                    if st not in ("error", "cancelled"):
                        continue
                    items.append({
                        "job_id": jid,
                        "status": st,
                        "kind": job.get("kind") or job.get("mode") or "",
                        "model": os.path.basename(job.get("model") or ""),
                        "error": str(job.get("error") or "")[:180],
                        "started": job.get("started") or 0,
                        "elapsed": job.get("elapsed", 0),
                    })
            items.sort(key=lambda x: x.get("started") or 0, reverse=True)
            self._json({"errors": items[:20]})
            return

        if path == "/api/dictionary":
            query = (q.get("q") or "").strip()
            ql = query.lower()
            hits = []
            if ql:
                for zh, tag in CHAR_ALIASES.items():
                    zl = str(zh).lower()
                    tl = str(tag).lower()
                    if ql in zl or ql in tl:
                        score = 0 if zl == ql else 1 if zl.startswith(ql) else 2
                        hits.append((score, str(zh), str(tag), "character"))
                for zh, tag in CHAR_SERIES.items():
                    zl = str(zh).lower()
                    tl = str(tag).lower()
                    if ql in zl or ql in tl:
                        score = 0 if zl == ql else 1 if zl.startswith(ql) else 2
                        hits.append((score, str(zh), str(tag), "series"))
                hits.sort(key=lambda x: (x[0], len(x[1])))
            self._json({
                "q": query,
                "counts": {"characters": len(CHAR_ALIASES),
                           "series": len(CHAR_SERIES)},
                "matches": [{"zh": h[1], "tag": h[2], "kind": h[3]}
                            for h in hits[:24]],
            })
            return

        if path == "/api/auto":
            activity_request("/api/auto", "GET", throttle=2.5)
            user = self._current_user()
            uid = (user or {}).get("id") or ""
            with AUTO_LOCK:
                snap = dict(AUTO)
            if not is_admin(user) and snap.get("user_id") not in ("", uid):
                snap = {"running": False, "done": 0, "target": 0,
                        "stop": False, "user_id": "", "username": ""}
            self._json(snap)
            return

        if path.startswith("/preview/"):
            jid = path.rsplit("/", 1)[-1]
            user = self._current_user()
            with JOBS_LOCK:
                job = JOBS.get(jid) or {}
            if (job and not is_admin(user)
                    and job.get("user_id") != (user or {}).get("id")):
                job = {}
            cpid = job.get("comfy_prompt_id")
            with WS_LOCK:
                blob = WS_PREVIEW.get(cpid) if cpid else None
            if blob:
                self._send(200, blob, "image/jpeg")
            else:
                self._send(204, b"", "image/jpeg")
            return

        if path == "/api/workers/bundle":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以生成部署包"}, 403)
                return
            try:
                scheme = "https" if https_enabled() else "http"
                central = "%s://%s:%d" % (scheme, HOTSPOT_IP, PORT)
                data, profile = worker_bundle.build_bundle(
                    ROOT, central, worker_name="")
                safe_host = re.sub(r"[^A-Za-z0-9._-]+", "_",
                                   socket.gethostname())[:40] or "host"
                filename = "ComfyUI-Worker-%s-%s.zip" % (
                    safe_host, time.strftime("%Y%m%d-%H%M%S"))
                audit("security", "worker_bundle", user=user,
                      ip=self.client_address[0], ok=True,
                      models=len(profile.get("models") or []),
                      nodes=len(profile.get("custom_nodes") or []))
                self._send(200, data, "application/zip", {
                    "Content-Disposition":
                        'attachment; filename="%s"' % filename,
                    "Cache-Control": "no-store",
                })
            except Exception as exc:
                self._json({"error": "生成部署包失败：%s" % exc}, 500)
            return

        if path == "/api/workers":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理算力节点"}, 403)
                return
            payload = lan_share.admin_payload()
            payload["local"] = self._local_worker_payload()
            try:
                payload["telemetry"] = monitor_center.all_worker_series(60)
            except Exception:
                payload["telemetry"] = {}
            self._json(payload)
            return

        if path == "/api/my/workers":
            self._handle_workers_mine()
            return

        if path == "/api/teams":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            rows = teams.list_for_user(user.get("id") or "", admin)
            for team in rows:
                for member in team.get("members") or []:
                    u = get_user(member.get("id")) or {}
                    member["username"] = u.get("username") or member.get("id")
                    member["name"] = u.get("name") or member.get("username")
            self._json({"teams": rows, "admin": admin,
                        "you": user.get("id") or ""})
            return

        if path == "/api/team_prompts":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            tid = str(q.get("team") or "").strip()[:80]
            if not tid or not teams.can_view(user.get("id") or "", tid, admin):
                self._json({"error": "没有权限查看这个团队"}, 403)
                return
            rows = teams.list_prompts(tid)
            for row in rows:
                u = get_user(row.get("by")) or {}
                row["by_name"] = u.get("name") or u.get("username") or row.get("by")
            team = teams.get_team(tid) or {}
            self._json({"prompts": rows,
                        "role": teams.role_of(user.get("id") or "", tid)
                        or ("admin" if admin else ""),
                        "team": teams.public_team(team, len(rows))})
            return

        if path == "/api/sessions":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            target = str(q.get("uid") or "")
            uid = (target if admin and target else user.get("id")) or ""
            if not admin and uid != user.get("id"):
                self._json({"error": "只能查看自己的登录设备"}, 403)
                return
            rows = sessions_for_user(uid)
            current = session_sid(self._cookie(COOKIE_NAME))
            for row in rows:
                row["current"] = bool(current and row.get("sid") == current)
            self._json({"sessions": rows, "uid": uid,
                        "username": (get_user(uid) or {}).get("username", uid)})
            return

        if path == "/api/users":
            user = self._current_user()
            if not is_admin(user):
                audit("security", "admin_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      route="/api/users", method="GET")
                self._json({"error": "只有管理员可以管理账号"}, 403)
                return
            # 后台刷新只定向推给管理员自己，普通账号的星图不应看到。
            activity_request("/api/users", "GET", throttle=1.0, silent=True,
                             private_user_id=(user or {}).get("id"))
            self._json({"users": admin_users_payload(),
                        "quota": account_quota(),
                        "me": public_user(user)})
            return

        if path == "/api/admin/translation":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以设置翻译模型"}, 403)
                return
            cfg = local_llm.load()
            self._json({"config": local_llm.public_config(cfg),
                        "status": translation_status(user),
                        "argos_ready": translate_ready()})
            return

        if path == "/api/admin/queue":
            user = self._current_user()
            if not is_admin(user):
                audit("security", "admin_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      route="/api/admin/queue", method="GET")
                self._json({"error": "只有管理员可以管理队列"}, 403)
                return
            activity_request("/api/admin/queue", "GET", throttle=1.0, silent=True,
                             private_user_id=(user or {}).get("id"))
            counts = {}
            with JOBS_LOCK:
                for job in JOBS.values():
                    st = job.get("status")
                    if st not in ("queued", "running"):
                        continue
                    uid = job.get("user_id") or "admin"
                    rec = counts.setdefault(uid, {"queued": 0, "running": 0})
                    rec["queued" if st == "queued" else "running"] += 1
            rows = []
            with USERS_LOCK:
                for u in USERS.values():
                    rec = counts.get(u.get("id"), {})
                    rows.append({
                        "id": u.get("id"),
                        "username": u.get("username"),
                        "name": u.get("name") or u.get("username"),
                        "role": u.get("role") or "user",
                        "enabled": bool(u.get("enabled", True)),
                        "queued": rec.get("queued", 0),
                        "running": rec.get("running", 0),
                    })
            control = queue_control.public()
            for row in rows:
                row["paused"] = row["id"] in (control.get("paused_users")
                                               or {})
                row["boost"] = int((control.get("priority_boost")
                                    or {}).get(row["id"], 0))
            rows.sort(key=lambda r: (-(r["queued"] + r["running"]),
                                     r.get("id") or ""))
            self._json({"control": control, "queue": scheduler_snapshot(),
                        "users": rows})
            return

        if path == "/api/admin/system":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以进行系统维护"}, 403)
                return
            snaps = system_state.list_snapshots(ROOT)
            payload = lan_share.admin_payload()
            with USERS_LOCK:
                user_count = len(USERS)
                guest_count = sum(1 for u in USERS.values()
                                  if u.get("guest"))
            self._json({
                "snapshots": snaps,
                "summary": {
                    "users": user_count,
                    "guests": guest_count,
                    "workers": len(payload.get("workers") or []),
                    "local_llm": local_llm.public_config(),
                },
                "snapshot_dir": system_state.SNAPSHOT_DIR_NAME,
                "restore_scope": list(system_state.CONFIG_FILES),
                "license": license_guard.status(),
            })
            return

        if path == "/api/supervisor":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以查看守护设置"}, 403)
                return
            settings = runtime_settings.load()
            status = runtime_settings.read_status()
            updated = float(status.get("updated") or 0)
            age = max(0.0, time.time() - updated) if updated else None
            timeout = max(15, int(settings.get("check_seconds") or 5) * 3)
            running = bool(status.get("running")) and age is not None and age <= timeout
            self._json({
                "settings": settings,
                "status": status,
                "running": running,
                "age": round(age, 1) if age is not None else None,
                "recovery_pending": len(RECOVERY_PENDING),
            })
            return

        if path == "/api/time":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以查看时间同步"}, 403)
                return
            self._json(trusted_time.status())
            return

        if path == "/api/monitor/overview":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以查看监控总览"}, 403)
                return
            snap = monitor_snapshot()
            alerts = monitor_center.evaluate(snap)
            self._json({
                "health": monitor_center.health(snap),
                "summary": monitor_center.alert_summary(),
                "snapshot": {
                    "gpu_util": snap.get("gpu_util"),
                    "vram_used_mb": snap.get("vram_used_mb"),
                    "vram_total_mb": snap.get("vram_total_mb"),
                    "gpu_temp_c": snap.get("gpu_temp_c"),
                    "cpu_percent": snap.get("cpu_percent"),
                    "ram_percent": snap.get("ram_percent"),
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
                    "storage": snap.get("storage"),
                },
                "alerts": alerts[:12],
                "trends": monitor_center.trends(24),
                "workers": snap.get("workers") or [],
                "generated": time.time(),
            })
            return

        if path == "/api/monitor/alerts":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以查看告警中心"}, 403)
                return
            snap = monitor_snapshot()
            monitor_center.evaluate(snap)
            try:
                limit = max(1, min(200, int(q.get("limit", 100))))
            except Exception:
                limit = 100
            self._json({
                "active": monitor_center.active_alerts(),
                "history": monitor_center.alert_history(limit),
                "summary": monitor_center.alert_summary(),
                "settings": monitor_center.public_settings(),
                "generated": time.time(),
            })
            return

        if path == "/api/monitor/trends":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以查看趋势"}, 403)
                return
            try:
                hours = max(1, min(168, int(q.get("hours", 24))))
            except Exception:
                hours = 24
            self._json({"trends": monitor_center.trends(hours),
                        "hours": hours, "generated": time.time()})
            return

        if path == "/api/monitor/storage":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以查看容量预测"}, 403)
                return
            self._json({"storage": storage_forecast(force=bool(q.get("refresh"))),
                        "generated": time.time()})
            return

        if path == "/api/monitor/settings":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以修改监控设置"}, 403)
                return
            self._json({"settings": monitor_center.public_settings()})
            return

        if path == "/api/admin/nodes":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理自定义节点"}, 403)
                return
            check = str(q.get("check") or "") in ("1", "true", "yes")
            if check:
                payload = node_manager.check_all()
            else:
                payload = {"nodes": node_manager.list_nodes(check=False),
                           "summary": None}
            payload["dir"] = "ComfyUI/custom_nodes"
            payload["limits"] = {
                "max_upload_mb": node_manager.MAX_UPLOAD_BYTES // 1048576,
                "max_extract_mb": node_manager.MAX_EXTRACT_BYTES // 1048576,
            }
            self._json(payload)
            return

        if path == "/api/admin/workflows":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理工作流"}, 403)
                return
            check = str(q.get("check") or "") in ("1", "true", "yes")
            object_info = comfy_object_info_cached() if check else None
            model_payload = _models_payload()
            if check:
                payload = workflow_manager.check_all(object_info,
                                                     model_payload)
            else:
                payload = {"workflows": workflow_manager.list_workflows(),
                           "summary": None}
            payload["comfy_online"] = bool(object_info)
            payload["model_count"] = sum(
                len(c.get("files") or [])
                for c in model_payload.get("categories") or [])
            self._json(payload)
            return

        if path.startswith("/api/admin/workflows/"):
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以下载工作流"}, 403)
                return
            wid = urllib.request.unquote(path[len("/api/admin/workflows/"):])
            meta = workflow_manager.load_workflow(wid, include_raw=True)
            if not meta:
                self._json({"error": "工作流不存在"}, 404)
                return
            body = json.dumps(meta.get("raw") or {}, ensure_ascii=False,
                              indent=1)
            self._send(200, body, "application/json; charset=utf-8",
                       headers={"Content-Disposition":
                                'attachment; filename="%s.json"' %
                                (wid or "workflow")})
            return

        if path == "/api/admin/cleanup":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以设置磁盘清理"}, 403)
                return
            data = cleanup_overview()
            data["generated"] = time.time()
            self._json(data)
            return

        if path == "/api/admin/report":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以生成体检报告"}, 403)
                return
            try:
                report, filename = build_health_report()
            except Exception as exc:
                self._json({"error": "生成体检报告失败：%s" % exc}, 500)
                return
            audit("security", "health_report", user=user,
                  ip=self.client_address[0], bytes=len(report))
            self._send(200, report, "application/zip", {
                "Content-Disposition":
                    'attachment; filename="%s"' % filename,
                "Cache-Control": "no-store",
            })
            return

        if path == "/api/admin/models":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理模型"}, 403)
                return
            data = _models_payload()
            data["categories_meta"] = model_manager.category_public()
            data["generated"] = time.time()
            self._json(data)
            return

        if path == "/api/monitor/jobs":
            user = self._current_user()
            self._json({"jobs": monitor_recent_jobs(user, q.get("limit", 20)),
                        "generated": time.time()})
            return

        if path.startswith("/api/monitor/timeline/"):
            user = self._current_user()
            jid = path.rsplit("/", 1)[-1]
            data = job_timeline(jid, user)
            if not data:
                self._json({"error": "任务不存在或无权查看"}, 404)
                return
            self._json({"timeline": data})
            return

        if path.startswith("/api/monitor/worker/"):
            user = self._current_user()
            wid = path.rsplit("/", 1)[-1]
            worker = lan_share.get_worker(wid)
            if not worker:
                self._json({"error": "算力节点不存在"}, 404)
                return
            if not is_admin(user) and worker.get("owner_id") != (user or {}).get("id"):
                self._json({"error": "只能查看自己的算力节点"}, 403)
                return
            self._json({
                "worker": lan_share.worker_public(
                    worker, admin=is_admin(user)),
                "series": monitor_center.worker_series(wid, 60),
            })
            return

        if path == "/api/gallery":
            activity_request("/api/gallery", "GET", throttle=0.7, silent=True)
            try:
                offset = max(0, int(q.get("offset", 0)))
            except Exception:
                offset = 0
            try:
                limit = max(1, min(200, int(q.get("limit", 40))))
            except Exception:
                limit = 40
            kind = q.get("kind") or "all"
            fav_only = q.get("fav") in ("1", "true") or kind == "fav"
            if kind == "fav":
                kind = "all"
            user = self._current_user()
            if not self._require_traffic(user):
                return
            if not self._require_feature(user, "gallery"):
                return
            admin = is_admin(user)
            uid = user.get("id") or "admin"
            model = (q.get("model") or "").strip()[:80]
            if model in ("all", "全部"):
                model = ""
            user_filter = (q.get("user") or "").strip()[:40] if admin else ""
            if user_filter in ("all", "全部"):
                user_filter = ""
            team_id = str(q.get("team") or "").strip()[:80]
            team_info = None
            scope_uids = None
            if team_id:
                team = teams.get_team(team_id)
                if not team:
                    self._json({"error": "团队不存在"}, 404)
                    return
                role = teams.role_of(uid, team_id)
                if not role and not admin:
                    self._json({"error": "你不在这个团队里"}, 403)
                    return
                scope_uids = set(teams.members_for(team_id)) | {uid}
                team_info = teams.public_team(
                    team, len(teams.list_prompts(team_id)))
                team_info["role"] = "admin" if admin and not role else role
                user_filter = ""
            items, total = list_gallery(
                offset, limit, kind, fav_only, q.get("q"),
                folder=(model or None),
                scope_uid=None if (admin or team_id) else uid,
                user_filter=(user_filter or None) if admin and not team_id else None,
                fav_uid=uid,
                scope_uids=scope_uids)
            self._json({"items": items, "total": total, "offset": offset,
                        "folders": gallery_folders(
                            None if (admin or team_id) else uid,
                            scope_uids=scope_uids),
                        "users": gallery_users() if admin and not team_id else [],
                        "teams": teams.list_for_user(uid, admin),
                        "team": team_info,
                        "cleanup": disk_cleanup.notice(),
                        "you": public_user(user)})
            return

        if path == "/api/jobs":
            activity_request("/api/jobs", "GET", throttle=2.0, silent=True)
            user = self._current_user()
            admin = is_admin(user)
            uid = (user or {}).get("id") or ""
            with JOBS_LOCK:
                rows = [dict(job_id=k, **{kk: vv for kk, vv in v.items()
                                          if kk in ("status", "elapsed", "error",
                                                    "images", "started",
                                                    "queued_at", "user_id",
                                                    "username", "kind", "mode",
                                                    "model", "worker_id",
                                                    "worker_name", "worker_kind",
                                                    "retry_count")})
                        for k, v in JOBS.items()
                        if admin or v.get("user_id") == uid]
            for row in rows:
                info = scheduler_job_info(row["job_id"])
                row.update({"queue_position": info.get("queue_position"),
                            "queue_size": info.get("queue_size"),
                            "queue_eta": info.get("queue_eta"),
                            "queue_eta_min": info.get("queue_eta_min"),
                            "queue_eta_max": info.get("queue_eta_max"),
                            "queue_start_in": info.get("queue_start_in"),
                            "queue_finish_in": info.get("queue_finish_in"),
                            "queue_state": info.get("queue_state"),
                            "queue_reason": info.get("queue_reason"),
                            "queue_slot": info.get("queue_slot")})
            rows.sort(key=lambda r: r.get("started") or r.get("queued_at") or 0,
                      reverse=True)
            self._json({"jobs": rows[:10], "queue": scheduler_snapshot()})
            return

        if path.startswith("/archive/"):
            user = self._current_user()
            if not self._require_traffic(user):
                return
            if not self._require_feature(user, "organize"):
                return
            token = path.rsplit("/", 1)[-1]
            fp, display = archive_download(token, user)
            if not fp:
                self._send(404, "not found", "text/plain; charset=utf-8")
                return
            activity_request("/archive", "GET", throttle=0.5,
                             count=1, silent=True)
            audit("activity", "archive_download", user=user,
                  ip=self.client_address[0])
            self._stream_file(fp, "application/zip", display)
            return

        if path.startswith("/thumb/"):
            activity_request("/thumb", "GET", throttle=1.2)
            name = urllib.request.unquote(path[7:])
            user = self._current_user()
            if not self._require_traffic(user):
                return
            tp = thumb_path(name, user)
            if tp and os.path.isfile(tp):
                self._file(tp, "image/jpeg")
            else:
                fp = find_image(name, user)
                if fp and self._file(
                        fp,
                        MEDIA_CTYPES.get(os.path.splitext(name)[1].lower(),
                                         "application/octet-stream")):
                    return
                self._send(404, "not found", "text/plain; charset=utf-8")
            return

        if path.startswith("/img/"):
            activity_request("/img", "GET", throttle=1.2)
            name = urllib.request.unquote(path[5:])
            user = self._current_user()
            if not self._require_traffic(user):
                return
            fp = find_image(name, user)
            ctype = MEDIA_CTYPES.get(os.path.splitext(name)[1].lower(),
                                     "application/octet-stream")
            if fp and self._file(fp, ctype):
                return
            self._send(404, "not found", "text/plain; charset=utf-8")
            return

        self._send(404, "not found", "text/plain; charset=utf-8")

    # ------------------------------------------------------------ POST
    def do_POST(self):
        set_activity_user(None)
        route = self.path.split("?")[0]
        if (license_guard.license_required()
                and route not in ("/api/license", "/api/login",
                                  "/api/logout")):
            self._json({"error": "商用版尚未激活", "code": "license_required"}, 403)
            return

        # worker 请求有自己的 token 和原始字节协议，必须在 cookie 校验和
        # 通用 JSON 解析之前分流。
        if route.startswith("/api/worker/"):
            self._handle_worker_post(route)
            return

        # 除登录/退出外，没登录的请求连 body 都不读，直接挡掉
        if route not in ("/api/login", "/api/logout") and not self._authed():
            self._deny()
            return
        if route not in ("/api/login", "/api/logout"):
            self._current_user()

        if route == "/api/admin/models/upload_chunk":
            self._handle_model_chunk()
            return
        if route == "/api/admin/nodes/upload_chunk":
            self._handle_node_chunk()
            return

        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            self._json({"error": "Content-Length 无效"}, 400)
            return
        # 负数会让 rfile.read(-1) 一直读到连接断开，把线程挂住
        if n < 0:
            self._json({"error": "Content-Length 不合法"}, 400)
            return
        if n > MAX_BODY_BYTES:
            self._json({"error": "请求体太大"}, 413)
            return
        try:
            raw = self.rfile.read(n) if n else b"{}"
            note_traffic(activity_user_id(), rx=n)
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            self._json({"error": "请求格式错误"}, 400)
            return

        # 登录 / 退出：这两个不需要已经登录
        if route == "/api/login":
            self._handle_login(data)
            return

        if route == "/api/logout":
            user = self._current_user()
            if user:
                audit("activity", "logout", user=user,
                      ip=self.client_address[0])
            activity_request("/api/logout", "POST")
            drop_session(self._cookie(COOKIE_NAME))
            self._send(200, json.dumps({"ok": True}),
                       headers=[self._set_cookie_header("", 0)])
            return

        if route == "/api/license":
            user = self._current_user()
            if auth_enabled() and not is_admin(user):
                self._json({"error": "只有管理员可以激活商用版"}, 403)
                return
            code = str(data.get("code") or "")
            try:
                new_status = license_guard.activate(code)
            except ValueError as exc:
                audit("security", "license_activate", user=user,
                      ip=self.client_address[0], ok=False, reason=str(exc)[:80])
                self._json({"error": str(exc)}, 400)
                return
            audit("security", "license_activate", user=user,
                  ip=self.client_address[0], ok=True,
                  customer=new_status.get("customer"),
                  expires=new_status.get("expires"))
            activity_request("/api/license", "POST", ok=True, silent=True)
            self._json({"ok": True, "status": new_status})
            return

        if route == "/api/workers":
            self._handle_workers_admin(data)
            return

        if route == "/api/my/workers":
            self._handle_workers_mine(data)
            return

        if route == "/api/cancel":
            user = self._current_user()
            admin = is_admin(user)
            uid = (user or {}).get("id") or "admin"
            scope_all = bool(admin and data.get("all"))
            target = str(data.get("job_id") or data.get("id") or "").strip()
            with JOBS_LOCK:
                mine = [(jid, dict(job)) for jid, job in JOBS.items()
                        if job.get("status") in ("queued", "running")
                        and (not target or jid == target)
                        and (scope_all or job.get("user_id") == uid)]
            if not mine:
                self._json({"error": "没有可取消的任务"}, 403)
                return
            # 本机任务用定向 interrupt；远端任务只发取消指令，绝不打断
            # 中央本机 ComfyUI 上别人的任务。
            local_running = [(jid, job) for jid, job in mine
                             if job.get("status") == "running"
                             and (job.get("worker_id") in ("", "local"))]
            remote_running = [(jid, job) for jid, job in mine
                              if job.get("status") == "running"
                              and job.get("worker_id") not in ("", "local")]
            if local_running:
                try:
                    current = comfy_current_prompt()
                except Exception:
                    current = ""
                for _jid, job in local_running:
                    cpid = job.get("comfy_prompt_id") or ""
                    if not cpid:
                        continue
                    try:
                        http_json("/interrupt", {"prompt_id": cpid}, timeout=15)
                        http_json("/queue", {"delete": [cpid]}, timeout=10)
                    except Exception:
                        pass
            cancelled = []
            stages = []
            with JOBS_LOCK:
                for jid, job in JOBS.items():
                    if job.get("status") not in ("queued", "running"):
                        continue
                    if target and jid != target:
                        continue
                    if not scope_all and job.get("user_id") != uid:
                        continue
                    was_remote = job.get("worker_id") not in ("", "local")
                    job["status"] = "error"
                    job["error"] = "已取消"
                    item = {"job_id": jid,
                            "elapsed": job.get("elapsed", 0)}
                    item.update(job_activity_fields(job))
                    cancelled.append(item)
                    # 远端任务的输入/临时目录由 run_job 的 finally 清理，
                    # 这里先删会让 worker 下载输入失败。
                    if not was_remote:
                        stages.append((job.get("user_id") or uid,
                                       job.get("stage_id")))
            for jid, _job in remote_running:
                request_remote_cancel(jid)
            for jid, _job in mine:
                scheduler_cancel_job(jid)
            for juid, sid in stages:
                cleanup_stage(juid, sid)
            activity_request("/api/cancel", "POST", count=len(cancelled),
                             user=user.get("username"))
            audit("activity", "cancel", user=user,
                  ip=self.client_address[0], count=len(cancelled))
            for item in cancelled:
                activity("job", phase="cancel", **item)
            self._json({"ok": True, "cancelled": len(cancelled),
                        "queue": scheduler_snapshot()})
            return

        if route == "/api/teams":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            uid = user.get("id") or ""
            action = str(data.get("action") or "")
            try:
                if action == "create":
                    team = teams.create_team(data.get("name"), uid)
                    audit("activity", "team_create", user=user,
                          ip=self.client_address[0], target=team.get("id"))
                else:
                    tid = str(data.get("id") or "").strip()[:80]
                    if not tid or not teams.get_team(tid):
                        self._json({"error": "团队不存在"}, 404)
                        return
                    if not teams.can_manage(uid, tid, admin):
                        self._json({"error": "只有团队所有者可以管理"}, 403)
                        return
                    if action == "update":
                        team = teams.update_team(tid, data.get("name"))
                    elif action == "delete":
                        teams.delete_team(tid)
                        audit("activity", "team_delete", user=user,
                              ip=self.client_address[0], target=tid)
                        self._json({"ok": True})
                        return
                    elif action == "add_member":
                        target = str(data.get("uid") or "").strip()
                        if not target:
                            found = find_user(str(data.get("username") or ""))
                            target = (found or {}).get("id") or ""
                        if not target or not get_user(target):
                            self._json({"error": "账号不存在"}, 404)
                            return
                        team = teams.add_member(
                            tid, target, data.get("role") or "viewer")
                    elif action == "remove_member":
                        team = teams.remove_member(
                            tid, str(data.get("uid") or ""))
                    elif action == "set_role":
                        team = teams.set_role(
                            tid, str(data.get("uid") or ""),
                            data.get("role") or "viewer")
                    else:
                        self._json({"error": "未知操作"}, 400)
                        return
                    audit("activity", "team_" + action, user=user,
                          ip=self.client_address[0], target=tid)
                self._json({"ok": True, "team": teams.public_team(
                    team, len(teams.list_prompts(team.get("id"))))})
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            return

        if route == "/api/team_prompts":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            uid = user.get("id") or ""
            tid = str(data.get("team") or "").strip()[:80]
            if not tid or not teams.can_view(uid, tid, admin):
                self._json({"error": "没有权限访问这个团队"}, 403)
                return
            action = str(data.get("action") or "")
            try:
                if action == "add":
                    if not teams.can_edit(uid, tid, admin):
                        self._json({"error": "只读成员不能添加提示词"}, 403)
                        return
                    item = teams.add_prompt(tid, data.get("text"), by=uid)
                elif action == "delete":
                    teams.delete_prompt(tid, str(data.get("id") or ""),
                                        uid=uid, admin=admin)
                    item = None
                else:
                    self._json({"error": "未知操作"}, 400)
                    return
                audit("activity", "team_prompt_" + action, user=user,
                      ip=self.client_address[0], target=tid)
                self._json({"ok": True, "prompt": item,
                            "prompts": teams.list_prompts(tid)})
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            return

        if route == "/api/sessions":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            admin = is_admin(user)
            action = str(data.get("action") or "")
            current = session_sid(self._cookie(COOKIE_NAME))
            removed = 0
            if action == "revoke":
                sid = str(data.get("sid") or "")
                removed = drop_session_sid(user.get("id"), sid, admin=admin)
            elif action == "revoke_others":
                removed = drop_other_sessions(user.get("id"), current)
            elif action == "revoke_user" and admin:
                target = str(data.get("uid") or "")
                if not target or not get_user(target):
                    self._json({"error": "账号不存在"}, 404)
                    return
                drop_user_sessions(target)
                removed = 1
            else:
                self._json({"error": "未知操作"}, 400)
                return
            audit("security", "session_revoke", user=user,
                  ip=self.client_address[0], ok=True, operation=action,
                  removed=removed)
            self._json({"ok": True, "removed": removed})
            return

        if route == "/api/password":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            old = str(data.get("old_password") or "")
            new = str(data.get("new_password") or "")
            if not verify_user_password(user, old):
                audit("security", "password_change_denied", user=user,
                      ip=self.client_address[0], ok=False)
                self._json({"error": "当前密码不对"}, 403)
                return
            if len(new) < 8:
                self._json({"error": "新密码至少 8 位"}, 400)
                return
            if new == old:
                self._json({"error": "新密码不能和当前密码一样"}, 400)
                return
            try:
                update_user(user.get("id"), {"password": new})
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            audit("security", "password_change", user=user,
                  ip=self.client_address[0], ok=True)
            self._json({"ok": True})
            return

        if route == "/api/preferences":
            user = self._current_user()
            if not user:
                self._json({"error": "需要登录"}, 401)
                return
            home = normalize_home(data.get("default_home"))
            tr_mode = normalize_translation_mode(
                data.get("translation_mode",
                         (user or {}).get("translation_mode")))
            status = translation_status(user)
            if tr_mode == "local" and not status.get("local_ready"):
                self._json({"error": "管理员还没有启用本地翻译模型"}, 400)
                return
            update_user(user.get("id"),
                        {"default_home": home,
                         "translation_mode": tr_mode})
            activity_request("/api/preferences", "POST",
                             default_home=home, translation_mode=tr_mode,
                             user=user.get("username"))
            audit("activity", "preference_update", user=user,
                  ip=self.client_address[0], default_home=home,
                  translation_mode=tr_mode)
            fresh = get_user(user.get("id"))
            self._json({"ok": True, "default_home": home,
                        "translation_mode": tr_mode,
                        "translation": translation_status(fresh),
                        "redirect": ("/universe" if home == "star"
                                     and not self._is_mobile() else "/"),
                        "user": public_user(fresh)})
            return

        if route == "/api/admin/batch":
            user = self._current_user()
            if not is_admin(user):
                audit("security", "admin_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      route="/api/admin/batch", method="POST")
                self._json({"error": "只有管理员可以批量操作"}, 403)
                return
            action = str(data.get("action") or "")
            raw_ids = data.get("ids")
            if not isinstance(raw_ids, list):
                self._json({"error": "请选择账号"}, 400)
                return
            ids = []
            for it in raw_ids[:200]:
                uid = str(it or "")
                if uid and uid not in ids:
                    ids.append(uid)
            if not ids:
                self._json({"error": "请选择账号"}, 400)
                return
            if action not in ("enable", "disable", "delete", "update"):
                self._json({"error": "未知批量操作"}, 400)
                return

            limit_keys = ("daily_images", "max_images", "max_storage_mb",
                          "max_upload_mb", "max_pixels", "max_steps",
                          "max_count", "max_concurrent",
                          "daily_traffic_mb", "monthly_traffic_mb")
            limits = data.get("limits")
            features = data.get("features")
            limits = limits if isinstance(limits, dict) else {}
            features = features if isinstance(features, dict) else {}
            has_update = bool(limits or features)
            if action == "update" and not has_update:
                self._json({"error": "没有要修改的字段"}, 400)
                return

            applied = []
            failed = []
            for uid in ids:
                if action in ("disable", "delete") and uid == user.get("id"):
                    failed.append({"id": uid, "error": "不能操作当前登录账号"})
                    continue
                try:
                    target = get_user(uid)
                    if not target:
                        raise ValueError("账号不存在")
                    if action == "enable":
                        update_user(uid, {"enabled": True})
                    elif action == "disable":
                        update_user(uid, {"enabled": False})
                    elif action == "delete":
                        delete_user(uid)
                    else:
                        base = dict(target.get("limits") or {})
                        if limits:
                            for key in limit_keys:
                                if key in limits:
                                    base[key] = limits[key]
                        if features:
                            feats = dict(base.get("features") or {})
                            for key, val in features.items():
                                if key in FEATURE_LABELS:
                                    feats[key] = bool(val)
                            base["features"] = feats
                        update_user(uid, {"limits": base})
                    applied.append(uid)
                except Exception as exc:
                    failed.append({"id": uid, "error": str(exc)})
            audit("security", "admin_batch", user=user,
                  ip=self.client_address[0], operation=action,
                  target=",".join(ids[:20]), count=len(applied),
                  failed=len(failed))
            audit("activity", "admin_batch", user=user,
                  ip=self.client_address[0], operation=action,
                  count=len(applied), failed=len(failed))
            activity_request("/api/admin/batch", "POST", action=action,
                             count=len(applied), silent=True)
            self._json({"ok": not failed, "applied": len(applied),
                        "failed": failed, "action": action,
                        "users": admin_users_payload()})
            return

        if route == "/api/monitor/diagnostics":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以运行诊断"}, 403)
                return
            try:
                result = diagnose_system()
            except Exception as exc:
                self._json({"error": "诊断失败：%s" % exc}, 500)
                return
            audit("security", "monitor_diagnostics", user=user,
                  ip=self.client_address[0],
                  summary=result.get("summary"))
            self._json(result)
            return

        if route == "/api/monitor/settings":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以修改监控设置"}, 403)
                return
            action = str(data.get("action") or "save")
            try:
                if action == "rotate_metrics":
                    token = monitor_center.new_metrics_token()
                    cfg = monitor_center.save_settings({
                        "metrics_enabled": True,
                        "metrics_token": token,
                    })
                    result = {"settings": monitor_center.public_settings(cfg),
                              "metrics_token": token}
                elif action == "clear_metrics":
                    cfg = monitor_center.save_settings({
                        "clear_metrics_token": True,
                        "metrics_enabled": False,
                    })
                    result = {"settings": monitor_center.public_settings(cfg)}
                elif action == "test_webhook":
                    ok, error = monitor_center.send_test_webhook()
                    result = {"ok": ok, "error": error,
                              "settings": monitor_center.public_settings()}
                else:
                    patch = {}
                    for key in ("alerts_enabled", "gpu_high",
                                "gpu_temp_high", "queue_warn",
                                "worker_offline_sec", "worker_critical_sec",
                                "error_rate_pct", "error_min_jobs",
                                "disk_free_gb", "cert_days", "job_stuck_min",
                                "webhook_enabled", "webhook_url",
                                "webhook_cooldown", "job_notify",
                                "job_notify_start", "job_notify_done",
                                "job_notify_error", "metrics_enabled"):
                        if key in data:
                            patch[key] = data.get(key)
                    cfg = monitor_center.save_settings(patch)
                    result = {"settings": monitor_center.public_settings(cfg)}
            except Exception as exc:
                self._json({"error": "保存监控设置失败：%s" % exc}, 400)
                return
            audit("security", "monitor_settings", user=user,
                  ip=self.client_address[0], operation=action)
            self._json(result)
            return

        if route == "/api/admin/models":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理模型"}, 403)
                return
            action = str(data.get("action") or "")
            try:
                if action == "delete":
                    category = str(data.get("category") or "")
                    name = str(data.get("name") or "")
                    payload = _models_payload()
                    if name in (payload.get("busy_models") or []):
                        self._json({"error": "这个模型正在被任务使用，先等任务结束或取消"}, 409)
                        return
                    meta = model_manager.remove_model(
                        category, name, by=user.get("id") or "")
                    audit("security", "model_delete", user=user,
                          ip=self.client_address[0], model_category=category,
                          model=meta.get("name"), mb=round(
                              (meta.get("size") or 0) / 1048576, 1))
                    self._json({"ok": True, "trashed": meta,
                                "models": _models_payload()})
                    return
                if action == "restore":
                    meta = model_manager.restore_model(
                        str(data.get("id") or ""))
                    audit("security", "model_restore", user=user,
                          ip=self.client_address[0],
                          model_category=meta.get("category"),
                          model=meta.get("name"))
                    self._json({"ok": True, "models": _models_payload()})
                    return
                if action == "purge":
                    removed = model_manager.purge_model(
                        str(data.get("id") or ""))
                    audit("security", "model_purge", user=user,
                          ip=self.client_address[0], files=removed)
                    self._json({"ok": True, "models": _models_payload()})
                    return
                if action == "empty_trash":
                    removed = model_manager.empty_trash()
                    audit("security", "model_empty_trash", user=user,
                          ip=self.client_address[0], files=removed)
                    self._json({"ok": True, "removed": removed,
                                "models": _models_payload()})
                    return
                if action == "import_path":
                    category = str(data.get("category") or "")
                    info = model_manager.import_path(
                        category, data.get("path"),
                        move=bool(data.get("move")),
                        by=user.get("id") or "")
                    audit("security", "model_import", user=user,
                          ip=self.client_address[0], model_category=category,
                          model=info.get("name"), move=bool(data.get("move")))
                    self._json({"ok": True, "file": info,
                                "models": _models_payload()})
                    return
                if action == "upload_start":
                    info = model_manager.upload_start(
                        str(data.get("category") or ""),
                        data.get("filename"), data.get("size"),
                        by=user.get("id") or "")
                    self._json({"ok": True, "upload": info})
                    return
                if action == "upload_finish":
                    info = model_manager.upload_finish(
                        str(data.get("upload_id") or ""))
                    audit("security", "model_upload", user=user,
                          ip=self.client_address[0],
                          model_category=(info or {}).get("category") or "",
                          model=info.get("name"),
                          mb=round((info.get("size") or 0) / 1048576, 1))
                    self._json({"ok": True, "file": info,
                                "models": _models_payload()})
                    return
                if action == "upload_cancel":
                    removed = model_manager.upload_cancel(
                        str(data.get("upload_id") or ""))
                    self._json({"ok": True, "removed": removed})
                    return
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except Exception as exc:
                self._json({"error": "模型操作失败：%s" % exc}, 400)
                return
            self._json({"error": "未知操作"}, 400)
            return

        if route == "/api/admin/queue":
            user = self._current_user()
            if not is_admin(user):
                audit("security", "admin_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      route="/api/admin/queue", method="POST")
                self._json({"error": "只有管理员可以管理队列"}, 403)
                return
            action = str(data.get("action") or "")
            reason = str(data.get("reason") or "")[:200]
            target = str(data.get("uid") or "").strip()
            if action in ("pause_user", "resume_user", "boost_user",
                          "cancel_user"):
                if not target or not get_user(target):
                    self._json({"error": "账号不存在"}, 404)
                    return
            cancelled = 0
            if action == "pause_all":
                queue_control.set_paused(True, reason, by=user.get("username") or "")
            elif action == "resume_all":
                queue_control.set_paused(False, "", by=user.get("username") or "")
            elif action == "pause_user":
                queue_control.set_user_paused(
                    target, True, reason, by=user.get("username") or "")
            elif action == "resume_user":
                queue_control.set_user_paused(
                    target, False, "", by=user.get("username") or "")
            elif action == "boost_user":
                queue_control.set_priority(target, data.get("boost"))
            elif action == "cancel_user":
                jids = scheduler_cancel_user(target)
                for jid in jids:
                    if cancel_queued_job(jid, "管理员取消排队任务"):
                        cancelled += 1
            elif action == "set_max_wait":
                queue_control.set_max_wait(data.get("seconds"))
            elif action == "set_maintenance":
                days = data.get("days")
                if not isinstance(days, list):
                    days = []
                queue_control.set_maintenance(
                    bool(data.get("enabled")),
                    data.get("start") or "02:00",
                    data.get("end") or "04:00",
                    days)
            elif action == "kick":
                pass
            else:
                self._json({"error": "未知操作"}, 400)
                return
            ensure_queue_watchdog()
            scheduler_kick()
            audit("security", "queue_" + action, user=user,
                  ip=self.client_address[0], ok=True,
                  target=target, reason=reason,
                  cancelled=cancelled)
            self._json({"ok": True, "cancelled": cancelled,
                        "control": queue_control.public(),
                        "queue": scheduler_snapshot()})
            return

        if route == "/api/plugins":
            user = self._current_user()
            uid = (user or {}).get("id") or "admin"
            action = str(data.get("action") or "")
            try:
                if action == "import_pack":
                    if not self._require_feature(user, "plugin_pack"):
                        return
                    manifest = data.get("manifest")
                    if manifest is None and data.get("content") is not None:
                        raw = str(data.get("content") or "")
                        if len(raw.encode("utf-8")) > plugin_manager.MAX_PACK_BYTES:
                            self._json({"error": "插件包超过 256KB"}, 400)
                            return
                        try:
                            manifest = json.loads(raw)
                        except Exception:
                            self._json({"error": "插件包不是合法 JSON"}, 400)
                            return
                    pack = plugin_manager.import_pack(uid, manifest)
                    audit("security", "plugin_pack_import", user=user,
                          ip=self.client_address[0], target=pack.get("id"))
                    self._json({"ok": True, "pack": pack,
                                "plugins": plugin_manager.user_center(uid),
                                "restart_required": False})
                    return
                if action == "toggle_pack":
                    if not self._require_feature(user, "plugin_pack"):
                        return
                    pack = plugin_manager.set_pack_enabled(
                        uid, data.get("id"), bool(data.get("enabled", True)))
                    self._json({"ok": True, "pack": pack,
                                "plugins": plugin_manager.user_center(uid)})
                    return
                if action == "delete_pack":
                    if not self._require_feature(user, "plugin_pack"):
                        return
                    plugin_manager.delete_pack(uid, data.get("id"))
                    audit("security", "plugin_pack_delete", user=user,
                          ip=self.client_address[0], target=str(data.get("id")))
                    self._json({"ok": True,
                                "plugins": plugin_manager.user_center(uid)})
                    return
                if action == "submit_node":
                    if not self._require_feature(user, "plugin_submit"):
                        return
                    raw_b64 = str(data.get("zip_b64") or "")
                    if not raw_b64:
                        self._json({"error": "没有收到 ZIP 文件"}, 400)
                        return
                    if len(raw_b64) > (plugin_manager.MAX_SUBMIT_BYTES * 4 // 3) + 8192:
                        self._json({"error": "代码插件 ZIP 最大 20MB"}, 400)
                        return
                    try:
                        blob = base64.b64decode(raw_b64, validate=True)
                    except Exception:
                        self._json({"error": "ZIP 数据损坏"}, 400)
                        return
                    sub = plugin_manager.submit_node(
                        uid, data.get("filename"), blob,
                        admin=is_admin(user))
                    audit("security", "plugin_submit", user=user,
                          ip=self.client_address[0], target=sub.get("name"),
                          size=sub.get("size"), risk=sub.get("risk_level"))
                    self._json({"ok": True, "submission": sub,
                                "plugins": plugin_manager.user_center(uid)})
                    return
                if action == "cancel_submission":
                    plugin_manager.cancel_submission(
                        uid, data.get("id"), admin=is_admin(user))
                    self._json({"ok": True,
                                "plugins": plugin_manager.user_center(uid)})
                    return
                self._json({"error": "未知操作"}, 400)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            except Exception:
                self._json({"error": "插件操作失败，请查看服务日志"}, 500)
            return

        if route == "/api/admin/plugins":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理插件"}, 403)
                return
            action = str(data.get("action") or "")
            try:
                target = ""
                if action == "approve":
                    target = str(data.get("name") or data.get("id") or "")
                    result = plugin_manager.approve_submission(
                        data.get("id"), user,
                        force=bool(data.get("force")),
                        replace=bool(data.get("replace")))
                    target = result.get("name") or target
                elif action == "reject":
                    result = plugin_manager.reject_submission(
                        data.get("id"), user, data.get("reason") or "")
                    target = data.get("id") or ""
                elif action == "disable":
                    result = plugin_manager.disable_node(
                        str(data.get("name") or ""), user)
                    target = result.get("name") or ""
                elif action == "enable":
                    result = plugin_manager.enable_node(
                        str(data.get("name") or ""), user)
                    target = result.get("name") or ""
                elif action == "rollback":
                    result = plugin_manager.rollback_node(
                        str(data.get("name") or ""), user)
                    target = result.get("name") or ""
                elif action == "verify":
                    result = plugin_manager.verify_node(
                        str(data.get("name") or ""), user)
                    target = result.get("name") or ""
                elif action == "remove":
                    result = plugin_manager.remove_managed_node(
                        str(data.get("name") or ""), user)
                    target = result.get("name") or ""
                elif action == "disable_all":
                    removed = plugin_manager.disable_all_managed(user)
                    self._json({"ok": True, "disabled": removed,
                                "restart_required": True})
                    return
                elif action == "clear_restart":
                    plugin_manager.clear_restart_flag()
                    self._json({"ok": True, "restart_required": False})
                    return
                elif action == "delete_pack":
                    plugin_manager.delete_pack(
                        data.get("owner") or "", data.get("id"))
                    self._json({"ok": True,
                                "snapshot": plugin_manager.admin_snapshot()})
                    return
                else:
                    self._json({"error": "未知操作"}, 400)
                    return
                audit("security", "plugin_" + action, user=user,
                      ip=self.client_address[0], target=target, ok=True)
                self._json({"ok": True, "result": result,
                            "snapshot": plugin_manager.admin_snapshot(),
                            "restart_required": plugin_manager.restart_required()})
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            except Exception:
                self._json({"error": "插件操作失败，请查看服务日志"}, 500)
            return

        if route == "/api/admin/nodes":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理自定义节点"}, 403)
                return
            action = str(data.get("action") or "")
            try:
                if action == "import_path":
                    info = node_manager.import_path(
                        data.get("path"), data.get("name"),
                        replace=bool(data.get("replace")))
                    plugin_manager.adopt_installed(
                        info.get("name"), user.get("id") or "")
                    audit("security", "node_import", user=user,
                          ip=self.client_address[0], target=info.get("name"))
                    self._json({"ok": True, "node": info,
                                "nodes": node_manager.list_nodes(),
                                "restart_required": True})
                    return
                if action == "check":
                    name = str(data.get("name") or "")
                    if name:
                        info = node_manager.check_node(name)
                    else:
                        info = node_manager.check_all()
                    self._json({"ok": True, "result": info})
                    return
                if action == "remove":
                    name = str(data.get("name") or "")
                    dest = node_manager.remove_node(name)
                    plugin_manager.note_removed(node_manager.safe_node_name(name))
                    audit("security", "node_remove", user=user,
                          ip=self.client_address[0], target=name)
                    self._json({"ok": True, "trash": os.path.basename(dest),
                                "nodes": node_manager.list_nodes(),
                                "restart_required": True})
                    return
                if action == "upload_start":
                    info = node_manager.upload_start(
                        data.get("filename"), data.get("size"),
                        by=user.get("id") or "")
                    self._json({"ok": True, "upload": info})
                    return
                if action == "upload_finish":
                    info = node_manager.upload_finish(
                        data.get("upload_id"),
                        replace=bool(data.get("replace")))
                    plugin_manager.adopt_installed(
                        info.get("name"), user.get("id") or "")
                    audit("security", "node_import", user=user,
                          ip=self.client_address[0], target=info.get("name"))
                    self._json({"ok": True, "node": info,
                                "nodes": node_manager.list_nodes(),
                                "restart_required": True})
                    return
                if action == "upload_cancel":
                    removed = node_manager.upload_cancel(
                        data.get("upload_id"))
                    self._json({"ok": True, "removed": removed})
                    return
                self._json({"error": "未知操作"}, 400)
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            return

        if route == "/api/admin/workflows":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以管理工作流"}, 403)
                return
            action = str(data.get("action") or "import")
            object_info = comfy_object_info_cached()
            model_payload = _models_payload()
            try:
                if action == "import":
                    info = workflow_manager.import_content(
                        data.get("content"), name=data.get("name") or "",
                        filename=data.get("filename") or "",
                        by=user.get("id") or "",
                        object_info=object_info,
                        model_payload=model_payload)
                elif action == "import_path":
                    info = workflow_manager.import_path(
                        data.get("path"), name=data.get("name") or "",
                        by=user.get("id") or "",
                        object_info=object_info,
                        model_payload=model_payload)
                elif action == "check":
                    wid = str(data.get("id") or "")
                    if wid:
                        info = workflow_manager.check_saved(
                            wid, object_info, model_payload)
                    else:
                        info = workflow_manager.check_all(
                            object_info, model_payload)
                elif action == "delete":
                    workflow_manager.delete_workflow(str(data.get("id") or ""))
                    audit("security", "workflow_delete", user=user,
                          ip=self.client_address[0],
                          target=str(data.get("id") or ""))
                    self._json({"ok": True,
                                "workflows": workflow_manager.list_workflows()})
                    return
                else:
                    self._json({"error": "未知操作"}, 400)
                    return
                audit("security", "workflow_import" if action in
                      ("import", "import_path") else "workflow_check",
                      user=user, ip=self.client_address[0], ok=True,
                      target=(info or {}).get("id") if isinstance(info, dict)
                      else "")
                self._json({"ok": True, "result": info,
                            "workflows": workflow_manager.list_workflows()})
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
            return

        if route == "/api/admin/cleanup":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以设置磁盘清理"}, 403)
                return
            action = str(data.get("action") or "save")
            if action == "run":
                result = run_disk_cleanup("manual", user=user)
                audit("security", "disk_cleanup_run", user=user,
                      ip=self.client_address[0],
                      operation=result.get("skipped") or "done",
                      deleted=result.get("deleted_images", 0) +
                      result.get("deleted_outputs", 0))
                self._json({"ok": True, "result": result,
                            "overview": cleanup_overview()})
                return
            if action != "save":
                self._json({"error": "未知操作"}, 400)
                return
            patch = {}
            for key in ("enabled", "retention_days", "min_free_gb",
                        "target_free_gb", "include_videos",
                        "include_comfy_output", "max_files_per_run"):
                if key in data:
                    patch[key] = data.get(key)
            cfg = disk_cleanup.save(patch)
            audit("security", "disk_cleanup_settings", user=user,
                  ip=self.client_address[0], enabled=bool(cfg.get("enabled")),
                  retention_days=cfg.get("retention_days"),
                  min_free_gb=cfg.get("min_free_gb"),
                  target_free_gb=cfg.get("target_free_gb"))
            self._json({"ok": True,
                        "settings": disk_cleanup.public_settings(cfg),
                        "overview": cleanup_overview()})
            return

        if route == "/api/monitor/alerts":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以处理告警"}, 403)
                return
            action = str(data.get("action") or "")
            if action == "ack":
                ok = monitor_center.ack_alert(str(data.get("id") or ""))
                if not ok:
                    self._json({"error": "告警不存在"}, 404)
                    return
                self._json({"ok": True,
                            "active": monitor_center.active_alerts(),
                            "summary": monitor_center.alert_summary()})
                return
            self._json({"error": "未知操作"}, 400)
            return

        if route == "/api/admin/translation":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以设置翻译模型"}, 403)
                return
            action = str(data.get("action") or "save")
            patch = {}
            for key in ("enabled", "provider", "base_url", "model",
                        "timeout", "temperature", "max_tokens"):
                if key in data:
                    patch[key] = data.get(key)
            if "api_key" in data:
                if str(data.get("api_key") or "").strip():
                    patch["api_key"] = str(data.get("api_key")).strip()
                elif data.get("clear_api_key"):
                    patch["api_key"] = ""
            try:
                if patch:
                    cfg = local_llm.save(patch)
                else:
                    cfg = local_llm.load(force=True)
                test_result = None
                if action == "test":
                    test_result = local_llm.test()
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except Exception as exc:
                self._json({"error": "保存翻译模型设置失败：%s" % exc}, 500)
                return
            activity_request("/api/admin/translation", "POST",
                             action=action, silent=True)
            audit("security", "translation_config", user=user,
                  ip=self.client_address[0], operation=action,
                  enabled=bool(cfg.get("enabled")),
                  provider=cfg.get("provider"), model=cfg.get("model"))
            self._json({"ok": True,
                        "config": local_llm.public_config(cfg),
                        "status": translation_status(user),
                        "test": test_result})
            return

        if route == "/api/admin/system":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以进行系统维护"}, 403)
                return
            action = str(data.get("action") or "")
            try:
                if action == "snapshot":
                    snap = system_snapshot(str(data.get("label") or "手动还原点"))
                    result = {"snapshot": snap}
                elif action == "rollback":
                    result = system_rollback(str(data.get("name") or ""))
                elif action == "reset":
                    if str(data.get("confirm") or "") != "RESET":
                        raise ValueError("请输入 RESET 确认系统重置")
                    result = system_reset(user)
                else:
                    raise ValueError("未知操作")
            except ValueError as exc:
                self._json({"error": str(exc)}, 400)
                return
            except Exception as exc:
                self._json({"error": "系统维护失败：%s" % exc}, 500)
                return
            current = get_user(user.get("id") or "")
            activity_request("/api/admin/system", "POST", action=action,
                             silent=True)
            audit("security", "system_" + action, user=user,
                  ip=self.client_address[0], ok=True,
                  detail=str(result.get("snapshot") or result.get("safety")
                             or "")[:120])
            self._json({"ok": True, "action": action, "result": result,
                        "snapshots": system_state.list_snapshots(ROOT),
                        "need_login": not user_is_active(current),
                        "user": public_user(current)})
            return

        if route == "/api/supervisor":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以修改守护设置"}, 403)
                return
            try:
                saved = runtime_settings.save(data.get("settings") or {})
            except Exception as exc:
                self._json({"error": "保存失败：%s" % exc}, 500)
                return
            activity_request("/api/supervisor", "POST", silent=True)
            audit("security", "supervisor_settings", user=user,
                  ip=self.client_address[0], ok=True,
                  enabled=saved.get("enabled"),
                  auto_restart_comfy=saved.get("auto_restart_comfy"),
                  auto_restart_web=saved.get("auto_restart_web"))
            self._json({"ok": True, "settings": saved})
            return

        if route == "/api/time":
            user = self._current_user()
            if not is_admin(user):
                self._json({"error": "只有管理员可以同步时间"}, 403)
                return
            action = str(data.get("action") or "sync")
            if action != "sync":
                self._json({"error": "未知操作"}, 400)
                return
            ok = trusted_time.sync_now()
            status = trusted_time.status()
            audit("security", "time_sync", user=user,
                  ip=self.client_address[0], ok=ok,
                  source=status.get("source"), offset=status.get("offset"))
            self._json({"ok": ok, "status": status})
            return

        if route == "/api/users":
            user = self._current_user()
            if not is_admin(user):
                audit("security", "admin_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      route="/api/users", method="POST")
                self._json({"error": "只有管理员可以管理账号"}, 403)
                return
            action = str(data.get("action") or "list")
            target_id = str(data.get("id") or "")
            target_name = str(data.get("username") or "")
            if action in ("update", "delete", "renew_guest") and target_id:
                target_name = (get_user(target_id) or {}).get("username") or target_id
            guest_result = None
            try:
                if action == "create":
                    create_user(data.get("username"), data.get("password"),
                                data.get("name"), data.get("role", "user"),
                                data.get("limits"))
                elif action == "create_guest":
                    res = create_guest(user, data.get("hours") or 24)
                    guest_result = {
                        "user": public_user(res.get("user")),
                        "password": res.get("password"),
                        "expires_at": res.get("expires_at"),
                        "hours": res.get("hours"),
                    }
                    target_name = (res.get("user") or {}).get("username") or ""
                elif action == "renew_guest":
                    res = renew_guest(target_id, data.get("hours") or 24)
                    guest_result = {
                        "user": public_user(res),
                        "hours": data.get("hours") or 24,
                    }
                elif action == "update":
                    uid = str(data.get("id") or "")
                    patch = {
                        k: data[k] for k in
                        ("name", "role", "enabled", "password", "limits")
                        if k in data
                    }
                    update_user(uid, patch)
                    if data.get("enabled") is False or data.get("password"):
                        drop_user_sessions(uid)
                elif action == "delete":
                    uid = str(data.get("id") or "")
                    if uid == user.get("id"):
                        raise ValueError("不能删除当前登录的账号")
                    delete_user(uid)
                else:
                    raise ValueError("未知操作")
            except ValueError as exc:
                audit("security", "admin_action_failed", user=user,
                      ip=self.client_address[0], ok=False, operation=action,
                      error=str(exc))
                self._json({"error": str(exc)}, 400)
                return
            # 创建 / 修改 / 删除账号属于敏感后台操作，不进入视觉播报
            activity_request("/api/users", "POST", action=action,
                             by=user.get("username"), silent=True)
            target = target_name or str(data.get("username") or data.get("id") or "")
            audit("security", "user_" + action, user=user,
                  ip=self.client_address[0], target=target,
                  role=data.get("role") or "",
                  enabled=data.get("enabled"),
                  password_reset=bool(data.get("password")))
            audit("activity", "user_" + action, user=user,
                  ip=self.client_address[0], target=target)
            self._json({"ok": True, "users": admin_users_payload(),
                        "quota": account_quota(),
                        "guest": guest_result,
                        "me": public_user(get_user(user.get("id")))})
            return

        if route == "/api/favorite":
            user = self._current_user()
            if not self._require_feature(user, "gallery"):
                return
            name = safe_media_rel(data.get("name") or "")
            if not name:
                self._json({"error": "缺少图片名"}, 400)
                return
            owner, _model, _fname = split_media_rel(name)
            uid = (user or {}).get("id") or ""
            if (not is_admin(user) and owner != uid
                    and not teams.share_owner(uid, owner)):
                self._json({"error": "没有权限"}, 403)
                return
            uid = (user or {}).get("id") or "admin"
            favs = load_favorites(uid)
            if data.get("on"):
                favs.add(name)
            else:
                favs.discard(name)
            save_favorites(uid, favs)
            activity_request("/api/favorite", "POST",
                             on=bool(data.get("on")))
            audit("activity", "favorite", user=user,
                  ip=self.client_address[0], on=bool(data.get("on")),
                  owner=owner)
            self._json({"ok": True, "fav": name in favs})
            return

        if route == "/api/delete":
            user = self._current_user()
            if not self._require_feature(user, "delete"):
                return
            removed = delete_images(data.get("names") or [], user)
            # 删除图片是敏感操作：只写日志，不触发星图闪烁
            activity_request("/api/delete", "POST",
                             count=len(data.get("names") or []),
                             removed_count=len(removed), silent=True)
            audit("activity", "delete_images",
                  user=self._current_user(), ip=self.client_address[0],
                  count=len(data.get("names") or []),
                  removed=len(removed))
            self._json({"ok": True, "removed": removed})
            return

        if route == "/api/upscale":
            self._handle_upscale(data)
            return

        if route == "/api/translate":
            user = self._current_user()
            if not self._require_feature(user, "translate"):
                return
            text, text_info = input_guard.clean_text(data.get("text"), 4000)
            activity_request("/api/translate", "POST", chars=len(text))
            if not text:
                self._json({"error": "要翻译的内容是空的"}, 400)
                return
            if USE_PROMPT_OPTIMIZER:
                self._json({"text": optimize_prompt(text), "provider": "tags",
                            "input_cleaned": text_info})
            else:
                cleaned, tags = extract_char_tags(text)
                out, provider, err = translate_text_for_user(cleaned, user)
                if not out and has_chinese(cleaned):
                    self._json({"error": err or "翻译失败，请检查翻译组件",
                                "provider": provider}, 502)
                    return
                if tags:
                    out = ", ".join(tags) + ", " + (out or "")
                self._json({"text": out, "provider": provider,
                            "input_cleaned": text_info,
                            "fallback": provider == "argos"
                            and normalize_translation_mode(
                                (user or {}).get("translation_mode")) == "local"})
            return

        if route == "/api/collage":
            user = self._current_user()
            if not self._require_feature(user, "organize"):
                return
            try:
                cols = int(data.get("cols") or 2)
            except Exception:
                cols = 2
            activity_request("/api/collage", "POST",
                             count=len(data.get("names") or []),
                             cols=cols)
            audit("activity", "collage", user=self._current_user(),
                  ip=self.client_address[0],
                  count=len(data.get("names") or []), cols=cols)
            name = make_collage(data.get("names") or [], cols,
                                self._current_user())
            if name:
                self._json({"ok": True, "name": name})
            else:
                self._json({"error": "没有可用的图片"}, 400)
            return

        if route == "/api/archive":
            user = self._current_user()
            if not self._require_feature(user, "organize"):
                return
            names = data.get("names")
            if not isinstance(names, list) or not names:
                self._json({"error": "请先选择要下载的图片"}, 400)
                return
            if len(names) > ARCHIVE_MAX_FILES:
                self._json({"error": "一次最多打包 %d 个文件" %
                            ARCHIVE_MAX_FILES}, 400)
                return
            result, error = make_archive(names, user)
            if not result:
                self._json({"error": error}, 400)
                return
            activity_request("/api/archive", "POST",
                             count=result["count"], silent=True)
            audit("activity", "archive_create", user=user,
                  ip=self.client_address[0], count=result["count"],
                  mb=round(result["size"] / 1048576, 1))
            self._json({"ok": True, "archive": result})
            return

        if route == "/api/export":
            user = self._current_user()
            if not self._require_feature(user, "organize"):
                return
            activity_request("/api/export", "POST")
            audit("activity", "export", user=user,
                  ip=self.client_address[0])
            src = safe_media_rel(data.get("name") or "")
            out = export_tagged(src, self._current_user())
            if out:
                self._json({"ok": True, "name": out})
            else:
                self._json({"error": "这张图没有可导出的参数信息"}, 400)
            return

        if route == "/api/auto":
            action = data.get("action")
            user = self._current_user()
            uid = (user or {}).get("id") or "admin"
            activity_request("/api/auto", "POST", action=action or "",
                             user=user.get("username"))
            if action != "stop" and not self._require_feature(user, "auto"):
                return
            if action == "stop":
                with AUTO_LOCK:
                    if (not is_admin(user)
                            and AUTO.get("user_id") not in ("", uid)):
                        self._json({"error": "不是你启动的挂机任务"}, 403)
                        return
                    AUTO["stop"] = True
                    AUTO["running"] = False
                audit("activity", "auto_stop", user=user,
                      ip=self.client_address[0])
                self._json({"ok": True, "running": False})
                return
            blocked = guard_block_message()
            if blocked:
                self._json({"error": blocked, "guard": guard_snapshot()}, 409)
                return
            ckpt = resolve_checkpoint(data.get("model"))
            preset = model_profile(ckpt)
            if not preset.get("supported", True):
                msg = "；".join(preset.get("warnings") or []) or \
                      "当前版本暂未自动适配这个模型，请换用 Anima、SDXL 或 SD1.5。"
                self._json({"error": msg, "model": ckpt, "profile": preset}, 400)
                return
            try:
                w, h = (int(v) for v in (data.get("size") or "832x1216").split("x"))
            except Exception:
                w, h = 832, 1216
            try:
                count = int(data.get("auto_count", 5))
            except Exception:
                count = 5
            count = max(1, min(50, count))
            try:
                interval = float(data.get("interval", 0))
            except Exception:
                interval = 0
            sampler = str(data.get("sampler") or "")
            if sampler not in SAMPLERS:
                sampler = preset.get("sampler") or DEFAULT_SAMPLER
            if preset.get("vpred"):
                sampler = "euler"
            auto_prompt, auto_prompt_info = input_guard.clean_text(
                data.get("prompt"), input_guard.MAX_PROMPT_CHARS)
            if not auto_prompt:
                self._json({"error": "提示词是空的（或只包含不可见字符）"}, 400)
                return
            auto_negative, auto_neg_info = input_guard.clean_text(
                data.get("negative"), input_guard.MAX_PROMPT_CHARS)
            params = {
                "prompt": auto_prompt,
                "negative": auto_negative
                            or (ANIMA_NEGATIVE if ckpt == ANIMA_MODEL
                                else NOOB_NEGATIVE if ckpt == NOOB_MODEL
                                else DEFAULT_NEGATIVE),
                "input_cleaned": {
                    "prompt": auto_prompt_info,
                    "negative": auto_neg_info,
                },
                "w": max(512, min(1536, w)), "h": max(512, min(1536, h)),
                "steps": max(4, min(60, int(data.get("steps")
                                            or preset.get("steps", 28)))),
                "cfg": max(1.0, min(15.0, float(data.get("cfg")
                                               or preset.get("cfg", 6.0)))),
                "seed": int.from_bytes(os.urandom(4), "little") % (2 ** 31),
                "ckpt": ckpt,
                "prompt_en": "",
                "sampler": sampler,
                "pag": bool(data.get("pag", True)),
                "turbo": bool(data.get("turbo")),
            }
            if (params["turbo"] and ckpt == ANIMA_MODEL
                    and anima_turbo_ready()):
                params["steps"] = ANIMA_TURBO_STEPS
                params["cfg"] = ANIMA_TURBO_CFG
            else:
                params["turbo"] = False
            if USE_PROMPT_OPTIMIZER:
                try:
                    if has_chinese(params["prompt"]):
                        cand = optimize_prompt(params["prompt"])
                        if cand and not has_chinese(cand):
                            params["prompt_en"] = cand
                    if has_chinese(params["negative"]):
                        cand = optimize_prompt(params["negative"], quality=False)
                        if cand and not has_chinese(cand):
                            params["negative"] = cand
                except Exception:
                    pass
            if not params["prompt"]:
                self._json({"error": "提示词是空的"}, 400)
                return
            reqs = job_requirements(params["ckpt"], [], params["turbo"], "gen")
            local_ready = bool(lan_share.settings().get("local_enabled", True)
                               and local_comfy_alive())
            if not local_ready and not scheduler_has_remote(
                    user, reqs, params["w"] * params["h"], 1):
                self._json({"error": "本机 ComfyUI 没在运行，也没有可用的算力节点。"}, 503)
                return
            lim = user_limits(user)
            if not is_admin(user) and not lim.get("allow_auto", True):
                self._json({"error": "管理员关闭了你的挂机造图权限。"}, 403)
                return
            limit_msg, quota = check_user_limits_detail(
                user, ckpt, False, params["steps"], count, "auto")
            if limit_msg:
                audit("security", "limit_denied", user=user,
                      ip=self.client_address[0], ok=False,
                      operation="auto", error=limit_msg)
                self._json({"error": limit_msg,
                            "code": "quota_exhausted" if quota else "limit_denied",
                            "quota": quota}, 403)
                return
            try:
                http_json("/system_stats", timeout=8)
            except Exception:
                self._json({"error": "ComfyUI 没在运行"})
                return
            with AUTO_LOCK:
                if AUTO["running"]:
                    if AUTO.get("user_id") not in ("", uid):
                        self._json({"error": "另一个账号正在挂机，等它结束再开"},
                                   409)
                    else:
                        self._json({"error": "已经在挂机了，先停掉再开"}, 400)
                    return
                AUTO.update(running=True, done=0, target=count, stop=False,
                            user_id=uid, username=user.get("username") or "")
            audit("activity", "auto_start", user=user,
                  ip=self.client_address[0], count=count, interval=interval,
                  model=os.path.basename(ckpt))
            threading.Thread(target=auto_loop,
                             args=(params, count, interval, uid),
                             daemon=True).start()
            self._json({"ok": True, "running": True, "target": count,
                        "input_cleaned": params.get("input_cleaned")})
            return

        if route != "/api/generate":
            self._send(404, "not found", "text/plain; charset=utf-8")
            return

        self._handle_generate(data)

    # ------------------------------------------------------------ 保存图片
    def _save_data_url(self, raw, prefix, stage_id, uid="admin",
                       max_bytes=UPLOAD_MAX_BYTES,
                       max_pixels=UPLOAD_MAX_PIXELS):
        """校验上传图片，转成干净的 PNG 存进隔离区，返回隔离区路径。"""
        uploader = get_user(uid) if uid else None
        if uploader and not feature_allowed(uploader, "upload"):
            raise ValueError("管理员暂时关闭了「上传参考图」功能。")
        if (not isinstance(raw, str) or not raw.startswith("data:image/")
                or "," not in raw):
            raise ValueError("不是有效的图片")
        _head, b64 = raw.split(",", 1)
        b64 = "".join(b64.split())
        try:
            blob = base64.b64decode(b64, validate=True)
        except Exception:
            raise ValueError("图片编码损坏")
        if not blob:
            raise ValueError("图片是空的")
        if len(blob) > max_bytes:
            raise ValueError("图片超过 %dMB" % max(1, max_bytes // 1048576))

        from PIL import Image, ImageOps
        try:
            with Image.open(io.BytesIO(blob)) as im:
                fmt = (im.format or "").upper()
                if fmt not in ("PNG", "JPEG", "WEBP"):
                    raise ValueError("只接受 PNG / JPEG / WebP")
                w, h = im.size
                if w < 1 or h < 1:
                    raise ValueError("图片尺寸无效")
                if w * h > max_pixels:
                    raise ValueError("图片像素太大（最多 %d 万像素）"
                                     % max(1, max_pixels // 10000))
                if max(w, h) > UPLOAD_MAX_SIDE:
                    raise ValueError("图片单边太长（最多 12000 像素）")
                im.load()
                # 按 EXIF 摆正，再统一转成 PNG；EXIF / 文本块 / 伪装内容全部丢掉
                im = ImageOps.exif_transpose(im)
                if im.mode == "P" and "transparency" in im.info:
                    im = im.convert("RGBA")
                elif im.mode not in ("RGB", "RGBA", "L"):
                    im = im.convert("RGB")
                out = io.BytesIO()
                im.save(out, format="PNG")
        except Image.DecompressionBombError:
            raise ValueError("图片像素太大（最多 4000 万像素）")
        except ValueError:
            raise
        except Exception:
            raise ValueError("图片已损坏或不是真正的图片")

        stage_dir = os.path.join(user_upload_root(uid), stage_id)
        os.makedirs(stage_dir, exist_ok=True)
        fname = "%s_%s.png" % (prefix, uuid.uuid4().hex[:10])
        path = os.path.join(stage_dir, fname)
        with open(path, "wb") as fh:
            fh.write(out.getvalue())
        return path

    # ------------------------------------------------------------ 出图
    def _handle_generate(self, data):
        # 网页开着且检测到前台/整机高负载时，临时拦下新的出图任务。
        blocked = guard_block_message()
        if blocked:
            self._json({"error": blocked, "guard": guard_snapshot()}, 409)
            return
        user = self._current_user()
        uid = (user or {}).get("id") or "admin"
        tr_mode = normalize_translation_mode(
            (user or {}).get("translation_mode"))
        tr_status = translation_status(user)
        tr_ready = bool(tr_status.get("ready"))
        tr_error = ""
        prompt, prompt_info = input_guard.clean_text(
            data.get("prompt"), input_guard.MAX_PROMPT_CHARS)
        if not prompt:
            self._json({"error": "提示词是空的（或只包含不可见字符）"}, 400)
            return

        # 中文先在这里转成 danbooru 标签，比让 ComfyUI 内部翻成自然英语准得多。
        # 万一词表和翻译都搞不定（还是中文），就留空退回原来的翻译节点。
        prompt_en = ""
        if USE_PROMPT_OPTIMIZER and has_chinese(prompt):
            try:
                cand = optimize_prompt(prompt)
                if cand and not has_chinese(cand):
                    prompt_en = cand
            except Exception:
                prompt_en = ""      # 优化失败就退回 ComfyUI 里的翻译节点

        negative, negative_info = input_guard.clean_text(
            data.get("negative"), input_guard.MAX_PROMPT_CHARS)
        if not negative:
            negative = DEFAULT_NEGATIVE
        if USE_PROMPT_OPTIMIZER and has_chinese(negative):
            try:
                cand = optimize_prompt(negative, quality=False)
                if cand and not has_chinese(cand):
                    negative = cand
            except Exception:
                pass
        if has_chinese(negative) and not tr_ready:
            self._json({"error": "负面提示词是中文，但当前账号没有可用的翻译方式。"
                                 "请改用英文，或在个人设置里选择本地翻译模型。"}, 400)
            return

        mode = str(data.get("mode") or "txt")
        is_video = mode in ("vid", "i2v")
        is_i2v = mode == "i2v"
        if mode in ("img", "img2img", "inpaint") and not data.get("image"):
            self._json({"error": "图生图 / 局部重绘需要先上传参考图"}, 400)
            return
        if mode == "inpaint" and not data.get("mask"):
            self._json({"error": "局部重绘需要涂抹蒙版"}, 400)
            return
        feature_key = ("video" if is_video else
                       "inpaint" if data.get("mask") else
                       "img2img" if data.get("image") else "txt2img")
        if not self._require_feature(user, feature_key):
            return

        # 内置角色词典：把「初音未来」这类中文名换成 hatsune_miku 标签，
        # 并从中文里删掉，避免 Argos 把它翻成 first-sounding future。
        prompt_raw = prompt
        char_tags = []
        if not is_video:
            prompt, char_tags = extract_char_tags(prompt)
        # 用户选了本地小参数大模型：先在中央翻译，ComfyUI 工作流里就不再需要
        # Argos 节点。失败时 translate_text_for_user() 会自动回退 Argos。
        if tr_mode == "local" and has_chinese(prompt) and not prompt_en:
            out, _provider, err = translate_text_for_user(
                prompt, user, "local")
            if out and not has_chinese(out):
                prompt_en = out
            else:
                tr_error = err or "本地翻译模型没有返回英文"
        if tr_mode == "local" and has_chinese(negative):
            out, _provider, err = translate_text_for_user(
                negative, user, "local")
            if out and not has_chinese(out):
                negative = out
            else:
                tr_error = tr_error or err or "负面提示词翻译失败"
        if has_chinese(prompt) and not prompt_en and not translate_ready():
            msg = ("本地翻译失败：%s。请检查本地模型服务，或在个人设置里"
                   "切回 Argos / 直接用英文提示词。" % tr_error
                   if tr_error else
                   "这台机器没有安装中文翻译组件，也没有启用本地翻译模型。"
                   "请直接用英文提示词。")
            self._json({"error": msg, "translation": tr_status}, 400)
            return
        if has_chinese(negative) and (prompt_en or not translate_ready()):
            self._json({"error": "负面提示词没有翻译成功，请改用英文，"
                                 "或检查本地翻译模型。"}, 400)
            return

        try:
            w, h = (int(v) for v in (data.get("size") or "832x1216").split("x"))
        except Exception:
            w, h = (480, 480) if is_video else (832, 1216)
        # 先做一次粗对齐；真正的模型上限在 ckpt 解析出来后再套。
        w, h = fit_size(w, h, 256, 2048, 0)

        def num(key, default, lo, hi, cast):
            try:
                return max(lo, min(hi, cast(data.get(key, default))))
            except Exception:
                return default

        # 视频时长按“秒”自由填，内部换算成 8fps 的帧数；必须是偶数，
        # 这样 Wan 的 length=帧数*2+1 才会落在 4n+1 上。
        frames = num("frames", 16, 4, 48, int)
        if frames % 2:
            frames -= 1
        count = 1 if is_video else num("count", 1, 1, 4, int)
        denoise = num("denoise", 0.6, 0.2, 1.0, float)
        if is_video:
            # 视频走 Wan 2.1，采样参数和出图那套完全不一样
            if is_i2v:
                if not i2v_ready():
                    self._json({"error": "图生视频模型还没装好：缺 "
                                         "wan2.1_vace_1.3B_fp16.safetensors。"}, 400)
                    return
            elif not video_ready():
                self._json({"error": "视频模型还没装好：需要 Wan 的 UNet / "
                                     "文本编码器 / VAE 三个文件。"}, 400)
                return
            ckpt = VIDEO_VACE if is_i2v else VIDEO_UNET
            preset = {}
            # 视频参数固定：Wan 2.1 1.3B 官方推荐 20 步 / CFG 6，
            # 不跟随出图页的步数滑块（那是给 SDXL 用的）。
            steps, cfg = 20, 6.0
        else:
            ckpt = resolve_checkpoint(data.get("model"))
            preset = model_profile(ckpt)
            if not preset.get("supported", True):
                msg = "；".join(preset.get("warnings") or []) or \
                      "当前版本暂未自动适配这个模型，请换用 Anima、SDXL 或 SD1.5。"
                self._json({"error": msg, "model": ckpt, "profile": preset}, 400)
                return
            steps = num("steps", preset.get("steps", 20), 4, 60, int)
            cfg = num("cfg", preset.get("cfg", 6.0), 1.0, 15.0, float)
            if negative == DEFAULT_NEGATIVE:
                if ckpt == ANIMA_MODEL:
                    negative = ANIMA_NEGATIVE
                elif ckpt == NOOB_MODEL:
                    negative = NOOB_NEGATIVE
                elif not preset.get("supports_negative", True):
                    negative = ""

        # 按具体模型再收一次画幅：16 像素对齐 + 单边 / 总像素上限。
        # 图生图 / 局部重绘的画幅由参考图决定，这里只影响任务记录和预估。
        if is_video:
            w, h = fit_size(w, h, 256, VIDEO_MAX_SIDE, VIDEO_MAX_PIXELS)
        else:
            w, h = fit_size(
                w, h, 256,
                int(preset.get("max_side") or 1536),
                int(preset.get("max_pixels") or 1500000))

        # LoRA：只接受 loras 目录里真实存在的文件名，强度限制在 -2 ~ 2
        loras = []
        lora_skipped = []
        raw_loras = data.get("loras") or []
        if isinstance(raw_loras, list) and not is_video:
            for it in raw_loras[:8]:
                if not isinstance(it, dict):
                    continue
                nm = os.path.basename(str(it.get("name") or ""))
                path = os.path.join(LORA_DIR, nm)
                if nm and os.path.isfile(path):
                    fam = model_profiles.detect_lora_family(nm, path)
                    if not model_profiles.lora_compatible(
                            preset.get("family"), fam):
                        lora_skipped.append({"name": nm, "family": fam})
                        continue
                    try:
                        st = float(it.get("strength", 1.0))
                    except (TypeError, ValueError):
                        st = 1.0
                    loras.append({"name": nm, "strength": max(-2.0, min(2.0, st))})

        hires = bool(data.get("hires")) and not is_video
        pag = bool(data.get("pag", True)) and not is_video
        if not is_video:
            if not preset.get("supports_lora", True):
                loras = []
            if not preset.get("supports_pag", True):
                pag = False
            if not preset.get("supports_hires", True):
                hires = False
        # Anima 极速模式：官方 Turbo LoRA，强制 8 步 / CFG 1
        turbo = (not is_video and ckpt == ANIMA_MODEL
                 and bool(data.get("turbo")) and anima_turbo_ready())
        if turbo:
            steps, cfg = ANIMA_TURBO_STEPS, ANIMA_TURBO_CFG
        sampler = str(data.get("sampler") or "")
        if sampler not in SAMPLERS:
            sampler = preset.get("sampler") or DEFAULT_SAMPLER
        # v-pred 模型官方要求只用 Euler
        if not is_video and preset.get("vpred"):
            sampler = "euler"

        eta_est = (max(60, frames * 5) if is_video
                   else round(estimate_seconds(ckpt, steps, count), 1))
        limit_msg, quota = check_user_limits_detail(
            user, ckpt, is_video, steps, count, "gen", eta=eta_est)
        if limit_msg:
            audit("security", "limit_denied", user=user,
                  ip=self.client_address[0], ok=False,
                  operation="generate", error=limit_msg)
            self._json({"error": limit_msg,
                        "code": "quota_exhausted" if quota else "limit_denied",
                        "quota": quota}, 403)
            return
        lim = user_limits(user)
        max_upload = max(1, int(lim.get("max_upload_mb") or 20)) * 1048576
        max_pixels = max(1, int(lim.get("max_pixels") or UPLOAD_MAX_PIXELS))

        stage_id = uuid.uuid4().hex[:12]
        init_store = init_mask_store = None
        init_image = init_mask = None
        raw_img = data.get("image") or ""
        if isinstance(raw_img, str) and raw_img.startswith("data:image"):
            try:
                init_store = self._save_data_url(
                    raw_img, "ref", stage_id, uid, max_upload, max_pixels)
            except Exception as e:
                cleanup_stage(uid, stage_id)
                self._json({"error": "参考图读取失败: %s" % e}, 400)
                return
        raw_mask = data.get("mask") or ""
        if init_store and isinstance(raw_mask, str) and raw_mask.startswith("data:image"):
            try:
                init_mask_store = self._save_data_url(
                    raw_mask, "mask", stage_id, uid, max_upload, max_pixels)
            except Exception as e:
                cleanup_stage(uid, stage_id)
                self._json({"error": "蒙版读取失败: %s" % e}, 400)
                return

        if is_i2v and not init_store:
            cleanup_stage(uid, stage_id)
            self._json({"error": "图生视频要先选一张参考图"}, 400)
            return

        # 只有真正要提交任务时才临时放进 ComfyUI/input，任务结束会删掉
        try:
            if init_store:
                init_image = _stage_to_input(stage_id, init_store, "ref")
            if init_mask_store:
                init_mask = _stage_to_input(stage_id, init_mask_store, "mask")
        except Exception as e:
            cleanup_stage(uid, stage_id)
            self._json({"error": "准备参考图失败: %s" % e}, 500)
            return

        reqs = job_requirements(ckpt, loras, turbo,
                                "gen" if not is_video else "video")
        local_ok = bool(local_comfy_alive()
                        and lan_share.settings().get("local_enabled", True))
        remote_ok = bool((not is_video) and
                         scheduler_has_remote(user, reqs, w * h, count))
        if not local_ok and not remote_ok:
            cleanup_stage(uid, stage_id)
            self._json({"error": "本机 ComfyUI 没在运行，也没有可用的算力节点。"}, 503)
            return

        jid = uuid.uuid4().hex[:12]
        seed = int.from_bytes(os.urandom(4), "little") % (2 ** 31)
        if data.get("seed") is not None:
            try:
                seed = int(data["seed"]) % (2 ** 31)
            except Exception:
                pass

        kind = "i2v" if is_i2v else ("video" if is_video else "gen")
        eta = eta_est
        input_refs = {}
        if init_store:
            input_refs["image"] = init_store
        if init_mask_store:
            input_refs["mask"] = init_mask_store
        with JOBS_LOCK:
            JOBS[jid] = {"status": "queued", "started": 0,
                         "queued_at": time.time(), "elapsed": 0,
                         "prompt": prompt_raw, "prompt_en": prompt_en,
                         "seed": seed, "kind": kind, "mode": mode,
                         "model": os.path.basename(ckpt),
                         "family": preset.get("family") or "",
                         "hires": hires, "pag": pag, "turbo": turbo,
                         "loras": len(loras),
                         "inpaint": bool(init_mask),
                         "img2img": bool(init_image),
                         "frames": frames, "steps": steps, "cfg": cfg,
                         "sampler": sampler, "stage_id": stage_id,
                         "user_id": uid,
                         "username": (user or {}).get("username") or uid,
                         "user_name": (user or {}).get("name") or "",
                         "eta": eta, "priority": 10,
                         "requirements": reqs,
                         "remote_ok": bool(kind == "gen"),
                         "pixels": int(w * h),
                         "count": int(count),
                         "input_refs": input_refs,
                         "attempt": 0,
                         "retry_count": 0,
                         "exclude_workers": [],
                         "worker_id": "",
                         "worker_name": "",
                         "worker_kind": "",
                         "dispatch_state": ""}
        save_job_resume(jid, {
            "created": time.time(),
            "prompt": prompt, "negative": negative,
            "width": int(w), "height": int(h),
            "steps": int(steps), "cfg": float(cfg), "seed": int(seed),
            "count": int(count),
            "init_image": init_image, "init_mask": init_mask,
            "denoise": float(denoise), "ckpt": ckpt, "kind": kind,
            "loras": loras, "hires": bool(hires),
            "prompt_en": prompt_en, "sampler": sampler,
            "frames": int(frames), "pag": bool(pag),
            "turbo": bool(turbo), "char_tags": char_tags,
            "prompt_display": prompt_raw, "stage_id": stage_id,
            "user_id": uid,
        })
        queue_err = scheduler_enqueue(jid)
        if queue_err:
            with JOBS_LOCK:
                JOBS.pop(jid, None)
            cleanup_stage(uid, stage_id)
            drop_job_resume(jid)
            audit("security", "limit_denied", user=user,
                  ip=self.client_address[0], ok=False,
                  operation="queue", error=queue_err)
            self._json({"error": queue_err,
                        "queue": scheduler_snapshot()}, 429)
            return
        activity_request("/api/generate", "POST", job_id=jid, mode=mode,
                         kind=kind, model=os.path.basename(ckpt),
                         hires=hires, pag=pag, turbo=turbo,
                         loras=len(loras), inpaint=bool(init_mask),
                         img2img=bool(init_image), frames=frames,
                         user=user.get("username"))
        audit("activity", "generate", user=user, ip=self.client_address[0],
              job_id=jid, mode=mode, kind=kind,
              model=os.path.basename(ckpt), count=count,
              steps=steps, cfg=cfg, size="%dx%d" % (w, h),
              turbo=turbo, pag=pag, hires=hires, frames=frames)
        if lora_skipped:
            audit("activity", "lora_incompatible", user=user,
                  ip=self.client_address[0], job_id=jid,
                  model=os.path.basename(ckpt),
                  loras=",".join(x["name"] for x in lora_skipped))
        threading.Thread(target=run_job,
                         args=(jid, prompt, negative, w, h, steps, cfg, seed,
                               count, init_image, init_mask, denoise, ckpt,
                               ("i2v" if is_i2v
                                else ("video" if is_video else "gen")),
                               loras, hires, prompt_en, sampler, frames, pag,
                               turbo, char_tags, prompt_raw, stage_id, uid),
                         daemon=True).start()
        info = scheduler_job_info(jid)
        with JOBS_LOCK:
            job_status = (JOBS.get(jid) or {}).get("status", "queued")
        self._json({"job_id": jid,
                    "prompt_en": prompt_en,
                    "eta": eta,
                    "status": job_status,
                    "queue_position": info.get("queue_position"),
                    "queue_size": info.get("queue_size"),
                    "queue_eta": info.get("queue_eta"),
                    "queue_eta_min": info.get("queue_eta_min"),
                    "queue_eta_max": info.get("queue_eta_max"),
                    "queue_start_in": info.get("queue_start_in"),
                    "queue_finish_in": info.get("queue_finish_in"),
                    "queue_state": info.get("queue_state"),
                    "queue_reason": info.get("queue_reason"),
                    "queue_slot": info.get("queue_slot"),
                    "input_cleaned": {
                        "prompt": prompt_info,
                        "negative": negative_info,
                    },
                    "lora_skipped": [x["name"] for x in lora_skipped]})

    # ------------------------------------------------------------ 放大
    def _handle_upscale(self, data):
        name = safe_media_rel(data.get("name") or "")
        if not name or not name.lower().endswith(IMAGE_EXT):
            self._json({"error": "请选择一张图片（视频不能放大）"}, 400)
            return
        user = self._current_user()
        if not self._require_feature(user, "upscale"):
            return
        uid = (user or {}).get("id") or "admin"
        if not lan_share.settings().get("local_enabled", True):
            self._json({"error": "放大只能在本机执行；本机接单已关闭。"}, 503)
            return
        src = find_image(name, user)
        if not src:
            self._json({"error": "找不到这张图片"}, 404)
            return
        try:
            factor = int(data.get("factor", 2))
        except Exception:
            factor = 2
        factor = 4 if factor >= 4 else 2

        meta = read_meta(name)
        ckpt = meta.get("model") or DEFAULT_CHECKPOINT
        eta_est = 60 if factor == 4 else 45
        limit_msg, quota = check_user_limits_detail(
            user, ckpt, False, 0, 1, "upscale", eta=eta_est)
        if limit_msg:
            audit("security", "limit_denied", user=user,
                  ip=self.client_address[0], ok=False,
                  operation="upscale", error=limit_msg)
            self._json({"error": limit_msg,
                        "code": "quota_exhausted" if quota else "limit_denied",
                        "quota": quota}, 403)
            return
        activity_request("/api/upscale", "POST", factor=factor,
                         user=user.get("username"))

        up = upscaler_for(ckpt)
        if not up:
            self._json({"error": "没装放大模型（ComfyUI/models/upscale_models）"})
            return

        # 临时复制进 ComfyUI/input（带隔离前缀，任务结束会删掉）
        stage_id = uuid.uuid4().hex[:12]
        try:
            fname = _stage_to_input(stage_id, src, "up")
        except Exception as e:
            cleanup_stage(uid, stage_id)
            self._json({"error": "准备图片失败: %s" % e}, 500)
            return

        try:
            http_json("/system_stats", timeout=8)
        except Exception:
            cleanup_stage(uid, stage_id)
            self._json({"error": "ComfyUI 没在运行"})
            return

        jid = uuid.uuid4().hex[:12]
        eta = 60 if factor == 4 else 45
        with JOBS_LOCK:
            JOBS[jid] = {"status": "queued", "started": 0,
                         "queued_at": time.time(), "elapsed": 0,
                         "prompt": "[放大 %d×] %s" % (factor, name),
                         "kind": "upscale", "mode": "upscale",
                         "model": os.path.basename(ckpt), "factor": factor,
                         "stage_id": stage_id, "user_id": uid,
                         "username": (user or {}).get("username") or uid,
                         "user_name": (user or {}).get("name") or "",
                         "eta": eta, "priority": 10}
        queue_err = scheduler_enqueue(jid)
        if queue_err:
            with JOBS_LOCK:
                JOBS.pop(jid, None)
            cleanup_stage(uid, stage_id)
            audit("security", "limit_denied", user=user,
                  ip=self.client_address[0], ok=False,
                  operation="queue", error=queue_err)
            self._json({"error": queue_err,
                        "queue": scheduler_snapshot()}, 429)
            return
        audit("activity", "upscale", user=user, ip=self.client_address[0],
              job_id=jid, factor=factor, model=os.path.basename(ckpt))
        threading.Thread(target=run_job,
                         args=(jid, "", "", 0, 0, 0, 0, 0,
                               factor, fname, None, 1.0, ckpt, "upscale"),
                         kwargs={"stage_id": stage_id, "user_id": uid},
                         daemon=True).start()
        info = scheduler_job_info(jid)
        with JOBS_LOCK:
            job_status = (JOBS.get(jid) or {}).get("status", "queued")
        self._json({"job_id": jid, "eta": eta, "status": job_status,
                    "queue_position": info.get("queue_position"),
                    "queue_size": info.get("queue_size"),
                    "queue_eta": info.get("queue_eta"),
                    "queue_eta_min": info.get("queue_eta_min"),
                    "queue_eta_max": info.get("queue_eta_max"),
                    "queue_start_in": info.get("queue_start_in"),
                    "queue_finish_in": info.get("queue_finish_in"),
                    "queue_state": info.get("queue_state"),
                    "queue_reason": info.get("queue_reason"),
                    "queue_slot": info.get("queue_slot")})


# --------------------------------------------------------------------- 启动

# Windows 移动热点(ICS)的网关地址固定是 192.168.137.1
HOTSPOT_IP = "192.168.137.1"


def lan_ips():
    """本机在局域网里的 IPv4 地址（可能不止一个）。"""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))      # 不发包，只为让系统选出出口网卡
            ips.add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


def is_private_ip(ip):
    """10/8、172.16/12、192.168/16、169.254/16 都算内网。"""
    try:
        a, b = [int(x) for x in ip.split(".")[:2]]
    except Exception:
        return False
    return (a == 10 or (a == 172 and 16 <= b <= 31)
            or (a == 192 and b == 168) or (a == 169 and b == 254))


def bind_addresses():
    """**始终**只监听本机 + 热点网卡。

    设不设密码都不碰校园网 —— 密码只是在这一层之上再加一道门，
    服务本身跟以前一样，公共网络里根本看不到它。
    """
    override = (os.environ.get("MOBILE_WEB_BIND") or "").strip()
    if override:
        return [override]
    addrs = ["127.0.0.1"]
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind((HOTSPOT_IP, 0))
        probe.close()
        addrs.append(HOTSPOT_IP)
    except OSError:
        pass
    return addrs


class MobileHTTPServer(ThreadingHTTPServer):
    # Windows 默认 listen backlog 只有 5；手机 + 浏览器并发刷新时会出现
    # 短暂的 connection refused。提高队列，连接突发时不再丢请求。
    request_queue_size = 128


def make_server(addr):
    httpd = MobileHTTPServer((addr, PORT), Handler)
    if https_enabled():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd


def already_running():
    """端口上已经有本服务在跑吗？

    Windows 的 SO_REUSEADDR 允许两个进程绑同一端口（第二个会绑成功），
    所以不能靠「bind 失败」来判断重复启动，得主动探一下 /api/session。
    """
    schemes = ("https", "http") if https_enabled() else ("http",)
    for host in ("127.0.0.1", HOTSPOT_IP):
        for scheme in schemes:
            try:
                url = "%s://%s:%d/api/session" % (scheme, host, PORT)
                if scheme == "https":
                    ctx = ssl._create_unverified_context()
                    with urllib.request.urlopen(url, timeout=1.5,
                                                context=ctx) as r:
                        if r.status == 200:
                            return True
                else:
                    with urllib.request.urlopen(url, timeout=1.5) as r:
                        if r.status == 200:
                            return True
            except Exception:
                pass
    return False


def set_console_title(text):
    """给黑窗口起个名字，避免被当成残留窗口误关。

    用 SetConsoleTitleW 而不是在 .bat 里写 title —— .bat 必须保持纯 ASCII。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        pass


def monitor_loop():
    """后台监控：每 10 秒评估告警，网页没开也能发 webhook。"""
    while True:
        try:
            snap = monitor_snapshot()
            monitor_center.evaluate(snap)
        except Exception:
            pass
        time.sleep(10)


def main():
    set_console_title("手机出图服务  ·  关闭这个窗口 = 服务停止")

    if already_running():
        print()
        print("!! 手机出图服务已经在运行了（端口 %d 被占用）。" % PORT)
        print("   去找一下已经开着的那个窗口，不用重复启动。")
        return 4        # 启动脚本看到 4 会直接关窗口，不会停在 pause

    # 可信时间：授权/额度/游客到期都使用它，启动时先建立基线。
    trusted_time.ensure_started()

    # 图片隔离：旧图库按模型分目录 → 再按用户分目录；旧上传移出 input
    migrate_gallery_to_model_folders()
    migrate_users_v1()
    migrate_legacy_inputs()
    cleanup_stale_stages()
    load_jobs_state()
    lan_share.ensure_workers()
    plugin_manager.ensure_plugins()
    ensure_queue_watchdog()
    threading.Thread(target=recover_queued_jobs, daemon=True,
                     name="job-recovery").start()
    ensure_guest_sweeper()
    expire_guests()
    threading.Thread(target=monitor_loop, daemon=True,
                     name="monitor-loop").start()
    ensure_cleanup_thread()
    cleanup_archives()
    model_manager.cleanup_uploads()
    remote_spool_cleanup_startup()

    threading.Thread(target=ws_listener, daemon=True).start()

    addresses = bind_addresses()
    servers = []
    for addr in addresses:
        try:
            servers.append((addr, make_server(addr)))
        except Exception as e:
            print("!! 无法监听 %s:%d —— %s" % (addr, PORT, e))

    if not servers:
        print()
        print("!! 端口 %d 无法监听 —— 大概率是手机出图服务已经在运行了。" % PORT)
        print("   去找一下已经开着的那个窗口，不用重复启动。")
        return 4        # 启动脚本看到 4 会直接关窗口，不会停在 pause

    scheme = "https" if https_enabled() else "http"
    audit("security", "server_start", ip="", https=https_enabled(),
          port=PORT, bind=",".join(addresses))

    print("=" * 56)
    print("  手机出图服务已启动")
    print("=" * 56)
    print()
    models = list_models()
    print("  可用底模: %s" % (", ".join(m["label"] for m in models) or "（无）"))
    print("  放大模型: %s" % (upscaler_for(DEFAULT_CHECKPOINT) or "（无）"))
    print()

    if auth_enabled():
        admin = next((u for u in USERS.values()
                      if u.get("role") == "admin"), None)
        print("  [账号] 已启用：%d 个账号，管理员 %s" % (
            len(USERS), admin.get("username") if admin else "?"))
        print("         管理员在 3D 星图 → 安全网关 → 用户管理 里加人 / 设限额")
    else:
        print("  [账号] 未启用（users.json 缺失）")
    print()
    print("  电脑打开：       %s://127.0.0.1:%d" % (scheme, PORT))
    if HOTSPOT_IP in addresses:
        print("  手机连热点打开： %s://%s:%d" % (scheme, HOTSPOT_IP, PORT))
        print()
        print("  只对【本机 + 热点设备】开放，校园网等其他网络访问不到。")
    else:
        print()
        print("  未检测到热点网卡 (%s)，手机暂时连不上。" % HOTSPOT_IP)
        print("  打开 Windows 移动热点后重启本服务即可。")
    if https_enabled():
        print()
        print("  HTTPS 用的是自签证书，手机第一次打开会提示“不安全”，")
        print("  点【高级】→【继续访问】即可，之后流量是加密的。")

    print()
    print("  本窗口不要关闭。关掉 = 服务停止。")
    print()

    # 除第一个外都放到后台线程
    for _, s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        servers[0][1].serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
