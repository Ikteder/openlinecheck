"""Explicit opt-in HTTP speed-test server; listens on loopback by default.

Run: python -m linecheck.server --port 8765
Test: python -m linecheck --origin http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

MAX_BYTES_PER_REQUEST = 16_000_000
CHUNK_SIZE = 65_536


class SpeedHandler(BaseHTTPRequestHandler):
    server_version = "OpenLineCheck/0.1"

    def _send(self, status: int, size: int = 0, **headers: str):
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        for key, value in headers.items():
            self.send_header(key.replace("_", "-"), value)
        self.end_headers()

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/__down":
            self._send(404)
            return
        try:
            value = parse_qs(parsed.query).get("bytes", ["0"])[0]
            count = int(value)
        except (ValueError, TypeError):
            self._send(400)
            return
        if not 0 <= count <= MAX_BYTES_PER_REQUEST:
            self._send(413)
            return
        self._send(200, count)
        try:
            payload = b"X" * CHUNK_SIZE
            while count:
                block = payload[: min(CHUNK_SIZE, count)]
                self.wfile.write(block)
                count -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if urlsplit(self.path).path != "/__up":
            self._send(404)
            return
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length)
        except ValueError:
            self._send(411)
            return
        if not 0 <= length <= MAX_BYTES_PER_REQUEST:
            self._send(413)
            return
        remaining = length
        while remaining:
            block = self.rfile.read(min(remaining, CHUNK_SIZE))
            if not block:
                self._send(400)
                return
            remaining -= len(block)
        self._send(204, 0, X_Received_Bytes=str(length))

    def log_message(self, *_args):
        # Avoid logging client IP addresses by default.
        return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start a local/LAN test server (localhost-only by default)")
    parser.add_argument("--bind", default="127.0.0.1", help="Bind interface; defaults to loopback only")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("port must be 1..65535")
    print(f"OpenLineCheck test server at http://{args.bind}:{args.port}")
    print("Only expose to a trusted LAN if you understand the implications. Ctrl+C to stop.")
    server = ThreadingHTTPServer((args.bind, args.port), SpeedHandler)
    server.daemon_threads = True
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
