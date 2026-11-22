"""Verify the shared reader's expiry and claim contract with a counted origin."""

import asyncio
import json
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import urlopen

import pytest

from browser_use_server import public_cache
from browser_use_server.read_page import PageRead


class Index:
    def __init__(self, clock):
        self.values = {}
        self.clock = clock

    @classmethod
    def from_url(cls, *_args, **_kwargs):
        return cls.instance

    async def get(self, key):
        value, until = self.values.get(key, (None, 0))
        return value if until > self.clock.now else None

    async def set(self, key, value, *, ex, nx):
        if nx and await self.get(key) is not None:
            return False
        self.values[key] = (value, self.clock.now + ex)
        return True

    async def eval(self, command, keys, claim, *arguments):
        if keys == 2:
            key, token, payload, ttl = arguments
            if await self.get(claim) == token:
                self.values[key] = (payload, self.clock.now + ttl / 1000)
                del self.values[claim]
                return 1
        elif await self.get(claim) == arguments[0]:
            del self.values[claim]
            return 1
        return 0

    async def aclose(self):
        pass


@pytest.mark.parametrize("lifetime", [None, 5])
def test_workers_share_one_origin_read_and_expire_to_the_second(monkeypatch, lifetime):
    clock = SimpleNamespace(now=10_000)
    monkeypatch.setattr(public_cache, "time", SimpleNamespace(
        time=lambda: clock.now, monotonic=lambda: 0,
    ))
    Index.instance = Index(clock)
    monkeypatch.setitem(sys.modules, "redis.asyncio", SimpleNamespace(Redis=Index))
    monkeypatch.setattr(public_cache, "indexed", lambda *_: None)
    monkeypatch.setattr(public_cache, "index", lambda *_: None)
    monkeypatch.setattr(public_cache, "store", lambda body, _token: body)
    monkeypatch.setattr(public_cache, "load", json.loads)
    calls = []
    url = "https://example.test/Exact"

    class CountedOrigin(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            self.send_header("Cache-Control", "public")
            self.end_headers()
            self.wfile.write(f"origin fetch {len(calls)}".encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), CountedOrigin)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def fetch():
        with urlopen(f"http://127.0.0.1:{server.server_port}/Exact") as response:
            return response.read().decode()

    async def origin():
        return PageRead(url=url, final_url=url, full_text=await asyncio.to_thread(fetch),
                        status=200, public_response=True, public_lifetime=lifetime)

    async def read():
        return await public_cache.read(url, True, 1, 10, origin)

    async def trial():
        first, second = await asyncio.gather(read(), read())
        assert first.full_text == second.full_text == "origin fetch 1"
        clock.now += (lifetime or public_cache.TTL) - 1
        assert (await read()).full_text == "origin fetch 1"
        clock.now += 1
        assert (await read()).full_text == "origin fetch 2"

    try:
        asyncio.run(trial())
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    assert calls == ["/Exact", "/Exact"]
    assert public_cache.key_for(url, True, 1) != public_cache.key_for(url.lower(), True, 1)
    assert not public_cache.candidate(url + "?token=secret")


def test_private_or_failed_response_is_not_eligible():
    url = "https://example.test/"
    page = PageRead(url=url, final_url=url, full_text="text", status=200, public_response=False)
    assert not public_cache.eligible(page, url)
    page.public_response = True
    page.error = "temporarily unavailable"
    assert not public_cache.eligible(page, url)


def test_response_restrictions_prevent_public_reuse():
    from browser_use_server.reader_client import public_cache_response

    assert public_cache_response({"Cache-Control": "public"})
    assert public_cache_response({"Cache-Control": "public, s-maxage=604800"})
    assert not public_cache_response({"Cache-Control": "public, private"})
    assert public_cache_response({"Cache-Control": "public, max-age=10"})
    assert public_cache_response({})
    assert not public_cache_response({"Cache-Control": "max-age=0"})
    assert not public_cache_response({"Cache-Control": "public", "Set-Cookie": "id=1"})
    assert not public_cache_response({"Cache-Control": "public", "Vary": "Cookie"})



def test_shared_pdf_reopens_checked_redirect_and_copies_assets(monkeypatch):
    from test_read_page_extent import DATA, URL
    from browser_use_server import read_page

    final = URL + "?b=First&a=2"
    _, text, _, extent = read_page.pdf_text(DATA, 1)
    source = PageRead(url=URL, final_url=final, public_chain=(URL, final), status=200,
                      full_text=text, extent=extent, public_lifetime=10,
                      pdf_data=DATA, shared_thumb=b"image", shared_body=b"archive")
    stored = json.loads(public_cache.prepare(source, public_cache.time.time(), 10))
    checked = []
    page = asyncio.run(public_cache.prepare_hit(stored, URL, 51, checked.append))
    assert checked == [URL, final]

    def blocked(address):
        if address == final:
            raise PermissionError("The redirect destination is no longer allowed.")

    with pytest.raises(PermissionError):
        asyncio.run(public_cache.prepare_hit(stored, URL, 1, blocked))
    assert page.extent["first"] == 51 and "Kaminski" in page.full_text
    assert public_cache.candidate(final)
    assert public_cache.key_for(final, True, 51) != public_cache.key_for(URL + "?a=2&b=First", True, 51)
    assert public_cache.key_for(final, True, 51) != public_cache.key_for(URL + "?b=first&a=2", True, 51)
    requests = []

    def put(request):
        requests.append(request)
        return request.session_id

    monkeypatch.setattr(public_cache.artifacts, "write", put)
    public_cache.copy_representation(page, "alice", "one")
    other = asyncio.run(public_cache.prepare_hit(stored, URL, 1, checked.append))
    public_cache.copy_representation(other, "bob", "two")
    assert [(r.username, r.session_id, r.thumb[1]) for r in requests] == [
        ("alice", "one", b"image"), ("bob", "two", b"image"),
    ]
    assert page.image["artifact_id"] == "one" and other.image["artifact_id"] == "two"


def test_response_freshness_uses_shortest_constraint_and_rejects_personalization():
    from browser_use_server.reader_client import private_request, public_cache_lifetime

    assert public_cache_lifetime({"Cache-Control": "max-age=60", "Age": "45"}, now=0) == 15
    assert public_cache_lifetime({"Cache-Control": "max-age=5, s-maxage=30"}, now=0) == 30
    assert public_cache_lifetime({"Vary": "Accept-Encoding"}, now=0) == public_cache.TTL
    assert public_cache_lifetime({"Vary": "Accept-Language"}, now=0) == 0
    assert private_request({"Cookie": "private"})
    assert private_request({"Authorization": "private"})
    assert not public_cache.candidate("https://example.test/report?X-Amz-Signature=ab")


def test_chat_owned_pdf_can_open_new_window_without_shared_index(monkeypatch):
    from test_read_page_extent import DATA, URL
    from browser_use_server import page_citations, read_page

    owner, chat = "reader", "different-chat"
    rows, objects = [], {}
    _, text, _, extent = read_page.pdf_text(DATA, 1)
    page = PageRead(url=URL, final_url=URL, full_text=text, extent=extent,
                    pdf_data=DATA, version=read_page.text_version(text, extent), status=200)

    def write(request, artifact_id, operation, data, mime):
        objects[artifact_id] = data
        if request.kind == page_citations.KIND_PAGE_TEXT:
            rows.append({"artifact_id": artifact_id, "detail": request.detail, "url": request.url})
        return artifact_id

    def load(request_owner, request_chat, artifact_id, start, length):
        assert (request_owner, request_chat) == (owner, chat)
        body = objects[artifact_id]
        return body[start:start + length], len(body)

    monkeypatch.setattr(page_citations.artifacts, "_read_back_body_sha256",
                        lambda user, artifact: "present" if artifact in objects else None)
    monkeypatch.setattr(page_citations.artifacts, "write_required", write)
    monkeypatch.setattr(page_citations.artifacts, "read_range", load)
    monkeypatch.setattr(page_citations, "_query", lambda *_a, **_k: rows)
    first = page_citations.store_read(owner, chat, page)
    second = page_citations.retained(owner, chat, URL, True, 51)
    assert first and second["version"] != page.version
    assert "Kaminski" in second["markdown"] and second["extent"]["first"] == 51
    assert objects[second["pdf_artifact"]] == DATA
