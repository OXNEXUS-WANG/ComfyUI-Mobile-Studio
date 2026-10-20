# -*- coding: utf-8 -*-
"""一键体检报告：把诊断、环境、监控和脱敏日志打成 ZIP。

只负责排版和打包；采集数据由 app_core 完成。报告里不包含密码、
API Key、worker secret、提示词正文、图片或授权码原文。
"""
import html
import io
import json
import time
import zipfile

REPORT_VERSION = 1

_LEVEL_LABEL = {
    "ok": "通过", "info": "提示", "warn": "警告",
    "error": "错误", "critical": "严重",
}
_LEVEL_CLASS = {
    "ok": "ok", "info": "info", "warn": "warn",
    "error": "bad", "critical": "bad",
}


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _fmt_time(ts):
    try:
        ts = float(ts or 0)
    except Exception:
        return "—"
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _fmt_mb(value):
    try:
        mb = float(value or 0)
    except Exception:
        return "—"
    return ("%.1f GB" % (mb / 1024)) if mb >= 1024 else ("%.1f MB" % mb)


def _table(headers, rows):
    head = "".join("<th>%s</th>" % _esc(x) for x in headers)
    body = []
    for row in rows or []:
        body.append("<tr>%s</tr>" % "".join(
            "<td>%s</td>" % _esc(x) for x in row))
    if not body:
        body.append('<tr><td colspan="%d" class="muted">没有数据</td></tr>'
                    % len(headers))
    return ('<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            % (head, "".join(body)))


def _summary_text(data):
    diag = data.get("diagnostics") or {}
    summary = diag.get("summary") or {}
    health = data.get("health") or {}
    snap = data.get("snapshot") or {}
    lic = data.get("license") or {}
    lines = [
        "ComfyUI Mobile Studio · 一键体检报告",
        "生成时间：%s" % _fmt_time(data.get("generated") or time.time()),
        "版本：%s（%s）" % ((data.get("app") or {}).get("version") or "—",
                           (data.get("app") or {}).get("edition") or "—"),
        "健康评分：%s %s" % (health.get("score", "—"),
                             health.get("label", "")),
        "检查结果：通过 %s · 提示 %s · 警告 %s · 错误 %s" % (
            summary.get("ok", 0), summary.get("info", 0),
            summary.get("warn", 0), summary.get("error", 0)),
        "队列：运行 %s · 排队 %s" % (
            snap.get("running_count", 0), snap.get("queue_size", 0)),
        "磁盘剩余：%s GB" % snap.get("disk_free_gb", "—"),
        "授权：%s" % ("已激活" if lic.get("valid") else
                     ("分享版" if lic.get("commercial") is False
                      else lic.get("error") or "未激活")),
        "",
        "主要问题：",
    ]
    problems = [c for c in (diag.get("checks") or [])
                if c.get("level") in ("warn", "error", "critical")]
    if not problems:
        lines.append("  没有发现明显问题。")
    else:
        for c in problems[:20]:
            lines.append("  [%s] %s：%s %s" % (
                _LEVEL_LABEL.get(c.get("level"), c.get("level")),
                c.get("title") or c.get("id"), c.get("detail") or "",
                ("建议：" + c.get("hint")) if c.get("hint") else ""))
    lines.append("")
    lines.append("详细内容见 report.html / report.json；"
                 "报告不含密码、API Key、worker secret 或提示词正文。")
    return "\n".join(lines)


def _html_report(data):
    app = data.get("app") or {}
    diag = data.get("diagnostics") or {}
    summary = diag.get("summary") or {}
    health = data.get("health") or {}
    snap = data.get("snapshot") or {}
    storage = data.get("storage") or {}
    lic = data.get("license") or {}
    models = data.get("models") or {}
    workers = data.get("workers") or []
    jobs = data.get("jobs") or []
    alerts = data.get("alerts") or []
    logs = data.get("logs") or {}
    checks = diag.get("checks") or []

    check_rows = []
    for c in checks:
        check_rows.append([
            _LEVEL_LABEL.get(c.get("level"), c.get("level") or ""),
            c.get("title") or c.get("id") or "",
            c.get("detail") or "",
            c.get("hint") or "",
        ])

    model_rows = []
    for cat in models.get("categories") or []:
        model_rows.append([
            cat.get("label") or cat.get("key") or "",
            len(cat.get("files") or []),
            _fmt_mb((cat.get("bytes") or 0) / 1048576.0),
        ])

    worker_rows = []
    for w in workers:
        worker_rows.append([
            w.get("name") or w.get("id") or "",
            w.get("status") or "",
            "在线" if w.get("online") else "离线",
            w.get("gpu_util") if w.get("gpu_util") is not None else "—",
            w.get("vram_used_mb") if w.get("vram_used_mb") is not None else "—",
            w.get("gpu_temp_c") if w.get("gpu_temp_c") is not None else "—",
        ])

    job_rows = []
    for j in jobs:
        job_rows.append([
            j.get("job_id") or "",
            j.get("status") or "",
            j.get("model") or "",
            j.get("worker_name") or "",
            j.get("elapsed") or 0,
        ])

    alert_rows = []
    for a in alerts:
        alert_rows.append([
            a.get("severity") or "",
            a.get("title") or "",
            a.get("detail") or "",
            _fmt_time(a.get("last_seen")),
        ])

    env_rows = [
        ["操作系统", app.get("platform") or ""],
        ["Python", app.get("python") or ""],
        ["进程 PID", app.get("pid") or ""],
        ["启动时间", _fmt_time(app.get("started"))],
        ["CPU", "%s%% · %s 核" % (snap.get("cpu_percent", "—"),
                                  snap.get("cpu_count", "—"))],
        ["内存", "%s%%" % snap.get("ram_percent", "—")],
        ["GPU", snap.get("gpu_name") or "—"],
        ["显存", "%s / %s MB" % (snap.get("vram_used_mb", "—"),
                                snap.get("vram_total_mb", "—"))],
        ["GPU 温度", "%s °C" % snap.get("gpu_temp_c", "—")],
        ["ComfyUI", "在线" if snap.get("comfy_ready") else "离线"],
        ["ComfyUI 版本", diag.get("version") or "—"],
        ["图库", "%s 张 · %s" % (storage.get("total_images", 0),
                                _fmt_mb(storage.get("total_mb")))],
        ["磁盘剩余", "%s GB" % storage.get("free_gb", "—")],
        ["授权", ("已激活 · " + (lic.get("customer") or "") + " · 到期 " +
                  (_fmt_time(lic.get("expires")) if lic.get("expires")
                   else "永久")) if lic.get("valid") else
                 ("分享版" if lic.get("commercial") is False
                  else (lic.get("error") or "未激活"))],
        ["机器码", lic.get("machine_code") or "—"],
    ]

    cards = [
        ("健康评分", "%s · %s" % (health.get("score", "—"),
                                  health.get("label", ""))),
        ("检查", "通过 %s · 提示 %s · 警告 %s · 错误 %s" % (
            summary.get("ok", 0), summary.get("info", 0),
            summary.get("warn", 0), summary.get("error", 0))),
        ("队列", "运行 %s · 排队 %s" % (snap.get("running_count", 0),
                                       snap.get("queue_size", 0))),
        ("磁盘", "%s GB 可用" % storage.get("free_gb", "—")),
    ]
    card_html = "".join(
        '<div class="card"><div class="k">%s</div><div class="v">%s</div></div>'
        % (_esc(k), _esc(v)) for k, v in cards)

    activity = "\n".join(str(x) for x in (logs.get("activity") or []))
    security = "\n".join(str(x) for x in (logs.get("security") or []))
    problems = [c for c in checks
                if c.get("level") in ("warn", "error", "critical")]
    problem_html = "".join(
        '<li><b>[%s]</b> %s：%s %s</li>' % (
            _esc(_LEVEL_LABEL.get(c.get("level"), c.get("level"))),
            _esc(c.get("title")), _esc(c.get("detail")),
            ("<span class='muted'>建议：%s</span>" % _esc(c.get("hint")))
            if c.get("hint") else "")
        for c in problems) or "<li>没有发现明显问题。</li>"

    return """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>体检报告 · ComfyUI Mobile Studio</title>
<style>
body{margin:0;background:#0a0e16;color:#e8f2fb;font:14px/1.65 "Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:24px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 10px;color:#8fe6ff}
.muted{color:#7f91a8} .sub{color:#93a4ba;font-size:12px;margin-bottom:18px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.card{padding:12px 14px;border:1px solid rgba(127,227,255,.15);border-radius:10px;
background:rgba(255,255,255,.03)}
.card .k{color:#7f91a8;font-size:11px;text-transform:uppercase;letter-spacing:.08em}
.card .v{font-size:16px;font-weight:700;margin-top:3px}
table{width:100%%;border-collapse:collapse;font-size:12px}
th,td{padding:7px 9px;border-bottom:1px solid rgba(255,255,255,.07);text-align:left;vertical-align:top}
th{color:#8fe6ff;font-weight:600;background:rgba(70,170,255,.06)}
pre{white-space:pre-wrap;word-break:break-word;background:#080f1b;border:1px solid rgba(255,255,255,.08);
border-radius:8px;padding:10px;font:11px/1.5 Consolas,monospace;max-height:420px;overflow:auto}
ul{margin:6px 0 0;padding-left:20px} li{margin:5px 0}
.note{margin-top:18px;padding:10px 12px;border:1px dashed rgba(255,190,110,.35);
border-radius:8px;color:#ffd18a;font-size:12px}
</style></head><body><div class="wrap">
<h1>ComfyUI Mobile Studio · 体检报告</h1>
<div class="sub">生成时间：%s · 版本 %s（%s）· 报告格式 v%s</div>
<div class="cards">%s</div>
<h2>需要关注</h2><ul>%s</ul>
<h2>检查明细</h2>%s
<h2>运行环境</h2>%s
<h2>模型分类</h2>%s
<h2>算力节点</h2>%s
<h2>最近任务</h2>%s
<h2>当前告警</h2>%s
<h2>用户活动日志（最后 %s 条）</h2><pre>%s</pre>
<h2>安全日志（最后 %s 条）</h2><pre>%s</pre>
<div class="note">本报告用于维护排查，不含密码、API Key、worker secret、授权码原文、
提示词正文或图片。日志中的 IP 和用户名仅管理员可见。</div>
</div></body></html>""" % (
        _fmt_time(data.get("generated") or time.time()),
        _esc(app.get("version") or "—"), _esc(app.get("edition") or "—"),
        REPORT_VERSION, card_html, problem_html,
        _table(["级别", "检查项", "结果", "建议"], check_rows),
        _table(["项目", "值"], env_rows),
        _table(["分类", "文件数", "占用"], model_rows),
        _table(["节点", "状态", "在线", "GPU %", "显存 MB", "温度 °C"],
               worker_rows),
        _table(["任务", "状态", "模型", "节点", "耗时 秒"], job_rows),
        _table(["级别", "告警", "详情", "最近时间"], alert_rows),
        len(logs.get("activity") or []), _esc(activity),
        len(logs.get("security") or []), _esc(security),
    )


def build_zip(data, logs=None):
    """返回报告 ZIP 的 bytes。logs 可传 {'activity': [...], 'security': [...]}。"""
    data = dict(data or {})
    if logs:
        data["logs"] = logs
    data.setdefault("generated", time.time())
    data["report_version"] = REPORT_VERSION
    payload = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    html_text = _html_report(data)
    summary = _summary_text(data)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED,
                         allowZip64=True) as zf:
        zf.writestr("report.html", html_text)
        zf.writestr("report.json", payload)
        zf.writestr("summary.txt", summary)
        for key, name in (("activity", "logs/activity.log"),
                          ("security", "logs/security.log")):
            lines = (data.get("logs") or {}).get(key) or []
            zf.writestr(name, "\n".join(str(x) for x in lines) + "\n")
    return buf.getvalue()
