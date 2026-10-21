# -*- coding: utf-8 -*-
"""模型下载器的重试、断点续传和大小校验测试（本地 mock HTTP，不联网）。"""
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

    def test_wrong_size_is_rejected_and_repair_on_retry(self):
        self.dest.write_bytes(b"short")
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "size")
        self.assertTrue(ok)
        self.assertEqual(self.dest.stat().st_size, len(_Handler.payload))
        self.assertEqual(self.dest.read_bytes(), _Handler.payload)

    def test_existing_complete_file_is_skipped(self):
        self.dest.write_bytes(_Handler.payload)
        ok = download_models.download_one(
            [self.url], self.dest, len(_Handler.payload), "skip")
        self.assertTrue(ok)
        self.assertEqual(_Handler.hits, 0)


if __name__ == "__main__":
    unittest.main()
