# -*- coding: utf-8 -*-
"""可信时间：在线 NTP / HTTP Date 校时，离线单调计时，检测系统时间回拨。

不依赖第三方库。在线时优先 NTP，失败后退到 HTTPS Date 响应头；离线时
使用上次可信时间 + 单调时钟，并把状态用 HMAC 保护，防止直接改 state 文件
延长授权或重置每日额度。整机快照回滚无法在纯软件层完全防住，这一点在
文档里会说明。
"""
import datetime
import email.utils
import hashlib
import hmac
import json
import os
import secrets
import socket
import ssl
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT, "time_state.json")
KEY_FILE = os.path.join(ROOT, "trusted_time.key")
LOG_DIR = os.path.join(ROOT, "logs")

NTP_SERVERS = ("ntp.aliyun.com", "time.windows.com", "cn.pool.ntp.org")
HTTP_SOURCES = ("https://www.baidu.com/", "https://www.aliyun.com/",
                "https://www.qq.com/")
SYNC_INTERVAL = 3600
ROLLBACK_TOLERANCE = 120
PERSIST_INTERVAL = 60
NTP_EPOCH_DELTA = 2208988800

_LOCK = threading.RLock()
_STARTED = False
_SYNC_THREAD = None
_LAST_PERSIST = 0.0
_BASE = {
    "ready": False,
    "trusted": 0.0,
    "mono": 0.0,
    "source": "wall",
    "last_sync": 0.0,
    "last_seen": 0.0,
    "rollback_count": 0,
    "last_rollback": 0.0,
    "error": "",
}


def _log(text):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "time-sync-%s.log" %
                            time.strftime("%Y-%m-%d"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except Exception:
        pass


def _read_key():
    try:
        raw = open(KEY_FILE, "r", encoding="ascii").read().strip()
        key = bytes.fromhex(raw)
        if len(key) >= 16:
            return key
    except Exception:
        pass
    key = secrets.token_bytes(32)
    try:
        tmp = KEY_FILE + ".tmp"
        with open(tmp, "w", encoding="ascii") as fh:
            fh.write(key.hex())
        os.replace(tmp, KEY_FILE)
    except Exception:
        pass
    return key


def _canon(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _sign(payload):
    return hmac.new(_read_key(), _canon(payload), hashlib.sha256).hexdigest()


def _load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        payload = data.get("payload")
        signature = str(data.get("hmac") or "")
        if not isinstance(payload, dict) or not signature:
            return None
        if not hmac.compare_digest(signature, _sign(payload)):
            _log("状态文件 HMAC 校验失败，忽略")
            return None
        return payload
    except Exception:
        return None


def _save_locked(source=None):
    now = float(_BASE.get("trusted") or time.time())
    payload = {
        "version": 1,
        "last_seen": now,
        "last_mono": time.monotonic(),
        "source": source or _BASE.get("source") or "wall",
        "last_sync": float(_BASE.get("last_sync") or 0.0),
        "rollback_count": int(_BASE.get("rollback_count") or 0),
        "last_rollback": float(_BASE.get("last_rollback") or 0.0),
        "updated": now,
    }
    data = {"payload": payload, "hmac": _sign(payload)}
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, STATE_FILE)
        _BASE["last_seen"] = now
    except Exception:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
    global _LAST_PERSIST
    _LAST_PERSIST = time.monotonic()


def _apply(trusted, source, last_sync=None):
    with _LOCK:
        _BASE.update(ready=True, trusted=float(trusted),
                     mono=time.monotonic(), source=source,
                     error="")
        if last_sync is not None:
            _BASE["last_sync"] = float(last_sync)
        _save_locked(source)


def _ntp_query(host, timeout=1.5):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        packet = b"\x1b" + b"\x00" * 47
        t1 = time.time()
        sock.sendto(packet, (host, 123))
        data, _addr = sock.recvfrom(48)
        t4 = time.time()
    finally:
        sock.close()
    if len(data) < 48:
        raise ValueError("NTP 响应过短")
    seconds = int.from_bytes(data[40:44], "big") - NTP_EPOCH_DELTA
    fraction = int.from_bytes(data[44:48], "big") / 4294967296.0
    value = seconds + fraction
    if value < 946684800:  # 2000-01-01
        raise ValueError("NTP 时间异常")
    return value + (t4 - t1) / 2.0


def _http_date(url, timeout=2.5):
    req = urllib.request.Request(
        url, headers={"User-Agent": "ComfyUI-Mobile-Studio-time/1.0"})
    t1 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        header = resp.headers.get("Date")
        resp.read(256)
    t4 = time.time()
    if not header:
        raise ValueError("响应没有 Date")
    dt = email.utils.parsedate_to_datetime(header)
    if dt is None:
        raise ValueError("Date 无法解析")
    if dt.tzinfo is None:
        # HTTP Date 应该是 GMT；按 UTC 处理。
        value = dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    else:
        value = dt.timestamp()
    if value < 946684800:
        raise ValueError("Date 时间异常")
    return value + (t4 - t1) / 2.0


def _fetch_online():
    errors = []
    for host in NTP_SERVERS:
        try:
            return _ntp_query(host), "ntp:" + host, errors
        except Exception as exc:
            errors.append("%s: %s" % (host, exc))
    for url in HTTP_SOURCES:
        try:
            return _http_date(url), "http:" + url, errors
        except Exception as exc:
            errors.append("%s: %s" % (url, exc))
    return None, "", errors


def sync_now():
    """立即在线校时；成功返回 True。失败时保留当前可信时间。"""
    value, source, errors = _fetch_online()
    if value is None:
        with _LOCK:
            _BASE["error"] = "; ".join(errors[-3:])[:300]
        _log("校时失败：" + "; ".join(errors[-3:])[:300])
        return False
    _apply(value, source, last_sync=value)
    _log("校时成功：%s，trusted=%.3f" % (source, value))
    return True


def ensure_started(start_sync=True):
    """启动时调用一次：加载/校验状态、建立可信时间基线，并启动后台校时。"""
    global _STARTED, _SYNC_THREAD
    with _LOCK:
        if _STARTED:
            return
        wall = time.time()
        mono = time.monotonic()
        state = _load_state()
        source = "wall"
        base = wall
        rollback_count = 0
        last_rollback = 0.0
        last_sync = 0.0
        if state:
            try:
                last_seen = float(state.get("last_seen") or 0)
                last_mono = float(state.get("last_mono") or 0)
                rollback_count = int(state.get("rollback_count") or 0)
                last_rollback = float(state.get("last_rollback") or 0)
                last_sync = float(state.get("last_sync") or 0)
            except Exception:
                last_seen = last_mono = last_rollback = last_sync = 0.0
            same_boot = last_mono > 0 and mono >= last_mono
            estimated = last_seen
            if same_boot:
                # 单次运行内单调时钟可靠；离线时用它防止小幅回拨。
                estimated = last_seen + max(0.0, mono - last_mono)
            if last_seen and wall < last_seen - ROLLBACK_TOLERANCE:
                rollback_count += 1
                last_rollback = wall
                base = max(wall, last_seen)
                source = "rollback"
                _log("检测到系统时间回拨：wall=%.3f last_seen=%.3f" %
                     (wall, last_seen))
            elif same_boot and estimated > wall + ROLLBACK_TOLERANCE:
                base = estimated
                source = "monotonic"
            else:
                base = max(wall, last_seen) if last_seen else wall
                source = "wall"
        _BASE.update(ready=True, trusted=base, mono=mono, source=source,
                     last_sync=last_sync, last_seen=base,
                     rollback_count=rollback_count,
                     last_rollback=last_rollback, error="")
        _save_locked(source)
        _STARTED = True
    if start_sync:
        _SYNC_THREAD = threading.Thread(target=_sync_loop, daemon=True,
                                        name="time-sync")
        _SYNC_THREAD.start()


def _sync_loop():
    # 首次稍等几秒，避免和启动时的下载/加载抢网络。
    time.sleep(3)
    while True:
        try:
            sync_now()
        except Exception as exc:
            _log("后台校时异常：%s" % exc)
        time.sleep(SYNC_INTERVAL)


def now():
    """当前可信 Unix 时间；未初始化时退回系统时间。"""
    with _LOCK:
        if not _BASE.get("ready"):
            return time.time()
        value = float(_BASE["trusted"]) + (
            time.monotonic() - float(_BASE["mono"]))
        if value > float(_BASE.get("last_seen") or 0):
            _BASE["last_seen"] = value
        global _LAST_PERSIST
        if time.monotonic() - _LAST_PERSIST >= PERSIST_INTERVAL:
            _save_locked()
        return value


def localtime(ts=None):
    return time.localtime(now() if ts is None else ts)


def strftime(fmt, ts=None):
    return time.strftime(fmt, localtime(ts))


def status():
    with _LOCK:
        current = now() if _BASE.get("ready") else time.time()
        local = time.time()
        return {
            "ready": bool(_BASE.get("ready")),
            "source": _BASE.get("source") or "wall",
            "trusted": round(current, 3),
            "local": round(local, 3),
            "offset": round(current - local, 3),
            "last_sync": round(float(_BASE.get("last_sync") or 0), 3),
            "last_sync_text": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(float(_BASE.get("last_sync") or 0)))
            if _BASE.get("last_sync") else "",
            "rollback_count": int(_BASE.get("rollback_count") or 0),
            "last_rollback": round(float(_BASE.get("last_rollback") or 0), 3),
            "error": _BASE.get("error") or "",
        }
