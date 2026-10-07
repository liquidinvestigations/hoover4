"""Read public pages in isolated contexts with bounded direct and Tor attempts."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import MutableMapping
from types import SimpleNamespace
from urllib.parse import urlsplit

from browser_use_server import tor_routes
from browser_use_server.reader_client import TabClient
from browser_use_server.special_browser import SlotWaitTimeout
from browser_use_server.urlcheck import UrlNotAllowed, check_url

KEEP_MAX_CHARS = int(os.getenv("READ_PAGE_KEEP_MAX_CHARS", "32000000"))
TOR_MIN_LEFT_S = 15.0
_RETRY_ERRORS = (
    "ERR_TIMED_OUT", "ERR_CONNECTION_TIMED_OUT", "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_REFUSED", "ERR_EMPTY_RESPONSE",
    "ERR_HTTP2_PROTOCOL_ERROR", "ERR_QUIC_PROTOCOL_ERROR", "ERR_SSL_PROTOCOL_ERROR",
    "ERR_NETWORK_CHANGED", "ERR_ADDRESS_UNREACHABLE",
)


class ScopedCache(MutableMapping):
    """Expose one caller's cache while bounding all cached text in the reader pool."""

    def __init__(self, kept: dict, scope: tuple[str, str]) -> None:
        self.kept = kept
        self.scope = scope

    def __getitem__(self, key):
        return self.kept[(self.scope, key)]

    def __setitem__(self, key, entry):
        self.kept[(self.scope, key)] = entry
        now = time.monotonic()
        for old, stored in list(self.kept.items()):
            if stored[0] <= now:
                del self.kept[old]
        total = sum(len(stored[3]) for stored in self.kept.values())
        for old, stored in sorted(self.kept.items(), key=lambda item: item[1][0]):
            if total <= KEEP_MAX_CHARS:
                break
            total -= len(stored[3])
            del self.kept[old]

    def __delitem__(self, key):
        del self.kept[(self.scope, key)]

    def __iter__(self):
        return (key for scope, key in self.kept if scope == self.scope)

    def __len__(self):
        return sum(1 for scope, _ in self.kept if scope == self.scope)


class Reader:
    """Bind a shared reader pool to caller and run ownership."""

    def __init__(self, pool, username: str, session_id: str) -> None:
        self.pool = pool
        self.session_id = session_id
        self.page_reads = ScopedCache(pool.page_reads, (username, session_id))


def retry(page) -> bool:
    if page.blocked:
        return True
    if not page.error or page.full_text:
        return False
    return "did not settle" in page.error or any(code in page.error for code in _RETRY_ERRORS)


async def read_fresh(reader, url: str, goal: str, limit: int, username: str,
                     deadline: float, links: bool = True):
    """Read one URL before the call deadline and release every owned context."""
    from browser_use_server import read_page

    try:
        await asyncio.to_thread(check_url, url)
        async with reader.pool.lease(deadline) as lease:
            reading = asyncio.create_task(_routes(reader, lease, url, goal, limit,
                                                  username, deadline, links))
            died = asyncio.create_task(lease.died.wait())
            try:
                done, _ = await asyncio.wait(
                    {reading, died}, timeout=max(0.0, deadline - time.monotonic()),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reading in done:
                    return reading.result()
                if died in done:
                    return read_page.PageRead(url=url, error="The reader browser stopped during the read.")
                return read_page.PageRead(url=url, error="The page read reached its call deadline.")
            finally:
                for task in (reading, died):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(reading, died, return_exceptions=True)
    except UrlNotAllowed as exc:
        return read_page.PageRead(url=url, error=f"refused: {exc}")
    except (SlotWaitTimeout, asyncio.TimeoutError):
        return read_page.PageRead(url=url, error="No reader slot became available before the call deadline.")
    except Exception as exc:
        return read_page.PageRead(url=url, error=f"The page could not be read: {exc}")


async def _routes(reader, lease, url, goal, limit, username, deadline, links):
    from browser_use_server import read_page

    host = (urlsplit(url).hostname or "").lower()
    names = tor_routes.order(host)
    tried = []
    page = read_page.PageRead(url=url, error="The page was not read.")
    for index, name in enumerate(names):
        if tried and deadline - time.monotonic() < TOR_MIN_LEFT_S:
            break
        route = None if name == tor_routes.DIRECT else tor_routes.route(name)
        # Every attempt gets a fresh cookie context and a public-destination proxy.
        async with tor_routes.SocksRelay(route) as relay:
            async with reader.pool.context_tab(lease, relay.proxy_server, "<-loopback>") as tab:
                chat = SimpleNamespace(client=TabClient(tab), tab=tab, session_id=reader.session_id)
                page = await read_page._read_one(chat, url, goal, limit, username,
                                                 links=links, capture_result=False)
                page.route = name
                tor_routes.record(host, name, page.blocked)
                try_next = retry(page) and index + 1 < len(names) and deadline - time.monotonic() >= TOR_MIN_LEFT_S
                if not try_next:
                    await read_page._capture_read(chat, page, url, goal, username)
                    break
        tried.append(f"{name} ({page.error or 'read'})")
    page.tried = tried
    return page
