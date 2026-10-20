# -*- coding: utf-8 -*-
"""工作流导入与体检：支持 ComfyUI UI 格式和 API prompt 格式。

导入只做“保存 + 检查”，不会自动执行工作流；避免管理员误点一个陌生
JSON 就直接占用 GPU。检查内容包括：
- 节点类型是否在当前 ComfyUI 的 /object_info 里；
- 引用的模型文件名是否已安装；
- UI links / API inputs 是否指向不存在的节点；
- 是否存在明显的循环依赖。

工作流文件保存在 workflows/<id>.json，最多 8MB。
"""
import json
import os
import re
import secrets
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.join(ROOT, "workflows")

MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 2000
MAX_LINKS = 5000
_ID_RE = re.compile(r"^wf_[0-9a-f]{12}$")
_LOCK = threading.RLock()
MODEL_EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf",
              ".onnx", ".sft")
UI_SKIP_TYPES = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode"}
MODEL_KEYS = {
    "ckpt_name", "lora_name", "vae_name", "unet_name", "clip_name",
    "clip_name1", "clip_name2", "control_net_name", "style_model_name",
    "model_name", "upscale_model", "ipadapter_file", "insightface",
    "bbox_model_name", "segm_model_name", "detector_model",
}


def _safe_id(wid):
    wid = str(wid or "")
    return wid if _ID_RE.match(wid) else ""


def _path(wid):
    wid = _safe_id(wid)
    return os.path.join(WORKFLOW_DIR, wid + ".json") if wid else ""


def _clean_name(name, fallback="workflow"):
    name = str(name or "").strip().replace("\x00", "")[:80]
    return name or fallback


def _json_size(data):
    try:
        return len(json.dumps(data, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


def parse_workflow(content):
    """content 可以是 JSON 字符串或 dict；返回原始 dict。"""
    if isinstance(content, (dict, list)):
        data = content
    else:
        text = str(content or "")
        if len(text.encode("utf-8", "ignore")) > MAX_BYTES:
            raise ValueError("工作流文件超过 8MB")
        try:
            data = json.loads(text)
        except Exception as exc:
            raise ValueError("不是有效的 JSON：%s" % exc)
    if not isinstance(data, dict):
        raise ValueError("工作流 JSON 顶层必须是对象")
    if _json_size(data) > MAX_BYTES:
        raise ValueError("工作流文件超过 8MB")
    return data


def detect_format(data):
    if isinstance(data.get("nodes"), list):
        return "ui"
    if data and all(isinstance(v, dict) for v in data.values()) and any(
            "class_type" in v for v in data.values() if isinstance(v, dict)):
        return "api"
    return ""


def normalize(data):
    """提取节点、连线、依赖，不修改原始数据。"""
    fmt = detect_format(data)
    nodes = []
    links = []
    deps = {}
    if fmt == "ui":
        for item in (data.get("nodes") or [])[:MAX_NODES]:
            if not isinstance(item, dict):
                continue
            nid = item.get("id")
            if nid is None:
                continue
            ntype = str(item.get("type") or item.get("class_type") or "")
            nodes.append({
                "id": str(nid),
                "type": ntype,
                "title": str(item.get("title") or "")[:120],
                "mode": item.get("mode"),
            })
        for link in (data.get("links") or [])[:MAX_LINKS]:
            if not isinstance(link, (list, tuple)) or len(link) < 5:
                continue
            links.append({
                "id": link[0] if len(link) > 0 else "",
                "src": str(link[1]) if link[1] is not None else "",
                "src_slot": link[2] if len(link) > 2 else None,
                "dst": str(link[3]) if link[3] is not None else "",
                "dst_slot": link[4] if len(link) > 4 else None,
                "type": str(link[5]) if len(link) > 5 else "",
            })
            if link[1] is not None:
                deps.setdefault(str(link[3]), set()).add(str(link[1]))
    elif fmt == "api":
        for nid, item in list(data.items())[:MAX_NODES]:
            if not isinstance(item, dict):
                continue
            ntype = str(item.get("class_type") or "")
            nodes.append({
                "id": str(nid), "type": ntype,
                "title": str(item.get("_meta", {}).get("title") or "")[:120],
                "mode": None,
            })
            inputs = item.get("inputs") or {}
            if not isinstance(inputs, dict):
                continue
            for value in inputs.values():
                if (isinstance(value, list) and len(value) >= 2
                        and isinstance(value[0], (str, int))):
                    deps.setdefault(str(nid), set()).add(str(value[0]))
                elif isinstance(value, dict):
                    # 少数节点用 {"node": id} 形式
                    src = value.get("node") or value.get("node_id")
                    if src is not None:
                        deps.setdefault(str(nid), set()).add(str(src))
    else:
        raise ValueError("无法识别工作流格式（需要 UI 的 nodes/links 或 API prompt）")
    return {"format": fmt, "nodes": nodes, "links": links, "deps": deps}


def _collect_model_strings(value, out, depth=0):
    if depth > 20:
        return
    if isinstance(value, str):
        low = value.lower()
        if len(value) <= 240 and any(low.endswith(ext) for ext in MODEL_EXTS):
            out.add(os.path.basename(value.replace("\\", "/")))
    elif isinstance(value, dict):
        for key, item in value.items():
            if str(key) in MODEL_KEYS and isinstance(item, str):
                out.add(os.path.basename(item.replace("\\", "/")))
            _collect_model_strings(item, out, depth + 1)
    elif isinstance(value, list):
        for item in value[:MAX_NODES]:
            _collect_model_strings(item, out, depth + 1)


def required_models(data):
    out = set()
    _collect_model_strings(data, out)
    return sorted(out, key=lambda x: x.lower())


def installed_model_names(model_payload=None):
    names = set()
    categories = (model_payload or {}).get("categories") or []
    for cat in categories:
        for item in cat.get("files") or []:
            name = os.path.basename(str(item.get("name") or ""))
            if name:
                names.add(name.casefold())
    return names


def _cycle_nodes(deps):
    """返回一组处于循环依赖中的节点 id；最多检查 2000 个节点。"""
    visiting = set()
    done = set()
    cycles = set()

    def visit(node, path):
        if node in visiting:
            cycles.update(path[path.index(node):] if node in path else [node])
            return
        if node in done:
            return
        visiting.add(node)
        for nxt in deps.get(node, ()):
            visit(nxt, path + [node])
        visiting.discard(node)
        done.add(node)

    for node in list(deps.keys())[:MAX_NODES]:
        visit(node, [])
    return sorted(cycles)


def check_workflow(data, object_info=None, model_payload=None):
    norm = normalize(data)
    nodes = norm["nodes"]
    node_ids = {n["id"] for n in nodes}
    known = set(object_info.keys()) if isinstance(object_info, dict) else None
    missing_nodes = []
    if known is not None:
        for node in nodes:
            ntype = node["type"]
            if not ntype or ntype in UI_SKIP_TYPES:
                continue
            if ntype not in known and ntype not in missing_nodes:
                missing_nodes.append(ntype)
    installed = installed_model_names(model_payload)
    required = required_models(data)
    missing_models = [m for m in required
                      if m.casefold() not in installed]
    broken_links = []
    for link in norm["links"]:
        if link["src"] and link["src"] not in node_ids:
            broken_links.append("连线 %s 的源节点 %s 不存在" %
                                (link["id"], link["src"]))
        if link["dst"] and link["dst"] not in node_ids:
            broken_links.append("连线 %s 的目标节点 %s 不存在" %
                                (link["id"], link["dst"]))
    for nid, srcs in norm["deps"].items():
        if nid not in node_ids:
            continue
        for src in srcs:
            if src not in node_ids:
                broken_links.append("节点 %s 依赖不存在的节点 %s" % (nid, src))
    cycles = _cycle_nodes(norm["deps"])
    warnings = []
    errors = []
    if not nodes:
        errors.append("工作流没有节点")
    if len(nodes) > MAX_NODES:
        errors.append("节点数量超过上限")
    if missing_nodes:
        warnings.append("缺少节点类型：%s" % ", ".join(missing_nodes[:8]))
    if missing_models:
        warnings.append("缺少模型文件：%s" % ", ".join(missing_models[:8]))
    if broken_links:
        warnings.append("断开的连线：%d 处" % len(broken_links))
    if cycles:
        warnings.append("可能存在循环依赖：%s" % ", ".join(cycles[:6]))
    if known is None:
        warnings.append("ComfyUI 不在线，节点类型未校验")
    level = "error" if errors else ("warn" if warnings else "ok")
    return {
        "level": level,
        "format": norm["format"],
        "node_count": len(nodes),
        "link_count": len(norm["links"]),
        "node_types": sorted({n["type"] for n in nodes if n["type"]}),
        "required_models": required,
        "missing_nodes": missing_nodes,
        "missing_models": missing_models,
        "broken_links": broken_links[:30],
        "cycles": cycles[:20],
        "errors": errors,
        "warnings": warnings,
        "checked_at": time.time(),
    }


def save_workflow(data, name="", filename="", by="", health=None):
    os.makedirs(WORKFLOW_DIR, exist_ok=True)
    wid = "wf_" + secrets.token_hex(6)
    meta = {
        "id": wid,
        "name": _clean_name(name or data.get("name") or filename),
        "filename": str(filename or "")[:180],
        "format": detect_format(data) or "unknown",
        "created": time.time(),
        "by": str(by or "")[:80],
        "size": _json_size(data),
        "health": health or {},
        "raw": data,
    }
    with _LOCK:
        tmp = _path(wid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(wid))
    return public_meta(meta)


def public_meta(meta):
    return {k: v for k, v in meta.items() if k != "raw"}


def load_workflow(wid, include_raw=False):
    path = _path(wid)
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except Exception:
        return None
    if include_raw:
        return meta
    return public_meta(meta)


def list_workflows():
    if not os.path.isdir(WORKFLOW_DIR):
        return []
    rows = []
    for fn in os.listdir(WORKFLOW_DIR):
        if not fn.endswith(".json") or fn.startswith("."):
            continue
        meta = load_workflow(fn[:-5])
        if meta:
            rows.append(meta)
    rows.sort(key=lambda x: x.get("created") or 0, reverse=True)
    return rows


def delete_workflow(wid):
    path = _path(wid)
    if not path or not os.path.isfile(path):
        raise ValueError("工作流不存在")
    os.remove(path)


def import_content(content, name="", filename="", by="", object_info=None,
                   model_payload=None):
    data = parse_workflow(content)
    health = check_workflow(data, object_info, model_payload)
    return save_workflow(data, name=name, filename=filename, by=by,
                         health=health)


def import_path(path, name="", by="", object_info=None,
                model_payload=None):
    path = os.path.abspath(str(path or ""))
    if not os.path.isfile(path):
        raise ValueError("工作流文件不存在")
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("工作流文件超过 8MB")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except Exception as exc:
        raise ValueError("读取工作流失败：%s" % exc)
    return import_content(content, name=name,
                          filename=os.path.basename(path), by=by,
                          object_info=object_info,
                          model_payload=model_payload)


def check_saved(wid, object_info=None, model_payload=None):
    meta = load_workflow(wid, include_raw=True)
    if not meta:
        raise ValueError("工作流不存在")
    health = check_workflow(meta.get("raw") or {}, object_info,
                            model_payload)
    meta["health"] = health
    with _LOCK:
        tmp = _path(wid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(wid))
    return public_meta(meta)


def check_all(object_info=None, model_payload=None):
    rows = []
    for meta in list_workflows():
        try:
            rows.append(check_saved(meta["id"], object_info, model_payload))
        except ValueError:
            continue
    summary = {"ok": 0, "warn": 0, "error": 0, "total": len(rows)}
    for item in rows:
        level = (item.get("health") or {}).get("level") or "warn"
        summary[level] = summary.get(level, 0) + 1
    return {"workflows": rows, "summary": summary}
