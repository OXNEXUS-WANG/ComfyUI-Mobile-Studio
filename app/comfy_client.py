# -*- coding: utf-8 -*-
"""ComfyUI 访问层。

这是 CometInk 唯一直接访问 ComfyUI HTTP API 的模块：
- 地址、端口、超时集中在这里；
- /prompt、/history、/queue、/interrupt、/free、/object_info、/system_stats
  都有明确方法；
- 通过 /object_info 做节点能力探测，避免工作流跑到一半才报缺节点。

业务模块（app_core、web_server、comfy_workflows）不要再自己拼 ComfyUI URL。
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8188


def _env_port(name, default):
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        return default
    return port if 1 <= port <= 65535 else default


COMFY_HOST = str(os.environ.get("MGS_COMFY_HOST") or DEFAULT_HOST).strip()
COMFY_PORT = _env_port("MGS_COMFY_PORT", DEFAULT_PORT)
COMFY_BASE = str(
    os.environ.get("MGS_COMFY_URL")
    or "http://%s:%d" % (COMFY_HOST, COMFY_PORT)
).strip().rstrip("/")

# 只检查工作流真正依赖的节点。缺少时给出明确提示，而不是让 ComfyUI 返回
# “node type not found” 这种用户看不懂的错误。
CORE_NODES = (
    "CheckpointLoaderSimple",
    "EmptyLatentImage",
    "CLIPTextEncode",
    "KSampler",
    "VAEDecode",
    "SaveImage",
    "LoadImage",
    "VAEEncode",
    "VAEEncodeForInpaint",
    "ImageToMask",
    "ImageScaleToTotalPixels",
    "LatentUpscaleBy",
)
ANIMA_NODES = (
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
)
# NoobAI v-pred 必需；LoRA 和 PAG 节点按实际开关再追加。
SDXL_NODES = (
    "CLIPSetLastLayer",
    "ModelSamplingDiscrete",
    "RescaleCFG",
)
VIDEO_NODES = (
    "UNETLoader",
    "CLIPLoader",
    "VAELoader",
    "ModelSamplingSD3",
    "EmptyHunyuanLatentVideo",
    "CreateVideo",
    "SaveVideo",
)
I2V_NODES = VIDEO_NODES + ("WanVaceToVideo",)
UPSCALE_NODES = (
    "UpscaleModelLoader",
    "ImageUpscaleWithModel",
)
TRANSLATE_NODES = ("ArgosTranslateTextNode",)
PONY_NODES = ("ConditioningConcat",)

REQUIRED_BY_FEATURE = {
    "txt2img": CORE_NODES,
    "img2img": CORE_NODES,
    "inpaint": CORE_NODES,
    "anima": CORE_NODES + ANIMA_NODES,
    "noob": CORE_NODES + SDXL_NODES,
    "sdxl": CORE_NODES + ("LoraLoader",),
    "video": VIDEO_NODES,
    "i2v": I2V_NODES,
    "upscale": UPSCALE_NODES,
    "translate": TRANSLATE_NODES,
    "pony": CORE_NODES + PONY_NODES,
}


class ComfyError(RuntimeError):
    """ComfyUI HTTP 调用失败。status=0 表示连接失败。"""

    def __init__(self, message, status=0, body=""):
        super().__init__(message)
        self.status = int(status or 0)
        self.body = str(body or "")[:2000]


class ComfyCapabilityError(ComfyError):
    """ComfyUI 在线，但缺少当前工作流必需的节点。"""

    def __init__(self, missing, context=""):
        self.missing = list(missing or [])
        prefix = ("%s：" % context) if context else ""
        super().__init__(
            "%sComfyUI 缺少必需节点：%s。请安装或更新对应自定义节点后重启 ComfyUI。"
            % (prefix, ", ".join(self.missing)),
            status=0,
        )


class ComfyClient:
    def __init__(self, base_url=None, timeout=60):
        self.base_url = str(base_url or COMFY_BASE).rstrip("/")
        self.timeout = float(timeout or 60)
        self._lock = threading.RLock()
        self._object_info = {"t": 0.0, "v": None}
        self._version = {"t": 0.0, "v": ""}

    # ---------------------------------------------------------------- HTTP
    def url(self, path):
        path = str(path or "")
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return self.base_url + path

    def request_json(self, path, payload=None, timeout=None, method=None):
        """请求 ComfyUI；GET 时 payload 为 None，POST 时序列化为 JSON。

        /free 这类接口可能返回空 body，这里统一返回 {}，避免 json.load 报错。
        """
        url = self.url(path)
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method or ("POST" if data else "GET"))
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            raise ComfyError(
                "ComfyUI 返回 HTTP %s：%s" % (exc.code, body[:500]),
                status=exc.code, body=body) from exc
        except urllib.error.URLError as exc:
            raise ComfyError(
                "连接 ComfyUI 失败（%s）：%s" % (url, exc.reason)) from exc
        except OSError as exc:
            raise ComfyError("连接 ComfyUI 失败（%s）：%s" % (url, exc)) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ComfyError("ComfyUI 返回了非 JSON 内容：%s"
                             % raw[:300].decode("utf-8", "replace")) from exc

    def get(self, path, timeout=None):
        return self.request_json(path, None, timeout=timeout, method="GET")

    def post(self, path, payload=None, timeout=None):
        return self.request_json(path, payload or {}, timeout=timeout, method="POST")

    # ------------------------------------------------------------ 常用接口
    def system_stats(self, timeout=2):
        return self.get("/system_stats", timeout=timeout)

    def queue(self, timeout=5):
        return self.get("/queue", timeout=timeout)

    def history(self, prompt_id, timeout=5):
        prompt_id = urllib.parse.quote(str(prompt_id or ""), safe="")
        return self.get("/history/" + prompt_id, timeout=timeout)

    def submit(self, workflow, timeout=60):
        return self.post("/prompt", workflow, timeout=timeout)

    def interrupt(self, prompt_id="", timeout=15):
        payload = {"prompt_id": prompt_id} if prompt_id else {}
        return self.post("/interrupt", payload, timeout=timeout)

    def delete_queue(self, prompt_ids, timeout=10):
        ids = [str(x) for x in (prompt_ids or []) if str(x or "").strip()]
        if not ids:
            return {}
        return self.post("/queue", {"delete": ids}, timeout=timeout)

    def free(self, unload_models=True, free_memory=True, timeout=5):
        return self.post("/free", {
            "unload_models": bool(unload_models),
            "free_memory": bool(free_memory),
        }, timeout=timeout)

    def ws_target(self, client_id="mobile_web"):
        """给 ComfyUI 实时进度 WebSocket 用的主机/端口/路径。"""
        parsed = urllib.parse.urlparse(self.base_url)
        host = parsed.hostname or DEFAULT_HOST
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return {
            "host": host,
            "port": port,
            "netloc": parsed.netloc or ("%s:%d" % (host, port)),
            "path": "/ws?clientId=" + urllib.parse.quote(str(client_id or "")),
            "secure": parsed.scheme == "https",
        }

    # ------------------------------------------------------------ 能力探测
    def object_info(self, max_age=30):
        """读取 /object_info，带线程安全缓存。max_age=0 表示强制刷新。"""
        now = time.time()
        with self._lock:
            cached = self._object_info.get("v")
            # 失败结果也缓存（v=None），避免 ComfyUI 离线时每个请求都去连一次。
            if (max_age
                    and now - float(self._object_info.get("t") or 0) < max_age):
                return cached
        try:
            info = self.get("/object_info", timeout=20)
        except Exception:
            with self._lock:
                self._object_info["t"] = now
                return self._object_info.get("v")
        if isinstance(info, dict):
            with self._lock:
                self._object_info["v"] = info
                self._object_info["t"] = now
            return info
        return None

    def comfyui_version(self, max_age=60):
        now = time.time()
        with self._lock:
            if (self._version.get("v")
                    and now - float(self._version.get("t") or 0) < max_age):
                return self._version["v"]
        version = ""
        try:
            stats = self.system_stats(timeout=2)
            version = str(((stats or {}).get("system") or {})
                          .get("comfyui_version") or "")
        except Exception:
            version = ""
        with self._lock:
            self._version = {"t": now, "v": version}
        return version

    def capabilities(self, required=None, max_age=30):
        info = self.object_info(max_age=max_age)
        online = isinstance(info, dict)
        nodes = set(info.keys()) if online else set()
        required = list(required if required is not None else CORE_NODES)
        missing = sorted(set(required) - nodes)
        return {
            "online": online,
            "base_url": self.base_url,
            "comfyui_version": self.comfyui_version() if online else "",
            "required": required,
            "missing": missing,
            "ok": bool(online and not missing),
        }

    def missing_nodes(self, required, max_age=30):
        report = self.capabilities(required=required, max_age=max_age)
        return report.get("missing") or []

    def ensure_nodes(self, required, context=""):
        """在线且缺节点时抛 ComfyCapabilityError。

        /object_info 暂时不可用时返回 True，让真正的提交请求去暴露连接问题，
        避免把“ComfyUI 还没启动”误报成“缺节点”。
        """
        report = self.capabilities(required=required)
        if not report.get("online"):
            return True
        if report.get("missing"):
            raise ComfyCapabilityError(report["missing"], context=context)
        return True


CLIENT = ComfyClient()
COMFY = CLIENT.base_url
COMFY_PORT = urllib.parse.urlparse(CLIENT.base_url).port or DEFAULT_PORT


def http_json(path, payload=None, timeout=60):
    """兼容旧调用点：所有 ComfyUI 请求都走同一个客户端。"""
    return CLIENT.request_json(path, payload, timeout=timeout)


def comfy_current_prompt():
    """ComfyUI 当前真正在跑的 prompt_id；读不到返回空字符串。"""
    try:
        q = CLIENT.queue(timeout=5)
        running = q.get("queue_running") or []
        if running and isinstance(running[0], (list, tuple)) and len(running[0]) > 1:
            return str(running[0][1])
    except Exception:
        pass
    return ""


def comfy_free():
    """让 ComfyUI 释放模型/显存。失败不抛，调用方通常只做尽力清理。"""
    try:
        CLIENT.free()
        return True
    except Exception:
        return False
