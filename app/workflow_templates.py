# -*- coding: utf-8 -*-
"""ComfyUI 基础工作流模板。

模板只描述“稳定的骨架”（加载器、采样器、保存节点和连线），
Python 构建器负责可选分支（LoRA、PAG、高清修复、重绘、翻译）。
这样节点 ID / class_type 不再散落在业务代码里。
"""
import copy
import json
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "workflow_templates.json")
_CACHE = None


def _load():
    global _CACHE
    if _CACHE is None:
        with open(_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        _CACHE = data if isinstance(data, dict) else {}
    return _CACHE


def names():
    return sorted(_load().keys())


def template(name):
    """返回模板的深拷贝，调用方可以安全地增删节点。"""
    data = _load().get(str(name))
    if not isinstance(data, dict):
        raise KeyError("未知工作流模板: %s" % name)
    return copy.deepcopy(data)


def _fill(value, mapping):
    if isinstance(value, dict):
        return {k: _fill(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, mapping) for v in value]
    if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
        key = value[2:-2]
        if key not in mapping:
            raise KeyError("工作流模板缺少参数: %s" % key)
        return mapping[key]
    return value


def build(name, **mapping):
    """取模板并替换 {{参数}}；替换值保留 int/float/list 类型。"""
    return _fill(template(name), mapping)
