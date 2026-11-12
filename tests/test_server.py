from __future__ import annotations

from contextlib import contextmanager
from http.server import ThreadingHTTPServer
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from linecheck.server import SpeedHandler
from linecheck.measure import _request_download, _request_upload


@contextmanager
def server():
    service = ThreadingHTTPServer(("127.0.0.1", 0), SpeedHandler)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{service.server_address[1]}"
    finally:
        service.shutdown()
        service.server_close()
        thread.join(timeout=2)


class ServerTests(unittest.TestCase):
    def test_roundtrip_and_byte_receipt(self):
        with server() as origin:
            self.assertEqual(_request_download(origin, 1024, timeout=3)[0], 1024)
            self.assertEqual(_request_upload(origin, 1024, timeout=3)[0], 1024)

    def test_bounds(self):
        with server() as origin:
            with self.assertRaises(HTTPError) as failure:
                urlopen(origin + "/__down?bytes=20000000")
            self.assertEqual(failure.exception.code, 413)
            with self.assertRaises(ValueError):
                _request_upload(origin, 20_000_000, timeout=3)
            with self.assertRaises(ValueError):
                _request_download(origin, -1, timeout=3)

    def test_bad_paths(self):
        with server() as origin:
            with self.assertRaises(HTTPError) as failure:
                urlopen(origin + "/unknown")
            self.assertEqual(failure.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
