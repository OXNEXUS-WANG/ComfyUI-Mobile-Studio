# -*- coding: utf-8 -*-
"""团队 / 项目：成员角色、共享图库范围、共享提示词。

默认仍然是账号隔离；这里只提供“可选的共享视图”：
- 团队图库是成员个人图库的聚合，不复制图片，不改变每人的存储配额；
- 共享提示词保存在 team_prompts.json，只有成员能看到；
- 删除图片仍然只能删自己的，团队角色不会扩大写权限。
"""
import json
import os
import secrets
import threading
import time

import input_guard

ROOT = os.path.dirname(os.path.abspath(__file__))
TEAMS_FILE = os.path.join(ROOT, "teams.json")
PROMPTS_FILE = os.path.join(ROOT, "team_prompts.json")

ROLES = ("owner", "editor", "viewer")
ROLE_LABELS = {
    "owner": "所有者",
    "editor": "编辑者",
    "viewer": "只读",
}
MAX_TEAMS = 100
MAX_MEMBERS = 100
MAX_PROMPTS = 200
MAX_PROMPT_CHARS = 4000

_LOCK = threading.RLock()
_CACHE = {"mtime": 0.0, "data": None}
_PROMPTS = {"mtime": 0.0, "data": None}


def _clean_role(value, default="viewer"):
    value = str(value or "").strip().lower()
    return value if value in ROLES else default


def _clean_name(value):
    return str(value or "").strip()[:60]


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load():
    try:
        mtime = os.path.getmtime(TEAMS_FILE)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if _CACHE["data"] is not None and mtime == _CACHE["mtime"]:
            return dict(_CACHE["data"])
        data = _load_json(TEAMS_FILE, {"version": 1, "teams": {}})
        teams = data.get("teams")
        if not isinstance(teams, dict):
            teams = {}
        clean = {"version": 1, "teams": {}}
        for tid, team in list(teams.items())[:MAX_TEAMS]:
            if not isinstance(team, dict):
                continue
            members = team.get("members") if isinstance(team.get("members"), dict) else {}
            clean_members = {}
            for uid, role in list(members.items())[:MAX_MEMBERS]:
                uid = str(uid or "")[:80]
                if uid:
                    clean_members[uid] = _clean_role(role)
            if not clean_members:
                continue
            owner = str(team.get("owner_id") or next(iter(clean_members)))
            if owner not in clean_members:
                clean_members[owner] = "owner"
            clean_members[owner] = "owner"
            clean["teams"][str(tid)] = {
                "id": str(tid),
                "name": _clean_name(team.get("name")) or str(tid),
                "owner_id": owner,
                "created": float(team.get("created") or time.time()),
                "members": clean_members,
            }
        _CACHE["mtime"] = mtime
        _CACHE["data"] = clean
        return dict(clean)


def save(data):
    data = data if isinstance(data, dict) else {"version": 1, "teams": {}}
    with _LOCK:
        _save_json(TEAMS_FILE, data)
        _CACHE["mtime"] = os.path.getmtime(TEAMS_FILE)
        _CACHE["data"] = data
    return data


def load_prompts():
    try:
        mtime = os.path.getmtime(PROMPTS_FILE)
    except OSError:
        mtime = 0.0
    with _LOCK:
        if _PROMPTS["data"] is not None and mtime == _PROMPTS["mtime"]:
            return dict(_PROMPTS["data"])
        data = _load_json(PROMPTS_FILE, {"version": 1, "teams": {}})
        teams = data.get("teams")
        if not isinstance(teams, dict):
            teams = {}
        clean = {"version": 1, "teams": {}}
        for tid, rows in list(teams.items())[:MAX_TEAMS]:
            if not isinstance(rows, list):
                continue
            items = []
            for row in rows[:MAX_PROMPTS]:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("text") or "").strip()[:MAX_PROMPT_CHARS]
                if not text:
                    continue
                items.append({
                    "id": str(row.get("id") or ("p_" + secrets.token_hex(6))),
                    "text": text,
                    "by": str(row.get("by") or "")[:80],
                    "name": str(row.get("name") or "")[:60],
                    "created": float(row.get("created") or time.time()),
                })
            clean["teams"][str(tid)] = items
        _PROMPTS["mtime"] = mtime
        _PROMPTS["data"] = clean
        return dict(clean)


def save_prompts(data):
    with _LOCK:
        _save_json(PROMPTS_FILE, data)
        _PROMPTS["mtime"] = os.path.getmtime(PROMPTS_FILE)
        _PROMPTS["data"] = data
    return data


def team_ids_for(uid):
    uid = str(uid or "")
    data = load()
    return [tid for tid, team in data["teams"].items()
            if uid in (team.get("members") or {})]


def get_team(tid):
    return (load().get("teams") or {}).get(str(tid or ""))


def role_of(uid, tid):
    team = get_team(tid)
    if not team:
        return ""
    return str((team.get("members") or {}).get(str(uid or "")) or "")


def can_view(uid, tid, admin=False):
    return bool(admin or role_of(uid, tid))


def can_edit(uid, tid, admin=False):
    return bool(admin or role_of(uid, tid) in ("owner", "editor"))


def can_manage(uid, tid, admin=False):
    return bool(admin or role_of(uid, tid) == "owner")


def members_for(tid):
    team = get_team(tid) or {}
    return dict(team.get("members") or {})


def shared_uids(uid):
    """这个账号在团队图库里应该看到的成员 uid 集合（含自己）。"""
    uid = str(uid or "")
    out = {uid} if uid else set()
    for tid in team_ids_for(uid):
        out.update(members_for(tid).keys())
    return out


def share_owner(viewer_uid, owner_uid):
    viewer_uid = str(viewer_uid or "")
    owner_uid = str(owner_uid or "")
    if not viewer_uid or not owner_uid:
        return False
    if viewer_uid == owner_uid:
        return True
    for tid in team_ids_for(viewer_uid):
        if owner_uid in members_for(tid):
            return True
    return False


def public_team(team, prompts_count=0):
    if not team:
        return None
    members = []
    for uid, role in (team.get("members") or {}).items():
        # 用户名由调用方补；这里只返回 uid/role，避免循环导入 app_core
        members.append({"id": uid, "role": role})
    members.sort(key=lambda x: (ROLES.index(x["role"])
                                if x["role"] in ROLES else 9, x["id"]))
    return {
        "id": team.get("id"),
        "name": team.get("name"),
        "owner_id": team.get("owner_id"),
        "created": team.get("created"),
        "members": members,
        "prompt_count": prompts_count,
    }


def list_for_user(uid, admin=False):
    data = load()
    prompt_data = load_prompts().get("teams") or {}
    out = []
    for tid, team in data["teams"].items():
        role = role_of(uid, tid)
        if not admin and not role:
            continue
        item = public_team(team, len(prompt_data.get(tid) or []))
        item["role"] = "admin" if admin and not role else role
        out.append(item)
    out.sort(key=lambda x: (x.get("name") or "").lower())
    return out


def create_team(name, owner_id):
    name = _clean_name(name)
    owner_id = str(owner_id or "")[:80]
    if not name:
        raise ValueError("团队名称不能为空")
    if not owner_id:
        raise ValueError("缺少创建者")
    data = load()
    if len(data["teams"]) >= MAX_TEAMS:
        raise ValueError("团队数量到上限了")
    tid = "t_" + secrets.token_hex(6)
    team = {
        "id": tid, "name": name, "owner_id": owner_id,
        "created": time.time(), "members": {owner_id: "owner"},
    }
    data["teams"][tid] = team
    save(data)
    return team


def update_team(tid, name):
    team = get_team(tid)
    if not team:
        raise ValueError("团队不存在")
    name = _clean_name(name)
    if not name:
        raise ValueError("团队名称不能为空")
    data = load()
    data["teams"][tid]["name"] = name
    save(data)
    return data["teams"][tid]


def delete_team(tid):
    data = load()
    if tid not in data["teams"]:
        raise ValueError("团队不存在")
    data["teams"].pop(tid, None)
    save(data)
    prompts = load_prompts()
    prompts["teams"].pop(tid, None)
    save_prompts(prompts)


def add_member(tid, uid, role="viewer"):
    team = get_team(tid)
    if not team:
        raise ValueError("团队不存在")
    uid = str(uid or "")[:80]
    if not uid:
        raise ValueError("缺少账号")
    data = load()
    members = data["teams"][tid]["members"]
    if len(members) >= MAX_MEMBERS:
        raise ValueError("团队成员到上限了")
    if uid == data["teams"][tid]["owner_id"]:
        members[uid] = "owner"
    else:
        members[uid] = _clean_role(role)
    save(data)
    return data["teams"][tid]


def remove_member(tid, uid):
    team = get_team(tid)
    if not team:
        raise ValueError("团队不存在")
    uid = str(uid or "")
    if uid == team.get("owner_id"):
        raise ValueError("不能移除团队所有者")
    data = load()
    data["teams"][tid]["members"].pop(uid, None)
    save(data)
    return data["teams"][tid]


def set_role(tid, uid, role):
    team = get_team(tid)
    if not team:
        raise ValueError("团队不存在")
    uid = str(uid or "")
    if uid == team.get("owner_id"):
        raise ValueError("所有者角色不能修改")
    if uid not in (team.get("members") or {}):
        raise ValueError("成员不存在")
    data = load()
    data["teams"][tid]["members"][uid] = _clean_role(role)
    save(data)
    return data["teams"][tid]


def list_prompts(tid):
    return list((load_prompts().get("teams") or {}).get(str(tid or "")) or [])


def add_prompt(tid, text, by="", name=""):
    team = get_team(tid)
    if not team:
        raise ValueError("团队不存在")
    text, _info = input_guard.clean_text(text, MAX_PROMPT_CHARS)
    if not text:
        raise ValueError("提示词不能为空（或只包含不可见字符）")
    data = load_prompts()
    rows = data["teams"].setdefault(tid, [])
    if len(rows) >= MAX_PROMPTS:
        raise ValueError("共享提示词到上限了")
    item = {
        "id": "p_" + secrets.token_hex(6),
        "text": text, "by": str(by or "")[:80],
        "name": str(name or "")[:60], "created": time.time(),
    }
    rows.append(item)
    save_prompts(data)
    return item


def delete_prompt(tid, pid, uid="", admin=False):
    team = get_team(tid)
    if not team:
        raise ValueError("团队不存在")
    data = load_prompts()
    rows = data["teams"].get(tid) or []
    keep = []
    removed = None
    for row in rows:
        if row.get("id") == pid:
            if not admin and row.get("by") != uid and not can_manage(uid, tid):
                raise ValueError("只能删除自己添加的提示词")
            removed = row
            continue
        keep.append(row)
    if removed is None:
        raise ValueError("提示词不存在")
    data["teams"][tid] = keep
    save_prompts(data)
    return removed
