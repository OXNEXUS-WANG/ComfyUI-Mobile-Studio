# -*- coding: utf-8 -*-
"""版本额度：普通分享版和商业版的账号数 / 算力节点数不同。

这里只读取 EDITION 文件，不检查授权码；商业版是否能启动由 license_guard 负责。
把额度集中在一个文件，方便以后按合同调整，不用在账号和 worker 代码里各写一套。
"""
from license_guard import edition

# 账号数包含管理员；只统计启用中的账号，停用/删除/过期游客会释放名额。
# 算力节点数统计 pending + approved，避免先占坑再审批绕过上限。
LIMITS = {
    "share": {
        "label": "分享版", "label_en": "Share edition",
        "max_accounts": 5,
        "max_workers": 2,
    },
    "commercial": {
        "label": "商业版", "label_en": "Commercial edition",
        "max_accounts": 50,
        "max_workers": 20,
    },
}


def policy():
    key = edition()
    out = dict(LIMITS.get(key) or LIMITS["share"])
    out["edition"] = key
    return out


def max_accounts():
    return int(policy().get("max_accounts") or 0)


def max_workers():
    return int(policy().get("max_workers") or 0)


def quota_message(kind="accounts"):
    p = policy()
    if kind == "accounts":
        return ("%s最多 %d 个启用账号（含管理员）。请先停用或删除账号，"
                "或升级商业版。" % (p["label"], p["max_accounts"]))
    return ("%s最多 %d 台算力节点。请先移除旧节点，"
            "或升级商业版。" % (p["label"], p["max_workers"]))
