# -*- coding: utf-8 -*-
"""本地小参数大模型翻译接口。

支持两种常见本地服务：

- Ollama：``http://127.0.0.1:11434``，调用 ``/api/chat``；
- OpenAI 兼容：LM Studio、llama.cpp server、vLLM 等，调用
  ``/v1/chat/completions``。

只负责“把中文提示词翻成英文”，不加载模型、不依赖第三方库。
配置保存在安装目录的 ``local_llm.json``；管理员设置，普通账号只选择
是否使用。密钥不会通过 public_config() 返回给前端。
"""
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(ROOT, "local_llm.json")

DEFAULT_CONFIG = {
    "enabled": False,
    "provider": "ollama",          # ollama | openai
    "base_url": "http://127.0.0.1:11434",
    "model": "",
    "api_key": "",
    "timeout": 45,
    "temperature": 0.1,
    "max_tokens": 512,
}

_CACHE = {"mtime": 0.0, "config": None}
_LOCK = threading.RLock()

_SYSTEM_PROMPT = (
    "You are a translation engine for anime image-generation prompts. "
    "Translate the user's Chinese text into concise English. Keep existing "
    "English words, Danbooru tags, commas, parentheses, weights and line "
    "breaks unchanged. Do not add explanations, quotes, markdown or quality "
    "tags that are not present. Output only the English translation."
)


def has_chinese(text):
    return bool(re.search(r"[一-鿿]", str(text or "")))


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


def _clean_base_url(value):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("请填写本地模型地址")
    if len(raw) > 300:
        raise ValueError("本地模型地址太长")
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("地址必须是 http:// 或 https:// 开头的完整地址")
    if parsed.username or parsed.password:
        raise ValueError("地址里不要写账号密码，请单独填写 API Key")
    if parsed.port is not None and not (1 <= parsed.port <= 65535):
        raise ValueError("端口不合法")
    return raw.rstrip("/")


def _host_is_local(host):
    """只允许本机 / 内网地址，避免管理员误把提示词发到公网。"""
    host = str(host or "").strip().strip("[]").lower()
    if not host:
        return False
    if host in ("localhost", "localhost.localdomain", "host.docker.internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return bool(ip.is_loopback or ip.is_private or ip.is_link_local)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except Exception:
            continue
        if not (ip.is_loopback or ip.is_private or ip.is_link_local):
            return False
    return bool(infos)


def validate(raw):
    src = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_CONFIG)
    out["enabled"] = bool(src.get("enabled", out["enabled"]))
    provider = str(src.get("provider") or out["provider"]).strip().lower()
    if provider not in ("ollama", "openai"):
        provider = "ollama"
    out["provider"] = provider
    out["base_url"] = _clean_base_url(src.get("base_url", out["base_url"]))
    parsed = urllib.parse.urlparse(out["base_url"])
    if not _host_is_local(parsed.hostname):
        raise ValueError("本地翻译模型只允许本机或内网地址")
    model = str(src.get("model") or "").strip()
    if len(model) > 160:
        raise ValueError("模型名太长")
    if re.search(r"[\r\n\t]", model):
        raise ValueError("模型名不能包含换行")
    out["model"] = model
    out["api_key"] = str(src.get("api_key") or "")[:300]
    out["timeout"] = _as_int(src.get("timeout"), 3, 180, out["timeout"])
    out["temperature"] = _as_float(src.get("temperature"), 0.0, 1.5,
                                  out["temperature"])
    out["max_tokens"] = _as_int(src.get("max_tokens"), 16, 2048,
                                out["max_tokens"])
    if out["enabled"] and not out["model"]:
        raise ValueError("启用本地翻译前要先填写模型名")
    return out


def load(force=False):
    try:
        mtime = os.path.getmtime(CONFIG_FILE)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if (not force and _CACHE["config"] is not None
                and mtime == _CACHE["mtime"]):
            return dict(_CACHE["config"])
        data = {}
        if mtime:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
            except Exception:
                data = {}
        try:
            cfg = validate(data) if data else dict(DEFAULT_CONFIG)
        except Exception:
            cfg = dict(DEFAULT_CONFIG)
        _CACHE.update({"mtime": mtime, "config": cfg})
        return dict(cfg)


def save(patch):
    with _LOCK:
        current = load(force=True)
        merged = dict(current)
        if isinstance(patch, dict):
            for key in DEFAULT_CONFIG:
                if key in patch:
                    merged[key] = patch[key]
        cfg = validate(merged)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
        _CACHE.update({"mtime": os.path.getmtime(CONFIG_FILE),
                       "config": cfg})
        return dict(cfg)


def public_config(cfg=None):
    cfg = dict(cfg or load())
    return {
        "enabled": bool(cfg.get("enabled")),
        "provider": cfg.get("provider") or "ollama",
        "base_url": cfg.get("base_url") or "",
        "model": cfg.get("model") or "",
        "timeout": int(cfg.get("timeout") or 45),
        "temperature": float(cfg.get("temperature") or 0.1),
        "max_tokens": int(cfg.get("max_tokens") or 512),
        "api_key_set": bool(cfg.get("api_key")),
        "configured": bool(cfg.get("enabled") and cfg.get("model")
                           and cfg.get("base_url")),
    }


def available(cfg=None):
    cfg = cfg or load()
    return bool(cfg.get("enabled") and cfg.get("model")
                and cfg.get("base_url"))


def _endpoint(cfg):
    base = str(cfg.get("base_url") or "").rstrip("/")
    if cfg.get("provider") == "openai":
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"
    if base.endswith("/api/chat"):
        return base
    if base.endswith("/api"):
        return base + "/chat"
    return base + "/api/chat"


def _post_json(url, payload, cfg):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": "ComfyUI-Mobile-Studio/local-llm",
    }
    key = str(cfg.get("api_key") or "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout") or 45)) as resp:
            raw = resp.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(600).decode("utf-8", "replace")
        except Exception:
            pass
        raise RuntimeError("本地模型返回 HTTP %s%s" %
                           (exc.code, (": " + detail) if detail else ""))
    except urllib.error.URLError as exc:
        raise RuntimeError("连不上本地模型：%s" % (exc.reason,))
    except socket.timeout:
        raise RuntimeError("本地模型响应超时")
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise RuntimeError("本地模型返回的不是 JSON")


def _clean_output(text):
    out = str(text or "").strip()
    out = re.sub(r"^```(?:text|json)?\s*", "", out, flags=re.I)
    out = re.sub(r"\s*```$", "", out)
    out = re.sub(r"^(?:translation|english|译文|翻译)\s*[:：]\s*", "",
                 out, flags=re.I)
    out = out.strip().strip('"').strip("'").strip()
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()[:4000]


def translate(text, cfg=None):
    """返回 (英文, 错误信息)。失败时英文为空串。"""
    src = str(text or "").strip()
    if not src:
        return "", ""
    if not has_chinese(src):
        return src, ""
    cfg = dict(cfg or load())
    if not available(cfg):
        return "", "本地翻译模型未启用或未配置"
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content":
            "Translate this Chinese prompt into English. Output only the "
            "translation.\n<text>\n%s\n</text>" % src[:4000]},
    ]
    if cfg.get("provider") == "openai":
        payload = {
            "model": cfg.get("model"),
            "messages": messages,
            "temperature": float(cfg.get("temperature") or 0.1),
            "max_tokens": int(cfg.get("max_tokens") or 512),
            "stream": False,
        }
    else:
        payload = {
            "model": cfg.get("model"),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": float(cfg.get("temperature") or 0.1),
                "num_predict": int(cfg.get("max_tokens") or 512),
            },
        }
    try:
        data = _post_json(_endpoint(cfg), payload, cfg)
    except Exception as exc:
        return "", str(exc)
    if cfg.get("provider") == "openai":
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            content = ""
    else:
        try:
            content = data["message"]["content"]
        except Exception:
            content = ""
    out = _clean_output(content)
    if not out:
        return "", "本地模型没有返回内容"
    if has_chinese(out):
        return "", "本地模型返回的仍是中文，请换一个翻译模型"
    return out, ""


def test(text=None):
    t0 = time.time()
    sample = str(text or "一个银发红眼的女孩站在雨夜的城市街头").strip()[:1000]
    out, err = translate(sample)
    return {
        "ok": not err,
        "input": sample,
        "output": out,
        "error": err,
        "seconds": round(time.time() - t0, 2),
        "config": public_config(),
    }
