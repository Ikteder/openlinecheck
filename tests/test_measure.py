"""All tests run against mocks or 127.0.0.1, never the public Internet."""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest
from urllib.parse import parse_qs, urlsplit

from linecheck.cli import main
from linecheck.measure import _percentile, measure_https_latency, measure_transfer, run_speed_test, validate_origin


class TestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.path != "/__down":
            self.send_error(404)
            return
        size = int(parse_qs(uri.query).get("bytes", [0])[0])
        if size < 0 or size > 10_000_000:
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        remaining = size
        while remaining:
            block = b"Z" * min(remaining, 65_536)
            self.wfile.write(block)
            remaining -= len(block)

    def do_POST(self):
        if self.path != "/__up":
            self.send_error(404)
            return
        remaining = int(self.headers.get("Content-Length", "0"))
        while remaining:
            block = self.rfile.read(min(remaining, 65_536))
            if not block:
                self.send_error(400)
                return
            remaining -= len(block)
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        pass


@contextmanager
def local_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


class Tests(unittest.TestCase):
    def test_origin_validation(self):
        self.assertEqual(validate_origin("https://example.org/"), "https://example.org")
        for value in ("ftp://example.org", "example.org", "https://user:pass@example.org", "https://example.org/private"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_origin(value)

    def test_percentile(self):
        self.assertIsNone(_percentile([], 0.95))
        self.assertEqual(_percentile([1, 2, 3, 4, 5], .5), 3)
        self.assertAlmostEqual(_percentile([10, 20, 30], .95), 29)

    def test_local_http_probe(self):
        with local_server() as origin:
            probe = measure_https_latency(origin, attempts=3)
            self.assertEqual(probe.successful, 3)
            self.assertIsNotNone(probe.median_ms)
            self.assertEqual(probe.failed_probe_percent, 0)

    def test_local_transfer(self):
        with local_server() as origin:
            download = measure_transfer(origin, "download", "quick")
            upload = measure_transfer(origin, "upload", "quick")
            self.assertEqual(download.failed_requests, 0)
            self.assertEqual(upload.failed_requests, 0)
            self.assertEqual(download.bytes_transferred, 4_512_000)
            self.assertEqual(upload.bytes_transferred, 2_256_000)
            self.assertGreater(download.mbps or 0, 0)
            self.assertGreater(upload.mbps or 0, 0)

    def test_result_shape(self):
        with local_server() as origin:
            record = run_speed_test(origin, "quick", attempts=2, no_upload=True).as_dict()
            self.assertIsNone(record["upload"])
            self.assertEqual(record["profile"], "quick")
            self.assertIn("latency", record)
            self.assertIn("download", record)


if __name__ == "__main__":
    unittest.main()
