# -*- coding: utf-8 -*-
"""手机出图一键启动：ComfyUI + 手机网页服务，然后打开网页。

桌面快捷方式指向同目录的 一键启动.bat。
已经在运行的服务会跳过，不会重复开窗口。
"""
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, "python_embeded", "python.exe")
WEB_PORT = 8800
COMFY_PORT = 8188
CERT_FILE = os.path.join(ROOT, "cert.pem")
KEY_FILE = os.path.join(ROOT, "key.pem")
WEB_SCHEME = "https" if (os.path.isfile(CERT_FILE) and
                         os.path.isfile(KEY_FILE)) else "http"
WEB_BASE = "%s://127.0.0.1:%d" % (WEB_SCHEME, WEB_PORT)
WEB_URL = WEB_BASE + "/"
COMFY_CHECK = "http://127.0.0.1:8188/system_stats"


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


def main():
    os.chdir(ROOT)
    no_browser = "--no-browser" in sys.argv
    log("=" * 48)
    log("  手机出图 · 一键启动")
    log("=" * 48)
    log("目录：%s" % ROOT)
    log("")

    comfy_port = port_open(COMFY_PORT)
    web_port = port_open(WEB_PORT)
    comfy_proc = comfy_port or proc_running(r"ComfyUI\main.py")
    web_proc = web_port or proc_running("mobile_web.py")

    # ---------- ComfyUI ----------
    if comfy_proc:
        log("[1/3] ComfyUI 已经在运行，跳过启动。")
    else:
        log("[1/3] 正在启动 ComfyUI …")
        env = os.environ.copy()
        env["PATH"] = (os.path.join(ROOT, "git", "cmd") + ";" +
                       os.path.join(ROOT, "git", "bin") + ";" +
                       env.get("PATH", ""))
        env["ARGOS_CHUNK_TYPE"] = "MINISBD"
        spawn([
            PY, "-s", os.path.join("ComfyUI", "main.py"),
            "--windows-standalone-build",
            "--reserve-vram", "0.8",
            "--preview-method", "auto",
        ], env)
        log("      已在新窗口启动（最小化）。")

    # ---------- 手机网页服务 ----------
    if web_proc:
        log("[2/3] 手机出图网页服务已经在运行，跳过启动。")
    else:
        log("[2/3] 正在启动手机出图网页服务 …")
        spawn([PY, "-s", "mobile_web.py"])
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
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print("启动失败：%s" % exc)
        input("按回车关闭…")
        sys.exit(1)
