"""HTTP server for in-document PDF search.

POST / with the PDF bytes as the body and `?keywords=<JSON array>` returns the results of
`search.py` for each keyword. GET /health returns 200 when the server answers.

Each search runs in a new `search.py` process, and at most `MAX_PROCESSES` run at the
same time. A process exits after its request, so all memory that PDFium used for a
document returns to the operating system. A process that crashes or is stopped fails only
its own request. The request body and the result go through temporary files, and this
server copies them in parts of 1 MiB. Thus the server memory does not grow with the size
of a document or of its result.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 13500
# The limits are fixed. The compose file sets the container memory limit to 12 GB.
MAX_PROCESSES = 4
# The website stops waiting after 120 s (`PDF_SEARCH_TIMEOUT`). A process that runs
# longer holds a slot for no caller, so it stops a short time after that.
PROCESS_TIMEOUT_SECONDS = 150
COPY_CHUNK_BYTES = 1 << 20
SEARCH_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "search.py")

slots = threading.BoundedSemaphore(MAX_PROCESSES)


def log(message):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), message, flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def send_file(self, file):
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(size))
        self.end_headers()
        while chunk := file.read(COPY_CHUNK_BYTES):
            self.wfile.write(chunk)

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(405, {"error": "Method Not Allowed. POST the PDF bytes with ?keywords="})

    def do_POST(self):
        try:
            keywords = json.loads(parse_qs(urlparse(self.path).query).get("keywords", ["null"])[0])
        except ValueError:
            keywords = None
        length = int(self.headers.get("Content-Length") or 0)
        if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords) or length <= 0:
            self.close_connection = True
            self.send_json(400, {"error": "Need a ?keywords=<json array> and a PDF body"})
            return
        with (tempfile.NamedTemporaryFile(prefix="pdf-search-", suffix=".pdf") as body,
              tempfile.NamedTemporaryFile(prefix="pdf-search-", suffix=".json") as result):
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(COPY_CHUNK_BYTES, remaining))
                if not chunk:
                    self.close_connection = True
                    self.send_json(400, {"error": "The request body ended before Content-Length"})
                    return
                body.write(chunk)
                remaining -= len(chunk)
            body.flush()
            error = run_search(body.name, result.name, keywords, length)
            if error:
                self.send_json(*error)
            else:
                self.send_file(result)


def run_search(path, result_path, keywords, length):
    """Run one search process. Returns None when the result file is complete, or the
    status and the JSON body of the error response."""
    started = time.monotonic()
    with slots:
        waited = time.monotonic() - started
        try:
            process = subprocess.run(
                [sys.executable, "-I", SEARCH_SCRIPT, path, result_path],
                input=json.dumps(keywords).encode(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=PROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            log(f"search timeout bytes={length} keywords={len(keywords)} after={PROCESS_TIMEOUT_SECONDS}s")
            return 504, {"error": "Search timeout", "details": f"over {PROCESS_TIMEOUT_SECONDS} s"}
    elapsed = time.monotonic() - started
    stderr = process.stderr.decode(errors="replace").strip()
    if process.returncode != 0:
        # A negative code is the signal that stopped the process, for example -9 for an
        # out-of-memory kill.
        details = stderr.splitlines()[-1] if stderr else f"search process exit code {process.returncode}"
        log(f"search failed bytes={length} keywords={len(keywords)} code={process.returncode} details={details}")
        return 500, {"error": "Internal Server Error", "details": details}
    peak = stderr.rsplit("peak_rss_kib=", 1)[-1] if "peak_rss_kib=" in stderr else "?"
    log(f"search ok bytes={length} keywords={len(keywords)} waited={waited:.2f}s "
        f"took={elapsed:.2f}s peak_rss_kib={peak}")
    return None


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    log(f"listening on port {PORT}, {MAX_PROCESSES} search processes at most")
    server.serve_forever()


if __name__ == "__main__":
    main()
