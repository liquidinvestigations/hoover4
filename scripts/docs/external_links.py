#!/usr/bin/env python3
"""Check public HTTP links on demand with bounded requests and cached results."""
import argparse
import ipaddress
import json
from pathlib import Path
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


def public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        raise ValueError("The link is not a public HTTP URL.")
    addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    if any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("The link resolves to a non-public address.")


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check(url):
    for attempt in range(2):
        try:
            public_url(url)
            request = Request(url, headers={"User-Agent": "hoover4-docs-link-check"})
            with build_opener(PublicRedirect()).open(request, timeout=10) as response:
                return dict(status="ok", code=response.status)
        except HTTPError as error:
            if error.code in (404, 410):
                return dict(status="missing", code=error.code)
            result = dict(status="unavailable", code=error.code)
        except (URLError, OSError, ValueError) as error:
            result = dict(status="unavailable", reason=type(error).__name__)
        if not attempt:
            time.sleep(1)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    cache = json.loads(args.cache.read_text()) if args.cache.exists() else {}
    urls = json.loads(args.report.read_text())["external_links"]
    for url in urls:
        old = cache.get(url, {})
        if time.time() - old.get("time", 0) > 86400:
            cache[url] = {**check(url), "time": time.time()}
        print(f"{cache[url]['status']}: {url}")
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    args.cache.write_text(json.dumps(cache, indent=2) + "\n")
    return int(any(row["status"] == "missing" for row in (cache[url] for url in urls)))


if __name__ == "__main__":
    raise SystemExit(main())
