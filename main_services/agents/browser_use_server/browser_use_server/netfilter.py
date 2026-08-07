"""What Chromium itself is allowed to fetch — the line that survives a redirect.

:mod:`.urlcheck` is the first boundary and it is a good one, but it only ever sees **tool
arguments**. Once Chromium is loading a page, everything after that is the browser's own
business: an HTTP 302, a `<meta http-equiv=refresh>`, `location = …` in a script, an
`<img src>` — none of them pass through a tool call, so none of them are checked. A public
page that redirects to `http://manticore:9308/sql?query=…` was fetched and returned to the
model. Measured, not assumed: with the filter off, that redirect answered with data.

playwright-mcp's `--blocked-origins` cannot close this. Its own documentation says the
flag "does not serve as a security boundary and *does not affect redirects*", and its
matching had a second bug on top: a bare hostname becomes the glob `*://<host>/**`, and a
single `*` does not cross `/`, so `http://manticore:9308/` never matched. Every service on
this network listens on a non-default port, so the entire flag was inert. It is still
passed — correctly, now — as the cheap second line it was always meant to be.

The boundary that does hold is a **proxy auto-config script**, handed to Chromium at
launch as a `data:` URL. PAC is consulted for *every* request the network stack makes,
including each hop of a redirect chain, before a connection is opened, browser-wide and
for every tab — which is exactly the coverage the tool-argument check lacks. Anything
internal is routed to a proxy that does not exist, so the request fails at once with
`ERR_PROXY_CONNECTION_FAILED` instead of reaching the service.

What counts as internal, in the order the script tests it:

* a **single-label** host (`isPlainHostName`) — every container on the `hoover4` network is
  reachable under a bare name, so this catches `clickhouse`, `manticore`, `localhost` and
  every service added after this file was written, without a list to keep in step;
* the `.internal` and `.localhost` suffixes (cloud metadata endpoints live in the first);
* an address, after resolution, in any private, loopback, link-local, CGNAT or reserved
  range — the same rule :mod:`.urlcheck` applies, now applied to what the browser actually
  connects to, which also covers a public name with a private `A` record.

Fail-closed: a name that does not resolve is blocked rather than tried.

Known limits, deliberately accepted: PAC's `dnsResolve` is IPv4-only (`dnsResolveEx` is a
Microsoft extension Chromium does not implement), so an IPv6-only internal host would not
be caught by the address rule — the name rules still catch every one that exists here, and
this network is IPv4. And PAC is consulted per *request*, so it does not see a page that
exfiltrates through a host it is allowed to reach; that was never this layer's job.
"""

from __future__ import annotations

import base64
import os

from browser_use_server.urlcheck import DENIED_HOSTS

#: Where a blocked request is sent instead. `127.0.0.1:1` is a privileged port nothing in
#: this container binds, so the connection is refused *immediately* — the failure is fast
#: and unambiguous. An unroutable public address (TEST-NET, say) would be tidier in theory
#: and much worse in practice: the container has a default route, so those hang until the
#: navigation deadline and every blocked fetch costs 30 seconds.
DEAD_PROXY = os.getenv("BROWSER_DEAD_PROXY", "127.0.0.1:1")

#: Private, loopback, link-local, CGNAT and "this network" ranges, as PAC `isInNet` pairs.
#: Same set as `urlcheck._address_is_public` refuses, minus multicast (a browser will not
#: navigate to one) and expressed the only way PAC can express it.
_PRIVATE_RANGES = (
    ("10.0.0.0", "255.0.0.0"),
    ("172.16.0.0", "255.240.0.0"),
    ("192.168.0.0", "255.255.0.0"),
    ("127.0.0.0", "255.0.0.0"),
    ("169.254.0.0", "255.255.0.0"),
    ("100.64.0.0", "255.192.0.0"),
    ("0.0.0.0", "255.0.0.0"),
)


def pac_script() -> str:
    """The PAC source Chromium is launched with. Kept small and allocation-free.

    It runs on every request, so it stays a handful of string comparisons plus one cached
    `dnsResolve`; anything heavier here is paid for by every image on every page.
    """
    ranges = " ||\n      ".join(
        f'isInNet(ip, "{net}", "{mask}")' for net, mask in _PRIVATE_RANGES
    )
    return f"""function FindProxyForURL(url, host) {{
  var BLOCK = "PROXY {DEAD_PROXY}";
  host = ("" + host).toLowerCase();
  // Every container on this network answers to a bare, dotless name.
  if (isPlainHostName(host)) return BLOCK;
  if (dnsDomainIs(host, ".internal") || dnsDomainIs(host, ".localhost")) return BLOCK;
  var ip = /^[0-9.]+$/.test(host) ? host : dnsResolve(host);
  if (!ip) return BLOCK;  // fail closed: a name we cannot resolve is not fetched
  if ({ranges}) return BLOCK;
  return "DIRECT";
}}
"""


def pac_data_url() -> str:
    """`pac_script()` as the `data:` URL `--proxy-pac-url` takes.

    A `data:` URL rather than a file so there is nothing to keep in step on disk and
    nothing a compromised page could rewrite; base64 rather than percent-encoding because
    the script contains characters (`;`, `&`) a bare data URL would eat.
    """
    encoded = base64.b64encode(pac_script().encode("utf-8")).decode("ascii")
    return f"data:application/x-ns-proxy-autoconfig;base64,{encoded}"


def blocked_origins(hosts: str) -> str:
    """Turn a `;`-separated host list into the origins playwright-mcp actually matches.

    `--blocked-origins` compiles each entry with `originOrHostGlob`, which has exactly one
    form that tolerates a port: `scheme://host:*`. A bare `host` becomes `*://host/**` and
    a single `*` does not cross `/`, so it matches nothing on this network. Both schemes
    are emitted per host because the glob pins the scheme.
    """
    out: list[str] = []
    for raw in hosts.split(";"):
        host = raw.strip().lower()
        if not host:
            continue
        if "://" in host:
            # Already an origin — trust the caller and pass it through untouched.
            out.append(host)
            continue
        out.extend((f"http://{host}:*", f"https://{host}:*"))
    return ";".join(out)


#: Hosts the sidecar is told to block. Derived from urlcheck's deny-list so the two lines
#: of defence cannot drift apart, which is what happened when this was a second literal.
DEFAULT_BLOCKED_HOSTS = ";".join(sorted(DENIED_HOSTS))
