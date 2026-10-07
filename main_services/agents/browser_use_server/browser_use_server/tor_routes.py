"""The Tor routes of `read_page`: the route list, the route order of a host, and a SOCKS5
relay that gives each Tor attempt a new circuit.

`READ_PAGE_TOR_PROXIES` lists the Tor SOCKS5 ports, separated by commas. An entry is
`name=host:port`, `host:port` or `port`. The name is shown in the `read_page` answer, and
it is `tor-<port>` when the entry has no name. An empty value means no Tor route, and
`read_page` then reads direct only.

A Tor attempt reads in a new CDP browser context whose proxy is a relay of this module (see
`special_browser.SpecialBrowser.context_tab`). The relay is needed for 2 reasons:

* Chromium sends no SOCKS5 user name. Tor makes a new circuit for each new user name
  (`IsolateSOCKSAuth`, which is on by default). The relay accepts the SOCKS5 request of
  Chromium without authentication and sends it to the Tor port with a new user name. So
  each attempt uses a circuit of its own.
* The relay refuses a destination that is not public: a loopback, private, link-local or
  reserved address, a single-label name, the name `localhost`, and the names that end in
  `.localhost`, `.local`, `.internal`, `.lan` or `.home.arpa` (`_LOCAL_SUFFIXES`). The
  context has `<-loopback>` in its bypass list, so Chromium sends loopback requests to the
  relay too. Tor refuses the address literals of these ranges as well
  (`ClientRejectInternalAddresses`). Tor sends a name to its exit, so the relay check is
  the only check of the names here.

The route order of a host is direct first, then the Tor routes in random order. A route
that gave a block page for a host in the last `COOLDOWN_S` seconds goes to the end of the
order for that host. The cooldown is in memory only.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import os
import random
import secrets
import socket
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: The name of the direct route.
DIRECT = "direct"

#: The most attempts for one URL: the direct one and 2 over Tor.
MAX_ATTEMPTS = 3

#: How long a route that gave a block page for a host goes to the end of the order.
COOLDOWN_S = float(os.getenv("READ_PAGE_ROUTE_COOLDOWN_S", "600"))

#: How long the relay waits for the Tor port to accept the connection and the user name.
CONNECT_TIMEOUT_S = 15.0

#: The bypass list of a Tor context. The hosts in it go direct. `<-loopback>` makes Chromium
#: send loopback requests to the proxy, where the relay refuses them. The other hosts are
#: requests of Chromium itself that each new context makes. They do not belong to the page.
CONTEXT_BYPASS = ";".join([
    "<-loopback>",
    "content-autofill.googleapis.com",
    "connectivitycheck.gstatic.com",
    "accounts.google.com",
    "clients2.google.com",
    "update.googleapis.com",
])


@dataclass(frozen=True)
class Route:
    """One Tor SOCKS5 port."""

    name: str
    host: str
    port: int


def parse_routes(text: str) -> list[Route]:
    """The routes of a `READ_PAGE_TOR_PROXIES` value. A malformed entry is logged and
    skipped."""
    routes: list[Route] = []
    for raw in (text or "").split(","):
        entry = raw.strip()
        if not entry:
            continue
        name, _, address = entry.rpartition("=")
        host, _, port_text = address.rpartition(":")
        try:
            port = int(port_text)
        except ValueError:
            log.warning("READ_PAGE_TOR_PROXIES: %r has no port; skipped", entry)
            continue
        if not 0 < port < 65536:
            log.warning("READ_PAGE_TOR_PROXIES: %r has no valid port; skipped", entry)
            continue
        route = Route(name=name.strip() or f"tor-{port}", host=host.strip() or "127.0.0.1",
                      port=port)
        if route.name == DIRECT or any(r.name == route.name for r in routes):
            log.warning("READ_PAGE_TOR_PROXIES: the name %r is used twice; %r skipped",
                        route.name, entry)
            continue
        routes.append(route)
    return routes


#: The Tor routes. Empty means that `read_page` reads direct only.
ROUTES: list[Route] = parse_routes(os.getenv("READ_PAGE_TOR_PROXIES", ""))

#: `(host, route name)` to the end of its cooldown, a `time.monotonic()` value.
_cooldown: dict[tuple[str, str], float] = {}

#: Above this many entries, `record` removes the expired ones.
_COOLDOWN_PRUNE = 1000


def route(name: str) -> Route | None:
    """The Tor route of that name, or None."""
    return next((r for r in ROUTES if r.name == name), None)


def order(host: str) -> list[str]:
    """The route names to try for `host`, at most `MAX_ATTEMPTS`. See the module text."""
    now = time.monotonic()
    tor = [r.name for r in ROUTES]
    random.shuffle(tor)
    names = [DIRECT, *tor]
    cooled = [n for n in names if _cooldown.get((host, n), 0.0) > now]
    names = [n for n in names if n not in cooled] + cooled
    return names[:MAX_ATTEMPTS]


def record(host: str, name: str, blocked: bool) -> None:
    """Note the outcome of one attempt. A block starts the cooldown of that route for
    `host`. A read that is not blocked ends it."""
    key = (host, name)
    if blocked:
        _cooldown[key] = time.monotonic() + COOLDOWN_S
        if len(_cooldown) > _COOLDOWN_PRUNE:
            now = time.monotonic()
            for stale in [k for k, until in _cooldown.items() if until <= now]:
                del _cooldown[stale]
    else:
        _cooldown.pop(key, None)


def health() -> dict:
    """The Tor routes and the count of routes in cooldown, for `/health`."""
    now = time.monotonic()
    return {
        "routes": [f"{r.name}={r.host}:{r.port}" for r in ROUTES],
        "cooldowns": sum(1 for until in _cooldown.values() if until > now),
    }


# ------------------------------------------------------------------ public destinations

#: Name suffixes that never name a public host.
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa")


def public_name(name: str) -> bool:
    """True when `name` (a host name or an address literal) can name a public host. A name
    is not resolved here."""
    host = name.strip().lower().rstrip(".").strip("[]")
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if host == "localhost" or "." not in host or host.endswith(_LOCAL_SUFFIXES):
        return False
    return True


def public_host(host: str) -> bool:
    """True when `host` is a public name and every address it resolves to is global. A
    host that does not resolve here is not public. Blocks on DNS, so call it in a thread."""
    if not public_name(host):
        return False
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


# ------------------------------------------------------------------------ the relay

#: SOCKS5 reply codes.
_GENERAL_FAILURE = 1
_NOT_ALLOWED = 2
_COMMAND_NOT_SUPPORTED = 7


class SocksRelay:
    """A local SOCKS5 relay for one direct or Tor attempt.

    Use it as `async with SocksRelay(route) as relay`, then give the context the proxy
    `relay.proxy_server`. A direct route validates DNS and connects to the validated address.
    Tor connections share one new authentication identity for the attempt.
    The block end closes the server and every connection.
    """

    def __init__(self, upstream: Route | None) -> None:
        self.upstream = upstream
        self.username = secrets.token_hex(8)
        self.port = 0
        self.refused = 0
        self._server: asyncio.base_events.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def proxy_server(self) -> str:
        return f"socks5://127.0.0.1:{self.port}"

    async def __aenter__(self) -> "SocksRelay":
        self._server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *_exc) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.close()
        for task in list(self._tasks):
            task.cancel()
        for writer in list(self._writers):
            writer.close()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if server is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(server.wait_closed(), 2.0)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        self._writers.add(writer)
        #: The writers of this connection: Chromium's side, then the Tor side after the login.
        owned = [writer]
        try:
            await self._serve(reader, writer, owned)
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            log.debug("tor relay %s: %s", (self.upstream.name if self.upstream else DIRECT), exc)
        finally:
            for w in owned:
                w.close()
                self._writers.discard(w)
            if task is not None:
                self._tasks.discard(task)

    async def _serve(self, reader, writer, owned: list) -> None:
        """Serve one SOCKS5 connection. The Tor connection goes into `owned` and into the
        writers that the block end closes, so no Tor connection outlives the relay."""
        version, count = await reader.readexactly(2)
        methods = await reader.readexactly(count)
        if version != 5 or 0 not in methods:
            writer.write(b"\x05\xff")
            await writer.drain()
            return None
        writer.write(b"\x05\x00")
        await writer.drain()
        head = await reader.readexactly(4)
        _version, command, _reserved, kind = head
        if kind == 1:
            raw = await reader.readexactly(4)
            name = str(ipaddress.IPv4Address(raw))
            address = raw
        elif kind == 4:
            raw = await reader.readexactly(16)
            name = str(ipaddress.IPv6Address(raw))
            address = raw
        elif kind == 3:
            size = await reader.readexactly(1)
            raw = await reader.readexactly(size[0])
            name = raw.decode("ascii", "replace")
            address = size + raw
        else:
            await _reply(writer, _COMMAND_NOT_SUPPORTED)
            return None
        port = await reader.readexactly(2)
        if command != 1:
            await _reply(writer, _COMMAND_NOT_SUPPORTED)
            return None
        if not public_name(name):
            self.refused += 1
            log.info("tor relay %s: refused the destination %s", (self.upstream.name if self.upstream else DIRECT), name)
            await _reply(writer, _NOT_ALLOWED)
            return None
        if self.upstream is None:
            try:
                infos = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(
                        name, int.from_bytes(port, "big"), type=socket.SOCK_STREAM),
                    CONNECT_TIMEOUT_S,
                )
                addresses = list(dict.fromkeys(info[4][0] for info in infos))
                if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
                    self.refused += 1
                    await _reply(writer, _NOT_ALLOWED)
                    return
                # Connect to the validated address without another DNS lookup.
                up_reader, up_writer = await asyncio.wait_for(
                    asyncio.open_connection(addresses[0], int.from_bytes(port, "big")),
                    CONNECT_TIMEOUT_S,
                )
            except (OSError, asyncio.TimeoutError, ValueError):
                await _reply(writer, _GENERAL_FAILURE)
                return
            owned.append(up_writer)
            self._writers.add(up_writer)
            await _reply(writer, 0)
            await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
            return
        try:
            up_reader, up_writer = await asyncio.wait_for(
                self._login(), CONNECT_TIMEOUT_S)
        except (asyncio.TimeoutError, OSError, ValueError, asyncio.IncompleteReadError) as exc:
            log.info("tor relay %s: no Tor connection: %s", (self.upstream.name if self.upstream else DIRECT), exc)
            await _reply(writer, _GENERAL_FAILURE)
            return None
        owned.append(up_writer)
        self._writers.add(up_writer)
        # The request goes to Tor as it came. Tor's reply goes back to Chromium unchanged.
        up_writer.write(head + address + port)
        await up_writer.drain()
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    async def _login(self):
        """Open the Tor port and authenticate with this relay's user name."""
        up_reader, up_writer = await asyncio.open_connection(
            self.upstream.host, self.upstream.port)
        try:
            up_writer.write(b"\x05\x01\x02")
            await up_writer.drain()
            if await up_reader.readexactly(2) != b"\x05\x02":
                raise ValueError("the Tor port did not accept a user name")
            user = self.username.encode()
            up_writer.write(b"\x01" + bytes([len(user)]) + user + b"\x01x")
            await up_writer.drain()
            if (await up_reader.readexactly(2))[1] != 0:
                raise ValueError("the Tor port refused the user name")
        except BaseException:
            up_writer.close()
            raise
        return up_reader, up_writer


async def _reply(writer: asyncio.StreamWriter, code: int) -> None:
    writer.write(bytes([5, code, 0, 1, 0, 0, 0, 0, 0, 0]))
    await writer.drain()


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy `reader` to `writer` until the end of the stream."""
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, OSError):
        writer.close()
