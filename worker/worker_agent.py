#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机出图 · 局域网算力节点代理（单文件，可复制到其他机器）

用法（在 worker 机器上）：
  python worker_agent.py probe
  python worker_agent.py join --server https://192.168.137.1:8800 --code XXXX \
      --name "书房 PC" --ca cert.pem
  python worker_agent.py run
  python worker_agent.py pause / resume / status

依赖：Python 3.9+；ComfyUI 便携版自带的 Pillow 可选（只用于缩小预览）。
不会在局域网上开监听端口；本机控制页只绑 127.0.0.1:8199。
"""

import argparse
import base64
import html as html_lib
import io
import json
import os
import platform
import re
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

AGENT_VERSION = "1.1"
PROTOCOL = 1
ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "worker_agent.json"
DEFAULT_COMFY = "http://127.0.0.1:8188"
PAUSE_FILE = ROOT / "worker_pause.flag"
CURRENT_FILE = ROOT / "current_job.json"
LOG_FILE = ROOT / "worker_agent.log"
CONTROL_HOST = "127.0.0.1"
CONTROL_PORT = 8199
MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_OUTPUT_BYTES = 40 * 1024 * 1024


# --------------------------------------------------------------------- 基础工具

def now():
    return time.time()


def log(msg):
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(path, data):
    path = str(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_config(path=None):
    path = Path(path or DEFAULT_CONFIG)
    cfg = read_json(path)
    if not isinstance(cfg, dict):
        return None, path
    return cfg, path


def save_config(cfg, path):
    write_json(path, cfg)


def is_paused():
    return PAUSE_FILE.exists()


def set_paused(value):
    if value:
        PAUSE_FILE.write_text("paused\n", encoding="utf-8")
    else:
        try:
            PAUSE_FILE.unlink()
        except FileNotFoundError:
            pass


def hostname():
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def human_mb(n):
    try:
        return round(float(n) / 1048576.0, 1)
    except Exception:
        return 0


# --------------------------------------------------------------------- 中央 HTTP

class AuthError(Exception):
    pass


def make_ssl_context(cfg):
    if cfg.get("insecure"):
        return ssl._create_unverified_context()
    ca = (cfg.get("ca") or "").strip()
    if ca:
        ca_path = ca if os.path.isabs(ca) else str(ROOT / ca)
        if os.path.isfile(ca_path):
            return ssl.create_default_context(cafile=ca_path)
        raise RuntimeError("找不到 CA 文件：%s" % ca_path)
    return ssl.create_default_context()


def server_request(cfg, path, payload=None, body=None, method=None,
                   auth=True, timeout=30, extra_headers=None):
    """请求中央服务；返回 (status, body_bytes, headers_dict)。"""
    base = str(cfg.get("server") or "").rstrip("/")
    if not base:
        raise RuntimeError("配置里没有 server 地址")
    url = base + path
    headers = {
        "X-Protocol": str(PROTOCOL),
        "Accept": "application/json",
        "User-Agent": "mobile-worker/%s" % AGENT_VERSION,
    }
    if auth:
        wid = cfg.get("worker_id") or ""
        secret = cfg.get("secret") or ""
        if not wid or not secret:
            raise AuthError("还没有接入中央，请先运行 join")
        headers["Authorization"] = "Bearer %s.%s" % (wid, secret)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    elif body is not None:
        data = body
        headers.setdefault("Content-Type", "application/octet-stream")
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data is not None else "GET"))
    ctx = make_ssl_context(cfg) if url.lower().startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read()
            return r.status, raw, dict(r.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        if exc.code in (401, 403):
            raise AuthError("中央拒绝了 worker 身份（HTTP %s）：%s" %
                            (exc.code, raw[:300].decode("utf-8", "replace")))
        return exc.code, raw, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上中央服务：%s" % exc.reason)


def server_json(cfg, path, payload=None, auth=True, timeout=30):
    status, raw, _ = server_request(cfg, path, payload=payload, auth=auth,
                                    timeout=timeout)
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        data = {}
    return status, data, raw


# --------------------------------------------------------------------- ComfyUI

def comfy_request(comfy, path, payload=None, body=None, method=None,
                  timeout=60, extra_headers=None):
    base = str(comfy or DEFAULT_COMFY).rstrip("/")
    url = base + path
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    elif body is not None:
        data = body
        headers.setdefault("Content-Type", "application/octet-stream")
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, raw, dict(r.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, raw, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上本机 ComfyUI：%s" % exc.reason)


def comfy_json(comfy, path, payload=None, timeout=60):
    status, raw, _ = comfy_request(comfy, path, payload=payload, timeout=timeout)
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        data = {}
    if status >= 400:
        raise RuntimeError("ComfyUI %s 返回 HTTP %s：%s" %
                           (path, status, raw[:400].decode("utf-8", "replace")))
    return data


def comfy_ready(comfy):
    try:
        comfy_json(comfy, "/system_stats", timeout=5)
        return True
    except Exception:
        return False


def comfy_queue_busy(comfy):
    try:
        data = comfy_json(comfy, "/queue", timeout=5)
        return bool(data.get("queue_running") or data.get("queue_pending"))
    except Exception:
        return True


def combo_values(info, node, key):
    spec = (info.get(node) or {}).get("input") or {}
    for section in ("required", "optional"):
        item = (spec.get(section) or {}).get(key)
        if not item:
            continue
        first = item[0] if isinstance(item, list) and item else item
        if isinstance(first, list):
            return [str(x) for x in first]
        # ComfyUI 0.40 新格式：["COMBO", {"options": [...]}]
        if first == "COMBO" and len(item) > 1 and isinstance(item[1], dict):
            opts = item[1].get("options") or []
            if isinstance(opts, list):
                return [str(x) for x in opts]
    return []


def model_inventory(info):
    info = info or {}
    loras = set(combo_values(info, "LoraLoader", "lora_name"))
    loras.update(combo_values(info, "LoraLoaderModelOnly", "lora_name"))
    return {
        "checkpoints": combo_values(info, "CheckpointLoaderSimple", "ckpt_name"),
        "diffusion_models": combo_values(info, "UNETLoader", "unet_name"),
        "text_encoders": combo_values(info, "CLIPLoader", "clip_name"),
        "vae": combo_values(info, "VAELoader", "vae_name"),
        "loras": sorted(loras),
        "upscale_models": combo_values(info, "UpscaleModelLoader", "model_name"),
    }


_MODEL_DIR_ALIASES = {
    "checkpoints": ("checkpoints",),
    "diffusion_models": ("diffusion_models", "unet"),
    "text_encoders": ("text_encoders", "clip"),
    "vae": ("vae",),
    "loras": ("loras",),
    "upscale_models": ("upscale_models",),
}


def model_sizes(comfy_dir, models):
    """按模型名读取文件大小；文件不存在或越界就跳过。"""
    models = models if isinstance(models, dict) else {}
    if not comfy_dir:
        return {}
    base = os.path.abspath(os.path.join(comfy_dir, "models"))
    out = {}
    for folder, names in models.items():
        dirs = _MODEL_DIR_ALIASES.get(folder) or (folder,)
        for name in names or []:
            name = str(name or "").replace("/", os.sep)
            if not name or name.startswith(".."):
                continue
            for sub in dirs:
                path = os.path.abspath(os.path.join(base, sub, name))
                try:
                    if os.path.commonpath([base, path]) != base:
                        continue
                    if os.path.isfile(path):
                        out.setdefault(folder, {})[str(name)] = os.path.getsize(path)
                        break
                except (OSError, ValueError):
                    continue
    return out


def comfy_system_stats(comfy):
    try:
        return comfy_json(comfy, "/system_stats", timeout=8)
    except Exception:
        return {}


def find_comfy_dir(stats, cfg=None):
    explicit = str((cfg or {}).get("comfy_dir") or "").strip()
    if explicit and os.path.isdir(explicit):
        return explicit
    argv = ((stats.get("system") or {}).get("argv") or [])
    if isinstance(argv, str):
        argv = [argv]
    for part in argv:
        text = str(part)
        if "main.py" in text and os.path.isabs(text):
            return os.path.dirname(os.path.dirname(text))
    # 代理通常放在 ComfyUI 同级目录或它的子目录里
    for base in (ROOT, ROOT.parent):
        candidate = base / "ComfyUI"
        if (candidate / "main.py").is_file():
            return str(candidate)
    return ""


def gpu_telemetry():
    """读取本机 NVIDIA GPU 利用率/显存/温度；没有 nvidia-smi 就返回空。"""
    exe = shutil.which("nvidia-smi") or ""
    if not exe:
        for cand in (r"C:\Windows\System32\nvidia-smi.exe",
                     r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.isfile(cand):
                exe = cand
                break
    if not exe:
        return {}
    try:
        out = subprocess.run(
            [exe, "--query-gpu=utilization.gpu,memory.used,memory.total,"
                  "temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = (out.stdout or "").strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            return {}

        def num(v):
            try:
                return round(float(v), 1)
            except Exception:
                return None
        return {"gpu_util": num(parts[0]), "vram_used_mb": num(parts[1]),
                "vram_total_mb": num(parts[2]), "gpu_temp_c": num(parts[3])}
    except Exception:
        return {}


def probe(cfg=None):
    cfg = cfg or {}
    comfy = str(cfg.get("comfy") or DEFAULT_COMFY).rstrip("/")
    stats = comfy_system_stats(comfy)
    info = {}
    if stats:
        try:
            info = comfy_json(comfy, "/object_info", timeout=30)
        except Exception:
            info = {}
    system = stats.get("system") or {}
    devices = stats.get("devices") or []
    dev = devices[0] if devices else {}
    models = model_inventory(info)
    comfy_dir = find_comfy_dir(stats, cfg)
    disk_free_mb = None
    if comfy_dir:
        try:
            disk_free_mb = round(shutil.disk_usage(comfy_dir).free / 1048576.0, 1)
        except Exception:
            pass
    telemetry = gpu_telemetry()
    return {
        "agent_version": AGENT_VERSION,
        "protocol": PROTOCOL,
        "hostname": hostname(),
        "os": system.get("os") or platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "gpu_name": dev.get("name") or "",
        "vram_mb": human_mb(dev.get("vram_total") or 0),
        "gpu_util": telemetry.get("gpu_util"),
        "vram_used_mb": telemetry.get("vram_used_mb"),
        "gpu_temp_c": telemetry.get("gpu_temp_c"),
        "comfy_version": system.get("comfyui_version") or "",
        "comfy_url": comfy,
        "comfy_dir": comfy_dir,
        "comfy_ready": bool(stats),
        "models": models,
        "model_sizes": model_sizes(comfy_dir, models),
        "nodes": sorted(info.keys()) if info else [],
        "disk_free_mb": disk_free_mb,
        "capabilities": {
            "kinds": ["gen"],
            "max_pixels": 4000000,
            "max_count": 4,
            "max_job_sec": 900,
        },
    }


def multipart_upload_image(comfy, filename, data):
    boundary = "----mobileworker%s" % base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
    parts = []
    parts.append(("--%s\r\n" % boundary).encode())
    parts.append(('Content-Disposition: form-data; name="type"\r\n\r\ninput\r\n').encode())
    parts.append(("--%s\r\n" % boundary).encode())
    parts.append(('Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n').encode())
    parts.append(("--%s\r\n" % boundary).encode())
    parts.append(('Content-Disposition: form-data; name="image"; filename="%s"\r\n'
                  'Content-Type: image/png\r\n\r\n' % filename).encode())
    parts.append(data)
    parts.append(("\r\n--%s--\r\n" % boundary).encode())
    body = b"".join(parts)
    status, raw, _ = comfy_request(
        comfy, "/upload/image", body=body, method="POST", timeout=60,
        extra_headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    if status >= 400:
        raise RuntimeError("ComfyUI 上传图片失败 HTTP %s：%s" %
                           (status, raw[:300].decode("utf-8", "replace")))
    result = json.loads(raw.decode("utf-8") or "{}")
    name = result.get("name") or filename
    sub = (result.get("subfolder") or "").strip("/")
    return (sub + "/" + name) if sub else name


def comfy_delete_prompt(comfy, prompt_id):
    try:
        comfy_json(comfy, "/queue", {"delete": [prompt_id]}, timeout=10)
    except Exception:
        pass


def comfy_interrupt(comfy, prompt_id):
    try:
        comfy_json(comfy, "/interrupt", {"prompt_id": prompt_id}, timeout=10)
    except Exception:
        try:
            comfy_json(comfy, "/interrupt", {}, timeout=10)
        except Exception:
            pass


def comfy_history_entry(comfy, prompt_id):
    try:
        data = comfy_json(comfy, "/history/" + urllib.parse.quote(prompt_id), timeout=20)
    except Exception:
        return None
    return data.get(prompt_id)


def comfy_view(comfy, item):
    query = urllib.parse.urlencode({
        "filename": item.get("filename") or "",
        "subfolder": item.get("subfolder") or "",
        "type": item.get("type") or "output",
    })
    status, raw, headers = comfy_request(comfy, "/view?" + query, timeout=120)
    if status >= 400:
        raise RuntimeError("ComfyUI 下载结果失败 HTTP %s" % status)
    return raw


# --------------------------------------------------------------------- WebSocket 进度

def _ws_read_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise IOError("WebSocket 已关闭")
        buf += chunk
    return buf


def _ws_connect(comfy, client_id):
    parsed = urllib.parse.urlsplit(comfy or DEFAULT_COMFY)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    key = base64.b64encode(os.urandom(16)).decode()
    sock = socket.create_connection((host, port), timeout=8)
    req = ("GET /ws?clientId=%s HTTP/1.1\r\n"
           "Host: %s:%d\r\n"
           "Upgrade: websocket\r\n"
           "Connection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\n"
           "Sec-WebSocket-Version: 13\r\n\r\n") % (
               urllib.parse.quote(client_id), host, port, key)
    sock.sendall(req.encode("ascii"))
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise IOError("WebSocket 握手失败")
        buf += chunk
    if b" 101 " not in buf.split(b"\r\n", 1)[0]:
        raise IOError("WebSocket 升级被拒绝")
    return sock


def _ws_read_frame(sock):
    hdr = _ws_read_exact(sock, 2)
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack("!H", _ws_read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _ws_read_exact(sock, 8))[0]
    mask = _ws_read_exact(sock, 4) if masked else b""
    payload = _ws_read_exact(sock, length) if length else b""
    if masked:
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    return opcode, payload


def _ws_send_frame(sock, opcode, payload):
    header = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        header += bytes([0x80 | 127]) + struct.pack("!Q", n)
    mask = os.urandom(4)
    masked = bytes(payload[i] ^ mask[i % 4] for i in range(n))
    sock.sendall(header + mask + masked)


def preview_jpeg(raw):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        im.thumbnail((512, 512))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=72)
        data = out.getvalue()
        if len(data) > 512 * 1024:
            return b""
        return data
    except Exception:
        if len(raw) <= 512 * 1024:
            return raw
        return b""


class WsProgress(threading.Thread):
    def __init__(self, comfy, client_id, on_progress, on_preview):
        super().__init__(daemon=True)
        self.comfy = comfy
        self.client_id = client_id
        self.on_progress = on_progress
        self.on_preview = on_preview
        self.stop_event = threading.Event()
        self.sock = None

    def run(self):
        try:
            self.sock = _ws_connect(self.comfy, self.client_id)
            self.sock.settimeout(1.0)
            while not self.stop_event.is_set():
                try:
                    opcode, payload = _ws_read_frame(self.sock)
                except socket.timeout:
                    continue
                except Exception:
                    break
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    try:
                        _ws_send_frame(self.sock, 0xA, payload)
                    except Exception:
                        break
                    continue
                if opcode == 0x1:
                    try:
                        msg = json.loads(payload.decode("utf-8"))
                    except Exception:
                        continue
                    typ = msg.get("type")
                    data = msg.get("data") or {}
                    if typ == "progress":
                        self.on_progress(data.get("value"), data.get("max"))
                    elif typ == "execution_start":
                        self.on_progress(0, 0)
                    elif typ in ("execution_error", "execution_interrupted"):
                        break
                elif opcode == 0x2 and len(payload) > 8:
                    # ComfyUI preview: 4-byte event type + 4-byte image format + image
                    event_type = struct.unpack("!I", payload[:4])[0]
                    fmt = struct.unpack("!I", payload[4:8])[0]
                    if event_type == 1 and fmt in (1, 2):
                        self.on_preview(payload[8:])
        except Exception:
            pass
        finally:
            try:
                if self.sock:
                    _ws_send_frame(self.sock, 0x8, b"")
            except Exception:
                pass
            try:
                if self.sock:
                    self.sock.close()
            except Exception:
                pass

    def stop(self):
        self.stop_event.set()


# --------------------------------------------------------------------- 工作流校验

MODEL_FIELDS = {
    "CheckpointLoaderSimple": ("ckpt_name", "checkpoints"),
    "UNETLoader": ("unet_name", "diffusion_models"),
    "CLIPLoader": ("clip_name", "text_encoders"),
    "VAELoader": ("vae_name", "vae"),
    "LoraLoader": ("lora_name", "loras"),
    "LoraLoaderModelOnly": ("lora_name", "loras"),
    "UpscaleModelLoader": ("model_name", "upscale_models"),
}


def workflow_prompt(job):
    wf = job.get("workflow") or {}
    if isinstance(wf, dict) and isinstance(wf.get("prompt"), dict):
        return wf["prompt"]
    return wf if isinstance(wf, dict) else {}


def validate_workflow(nodes, info):
    info = info or {}
    missing_nodes = sorted({str((n or {}).get("class_type") or "")
                            for n in nodes.values()
                            if (n or {}).get("class_type")
                            and (n or {}).get("class_type") not in info})
    missing_models = []
    for node in nodes.values():
        node = node or {}
        cls = node.get("class_type") or ""
        mapping = MODEL_FIELDS.get(cls)
        if not mapping:
            continue
        field, folder = mapping
        value = (node.get("inputs") or {}).get(field)
        if not value:
            continue
        available = model_inventory(info).get(folder) or []
        if str(value) not in available:
            missing_models.append({"folder": folder, "name": str(value)})
    return missing_nodes, missing_models


# --------------------------------------------------------------------- 任务执行

class AgentState:
    def __init__(self):
        self.lock = threading.RLock()
        self.approved = False
        self.central_paused = False
        self.current_job = ""
        self.attempt = 0
        self.prompt_id = ""
        self.status = "starting"
        self.last_error = ""
        self.last_heartbeat = 0
        self.cancel_event = threading.Event()
        self.running = True
        self.probe = {}
        self.inventory_dirty = True
        self.last_inventory = 0

    def snapshot(self):
        with self.lock:
            return {
                "approved": self.approved,
                "central_paused": self.central_paused,
                "current_job": self.current_job,
                "attempt": self.attempt,
                "prompt_id": self.prompt_id,
                "status": self.status,
                "last_error": self.last_error,
                "last_heartbeat": self.last_heartbeat,
                "paused": is_paused(),
            }


STATE = AgentState()


def report_job(cfg, job, suffix, extra=None, timeout=30):
    jid = job.get("job_id") or ""
    attempt = job.get("attempt") or 1
    payload = {"attempt": attempt}
    if extra:
        payload.update(extra)
    try:
        status, data, _ = server_json(
            cfg, "/api/worker/job/%s/%s" % (urllib.parse.quote(jid), suffix),
            payload=payload, timeout=timeout)
        return status, data
    except Exception as exc:
        log("上报 %s 失败：%s" % (suffix, exc))
        return 0, {}


def upload_output(cfg, job, index, count, data):
    jid = job.get("job_id") or ""
    attempt = job.get("attempt") or 1
    path = "/api/worker/job/%s/output?%s" % (
        urllib.parse.quote(jid),
        urllib.parse.urlencode({"index": index, "count": count}))
    for attempt_no in range(3):
        try:
            status, raw, _ = server_request(
                cfg, path, body=data, method="POST", timeout=120,
                extra_headers={"X-Attempt": str(attempt),
                               "Content-Type": "image/png"})
            if status < 400:
                return True
            log("上传结果 %s 失败 HTTP %s" % (index, status))
        except Exception as exc:
            log("上传结果 %s 失败：%s" % (index, exc))
        time.sleep(1.5 * (attempt_no + 1))
    return False


def fetch_input(cfg, job, key):
    jid = job.get("job_id") or ""
    attempt = job.get("attempt") or 1
    path = "/api/worker/job/%s/input/%s" % (
        urllib.parse.quote(jid), urllib.parse.quote(str(key)))
    status, raw, _ = server_request(
        cfg, path, timeout=120, extra_headers={"X-Attempt": str(attempt)})
    if status >= 400:
        raise RuntimeError("下载输入 %s 失败 HTTP %s" % (key, status))
    if len(raw) > MAX_INPUT_BYTES:
        raise RuntimeError("输入 %s 超过 %dMB" % (key, MAX_INPUT_BYTES // 1048576))
    return raw


def cleanup_comfy_files(comfy_dir, input_names, output_items):
    if not comfy_dir:
        return
    for name in input_names:
        try:
            path = os.path.join(comfy_dir, "input", *str(name).split("/"))
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass
    for item in output_items or []:
        try:
            path = os.path.join(comfy_dir, "output",
                                str(item.get("subfolder") or ""),
                                str(item.get("filename") or ""))
            if os.path.isfile(path):
                os.remove(path)
        except Exception:
            pass


def execute_job(cfg, job):
    comfy = str(cfg.get("comfy") or DEFAULT_COMFY).rstrip("/")
    jid = job.get("job_id") or ""
    attempt = job.get("attempt") or 1
    timeout = float(job.get("timeout") or 900)
    nodes = workflow_prompt(job)
    if job.get("cancel"):
        report_job(cfg, job, "cancelled", {})
        return
    if not nodes:
        report_job(cfg, job, "error", {"kind": "bad_workflow",
                                       "error": "中央没有下发工作流"})
        return

    info = {}
    try:
        info = comfy_json(comfy, "/object_info", timeout=30)
    except Exception as exc:
        report_job(cfg, job, "error", {"kind": "comfy_unavailable",
                                       "error": str(exc)})
        return
    missing_nodes, missing_models = validate_workflow(nodes, info)
    if missing_nodes or missing_models:
        report_job(cfg, job, "error", {
            "kind": "incompatible",
            "error": "缺少节点或模型",
            "missing_nodes": missing_nodes,
            "missing_models": missing_models,
        })
        return

    uploaded = {}
    input_names = []
    output_items = []
    state = STATE
    started = time.time()
    comfy_dir = (cfg.get("comfy_dir") or
                 find_comfy_dir(comfy_system_stats(comfy), cfg))
    with state.lock:
        state.current_job = jid
        state.attempt = attempt
        state.prompt_id = ""
        state.status = "downloading"
        state.cancel_event.clear()
    write_json(CURRENT_FILE, {"job_id": jid, "attempt": attempt, "prompt_id": ""})

    try:
        for item in job.get("inputs") or []:
            key = item.get("key") or ""
            if not key:
                continue
            if key not in uploaded:
                raw = fetch_input(cfg, job, key)
                filename = "_worker_%s_%s.png" % (re.sub(r"[^0-9A-Za-z]", "", jid)[:12], key)
                uploaded[key] = multipart_upload_image(comfy, filename, raw)
                input_names.append(uploaded[key])
            node_id = str(item.get("node_id") or "")
            field = item.get("field") or "image"
            if node_id in nodes:
                nodes[node_id].setdefault("inputs", {})[field] = uploaded[key]

        if STATE.cancel_event.is_set():
            with state.lock:
                state.status = "cancelled"
            report_job(cfg, job, "cancelled", {})
            cleanup_comfy_files(comfy_dir, input_names, [])
            return
        cid = "worker-%s-%s" % (jid, attempt)
        wf = {"prompt": nodes, "client_id": cid}
        with state.lock:
            state.status = "submitting"
        status, raw, _ = comfy_request(comfy, "/prompt", payload=wf, timeout=60)
        if status >= 400:
            text = raw[:800].decode("utf-8", "replace")
            report_job(cfg, job, "error", {"kind": "prompt_rejected",
                                           "error": "ComfyUI 拒绝了工作流：%s" % text})
            return
        result = json.loads(raw.decode("utf-8") or "{}")
        prompt_id = result.get("prompt_id") or ""
        if not prompt_id:
            report_job(cfg, job, "error", {"kind": "prompt_rejected",
                                           "error": "ComfyUI 没有返回 prompt_id"})
            return
        with state.lock:
            state.prompt_id = prompt_id
            state.status = "running"
        write_json(CURRENT_FILE, {"job_id": jid, "attempt": attempt,
                                  "prompt_id": prompt_id})
        report_job(cfg, job, "started", {"prompt_id": prompt_id})

        last_progress = {"t": 0.0}
        last_preview = {"t": 0.0}

        def on_progress(value, maximum):
            if time.time() - last_progress["t"] < 0.5:
                return
            last_progress["t"] = time.time()
            _st, resp = report_job(cfg, job, "progress", {
                "value": value, "max": maximum,
                "elapsed": round(time.time() - started, 1),
            }, timeout=10)
            if resp.get("cancel"):
                STATE.cancel_event.set()

        def on_preview(raw):
            if time.time() - last_preview["t"] < 1.0:
                return
            last_preview["t"] = time.time()
            jpeg = preview_jpeg(raw)
            if not jpeg:
                return
            b64 = base64.b64encode(jpeg).decode("ascii")
            _st, resp = report_job(cfg, job, "progress", {
                "preview_b64": b64,
                "elapsed": round(time.time() - started, 1),
            }, timeout=10)
            if resp.get("cancel"):
                STATE.cancel_event.set()

        ws = WsProgress(comfy, cid, on_progress, on_preview)
        ws.start()
        cancelled = False
        finished = None
        try:
            while time.time() - started < timeout:
                if STATE.cancel_event.is_set():
                    cancelled = True
                    comfy_interrupt(comfy, prompt_id)
                    comfy_delete_prompt(comfy, prompt_id)
                    break
                entry = comfy_history_entry(comfy, prompt_id)
                if entry:
                    finished = entry
                    break
                time.sleep(1.0)
        finally:
            ws.stop()
        if cancelled:
            with state.lock:
                state.status = "cancelled"
            report_job(cfg, job, "cancelled", {"prompt_id": prompt_id})
            cleanup_comfy_files(comfy_dir, input_names, [])
            return
        if not finished:
            comfy_interrupt(comfy, prompt_id)
            report_job(cfg, job, "error", {"kind": "timeout",
                                           "error": "超过 %d 秒未完成" % int(timeout)})
            return
        job_status = finished.get("status") or {}
        if job_status.get("status_str") == "error":
            report_job(cfg, job, "error", {"kind": "execution_error",
                                           "error": "ComfyUI 执行失败",
                                           "status": job_status})
            return
        found = []
        for out in (finished.get("outputs") or {}).values():
            for im in (out.get("images") or []):
                found.append(im)
        if not found:
            report_job(cfg, job, "error", {"kind": "no_output",
                                           "error": "完成但没有输出图片"})
            return
        output_items = found
        total = len(found)
        for idx, im in enumerate(found):
            data = comfy_view(comfy, im)
            if len(data) > MAX_OUTPUT_BYTES:
                report_job(cfg, job, "error", {"kind": "output_too_large",
                                               "error": "输出图片超过 %dMB" % (MAX_OUTPUT_BYTES // 1048576)})
                return
            if not upload_output(cfg, job, idx, total, data):
                report_job(cfg, job, "error", {"kind": "upload_failed",
                                               "error": "结果上传中央失败"})
                return
        complete_payload = {
            "prompt_id": prompt_id,
            "elapsed": round(time.time() - started, 1),
            "outputs": [{"index": i,
                         "filename": im.get("filename") or "",
                         "subfolder": im.get("subfolder") or ""}
                        for i, im in enumerate(found)],
        }
        for attempt_no in range(3):
            status, _resp = report_job(cfg, job, "complete",
                                        complete_payload, timeout=30)
            if 0 < status < 400:
                break
            time.sleep(1.0 + attempt_no)
        with state.lock:
            state.status = "idle"
            STATE.last_error = ""
        cleanup_comfy_files(comfy_dir, input_names, output_items)
    except Exception as exc:
        STATE.last_error = str(exc)[:300]
        log("任务 %s 失败：%s" % (jid, exc))
        report_job(cfg, job, "error", {"kind": "agent_error", "error": str(exc)[:500]})
    finally:
        try:
            if CURRENT_FILE.exists():
                CURRENT_FILE.unlink()
        except OSError:
            pass
        with state.lock:
            state.current_job = ""
            state.attempt = 0
            state.prompt_id = ""
            if state.status not in ("cancelled", "idle"):
                state.status = "idle"
            state.cancel_event.clear()
        cleanup_comfy_files(comfy_dir, input_names, output_items)


# --------------------------------------------------------------------- 心跳 / 轮询

def heartbeat_loop(cfg):
    while STATE.running:
        try:
            with STATE.lock:
                current = STATE.current_job
                attempt = STATE.attempt
                local_paused = is_paused()
            comfy = str(cfg.get("comfy") or DEFAULT_COMFY)
            ready = comfy_ready(comfy)
            busy = comfy_queue_busy(comfy) if ready else False
            probe_data = None
            if STATE.inventory_dirty or time.time() - STATE.last_inventory > 300:
                probe_data = probe(cfg)
                STATE.probe = probe_data
                STATE.last_inventory = time.time()
                STATE.inventory_dirty = False
            payload = {
                "protocol": PROTOCOL,
                "agent_version": AGENT_VERSION,
                "paused": bool(local_paused),
                "current_job": current,
                "attempt": attempt,
                "comfy_ready": ready,
                "comfy_busy": busy,
            }
            if probe_data:
                payload["inventory"] = probe_data
            status, data, _ = server_json(cfg, "/api/worker/heartbeat",
                                          payload=payload, timeout=20)
            if status >= 400:
                STATE.last_error = "心跳失败 HTTP %s" % status
                time.sleep(5)
                continue
            STATE.last_heartbeat = time.time()
            with STATE.lock:
                STATE.approved = bool(data.get("approved"))
                STATE.central_paused = bool(data.get("paused"))
                if data.get("refresh_inventory"):
                    STATE.inventory_dirty = True
            for jid in (data.get("cancel_jobs") or []):
                with STATE.lock:
                    if jid == STATE.current_job:
                        STATE.cancel_event.set()
        except AuthError as exc:
            STATE.last_error = str(exc)
            log("中央拒绝身份：%s；请重新 join" % exc)
            time.sleep(15)
        except Exception as exc:
            STATE.last_error = str(exc)[:200]
            time.sleep(5)
        time.sleep(5)


def poll_once(cfg):
    try:
        status, data, raw = server_json(cfg, "/api/worker/poll", payload={
            "protocol": PROTOCOL,
            "agent_version": AGENT_VERSION,
        }, timeout=30)
        if status == 204 or not data.get("job_id"):
            return None
        return data
    except AuthError:
        raise
    except Exception as exc:
        STATE.last_error = str(exc)[:200]
        time.sleep(2)
        return None


def run_loop(cfg, control=True):
    if control:
        start_control_server(int(cfg.get("control_port") or CONTROL_PORT))
    # 上次异常退出留下的任务：先把本机 ComfyUI 里的旧 prompt 清掉
    stale = read_json(CURRENT_FILE, {})
    if isinstance(stale, dict) and stale.get("prompt_id"):
        comfy = str(cfg.get("comfy") or DEFAULT_COMFY)
        comfy_interrupt(comfy, stale.get("prompt_id"))
        comfy_delete_prompt(comfy, stale.get("prompt_id"))
        log("已清理上次未完成的本地任务：%s" % stale.get("job_id", ""))
    try:
        if CURRENT_FILE.exists():
            CURRENT_FILE.unlink()
    except OSError:
        pass
    threading.Thread(target=heartbeat_loop, args=(cfg,), daemon=True).start()
    log("算力节点已启动：%s" % cfg.get("server"))
    while STATE.running:
        try:
            if is_paused():
                STATE.status = "paused"
                time.sleep(2)
                continue
            if not STATE.approved:
                STATE.status = "waiting_approval"
                time.sleep(3)
                continue
            if STATE.central_paused:
                STATE.status = "paused_by_admin"
                time.sleep(3)
                continue
            comfy = str(cfg.get("comfy") or DEFAULT_COMFY)
            if not comfy_ready(comfy):
                STATE.status = "comfy_offline"
                time.sleep(5)
                continue
            if STATE.current_job:
                time.sleep(1)
                continue
            if comfy_queue_busy(comfy):
                STATE.status = "comfy_busy"
                time.sleep(3)
                continue
            STATE.status = "idle"
            job = poll_once(cfg)
            if job:
                execute_job(cfg, job)
        except AuthError as exc:
            STATE.last_error = str(exc)
            log("身份失效：%s" % exc)
            time.sleep(15)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            STATE.last_error = str(exc)[:200]
            log("运行循环错误：%s" % exc)
            time.sleep(3)
    STATE.running = False


# --------------------------------------------------------------------- 本机控制页

def control_html():
    snap = STATE.snapshot()
    paused = snap["paused"]
    rows = [
        ("节点", "%s (%s)" % (hostname(), (read_config()[0] or {}).get("name", ""))),
        ("中央", (read_config()[0] or {}).get("server", "")),
        ("状态", snap["status"]),
        ("已批准", "是" if snap["approved"] else "否"),
        ("本机暂停", "是" if paused else "否"),
        ("当前任务", snap["current_job"] or "—"),
        ("上次心跳", time.strftime("%H:%M:%S", time.localtime(snap["last_heartbeat"]))
         if snap["last_heartbeat"] else "—"),
        ("上次错误", snap["last_error"] or "—"),
    ]
    body = "".join("<tr><th>%s</th><td>%s</td></tr>" %
                   (html_lib.escape(str(k)), html_lib.escape(str(v)))
                   for k, v in rows)
    action = ("resume" if paused else "pause")
    label = ("恢复接单" if paused else "暂停接单")
    report = ROOT / "环境检测结果.html"
    report_link = ('<p><a href="/report">查看环境检测报告</a></p>'
                   if report.is_file() else "")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>算力节点 · %s</title>
<style>
:root{--bg:#070b14;--card:rgba(20,28,48,.74);--line:rgba(150,180,255,.16);
--tx:#e8eefc;--tx2:#aab8d4;--ac:#7fb0ff;--ok:#7ee0b8}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;padding:28px;color:var(--tx);
font:14px/1.65 system-ui,"Microsoft YaHei",sans-serif;
background:radial-gradient(900px 480px at 78% -10%,#18325a 0,transparent 60%),var(--bg)}
.card{max-width:620px;margin:0 auto;padding:24px;background:var(--card);
border:1px solid var(--line);border-radius:20px;backdrop-filter:blur(16px);
box-shadow:0 24px 70px rgba(0,0,0,.28)}
.kicker{font-size:11px;letter-spacing:.16em;color:var(--ac);text-transform:uppercase}
h1{font-size:22px;margin:4px 0 18px;letter-spacing:.02em}
table{width:100%%;border-collapse:collapse}
th,td{text-align:left;padding:10px 6px;border-bottom:1px solid rgba(150,180,255,.10);font-size:13.5px}
th{color:var(--tx2);font-weight:500;width:112px}
button{margin-top:18px;padding:12px 18px;border:0;border-radius:11px;
background:linear-gradient(135deg,#8ab4ff,#a78bfa);color:#081020;font-weight:700;cursor:pointer;
box-shadow:0 8px 24px rgba(110,150,255,.25)}
a{color:#9dbcff}p{color:var(--tx2);font-size:12.5px}
</style><div class="card"><div class="kicker">COMETINK · WORKER</div>
<h1>算力节点</h1><table>%s</table>
<form method="post" action="/api/%s"><button>%s</button></form>
<p><a href="/">刷新</a> · 只允许本机访问</p>%s</div></html>""" % (
        hostname(), body, action, label, report_link)


def start_control_server(port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.split("?")[0] == "/api/status":
                body = json.dumps(STATE.snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.split("?")[0] == "/report":
                report = ROOT / "环境检测结果.html"
                if report.is_file():
                    body = report.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
                return
            body = control_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path == "/api/pause":
                set_paused(True)
            elif self.path == "/api/resume":
                set_paused(False)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

    try:
        httpd = ThreadingHTTPServer((CONTROL_HOST, port), Handler)
    except OSError as exc:
        log("控制页无法监听 %s:%s：%s" % (CONTROL_HOST, port, exc))
        return
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    log("本机控制页：http://%s:%s/" % (CONTROL_HOST, port))


# --------------------------------------------------------------------- CLI

def cmd_probe(args):
    cfg = {"comfy": args.comfy}
    data = probe(cfg)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    if not data.get("comfy_ready"):
        print("\n[提示] 连不上 ComfyUI。请先启动 ComfyUI，再重新盘点。",
              file=sys.stderr)
    return 0


def cmd_join(args):
    cfg_path = Path(args.config or DEFAULT_CONFIG)
    if cfg_path.exists() and not args.force:
        print("配置文件已存在：%s\n如要重新接入，请加 --force" % cfg_path)
        return 2
    cfg = {
        "server": args.server.rstrip("/"),
        "comfy": args.comfy,
        "name": args.name or hostname(),
        "ca": args.ca or "",
        "insecure": bool(args.insecure),
        "control_port": int(args.control_port or CONTROL_PORT),
    }
    data = probe(cfg)
    if not data.get("comfy_ready"):
        print("[警告] 当前连不上 ComfyUI，接入后节点会显示未就绪。", file=sys.stderr)
    try:
        status, resp, raw = server_json(cfg, "/api/worker/join", {
            "code": args.code,
            "name": cfg["name"],
            "probe": data,
            "agent_version": AGENT_VERSION,
            "protocol": PROTOCOL,
        }, auth=False, timeout=30)
    except Exception as exc:
        print("接入失败：%s" % exc, file=sys.stderr)
        return 1
    if status >= 400 or not resp.get("worker_id"):
        print("接入失败 HTTP %s：%s" % (status, raw[:500].decode("utf-8", "replace")),
              file=sys.stderr)
        return 1
    cfg["worker_id"] = resp["worker_id"]
    cfg["secret"] = resp["secret"]
    if data.get("comfy_dir"):
        cfg["comfy_dir"] = data["comfy_dir"]
    save_config(cfg, cfg_path)
    print("接入成功，正在等待管理员审批。")
    print("worker_id: %s" % cfg["worker_id"])
    print("配置已写入：%s" % cfg_path)
    print("下一步：python worker_agent.py run")
    return 0


def cmd_run(args):
    cfg, path = read_config(args.config)
    if not cfg:
        print("找不到配置，请先 join", file=sys.stderr)
        return 2
    if args.comfy:
        cfg["comfy"] = args.comfy
    try:
        run_loop(cfg, control=not args.no_control)
    except KeyboardInterrupt:
        pass
    return 0


def cmd_pause(args):
    set_paused(True)
    print("已暂停接单；当前任务会继续跑完。")
    return 0


def cmd_resume(args):
    set_paused(False)
    print("已恢复接单。")
    return 0


def cmd_status(args):
    cfg, path = read_config(args.config)
    if not cfg:
        print("找不到配置：%s" % path, file=sys.stderr)
        return 2
    print(json.dumps({
        "config": str(path),
        "server": cfg.get("server"),
        "worker_id": cfg.get("worker_id"),
        "name": cfg.get("name"),
        "paused": is_paused(),
        "state": STATE.snapshot(),
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="手机出图 · 局域网算力节点")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("probe", help="盘点本机算力")
    p.add_argument("--comfy", default=DEFAULT_COMFY)
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("join", help="用接入码接入中央")
    p.add_argument("--server", required=True)
    p.add_argument("--code", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--comfy", default=DEFAULT_COMFY)
    p.add_argument("--ca", default="")
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--control-port", type=int, default=CONTROL_PORT)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_join)

    p = sub.add_parser("run", help="开始接单")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--comfy", default="")
    p.add_argument("--no-control", action="store_true")
    p.set_defaults(func=cmd_run)

    for name, func, help_text in (("pause", cmd_pause, "暂停接单"),
                                  ("resume", cmd_resume, "恢复接单"),
                                  ("status", cmd_status, "查看状态")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default=str(DEFAULT_CONFIG))
        p.set_defaults(func=func)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
