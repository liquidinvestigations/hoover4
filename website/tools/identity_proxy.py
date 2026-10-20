#!/usr/bin/env python3
"""Forward HTTP requests to a website and add the identity headers of one account.

The browser tests of a fixture build use it. A fixture build runs beside the stack
website and has no reverse proxy in front of it, so a request without these headers gets
401. The script listens on one local port and adds `X-Forwarded-User` and
`X-Forwarded-Groups` to each request, as the development sign-in proxy does.

Example, as `serve_fixture_build.sh` starts it.

    identity_proxy.py --listen 8091 --upstream http://hoover4-website:8090 --user admin --groups admin
"""

from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HOP_HEADERS = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "upgrade",
               "te", "trailer", "content-length", "host"}


def handler(upstream: str, user: str, groups: str):
    target = urlsplit(upstream)

    class Forward(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _forward(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            headers = {k: v for k, v in self.headers.items()
                       if k.lower() not in HOP_HEADERS and not k.lower().startswith("x-forwarded-")}
            headers.update({"Host": target.netloc, "X-Forwarded-User": user,
                            "X-Forwarded-Groups": groups})
            connection = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=300)
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                data = response.read()
            except OSError as error:
                self.send_error(502, f"upstream unavailable: {error}")
                return
            finally:
                connection.close()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_PATCH = _forward

    return Forward


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--listen", type=int, required=True, help="local port")
    parser.add_argument("--upstream", required=True, help="base URL of the fixture build")
    parser.add_argument("--user", required=True, help="the account name to assert")
    parser.add_argument("--groups", default="", help="comma-separated groups to assert")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.listen),
                                 handler(args.upstream, args.user, args.groups))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
