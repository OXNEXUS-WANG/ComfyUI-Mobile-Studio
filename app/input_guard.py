# -*- coding: utf-8 -*-
"""提示词输入净化与长度限制。

前端负责即时字数提示；后端仍然做一次权威清理，防止绕过页面直接调 API。
只删除控制字符、零宽字符和双向控制字符，不改动正常中文、英文、emoji。
"""
import re
import unicodedata

MAX_PROMPT_CHARS = 2000
MAX_TEAM_PROMPT_CHARS = 4000
MAX_RAW_CHARS = 20000

# 明确要删除的不可见/双向控制字符。U+200D（ZWJ）保留，避免拆坏 emoji 组合。
_DROP = {
    0x00AD,  # soft hyphen
    0x061C,  # Arabic letter mark
    0x180E,  # Mongolian vowel separator
    0x200B, 0x200C, 0x200E, 0x200F,
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
    0x2060, 0x2061, 0x2062, 0x2063, 0x2064,
    0x2066, 0x2067, 0x2068, 0x2069,
    0xFEFF,
    0xFFF9, 0xFFFA, 0xFFFB,
}
_LINE_BREAKS = {" ", " "}


def clean_text(value, limit=MAX_PROMPT_CHARS):
    """返回 (清理后的文本, 信息字典)。

    信息字典：removed（删除的不可见字符数）、truncated（是否截断）、
    length（最终字符数）、limit（上限）。
    """
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value
    else:
        raw = str(value)

    hard_truncated = len(raw) > MAX_RAW_CHARS
    if hard_truncated:
        raw = raw[:MAX_RAW_CHARS]

    out = []
    removed = 0
    for ch in raw:
        code = ord(ch)
        if ch == "\n" or ch == "\t":
            out.append(ch)
            continue
        if ch in _LINE_BREAKS:
            out.append("\n")
            continue
        if code in _DROP:
            removed += 1
            continue
        category = unicodedata.category(ch)
        if category in ("Cc", "Cs"):
            removed += 1
            continue
        out.append(ch)

    text = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    # 行内连续空白压成一个空格；段落之间最多保留一个空行。
    text = re.sub(r"[  　]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    truncated = hard_truncated
    if limit and len(text) > limit:
        text = text[:limit].rstrip()
        truncated = True
    return text, {
        "removed": removed,
        "truncated": truncated,
        "length": len(text),
        "limit": int(limit or 0),
    }


def notice_text(info):
    """把清理信息转成一句给用户看的中文提示；没有变化时返回空字符串。"""
    if not info:
        return ""
    parts = []
    if info.get("removed"):
        parts.append("已清理 %d 个不可见字符" % int(info["removed"]))
    if info.get("truncated"):
        parts.append("超过 %d 字的部分已截断" % int(info.get("limit") or 0))
    return "，".join(parts)
