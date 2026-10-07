"""Verify reader ownership, independent capacity, fallback, and capture selection."""

import asyncio
import contextlib
import time
from types import SimpleNamespace

import pytest

from browser_use_server import capture, read_page, reader_routes, server, tor_routes
from browser_use_server.reader_routes import Reader, ScopedCache


def entry(text):
    return (time.monotonic() + 60, "Title", "https://page.example", text, read_page.text_version(text))


def test_cache_isolates_users_and_runs_and_bounds_total_text(monkeypatch):
    kept = {}
    first = ScopedCache(kept, ("first", "run"))
    second = ScopedCache(kept, ("second", "run"))
    other_run = ScopedCache(kept, ("first", "other-run"))
    key = ("https://page.example", True)
    first[key] = entry("first text")
    assert key not in second and key not in other_run
    second[key] = entry("second text")
    assert first[key][3] == "first text"
    monkeypatch.setattr(reader_routes, "KEEP_MAX_CHARS", 11)
    other_run[key] = entry("third text")
    assert sum(len(value[3]) for value in kept.values()) <= 11
    assert other_run[key][3] == "third text"


def test_parallel_reads_preserve_url_order_and_release_cancelled_jobs(monkeypatch):
    active = set()
    peak = []
    async def fresh(reader, url, goal, limit, username, deadline, links=True):
        active.add(url)
        peak.append(len(active))
        try:
            await asyncio.sleep(0.01 if url.endswith("first") else 10)
            return read_page.PageRead(url=url, full_text="First page text.")
        finally:
            active.remove(url)
    monkeypatch.setattr(read_page, "_read_fresh", fresh)
    monkeypatch.setattr(read_page, "CALL_TIMEOUT_S", 0.05)
    reader = Reader(SimpleNamespace(page_reads={}), "user", "run")
    urls = ["https://page.example/first", "https://page.example/second"]
    result = asyncio.run(read_page.read(reader, urls, "", "user"))
    assert max(peak) == 2 and not active
    assert [page.url for page in result.pages] == urls
    assert result.pages[0].full_text == "First page text."
    assert result.pages[1].error and not result.pages[1].full_text


class Pool:
    name = "_reader"
    def __init__(self):
        self.page_reads = {}
        self.active = 0
        self.tabs = []
        self.closed = []
    @contextlib.asynccontextmanager
    async def lease(self, deadline):
        self.active += 1
        try:
            yield SimpleNamespace(died=asyncio.Event())
        finally:
            self.active -= 1
    @contextlib.asynccontextmanager
    async def context_tab(self, lease, proxy, bypass):
        tab = SimpleNamespace(identity=len(self.tabs))
        self.tabs.append(tab)
        try:
            yield tab
        finally:
            self.closed.append(tab)


class Relay:
    proxy_server = "socks5://proxy.example:9050"
    def __init__(self, route):
        self.route = route
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass


def test_blocked_direct_read_retries_in_a_new_context_and_keeps_capture_owner(monkeypatch):
    pool = Pool()
    seen = []
    async def attempt(chat, url, goal, limit, username, **kwargs):
        assert kwargs["capture_result"] is False
        seen.append((chat.tab, username, chat.session_id))
        if len(seen) == 1:
            return read_page.PageRead(url=url, blocked=True, error=read_page.BOT_CHECK_ERROR)
        return read_page.PageRead(url=url, full_text="The required source passage.")
    captures = []
    async def archive(chat, page, url, goal, username):
        captures.append((chat.tab, chat.session_id, username))
        page.artifact = {"artifact_id": "owned-capture"}
    monkeypatch.setattr(reader_routes, "check_url", lambda _: None)
    monkeypatch.setattr(tor_routes, "SocksRelay", Relay)
    monkeypatch.setattr(tor_routes, "order", lambda _: ["direct", "tor-test"])
    monkeypatch.setattr(tor_routes, "route", lambda name: tor_routes.Route(name, "proxy.example", 9050))
    monkeypatch.setattr(tor_routes, "record", lambda *_: None)
    monkeypatch.setattr(read_page, "_read_one", attempt)
    monkeypatch.setattr(read_page, "_capture_read", archive)
    reader = Reader(pool, "user", "run")
    page = asyncio.run(reader_routes.read_fresh(
        reader, "https://page.example", "", 1000, "user", time.monotonic() + 60))
    assert page.full_text and not page.error and page.route == "tor-test"
    assert len(pool.tabs) == 2 and pool.tabs[0] is not pool.tabs[1]
    assert pool.closed == pool.tabs and pool.active == 0
    assert captures == [(pool.tabs[1], "run", "user")]
    assert len(page.tried) == 1 and page.tried[0].startswith("direct")


def test_explicit_capture_never_selects_another_parallel_tab(monkeypatch):
    written = []
    async def wrong_tab(_):
        pytest.fail("A reader capture selected the active browser tab.")
    async def identity(tab):
        return tab.url, tab.url
    async def screenshot(tab):
        return b"thumbnail"
    async def snapshot(tab):
        return b"snapshot"
    monkeypatch.setattr(capture, "_active_tab", wrong_tab)
    monkeypatch.setattr(capture, "_page_identity", identity)
    monkeypatch.setattr(capture, "_screenshot", screenshot)
    monkeypatch.setattr(capture, "_snapshot_mhtml", snapshot)
    monkeypatch.setattr(capture.mhtml_mod, "convert", lambda *_args, **_kwargs: SimpleNamespace(html="<p>Page</p>"))
    monkeypatch.setattr(capture.artifacts, "write", lambda request: written.append(request) or request.session_id)
    async def run():
        return await asyncio.gather(*[
            capture.capture(SimpleNamespace(session_id=f"run-{i}"), "read_page", f"user-{i}",
                            tab=SimpleNamespace(url=f"https://page.example/{i}"))
            for i in range(2)
        ])
    results = asyncio.run(run())
    assert {r.artifact_id for r in results} == {"run-0", "run-1"}
    assert {(r.session_id, r.username, r.url) for r in written} == {
        (f"run-{i}", f"user-{i}", f"https://page.example/{i}") for i in range(2)
    }


def test_reader_tool_uses_its_pool_without_starting_an_interactive_browser(monkeypatch):
    async def no_reaper():
        pass
    async def forbidden(*_):
        pytest.fail("A page read requested the interactive browser.")
    async def read(reader, urls, goal, username, *args, **kwargs):
        assert reader.pool is server.router.reader
        assert (reader.session_id, username) == ("run", "user")
        return read_page.ReadResult(pages=[read_page.PageRead(url=urls[0], full_text="Source text.")])
    monkeypatch.setattr(server.router, "ensure_reaper", no_reaper)
    monkeypatch.setattr(server.router, "get", forbidden)
    monkeypatch.setattr(server, "_header", lambda key: {server.RUN_HEADER: "run", server.USER_HEADER: "user"}.get(key, ""))
    monkeypatch.setattr(read_page, "read", read)
    monkeypatch.setattr(server.telemetry, "record_async", lambda *_args, **_kwargs: None)
    tool = server.ReadPageTool(name="read_page", description="Read public pages.", parameters=server.READ_PAGE_SCHEMA)
    asyncio.run(tool.run({"urls": ["https://page.example"]}))


def test_cached_tor_read_preserves_route_and_link_mode(monkeypatch):
    calls = []
    async def fresh(*args, **kwargs):
        calls.append(kwargs)
        return read_page.PageRead(url=args[1], title="Title\ud800", full_text="Source \ud83d\ude00 text.", route="tor-test")
    monkeypatch.setattr(read_page, "_read_fresh", fresh)
    reader = Reader(SimpleNamespace(page_reads={}), "user", "run")
    async def run():
        first = await read_page.read(reader, ["https://page.example"], "", "user", links=False)
        second = await read_page.read(reader, ["https://page.example"], "", "user",
                                      version=first.pages[0].version, links=False)
        return first, second
    first, second = asyncio.run(run())
    assert len(calls) == 1
    assert second.pages[0].route == "tor-test" and second.pages[0].links is False
    assert first.pages[0].full_text == "Source 😀 text."
    assert second.pages[0].title == "Title\ufffd"
    read_page.render(second).encode("utf-8")


def test_blocked_http_result_reports_status_without_a_wait_claim():
    result = read_page.ReadResult(pages=[read_page.PageRead(
        url="https://page.example", blocked=True, error="the page returned HTTP 403")])
    rendered = read_page.render(result)
    assert "HTTP 403" in rendered and "stayed on" not in rendered
    assert "Do not use this page as a source" in rendered
