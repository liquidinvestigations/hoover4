"""The HTTP front of clamd: `POST /scan` and `GET /health`.

`POST /scan` streams the request body to clamd with the INSTREAM command, in chunks, so
the front never holds a whole file. At most CLAMAV_CONCURRENCY scans run at once, and at
most 4 times that many wait. A request beyond that gets 503 at once.

The JSON answer has `status` (`clean`, `infected`, `incomplete`, `error`), `signature`,
`engine_version`, `database_version` and `config_fingerprint`. `incomplete` is a limit
alert of clamd (`Heuristics.Limits.Exceeded...`): the recursive scan stopped at a limit,
so no verdict exists. A body above MAX_FILE_BYTES gets 413 without a scan.

`GET /health` answers 200 only when clamd answers VERSION with an engine and a
signature database version, so a loaded engine with signatures is the readiness rule.
"""

import hashlib
import json
import os
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOCKET = os.environ.get("CLAMD_SOCKET", "/tmp/clamd.sock")
CONCURRENCY = max(1, int(os.environ.get("CLAMAV_CONCURRENCY", "4") or 4))
WAITING = 4 * CONCURRENCY
MAX_FILE_BYTES = 500 * 1024 * 1024
CHUNK = 64 * 1024
CONNECT_SECONDS = 10
SCAN_SECONDS = int(os.environ.get("CLAMAV_SCAN_SECONDS", "900") or 900)
CONFIG = "/etc/clamav/clamd.conf"
#: The clamd keys that change a verdict. Their values form the configuration fingerprint.
VERDICT_KEYS = ("StreamMaxLength", "MaxFileSize", "MaxScanSize", "MaxRecursion", "MaxFiles",
                "AlertExceedsMax", "HeuristicAlerts", "ScanArchive", "ScanPE", "ScanOLE2", "ScanPDF")

_slots = threading.BoundedSemaphore(CONCURRENCY)
#: The VERSION answer of clamd and its read time. A scan reuses it for VERSION_SECONDS.
VERSION_SECONDS = 60
_version_cache: dict = {}
_version_lock = threading.Lock()
_waiting = 0
_waiting_lock = threading.Lock()


def config_fingerprint() -> str:
    lines = []
    try:
        with open(CONFIG) as handle:
            for line in handle:
                parts = line.split()
                if parts and parts[0] in VERDICT_KEYS:
                    lines.append(" ".join(parts))
    except OSError:
        pass
    return hashlib.sha256("\n".join(sorted(lines)).encode()).hexdigest()[:16]


def _connect(timeout: float) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_SECONDS)
    sock.connect(SOCKET)
    sock.settimeout(timeout)
    return sock


def _reply(sock: socket.socket) -> str:
    data = b""
    while not data.endswith(b"\0"):
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data.rstrip(b"\0").decode("utf-8", "replace").strip()


def version() -> dict:
    """`{engine_version, database_version, database_date}` from clamd VERSION."""
    with _connect(CONNECT_SECONDS) as sock:
        sock.sendall(b"zVERSION\0")
        text = _reply(sock)
    parts = text.split("/")
    engine = parts[0].replace("ClamAV", "").strip() if parts else ""
    return {"engine_version": engine,
            "database_version": parts[1].strip() if len(parts) > 1 else "",
            "database_date": parts[2].strip() if len(parts) > 2 else ""}


def cached_version() -> dict:
    """`version()`, read again after VERSION_SECONDS. A scan does not open a second clamd
    connection for each file, so a busy clamd thread pool does not delay the scan."""
    with _version_lock:
        if _version_cache and time.monotonic() - _version_cache["at"] < VERSION_SECONDS:
            return _version_cache["info"]
    info = version()
    with _version_lock:
        _version_cache.update(at=time.monotonic(), info=info)
    return info


def classify(reply: str) -> tuple:
    """`(status, signature)` of an INSTREAM reply such as `stream: Eicar-Test-Signature FOUND`."""
    body = reply.split(":", 1)[1].strip() if ":" in reply else reply
    if body == "OK":
        return "clean", ""
    if body.endswith("FOUND"):
        signature = body[:-len("FOUND")].strip()
        if signature.startswith("Heuristics.Limits.Exceeded"):
            return "incomplete", signature
        return "infected", signature
    return "error", body[:500]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: D102 - one line per request is enough
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server names
        if self.path != "/health":
            self._send(404, {"error": "not found"})
            return
        try:
            info = version()
        except OSError as exc:
            self._send(503, {"ready": False, "error": f"clamd: {exc}"})
            return
        ready = bool(info["engine_version"] and info["database_version"])
        self._send(200 if ready else 503, {
            "ready": ready, **info, "config_fingerprint": config_fingerprint(),
            "concurrency": CONCURRENCY,
            "update_signatures": os.environ.get("CLAMAV_UPDATE_SIGNATURES", "false") == "true"})

    def do_POST(self):  # noqa: N802 - http.server names
        global _waiting
        if self.path != "/scan":
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or -1)
        if length < 0:
            self._send(411, {"status": "error", "signature": "", "error": "Content-Length is required"})
            return
        if length > MAX_FILE_BYTES:
            self._send(413, {"status": "error", "error": f"body above {MAX_FILE_BYTES} bytes"})
            return
        with _waiting_lock:
            if _waiting >= WAITING + CONCURRENCY:
                self.close_connection = True
                self._send(503, {"status": "error", "error": "scanner queue is full"})
                return
            _waiting += 1
        try:
            with _slots:
                self._scan(length)
        finally:
            with _waiting_lock:
                _waiting -= 1

    def _scan(self, length: int) -> None:
        try:
            info = cached_version()
            with _connect(SCAN_SECONDS) as sock:
                sock.sendall(b"zINSTREAM\0")
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        raise OSError("request body ended early")
                    sock.sendall(struct.pack(">L", len(chunk)) + chunk)
                    remaining -= len(chunk)
                sock.sendall(struct.pack(">L", 0))
                reply = _reply(sock)
        except OSError as exc:
            self.close_connection = True
            self._send(502, {"status": "error", "signature": "", "error": f"clamd: {exc}"})
            return
        status, signature = classify(reply)
        self._send(200, {"status": status, "signature": signature, **info,
                         "config_fingerprint": config_fingerprint(), "reply": reply[:500]})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler)
    server.daemon_threads = True
    server.serve_forever()
