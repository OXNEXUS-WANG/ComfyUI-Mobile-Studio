# -*- coding: utf-8 -*-
"""模型下载器的重试、断点续传和大小校验测试（本地 mock HTTP，不联网）。"""
import hashlib
import json
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from _common import ROOT

sys.path.insert(0, str(ROOT / "installer"))
import download_models  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    payload = b"0123456789abcdef" * 64
    hits = 0
    mode = "ok"

    def do_GET(self):
        cls = type(self)
        cls.hits += 1
        if cls.mode == "retry" and cls.hits <= 2:
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        start = 0
        rng = self.headers.get("Range") or ""
        if rng.startswith("bytes="):
            try:
                start = int(rng.split("=", 1)[1].split("-", 1)[0])
            except ValueError:
                start = 0
        body = cls.payload[start:]
        if start:
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (
                start, len(cls.payload) - 1, len(cls.payload)))
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DownloadModelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.url = "http://127.0.0.1:%d/model.bin" % cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        _Handler.hits = 0
        _Handler.mode = "ok"
        self.td = tempfile.TemporaryDirectory()
        self.dest = Path(self.td.name) / "model.bin"

    def tearDown(self):
        self.td.cleanup()

    def test_retry_after_429_then_success(self):
        _Handler.mode = "retry"
        started = time.time()
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "retry")
        self.assertTrue(ok)
        self.assertGreaterEqual(time.time() - started, 1.8)
        self.assertEqual(self.dest.read_bytes(), _Handler.payload)
        self.assertEqual(_Handler.hits, 3)

    def test_resume_from_part_file(self):
        part = Path(str(self.dest) + ".part")
        part.write_bytes(_Handler.payload[:100])
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "resume")
        self.assertTrue(ok)
        self.assertEqual(self.dest.read_bytes(), _Handler.payload)
        self.assertFalse(part.exists())

    def test_wrong_size_is_backed_up_and_repaired(self):
        self.dest.write_bytes(b"short")
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "size")
        self.assertTrue(ok)
        self.assertEqual(self.dest.stat().st_size, len(_Handler.payload))
        self.assertEqual(self.dest.read_bytes(), _Handler.payload)
        backups = list(self.dest.parent.glob("model.bin.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"short")

    def test_existing_complete_file_is_skipped(self):
        self.dest.write_bytes(_Handler.payload)
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "skip")
        self.assertTrue(ok)
        self.assertEqual(_Handler.hits, 0)

    def test_sha256_is_verified(self):
        sha = hashlib.sha256(_Handler.payload).hexdigest()
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "sha", sha)
        self.assertTrue(ok)
        self.assertEqual(self.dest.read_bytes(), _Handler.payload)

    def test_sha256_mismatch_is_rejected(self):
        ok = download_models.download_one(
            [self.url, self.url], self.dest, len(_Handler.payload), "bad",
            "0" * 64)
        self.assertFalse(ok)
        self.assertFalse(self.dest.exists())
        self.assertFalse(Path(str(self.dest) + ".part").exists())

    def test_existing_file_with_wrong_sha_is_redownloaded(self):
        self.dest.write_bytes(b"x" * len(_Handler.payload))
        sha = hashlib.sha256(_Handler.payload).hexdigest()
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "fix", sha)
        self.assertTrue(ok)
        self.assertEqual(self.dest.read_bytes(), _Handler.payload)
        backups = list(self.dest.parent.glob("model.bin.bak-*"))
        self.assertEqual(len(backups), 1)

    def test_build_urls_prefers_modelscope(self):
        f = {
            "repo": "org/repo", "path": "a/b.bin", "revision": "abc",
            "modelscope_repo": "ms/repo", "modelscope_revision": "def",
        }
        urls = download_models.build_urls(f)
        self.assertEqual(
            urls[0],
            "https://modelscope.cn/models/ms/repo/resolve/def/a/b.bin"
            "?download=true")
        self.assertTrue(urls[1].startswith(download_models.HF_MIRROR))
        plain = download_models.build_urls(f, use_modelscope=False)
        self.assertFalse(any("modelscope.cn" in u for u in plain))

    def test_manifest_pins_modelscope_and_sha256(self):
        manifest = json.loads(
            (ROOT / "installer" / "models_manifest.json").read_text(
                encoding="utf-8"))
        for key in manifest["default_packs"]:
            for f in manifest["packs"][key]["files"]:
                self.assertTrue(f.get("modelscope_repo"), f["path"])
                self.assertEqual(len(f.get("sha256") or ""), 64, f["path"])
        for pack in manifest["packs"].values():
            for f in pack["files"]:
                if f.get("modelscope_repo"):
                    self.assertEqual(len(f.get("sha256") or ""), 64,
                                     f["path"])


if __name__ == "__main__":
    unittest.main()
