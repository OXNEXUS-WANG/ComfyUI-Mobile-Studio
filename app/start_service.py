# -*- coding: utf-8 -*-
"""CometInk 一键启动：ComfyUI + 手机网页服务，然后打开网页。

桌面快捷方式指向同目录的 一键启动.bat。
已经在运行的服务会跳过，不会重复开窗口。
"""
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import webbrowser
from collections import deque

ROOT = os.path.dirname(os.path.abspath(__file__))
# 系统 Python 的 PYTHONHOME/PYTHONPATH 会污染便携版解释器。
for _key in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONUSERBASE",
             "PIP_TARGET", "PIP_USER"):
    os.environ.pop(_key, None)
os.environ["PYTHONNOUSERSITE"] = "1"
# 便携版 python313._pth 不会自动把脚本目录加进 sys.path。
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import runtime_settings  # noqa: E402
from comfy_client import COMFY_BASE, COMFY_PORT  # noqa: E402

PY = os.path.join(ROOT, "python_embeded", "python.exe")
WEB_PORT = 8800
CERT_FILE = os.path.join(ROOT, "cert.pem")
KEY_FILE = os.path.join(ROOT, "key.pem")
WEB_SCHEME = "https" if (os.path.isfile(CERT_FILE) and
                         os.path.isfile(KEY_FILE)) else "http"
WEB_BASE = "%s://127.0.0.1:%d" % (WEB_SCHEME, WEB_PORT)
WEB_URL = WEB_BASE + "/"
COMFY_CHECK = COMFY_BASE + "/system_stats"


def log(msg):
    print(msg, flush=True)


def port_open(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.7)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def http_ok(url, timeout=1.5):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "starter"})
        ctx = ssl._create_unverified_context() if url.startswith("https://") else None
        if ctx is not None:
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        else:
            resp = urllib.request.urlopen(req, timeout=timeout)
        with resp:
            return 200 <= getattr(resp, "status", 200) < 500
    except Exception:
        return False


def proc_running(marker):
    """按命令行判断服务是否已经在启动/运行，避免重复启动。"""
    marker = marker.lower().replace("/", "\\")
    try:
        import psutil
    except Exception:
        return False
    me = os.getpid()
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            if p.info.get("pid") == me:
                continue
            cmd = " ".join(p.info.get("cmdline") or [])
            if marker in cmd.lower().replace("/", "\\"):
                return True
        except Exception:
            pass
    return False


def url_json(url, timeout=2.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "starter"})
        ctx = ssl._create_unverified_context() if url.startswith("https://") else None
        if ctx is not None:
            resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        else:
            resp = urllib.request.urlopen(req, timeout=timeout)
        with resp:
            raw = resp.read(65536)
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None


def web_is_ours():
    for base in (WEB_BASE, "http://127.0.0.1:%d" % WEB_PORT):
        data = url_json(base + "/api/session", timeout=2.0)
        if isinstance(data, dict) and "authed" in data and "need_login" in data:
            return True
    return False


def comfy_is_comfy():
    data = url_json(COMFY_CHECK, timeout=2.0)
    return isinstance(data, dict) and ("system" in data or "devices" in data)


def port_owner(port):
    try:
        import psutil
        for conn in psutil.net_connections(kind="inet"):
            try:
                if (conn.status == psutil.CONN_LISTEN and conn.laddr and
                        conn.laddr.port == port):
                    pid = conn.pid or 0
                    if not pid:
                        return {"pid": 0, "name": "unknown", "exe": "",
                                "cmdline": ""}
                    p = psutil.Process(pid)
                    try:
                        exe = p.exe()
                    except Exception:
                        exe = ""
                    try:
                        cmdline = " ".join(p.cmdline() or [])
                    except Exception:
                        cmdline = ""
                    return {"pid": pid, "name": p.name(), "exe": exe,
                            "cmdline": cmdline}
            except Exception:
                continue
    except Exception:
        pass
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], stderr=subprocess.DEVNULL)
        text = out.decode("mbcs", "replace")
        for line in text.splitlines():
            parts = line.split()
            if (len(parts) >= 5 and parts[0].upper() == "TCP" and
                    parts[1].endswith(":" + str(port)) and
                    parts[3].upper() == "LISTENING"):
                pid = int(parts[4])
                name = "unknown"
                exe = ""
                try:
                    import psutil
                    p = psutil.Process(pid)
                    name = p.name()
                    try:
                        exe = p.exe()
                    except Exception:
                        pass
                except Exception:
                    pass
                return {"pid": pid, "name": name, "exe": exe,
                        "cmdline": ""}
    except Exception:
        pass
    return None


def owner_is_ours(owner):
    if not owner:
        return False
    exe = os.path.normcase(os.path.abspath(owner.get("exe") or ""))
    root = os.path.normcase(os.path.abspath(ROOT))
    return bool(exe) and (exe == root or exe.startswith(root + os.sep))


def owner_text(owner):
    if not owner:
        return "未知程序"
    parts = ["%s (PID %s)" % (owner.get("name") or "unknown",
                              owner.get("pid") or "?")]
    if owner.get("exe"):
        parts.append(owner["exe"])
    if owner.get("cmdline"):
        parts.append(owner["cmdline"][:180])
    return "\n".join(parts)


def can_dialog():
    if "--no-browser" in sys.argv:
        return False
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def show_message(text, title="CometInk", error=False, yes_no=False):
    try:
        import ctypes
        flags = 0x40000  # MB_TOPMOST
        flags |= 0x10 if error else 0x40
        if yes_no:
            flags |= 0x04
        return ctypes.windll.user32.MessageBoxW(
            None, text, title, flags) == 6
    except Exception:
        print(text)
        return False


def check_port_conflicts():
    """启动前区分：本项目的旧实例、兼容的 ComfyUI、完全不认识的外部程序。"""
    comfy_open = port_open(COMFY_PORT)
    web_open = port_open(WEB_PORT)
    web_ours = web_is_ours() if web_open else False
    # 服务刚启动时端口已开但 /api/session 还没就绪，按命令行认作本项目的服务
    if web_open and not web_ours and proc_running("mobile_web.py"):
        web_ours = True
    comfy_ok = comfy_is_comfy() if comfy_open else False
    if comfy_open and not comfy_ok and proc_running(r"ComfyUI\main.py"):
        comfy_ok = True

    if web_open and not web_ours:
        owner = port_owner(WEB_PORT)
        text = ("端口 8800 被其他程序占用：\n%s\n\n"
                "CometInk 网页服务无法启动。请关闭占用 8800 的程序，"
                "或在它的设置里改端口后重试。" % owner_text(owner))
        log(text)
        if can_dialog():
            show_message(text, "CometInk · 端口冲突", error=True)
        return False

    if web_open and web_ours:
        owner = port_owner(WEB_PORT)
        if owner and owner.get("exe") and not owner_is_ours(owner):
            text = ("8800 端口上已经有一个 CometInk 实例，但不是当前目录：\n%s\n\n"
                    "请先关闭那个实例，再启动当前安装。" % owner_text(owner))
            log(text)
            if can_dialog():
                show_message(text, "CometInk · 实例冲突", error=True)
            return False

    if comfy_open and not comfy_ok:
        owner = port_owner(COMFY_PORT)
        text = ("端口 8188 被其他程序占用：\n%s\n\n"
                "ComfyUI 无法启动。请关闭占用 8188 的程序后重试。"
                % owner_text(owner))
        log(text)
        if can_dialog():
            show_message(text, "CometInk · ComfyUI 端口冲突", error=True)
        return False

    if comfy_open:
        owner = port_owner(COMFY_PORT)
        if owner and owner.get("exe") and not owner_is_ours(owner):
            text = ("检测到另一个 ComfyUI 正在 8188 运行：\n%s\n\n"
                    "将直接复用它，不会重复启动。如果它不是本安装目录的 ComfyUI，"
                    "可能缺少本项目的模型或自定义节点，出图会失败。\n\n"
                    "是否继续？" % owner_text(owner))
            log(text)
            if can_dialog() and not show_message(
                    text, "CometInk · 已有 ComfyUI", yes_no=True):
                return False
    return True


def spawn(args, env=None):
    """在新控制台里启动；最小化，任务栏可还原看日志，关掉窗口即停止。"""
    if env is None:
        env = os.environ.copy()
    # 新控制台不是 UTF-8 代码页，别把启动器的编码强加给服务进程
    env.pop("PYTHONIOENCODING", None)
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 6  # SW_MINIMIZE
    return subprocess.Popen(
        args,
        cwd=ROOT,
        env=env,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=si,
        close_fds=True,
    )


def wait_until(ok, seconds, label):
    t0 = time.time()
    last = 0.0
    while time.time() - t0 < seconds:
        if ok():
            log("      %s 已就绪（%.1f 秒）" % (label, time.time() - t0))
            return True
        now = time.time()
        if now - last > 4:
            log("      等待 %s … %.0f 秒" % (label, now - t0))
            last = now
        time.sleep(0.5)
    log("      %s 在 %d 秒内没有就绪。" % (label, seconds))
    return False


def _restart_log(line):
    try:
        folder = os.path.join(ROOT, "logs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "supervisor-%s.log" %
                            time.strftime("%Y-%m-%d"))
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except Exception:
        pass


def _start_comfy():
    env = os.environ.copy()
    env["PATH"] = (os.path.join(ROOT, "git", "cmd") + ";" +
                   os.path.join(ROOT, "git", "bin") + ";" +
                   env.get("PATH", ""))
    env["ARGOS_CHUNK_TYPE"] = "MINISBD"
    reserve = "0.8"
    try:
        import hardware_profile
        reserve = str(hardware_profile.limits().get("reserve_vram") or 0.8)
    except Exception:
        pass
    return spawn([
        PY, "-s", os.path.join("ComfyUI", "main.py"),
        "--windows-standalone-build",
        "--reserve-vram", reserve,
        "--preview-method", "auto",
    ], env)


def _start_web():
    return spawn([PY, "-s", "mobile_web.py"])


def supervise(comfy_child=None, web_child=None):
    """--watch：监控 8188/8800，崩溃后按设置自动重启。"""
    log("[4/4] 守护模式已开启：异常退出会自动重启（关闭本窗口即停止守护）。")
    history = {"comfy": deque(), "web": deque()}
    backoff = {"comfy": 5.0, "web": 5.0}
    next_try = {"comfy": 0.0, "web": 0.0}
    consecutive = {"comfy": 0, "web": 0}
    stable_since = {"comfy": time.time(), "web": time.time()}
    last_restart = {"comfy": 0.0, "web": 0.0}
    last_error = ""

    def alive(kind, child, port):
        # 先看端口：另一个实例已经接手时，即使旧子进程退出了也不能再启一个。
        if port_open(port):
            return True
        proc = child if child is not None else None
        if proc is not None:
            return proc.poll() is None
        # 没记录子进程时按命令行判断；进程在但端口未开 = 正在加载，不算崩溃。
        return proc_running("ComfyUI\\main.py" if kind == "comfy"
                            else "mobile_web.py")

    def can_restart(kind, settings):
        now = time.time()
        q = history[kind]
        while q and now - q[0] > 3600:
            q.popleft()
        return len(q) < int(settings.get("max_restarts_per_hour") or 6)

    def restart(kind, settings):
        nonlocal last_error
        now = time.time()
        if now < next_try[kind]:
            return None
        if not can_restart(kind, settings):
            last_error = "每小时重启次数已达上限"
            return None
        try:
            child = _start_comfy() if kind == "comfy" else _start_web()
        except Exception as exc:
            last_error = "重启 %s 失败：%s" % (kind, exc)
            _restart_log(last_error)
            next_try[kind] = now + backoff[kind]
            backoff[kind] = min(120.0, backoff[kind] * 2)
            return None
        history[kind].append(now)
        last_restart[kind] = now
        consecutive[kind] += 1
        next_try[kind] = now + backoff[kind]
        backoff[kind] = min(120.0, backoff[kind] * 2)
        last_error = ""
        _restart_log("已重启 %s（第 %d 次，进程 %s）" %
                     (kind, consecutive[kind], getattr(child, "pid", "?")))
        log("      [守护] 已重启 %s，进程 %s" %
            ("ComfyUI" if kind == "comfy" else "网页服务",
             getattr(child, "pid", "?")))
        return child

    while True:
        settings = runtime_settings.load()
        now = time.time()
        comfy_alive = alive("comfy", comfy_child, COMFY_PORT)
        web_alive = alive("web", web_child, WEB_PORT)

        # 连续稳定 5 分钟后重置退避，避免一次偶发崩溃长期影响。
        for kind, ok in (("comfy", comfy_alive), ("web", web_alive)):
            if ok:
                if now - stable_since[kind] > 300:
                    backoff[kind] = 5.0
                    consecutive[kind] = 0
            else:
                stable_since[kind] = now

        if settings.get("enabled", True):
            if not comfy_alive and settings.get("auto_restart_comfy", True):
                child = restart("comfy", settings)
                if child is not None:
                    comfy_child = child
            if not web_alive and settings.get("auto_restart_web", True):
                child = restart("web", settings)
                if child is not None:
                    web_child = child

        runtime_settings.write_status(
            running=True, enabled=bool(settings.get("enabled", True)),
            auto_restart_comfy=bool(settings.get("auto_restart_comfy", True)),
            auto_restart_web=bool(settings.get("auto_restart_web", True)),
            comfy_alive=bool(comfy_alive), web_alive=bool(web_alive),
            restarts_last_hour={
                "comfy": len(history["comfy"]),
                "web": len(history["web"]),
            },
            last_restart={
                "comfy": last_restart["comfy"],
                "web": last_restart["web"],
            },
            last_error=last_error, updated=time.time())

        time.sleep(max(2, int(settings.get("check_seconds") or 5)))


def main():
    os.chdir(ROOT)
    no_browser = "--no-browser" in sys.argv
    log("=" * 48)
    log("  CometInk · 一键启动")
    log("=" * 48)
    log("目录：%s" % ROOT)
    log("")

    if not check_port_conflicts():
        log("")
        log("启动已取消：请先处理上面的端口/程序冲突。")
        if not no_browser:
            input("按回车关闭…")
        return 2

    comfy_port = port_open(COMFY_PORT)
    web_port = port_open(WEB_PORT)
    comfy_proc = comfy_port or proc_running(r"ComfyUI\main.py")
    web_proc = web_port or proc_running("mobile_web.py")

    comfy_child = web_child = None

    # ---------- ComfyUI ----------
    if comfy_proc:
        log("[1/3] ComfyUI 已经在运行，跳过启动。")
    else:
        log("[1/3] 正在启动 ComfyUI …")
        comfy_child = _start_comfy()
        log("      已在新窗口启动（最小化）。")

    # ---------- 手机网页服务 ----------
    if web_proc:
        log("[2/3] CometInk 网页服务已经在运行，跳过启动。")
    else:
        log("[2/3] 正在启动 CometInk 网页服务 …")
        web_child = _start_web()
        log("      已在新窗口启动（最小化）。")

    # ---------- 等网页服务 ----------
    log("[3/3] 等待服务就绪 …")
    if not http_ok(WEB_BASE + "/api/session"):
        if not wait_until(lambda: http_ok(WEB_BASE + "/api/session"),
                          30, "网页服务"):
            log("")
            log("网页服务没有起来。请还原最小化的服务窗口查看报错，")
            log("或检查 8800 端口是否被别的程序占用。")
            if not no_browser:
                input("按回车关闭…")
            return 1
    else:
        log("      网页服务已就绪。")

    # ---------- 等 ComfyUI ----------
    if comfy_port or http_ok(COMFY_CHECK):
        log("      ComfyUI 已就绪。")
    else:
        if not wait_until(lambda: http_ok(COMFY_CHECK), 75, "ComfyUI"):
            log("      ComfyUI 还在加载；网页可以先打开，出图前请再稍等。")

    log("")
    log("启动完成，正在打开：%s" % WEB_URL)
    if not no_browser:
        try:
            webbrowser.open(WEB_URL)
        except Exception as exc:
            log("打开浏览器失败：%s" % exc)
            log("请手动打开 %s" % WEB_URL)
    time.sleep(0.8)
    if "--watch" in sys.argv:
        supervise(comfy_child, web_child)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        try:
            runtime_settings.write_status(running=False,
                                          updated=time.time())
        except Exception:
            pass
        sys.exit(130)
    except Exception as exc:
        print("启动失败：%s" % exc)
        input("按回车关闭…")
        sys.exit(1)
