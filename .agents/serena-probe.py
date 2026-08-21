#!/usr/bin/env python3
"""One-command proof that the serena MCP server answers a real symbol lookup.

Speaks the MCP handshake by hand over whichever transport is asked for, so a failure
here is the server's, never the harness's.

    ./serena-probe.py                 # SSE   (http://127.0.0.1:21940/sse)
    ./serena-probe.py --transport http --url http://127.0.0.1:21940/mcp

Exit 0 and a printed source location means the server is healthy. Exit 1 prints the
server's own error, which is the one worth reading -- the harness's wording is not.
"""
import argparse
import json
import queue
import sys
import threading
import urllib.parse
import urllib.request

TIMEOUT = 120


def _post(url, payload, headers=None):
    body = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode(errors="replace")
    return resp.status, dict(resp.headers), resp.read().decode(errors="replace")


def _parse_sse(text):
    """Yield the JSON payload of each `data:` line in an SSE body."""
    for line in text.splitlines():
        if line.startswith("data:"):
            yield line[5:].strip()


class SseSession:
    """Client half of the 2024-11-05 SSE transport: a held GET plus POSTs back."""

    def __init__(self, url):
        self.url = url
        self.events = queue.Queue()
        self.endpoint = None
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.endpoint = self.events.get(timeout=30)

    def _read(self):
        req = urllib.request.Request(self.url, headers={"Accept": "text/event-stream"})
        stream = urllib.request.urlopen(req, timeout=TIMEOUT)
        event = None
        for raw in stream:
            line = raw.decode(errors="replace").rstrip("\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
                if event == "endpoint":
                    self.events.put(urllib.parse.urljoin(self.url, data))
                    event = None
                else:
                    self.events.put(data)

    def call(self, payload, expect_reply=True):
        status, _, body = _post(self.endpoint, payload)
        if status not in (200, 202):
            raise RuntimeError(f"POST {status}: {body}")
        if not expect_reply:
            return None
        return json.loads(self.events.get(timeout=TIMEOUT))


class HttpSession:
    """Client half of the streamable-HTTP transport: replies come back inline."""

    def __init__(self, url):
        self.url = url
        self.session_id = None

    def call(self, payload, expect_reply=True):
        headers = {"Mcp-Session-Id": self.session_id} if self.session_id else {}
        status, hdrs, body = _post(self.url, payload, headers)
        got = {k.lower(): v for k, v in hdrs.items()}.get("mcp-session-id")
        if got:
            self.session_id = got
        if status not in (200, 202):
            raise RuntimeError(f"POST {status}: {body}")
        if not expect_reply:
            return None
        for data in _parse_sse(body):
            return json.loads(data)
        return json.loads(body)


INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "serena-probe", "version": "1"},
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transport", choices=("sse", "http"), default="sse")
    ap.add_argument("--url", default=None)
    ap.add_argument("--symbol", default="insert_text_pages")
    args = ap.parse_args()
    url = args.url or ("http://127.0.0.1:21940/sse" if args.transport == "sse"
                       else "http://127.0.0.1:21940/mcp")

    session = SseSession(url) if args.transport == "sse" else HttpSession(url)
    init = session.call(INIT)
    server = init.get("result", {}).get("serverInfo", {})
    print(f"initialize ok: {server.get('name')} {server.get('version')}")
    session.call({"jsonrpc": "2.0", "method": "notifications/initialized"},
                 expect_reply=False)

    reply = session.call({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "find_symbol",
                   "arguments": {"name_path_pattern": args.symbol, "max_matches": 3}},
    })
    if "error" in reply:
        print("FAIL", json.dumps(reply["error"]), file=sys.stderr)
        return 1
    for block in reply["result"].get("content", []):
        print(block.get("text", "")[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
