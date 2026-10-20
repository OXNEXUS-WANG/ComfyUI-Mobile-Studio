#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""没有第二台机器时的 worker 近似验收。

用独立 worker 进程 + 本机 TCP 延迟代理连接真实 ComfyUI，模拟局域网延迟。
需要服务正在运行，并设置 MGS_TEST_PASSWORD。会提交一张 512x512 测试图，
跑完自动删除图片、节点和临时文件；不会修改本机接单设置以外的配置。
"""
import json
import os
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _common import ROOT  # noqa: E402

BASE = os.environ.get("MGS_TEST_URL", "https://127.0.0.1:8800").rstrip("/")
USER = os.environ.get("MGS_TEST_USER", "admin")
PASSWORD = os.environ.get("MGS_TEST_PASSWORD", "")
CTX = ssl._create_unverified_context()
PROXY_PORT = int(os.environ.get("MGS_WORKER_SIM_PORT", "18188"))
DELAY = float(os.environ.get("MGS_WORKER_SIM_DELAY", "0.02"))


def api(path, payload=None, cookie="", method=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(BASE + path, data=body, headers=headers,
                                 method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=30) as resp:
            return resp.status, resp.read(), resp.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Set-Cookie", "")


class Proxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            up = socket.create_connection(("127.0.0.1", 8188), timeout=5)
        except OSError:
            return

        def pump(src, dst):
            try:
                while True:
                    data = src.recv(65536)
                    if not data:
                        break
                    if DELAY:
                        time.sleep(DELAY)
                    dst.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    dst.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t = threading.Thread(target=pump, args=(up, self.request), daemon=True)
        t.start()
        pump(self.request, up)
        t.join(timeout=2)
        try:
            up.close()
        except OSError:
            pass


def wait_status(jid, cookie, timeout=240):
    end = time.time() + timeout
    last = ""
    while time.time() < end:
        status, raw, _ = api("/api/status/" + jid, cookie=cookie)
        if status != 200:
            time.sleep(2)
            continue
        st = json.loads(raw)
        cur = "%s %s" % (st.get("status"), st.get("progress", {}).get("value"))
        if cur != last:
            print("  ", cur)
            last = cur
        if st.get("status") in ("done", "error"):
            return st
        time.sleep(2)
    raise TimeoutError("job timeout: %s" % jid)


def main():
    if not PASSWORD:
        print("请先设置 MGS_TEST_PASSWORD；这个测试会提交一张真实图片。")
        return 2
    status, raw, cookie_hdr = api(
        "/api/login", {"username": USER, "password": PASSWORD})
    if status != 200:
        print("登录失败：HTTP %s" % status)
        return 2
    cookie = cookie_hdr.split(";", 1)[0]
    proxy = Proxy(("127.0.0.1", PROXY_PORT), ProxyHandler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    tmp = Path(tempfile.mkdtemp(prefix="_worker_sim_", dir=str(ROOT)))
    cfg = tmp / "worker_agent.json"
    worker = None
    wid = ""
    jid = ""
    try:
        status, raw, _ = api("/api/workers", {"action": "join_code"},
                             cookie=cookie)
        if status != 200:
            raise RuntimeError("join_code: HTTP %s %s" % (status, raw[:200]))
        code = json.loads(raw)["code"]
        cmd = [sys.executable, str(ROOT / "worker" / "worker_agent.py"),
               "join", "--server", BASE, "--code", code,
               "--name", "LAN sim", "--comfy",
               "http://127.0.0.1:%d" % PROXY_PORT,
               "--insecure", "--config", str(cfg), "--force"]
        subprocess.run(cmd, check=True, timeout=60,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        status, raw, _ = api("/api/workers", cookie=cookie)
        workers = json.loads(raw).get("workers") or []
        w = next((x for x in workers if x.get("name") == "LAN sim"), None)
        if not w:
            raise RuntimeError("worker did not register")
        wid = w["id"]
        status, raw, _ = api("/api/workers", {
            "action": "approve", "id": wid, "owner_id": "admin",
            "trusted": True, "allowed_users": ["admin"]}, cookie=cookie)
        if status != 200:
            raise RuntimeError("approve: HTTP %s %s" % (status, raw[:200]))
        api("/api/workers", {"action": "settings", "remote_enabled": True,
                             "local_enabled": False}, cookie=cookie)
        worker = subprocess.Popen(
            [sys.executable, str(ROOT / "worker" / "worker_agent.py"),
             "run", "--config", str(cfg), "--no-control"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        # 等节点在线且 ComfyUI 可用
        deadline = time.time() + 90
        online = False
        while time.time() < deadline:
            status, raw, _ = api("/api/workers", cookie=cookie)
            w = next((x for x in json.loads(raw).get("workers") or []
                      if x.get("id") == wid), None)
            if w and w.get("online") and w.get("comfy_ready"):
                online = True
                break
            time.sleep(2)
        if not online:
            raise RuntimeError("worker did not become online")
        status, raw, _ = api("/api/generate", {
            "prompt": "1girl, simple background, soft light, low saturation",
            "model": "Counterfeit-V2.5_pruned.safetensors",
            "size": "512x512", "steps": 4, "count": 1, "seed": 123456,
        }, cookie=cookie)
        if status != 200:
            raise RuntimeError("generate: HTTP %s %s" % (status, raw[:300]))
        jid = json.loads(raw)["job_id"]
        st = wait_status(jid, cookie)
        print("result:", st.get("status"), st.get("worker_kind"),
              st.get("worker_name"), st.get("images"), st.get("error"))
        if st.get("status") != "done" or st.get("worker_kind") != "remote":
            raise RuntimeError("worker simulation failed")
        for name in st.get("images") or []:
            api("/api/delete", {"names": [name]}, cookie=cookie)
        return 0
    finally:
        if worker:
            worker.terminate()
            try:
                worker.wait(timeout=15)
            except subprocess.TimeoutExpired:
                worker.kill()
        if wid:
            try:
                api("/api/workers", {"action": "remove", "id": wid},
                    cookie=cookie)
            except Exception:
                pass
        try:
            api("/api/workers", {"action": "settings", "remote_enabled": False,
                                 "local_enabled": True}, cookie=cookie)
        except Exception:
            pass
        proxy.shutdown()
        proxy.server_close()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
