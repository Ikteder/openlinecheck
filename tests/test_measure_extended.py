"""Extended offline tests for measurement correctness.

All tests run against mocks or 127.0.0.1, never the public Internet.
Covers: cancellation, HTTP errors, partial downloads, invalid origins,
payload bounds, compression handling, and data caps.
"""
from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

from linecheck.errors import CancelledError
from linecheck.measure import (
    CancelledError as MeasureCancelledError,
    _check_cancel,
    _down_url,
    _percentile,
    _request_download,
    _request_upload,
    measure_https_latency,
    measure_transfer,
    run_speed_test,
    validate_origin,
    MAX_TOTAL_DOWNLOAD_BYTES,
    MAX_TOTAL_UPLOAD_BYTES,
)


# ---------------------------------------------------------------------------
# Mock handlers
# ---------------------------------------------------------------------------

class SlowHandler(BaseHTTPRequestHandler):
    """Adds a small delay to each request to allow cancellation testing."""
    def do_GET(self):
        import time
        time.sleep(0.15)  # small delay so cancellation can fire between probes
        uri = urlsplit(self.path)
        if uri.path != "/__down":
            self.send_error(404)
            return
        size = int(parse_qs(uri.query).get("bytes", [0])[0])
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        # Send data if requested
        if size > 0:
            remaining = size
            while remaining:
                block = b"Z" * min(remaining, 65_536)
                self.wfile.write(block)
                remaining -= len(block)

    def do_POST(self):
        import time
        time.sleep(0.15)
        length = int(self.headers.get("Content-Length", "0"))
        remaining = length
        while remaining:
            block = self.rfile.read(min(remaining, 65_536))
            if not block:
                break
            remaining -= len(block)
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class RefuseUploadHandler(BaseHTTPRequestHandler):
    """Returns 403 for uploads."""
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.path != "/__down":
            self.send_error(404)
            return
        size = int(parse_qs(uri.query).get("bytes", [0])[0])
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        remaining = size
        while remaining:
            block = b"Z" * min(remaining, 65_536)
            self.wfile.write(block)
            remaining -= len(block)

    def do_POST(self):
        import time
        # Read the body first (to avoid broken pipe)
        length = int(self.headers.get("Content-Length", "0"))
        remaining = length
        while remaining:
            block = self.rfile.read(min(remaining, 65_536))
            if not block:
                break
            remaining -= len(block)
        time.sleep(0.5)  # small delay so cancel can fire
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class PartialDownloadHandler(BaseHTTPRequestHandler):
    """Sends fewer bytes than requested."""
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.path != "/__down":
            self.send_error(404)
            return
        size = int(parse_qs(uri.query).get("bytes", [0])[0])
        # Send only half
        actual = size // 2
        self.send_response(200)
        self.send_header("Content-Length", str(actual))
        self.end_headers()
        remaining = actual
        while remaining:
            block = b"Z" * min(remaining, 65_536)
            self.wfile.write(block)
            remaining -= len(block)

    def do_POST(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class CompressionHandler(BaseHTTPRequestHandler):
    """Sends gzip-encoded data (should be rejected by Accept-Encoding: identity)."""
    def do_GET(self):
        uri = urlsplit(self.path)
        if uri.path != "/__down":
            self.send_error(404)
            return
        size = int(parse_qs(uri.query).get("bytes", [0])[0])
        import gzip
        data = gzip.compress(b"Z" * size)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


class NotFoundHandler(BaseHTTPRequestHandler):
    """Returns 404 for all requests."""
    def do_GET(self):
        self.send_error(404)

    def do_POST(self):
        self.send_error(404)

    def log_message(self, *a):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@contextmanager
def _server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidation(unittest.TestCase):
    def test_valid_origins(self):
        self.assertEqual(validate_origin("https://speed.cloudflare.com"), "https://speed.cloudflare.com")
        self.assertEqual(validate_origin("http://127.0.0.1:8765"), "http://127.0.0.1:8765")
        self.assertEqual(validate_origin("https://example.org/"), "https://example.org")

    def test_invalid_origins(self):
        invalid = [
            "ftp://example.org",
            "example.org",
            "https://user:pass@example.org",
            "https://example.org/private",
            "https://example.org?query=1",
            "https://example.org#fragment",
            "",
            "not a url",
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_origin(value)


class TestPayloadBounds(unittest.TestCase):
    def test_negative_download_size(self):
        with self.assertRaises(ValueError):
            _request_download("http://127.0.0.1", -1, timeout=1)

    def test_huge_download_size(self):
        with self.assertRaises(ValueError):
            _request_download("http://127.0.0.1", MAX_TOTAL_DOWNLOAD_BYTES + 1, timeout=1)

    def test_negative_upload_size(self):
        with self.assertRaises(ValueError):
            _request_upload("http://127.0.0.1", -1, timeout=1)

    def test_huge_upload_size(self):
        with self.assertRaises(ValueError):
            _request_upload("http://127.0.0.1", MAX_TOTAL_UPLOAD_BYTES + 1, timeout=1)


class TestCancellation(unittest.TestCase):
    def test_cancel_before_request(self):
        """Cancellation is detected before the HTTP request is sent."""
        cancelled = [True]  # already cancelled
        with self.assertRaises(MeasureCancelledError):
            _request_download("http://127.0.0.1", 1000, timeout=1, cancel=lambda: cancelled[0])

    def test_cancel_before_upload(self):
        """Cancellation is detected before upload request is sent."""
        cancelled = [True]
        with self.assertRaises(MeasureCancelledError):
            _request_upload("http://127.0.0.1", 1000, timeout=1, cancel=lambda: cancelled[0])

    def test_cancel_during_latency(self):
        """Cancellation returns partial latency results."""
        with _server(SlowHandler) as origin:
            cancelled = [False]
            def cancel():
                return cancelled[0]
            # Cancel after a couple of probes complete
            def trigger_cancel():
                import time
                time.sleep(0.5)
                cancelled[0] = True
            t = threading.Thread(target=trigger_cancel, daemon=True)
            t.start()
            # Use many probes so some are cancelled
            probe = measure_https_latency(origin, attempts=20, timeout=2, cancel=cancel)
            t.join(timeout=3)
            # Should have some successful probes (the ones that completed before cancel)
            self.assertGreater(probe.successful, 0)
            # And some failed (the ones cancelled or timed out)
            self.assertGreater(probe.failed_probe_percent, 0)

    def test_cancel_during_full_test(self):
        """Cancellation stops a full speed test."""
        with _server(SlowHandler) as origin:
            cancelled = [False]
            def cancel():
                return cancelled[0]
            def trigger_cancel():
                import time
                time.sleep(0.3)
                cancelled[0] = True
            t = threading.Thread(target=trigger_cancel, daemon=True)
            t.start()
            with self.assertRaises(MeasureCancelledError):
                run_speed_test(origin, "quick", cancel=cancel)
            t.join(timeout=3)

    def test_cancel_during_transfer_stage(self):
        """Cancellation stops a transfer stage."""
        with _server(SlowHandler) as origin:
            cancelled = [False]
            def cancel():
                return cancelled[0]
            def trigger_cancel():
                import time
                time.sleep(0.3)
                cancelled[0] = True
            t = threading.Thread(target=trigger_cancel, daemon=True)
            t.start()
            with self.assertRaises(MeasureCancelledError):
                measure_transfer(origin, "download", "quick", timeout=2, cancel=cancel)
            t.join(timeout=3)


class TestHTTPErrorHandling(unittest.TestCase):
    def test_404_server(self):
        with _server(NotFoundHandler) as origin:
            probe = measure_https_latency(origin, attempts=2)
            self.assertEqual(probe.successful, 0)
            self.assertIsNone(probe.median_ms)
            self.assertEqual(probe.failed_probe_percent, 100.0)

    def test_upload_refused_403(self):
        with _server(RefuseUploadHandler) as origin:
            upload = measure_transfer(origin, "upload", "quick")
            self.assertIsNone(upload.mbps)
            self.assertGreater(upload.failed_requests, 0)

    def test_partial_download(self):
        """Server sends fewer bytes than requested — should fail gracefully."""
        with _server(PartialDownloadHandler) as origin:
            download = measure_transfer(origin, "download", "quick")
            # Partial download should cause stage failure
            self.assertGreater(download.failed_requests, 0)

    def test_compression_rejected(self):
        """Server sends gzip data; Accept-Encoding: identity should cause mismatch."""
        with _server(CompressionHandler) as origin:
            download = measure_transfer(origin, "download", "quick")
            # Compression should cause byte count mismatch or HTTP error
            self.assertGreater(download.failed_requests, 0)


class TestDataCap(unittest.TestCase):
    def test_download_cap_enforced(self):
        """Total download should not exceed MAX_TOTAL_DOWNLOAD_BYTES."""
        with _server(SlowHandler) as origin:
            # Use a very small cap to test
            result = measure_transfer(
                origin, "download", "quick", timeout=0.5, total_cap=100
            )
            self.assertLessEqual(result.bytes_transferred, 100)

    def test_upload_cap_enforced(self):
        """Total upload should not exceed MAX_TOTAL_UPLOAD_BYTES."""
        with _server(RefuseUploadHandler) as origin:
            result = measure_transfer(
                origin, "upload", "standard", timeout=0.5, total_cap=100
            )
            self.assertLessEqual(result.bytes_transferred, 100)


class TestPercentile(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(_percentile([], 0.95))

    def test_single(self):
        self.assertEqual(_percentile([42], 0.95), 42)

    def test_even(self):
        self.assertEqual(_percentile([1, 2, 3, 4, 5], 0.5), 3)

    def test_interpolation(self):
        result = _percentile([10, 20, 30], 0.95)
        self.assertAlmostEqual(result, 29, places=0)


class TestCheckCancel(unittest.TestCase):
    def test_no_cancel(self):
        _check_cancel(None)
        _check_cancel(lambda: False)

    def test_cancelled(self):
        with self.assertRaises(MeasureCancelledError):
            _check_cancel(lambda: True)


class TestDownUrl(unittest.TestCase):
    def test_url_format(self):
        url = _down_url("https://example.com", 1000)
        self.assertIn("/__down?", url)
        self.assertIn("bytes=1000", url)
        self.assertIn("ts=", url)


if __name__ == "__main__":
    unittest.main()
