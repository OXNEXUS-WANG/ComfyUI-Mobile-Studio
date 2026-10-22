# -*- coding: utf-8 -*-
"""可选的提示词敏感词过滤。

只做“提示词层”的本地词表匹配，不调用云端服务，也不保证输出图片安全。
默认关闭；管理员在系统设置里维护词表、范围和模式。

审计/接口不返回提示词正文；测试接口只在管理员请求时返回命中的规则。
"""
import json
import os
import re
import threading
import time
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(ROOT, "sensitive_filter.json")

MODES = ("off", "warn", "block")
MAX_WORDS = 1000
MAX_WORD_LEN = 64
MAX_TEST_CHARS = 5000
DEFAULT_SCOPE = {"prompt": True, "negative": True, "caption": False}
_LOCK = threading.RLock()
_RULES = {"key": None, "rules": []}

ZERO_WIDTH = set("​‌‍‎‏⁠﻿")


def _default():
    return {"version": 1, "mode": "off", "scope": dict(DEFAULT_SCOPE),
            "words": [], "updated": 0}


def normalize_text(text):
    text = unicodedata.normalize("NFKC", str(text or "")).lower()
    out = []
    for ch in text:
        if ch in ZERO_WIDTH:
            continue
        if ch in "\r\n\t":
            out.append(" ")
            continue
        if unicodedata.category(ch).startswith("C"):
            continue
        out.append(ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _compact(text):
    """去掉常见分隔符，识别 b.l.o.o.d / b l o o d 这类拆字。"""
    return re.sub(r"[\s._\-*·]+", "", text)


def clean_words(raw):
    if isinstance(raw, str):
        items = re.split(r"[\r\n,，]+", raw)
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = []
    words = []
    seen = set()
    for item in items:
        word = str(item or "").strip()
        if not word:
            continue
        word = word[:MAX_WORD_LEN]
        key = normalize_text(word)
        if not key or key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= MAX_WORDS:
            break
    return words


def normalize_settings(raw):
    out = _default()
    if not isinstance(raw, dict):
        return out
    mode = str(raw.get("mode") or "off").lower()
    out["mode"] = mode if mode in MODES else "off"
    scope = raw.get("scope")
    if isinstance(scope, dict):
        for key in DEFAULT_SCOPE:
            if key in scope:
                out["scope"][key] = bool(scope.get(key))
    out["words"] = clean_words(raw.get("words"))
    try:
        out["updated"] = float(raw.get("updated") or 0)
    except Exception:
        out["updated"] = 0
    return out


def load():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        raw = {}
    return normalize_settings(raw)


def save(values):
    data = normalize_settings(values)
    data["updated"] = time.time()
    tmp = SETTINGS_FILE + ".tmp"
    with _LOCK:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_FILE)
    return data


def public_settings(admin=False):
    data = load()
    out = {
        "mode": data["mode"],
        "scope": dict(data["scope"]),
        "count": len(data["words"]),
        "updated": data["updated"],
    }
    if admin:
        out["words"] = list(data["words"])
        out["max_words"] = MAX_WORDS
        out["max_word_len"] = MAX_WORD_LEN
    return out


def _is_ascii_word(term):
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9 ._'\-]*", term))


def _compile(settings):
    words = tuple(settings.get("words") or ())
    with _LOCK:
        if _RULES.get("key") == words:
            return _RULES["rules"]
    rules = []
    for index, word in enumerate(words, 1):
        term = normalize_text(word)
        if not term:
            continue
        rule = {"id": "w%d" % index, "term": word, "term_norm": term,
                "ascii": _is_ascii_word(term), "regex": None}
        if rule["ascii"]:
            rule["regex"] = re.compile(
                r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")
        rules.append(rule)
    with _LOCK:
        _RULES.update(key=words, rules=rules)
    return rules


def scan(text, settings=None):
    settings = settings or load()
    mode = settings.get("mode") or "off"
    if mode == "off":
        return {"mode": "off", "hit": False, "count": 0, "ids": [],
                "terms": []}
    normalized = normalize_text(text)
    compact = _compact(normalized)
    hits = []
    for rule in _compile(settings):
        term = rule["term_norm"]
        if rule["regex"] is not None:
            hit = bool(rule["regex"].search(normalized) or
                       rule["regex"].search(compact))
        else:
            hit = term in normalized or term in compact
        if hit:
            hits.append(rule)
    return {
        "mode": mode,
        "hit": bool(hits),
        "count": len(hits),
        "ids": [x["id"] for x in hits],
        "terms": [x["term"] for x in hits],
    }


def check(prompt="", negative="", caption=None, settings=None):
    settings = settings or load()
    scope = settings.get("scope") or DEFAULT_SCOPE
    chunks = []
    if scope.get("prompt", True):
        chunks.append(str(prompt or ""))
    if scope.get("negative", True):
        chunks.append(str(negative or ""))
    if caption is not None and scope.get("caption", False):
        chunks.append(str(caption or ""))
    result = scan("\n".join(chunks), settings)
    return {k: result[k] for k in ("mode", "hit", "count", "ids")}


def check_caption(text):
    settings = load()
    if not settings.get("scope", {}).get("caption"):
        return {"mode": settings.get("mode", "off"), "hit": False,
                "count": 0, "ids": []}
    return check(caption=text, settings=settings)


def test_text(text):
    """管理员测试接口：返回命中规则；不写日志、不保存文本。"""
    text = str(text or "")[:MAX_TEST_CHARS]
    result = scan(text)
    return result


def status_for_admin():
    data = load()
    return {"mode": data["mode"], "scope": data["scope"],
            "count": len(data["words"]), "updated": data["updated"]}
