"""`POST /internal/fetch` and the special session `_metasearch`.

None of this needs Chromium. The tab is a fake that answers the CDP commands through the
command parsers of `nodriver.cdp` and sends the `Network` events of a navigation.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from browser_use_server import internal_fetch, router as router_mod, server
from browser_use_server.special_browser import SlotWaitTimeout


def _run_cdp(command, answer: dict):
    try:
        command.send(answer)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("the command did not finish")


class NetTab:
    """A tab that answers `Network.enable`, `Network.setExtraHTTPHeaders`, `Page.navigate`
    and `Network.getResponseBody`.

    A navigation sends one `Network.responseReceived` event for the main document, with
    the id `request_id`, and first one event for each of `extra_documents`. `finish` is
    `""` for `loadingFinished`, a text for `loadingFailed`, or None for no end event.
    """

    def __init__(self, status=200, url="https://a.example/", headers=None, body="hello",
                 encoded=False, error_text=None, download=False, finish="", no_body=False,
                 hang=False, request_id="L1", extra_documents=()):
        self.status = status
        self.url = url
        self.headers = headers if headers is not None else {"Content-Type": "text/html"}
        self.body = body
        self.encoded = encoded
        self.error_text = error_text
        self.download = download
        self.finish = finish
        self.no_body = no_body
        self.hang = hang
        self.request_id = request_id
        self.extra_documents = extra_documents
        self.handlers: dict[type, list] = {}
        self.sent: list[tuple[str, dict]] = []

    def add_handler(self, event_type, callback):
        self.handlers.setdefault(event_type, []).append(callback)

    def emit(self, event_type, event):
        for callback in self.handlers.get(event_type, []):
            callback(event, self)

    def _document(self, request_id, frame, status, url, headers):
        from nodriver import cdp

        self.emit(cdp.network.ResponseReceived, SimpleNamespace(
            request_id=request_id, frame_id=frame, type_=cdp.network.ResourceType.DOCUMENT,
            response=SimpleNamespace(status=status, url=url, headers=headers,
                                     mime_type="text/html", charset="utf-8")))

    async def send(self, command):
        from nodriver import cdp

        cmd = next(command)
        method, params = cmd["method"], cmd.get("params", {})
        self.sent.append((method, params))
        if method in ("Network.enable", "Network.setExtraHTTPHeaders"):
            return _run_cdp(command, {})
        if method == "Page.navigate":
            if self.hang:
                await asyncio.sleep(60)
            for other_id, frame in self.extra_documents:
                self._document(other_id, frame, 200, "https://frame.example/", {})
            self._document(self.request_id, "F", self.status, self.url, self.headers)
            if self.finish == "":
                self.emit(cdp.network.LoadingFinished,
                          SimpleNamespace(request_id=self.request_id))
            elif self.finish is not None:
                self.emit(cdp.network.LoadingFailed,
                          SimpleNamespace(request_id=self.request_id, error_text=self.finish))
            answer = {"frameId": "F", "loaderId": "L1", "isDownload": self.download}
            if self.error_text:
                answer["errorText"] = self.error_text
            return _run_cdp(command, answer)
        assert method == "Network.getResponseBody", method
        assert params["requestId"] == self.request_id
        if self.no_body:
            raise RuntimeError("No resource with given identifier found")
        return _run_cdp(command, {"body": self.body, "base64Encoded": self.encoded})


def _replay(cmd: dict, command):
    """A command generator that gives `cmd` again, then the rest of `command`."""
    def again():
        answer = yield cmd
        try:
            command.send(answer)
        except StopIteration as stop:
            return stop.value
    return again()


class FakePool:
    """A special session with one tab. `full` makes a lease time out like a full queue.
    `died` makes the browser of the lease stopped."""

    name = "_metasearch"
    slots = 16

    def __init__(self, tab=None, full=False, died=False, slot_wait_s=0.0, tab_open_s=0.0):
        self.tab = tab or NetTab()
        self.full = full
        self.died = died
        self.leases = 0
        self.slot_wait_s = slot_wait_s
        self.tab_open_s = tab_open_s

    @contextlib.asynccontextmanager
    async def lease(self, deadline):
        if self.full:
            raise SlotWaitTimeout
        self.leases += 1
        died = asyncio.Event()
        if self.died:
            died.set()
        yield SimpleNamespace(tab=self.tab, died=died, cdp_port=0,
                              slot_wait_s=self.slot_wait_s, tab_open_s=self.tab_open_s)


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    monkeypatch.setattr(internal_fetch, "check_url", lambda url: url)


def _fetch(pool, url="https://a.example/", **kwargs):
    return asyncio.run(internal_fetch.fetch(pool, url, **kwargs))


class TestBuildUrlAndHeaders:
    def test_params_join_the_query_in_order(self):
        assert internal_fetch.build_url("https://a.example/s", {"q": "a b", "n": 2}) == \
            "https://a.example/s?q=a+b&n=2"
        assert internal_fetch.build_url("https://a.example/s?x=1", {"q": "é"}) == \
            "https://a.example/s?x=1&q=%C3%A9"
        assert internal_fetch.build_url("https://a.example/s", None) == "https://a.example/s"

    def test_only_accept_language_passes_and_referer_becomes_the_referrer(self):
        sent, referrer = internal_fetch.passed_headers({
            "User-Agent": "script/1.0", "accept": "application/json",
            "Accept-Language": "en", "Referer": "https://duckduckgo.com/", "Cookie": "a=b"})
        assert sent == {"Accept-Language": "en"}
        assert referrer == "https://duckduckgo.com/"


class TestFetch:
    def test_returns_the_raw_body_status_and_final_url(self):
        tab = NetTab(status=429, url="https://b.example/final",
                     headers={"content-type": "application/json; charset=utf-8"},
                     body='{"error": "slow down"}')
        out = _fetch(FakePool(tab), params={"q": "x"}, headers={
            "Accept": "application/json", "Accept-Language": "en",
            "Referer": "https://r.example/"})
        assert (out.status, out.url, out.error) == (429, "https://b.example/final", "")
        assert out.content_type == "application/json; charset=utf-8"
        assert json.loads(out.body) == {"error": "slow down"}
        methods = dict(tab.sent)
        assert methods["Page.navigate"]["url"] == "https://a.example/?q=x"
        assert methods["Page.navigate"]["referrer"] == "https://r.example/"
        assert methods["Network.setExtraHTTPHeaders"]["headers"] == {"Accept-Language": "en"}

    def test_a_base64_body_is_decoded(self):
        tab = NetTab(body=base64.b64encode("café".encode()).decode(), encoded=True)
        assert _fetch(FakePool(tab)).body == "café"

    def test_a_long_body_is_cut(self, monkeypatch):
        monkeypatch.setattr(internal_fetch, "MAX_BODY_BYTES", 4)
        out = _fetch(FakePool(NetTab(body="abcdefgh")))
        assert (out.body, out.truncated) == ("abcd", True)

    def test_an_error_status_without_a_body_keeps_its_status(self):
        # Chromium shows its own error page. Its body is not the server's body.
        tab = NetTab(status=404, error_text="net::ERR_HTTP_RESPONSE_CODE_FAILURE",
                     body="<html>chromium error page</html>")
        out = _fetch(FakePool(tab))
        assert (out.status, out.body, out.error) == (404, "", "")
        assert "Network.getResponseBody" not in dict(tab.sent)

    def test_a_body_that_did_not_arrive_is_a_navigation_error(self):
        out = _fetch(FakePool(NetTab(finish="net::ERR_CONNECTION_RESET", no_body=True)))
        assert out.status == 200 and out.error_kind == internal_fetch.NAVIGATION
        assert "ERR_CONNECTION_RESET" in out.error

    def test_a_body_that_chromium_no_longer_holds_is_a_navigation_error(self):
        # `loadingFinished` came, but `Network.getResponseBody` fails, for example because
        # the body was larger than the buffer of the tab.
        out = _fetch(FakePool(NetTab(no_body=True)))
        assert out.status == 200 and out.body == ""
        assert out.error_kind == internal_fetch.NAVIGATION
        assert "the body is not available" in out.error

    def test_dom_gives_the_html_of_the_document_that_a_script_loaded(self, monkeypatch):
        """Google's first search page loads the same search again with a script. The body
        of the first document is then gone, so `raw` fails. `dom` reads the last one."""
        from nodriver import cdp

        monkeypatch.setattr(internal_fetch, "DOM_QUIET_S", 0.05)
        monkeypatch.setattr(internal_fetch, "DOM_POLL_S", 0.01)

        class ScriptRedirect(NetTab):
            async def send(self, command):
                cmd = next(command)
                if cmd["method"] == "Runtime.evaluate":
                    expression = cmd["params"]["expression"]
                    value = ("complete" if expression == "document.readyState"
                             else "<html><body>results</body></html>")
                    self.sent.append(("Runtime.evaluate", {"expression": expression}))
                    return _run_cdp(command, {"result": {"type": "string", "value": value}})
                answer = await NetTab.send(self, _replay(cmd, command))
                if cmd["method"] == "Page.navigate":
                    async def redirect():
                        await asyncio.sleep(0.02)
                        self._document("L2", "F", 200, "https://a.example/?q=x&sei=1", {})
                        self.emit(cdp.network.LoadingFinished, SimpleNamespace(request_id="L2"))
                    asyncio.ensure_future(redirect())
                return answer

        tab = ScriptRedirect(no_body=True)
        out = _fetch(FakePool(tab), body=internal_fetch.DOM_BODY)
        assert (out.status, out.url, out.error) == (200, "https://a.example/?q=x&sei=1", "")
        assert out.body == "<html><body>results</body></html>"
        assert "Network.getResponseBody" not in dict(tab.sent)

    @pytest.mark.parametrize("status", [204, 304])
    def test_a_status_without_a_body_is_not_an_error(self, status):
        out = _fetch(FakePool(NetTab(status=status, no_body=True)))
        assert (out.status, out.body, out.error, out.error_kind) == (status, "", "", "")

    def test_the_main_document_is_matched_by_its_frame_when_the_ids_differ(self):
        tab = NetTab(request_id="R9", body="main", extra_documents=[("R1", "CHILD")])
        out = _fetch(FakePool(tab))
        assert (out.status, out.body) == (200, "main")

    def test_a_failed_navigation_is_a_navigation_error(self):
        class NoResponse(NetTab):
            def emit(self, event_type, event):
                return None

        out = _fetch(FakePool(NoResponse(error_text="net::ERR_NAME_NOT_RESOLVED")))
        assert out.error_kind == internal_fetch.NAVIGATION
        assert "ERR_NAME_NOT_RESOLVED" in out.error

    def test_a_download_is_refused(self):
        out = _fetch(FakePool(NetTab(download=True)))
        assert out.error_kind == internal_fetch.NAVIGATION and "download" in out.error

    def test_a_full_queue_is_named_as_no_slot(self):
        out = _fetch(FakePool(full=True), timeout_s=0.5)
        assert out.error_kind == internal_fetch.NO_SLOT
        assert "no free tab of the _metasearch browser within 0.5 s" in out.error
        assert "16 slots" in out.error

    def test_the_slot_wait_and_the_tab_opening_are_reported_apart(self):
        out = _fetch(FakePool(slot_wait_s=0.25, tab_open_s=1.5))
        assert (out.slot_wait_s, out.tab_open_s) == (0.25, 1.5)
        out = _fetch(FakePool(NetTab(hang=True), slot_wait_s=0.0, tab_open_s=1.5),
                     timeout_s=0.2)
        assert "after a wait of 0.0 s for a free tab and 1.5 s to open the tab" in out.error

    def test_the_deadline_ends_a_request_that_does_not_answer(self):
        out = _fetch(FakePool(NetTab(hang=True)), timeout_s=0.2)
        assert out.error_kind == internal_fetch.TIMEOUT

    def test_a_document_that_never_ends_loading_times_out(self):
        out = _fetch(FakePool(NetTab(finish=None)), timeout_s=0.2)
        assert out.error_kind == internal_fetch.TIMEOUT

    def test_a_stopped_browser_is_reported(self):
        out = _fetch(FakePool(NetTab(hang=True), died=True), timeout_s=5)
        assert out.error_kind == internal_fetch.BROWSER and "stopped" in out.error

    def test_a_refused_url_takes_no_slot(self, monkeypatch):
        def refuse(url):
            raise internal_fetch.UrlNotAllowed("internal")

        monkeypatch.setattr(internal_fetch, "check_url", refuse)
        pool = FakePool()
        out = _fetch(pool, "http://metadata.google.internal/")
        assert out.error_kind == internal_fetch.REFUSED and pool.leases == 0

    def test_a_host_name_that_cannot_be_encoded_is_refused(self, monkeypatch):
        from browser_use_server import urlcheck

        monkeypatch.setattr(internal_fetch, "check_url", urlcheck.check_url)
        pool = FakePool()
        out = _fetch(pool, f"https://{'a' * 70}.example/")
        assert out.error_kind == internal_fetch.REFUSED and pool.leases == 0

    def test_a_url_that_does_not_parse_is_refused(self):
        out = _fetch(FakePool(), "http://[::1/", params={"q": "x"})
        assert out.error_kind == internal_fetch.REFUSED

    def test_the_url_check_runs_off_the_event_loop(self, monkeypatch):
        import threading

        threads = []

        def check(url):
            threads.append(threading.get_ident())
            return url

        monkeypatch.setattr(internal_fetch, "check_url", check)
        _fetch(FakePool())
        assert threads and threads[0] != threading.get_ident()

    def test_the_answer_comes_after_the_deadline_also_when_no_tab_opens(self, monkeypatch):
        monkeypatch.setattr(internal_fetch, "ANSWER_GRACE_S", 0.1)

        class NoTab(FakePool):
            @contextlib.asynccontextmanager
            async def lease(self, deadline):
                await asyncio.sleep(60)
                yield None

        async def run():
            started = asyncio.get_running_loop().time()
            out = await internal_fetch.fetch(NoTab(), "https://a.example/", timeout_s=0.2)
            return out, asyncio.get_running_loop().time() - started

        out, took = asyncio.run(run())
        assert out.error_kind == internal_fetch.TIMEOUT and took < 1

    def test_the_timeout_is_capped(self, monkeypatch):
        monkeypatch.setattr(internal_fetch, "MAX_TIMEOUT_S", 2.0)
        out = _fetch(FakePool(full=True), timeout_s=500)
        assert "within 2 s" in out.error
