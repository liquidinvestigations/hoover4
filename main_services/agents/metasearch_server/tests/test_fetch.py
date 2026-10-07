"""`fetch.py`: the route order, the attempts, the cooldown, the rate caps, the browser client,
the source deadline, the diagnostic rows and the health probes.

No network. The clients are replaced by fakes, and the browser server is an httpx mock
transport.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from metasearch_server import fetch as fetch_mod, server, sources as sources_mod
from metasearch_server.fetch import FetchError, FetchResponse


@pytest.fixture(autouse=True)
def no_cooldowns(monkeypatch):
    """Each test starts without cooldowns and with full rate buckets."""
    monkeypatch.setattr(fetch_mod, "_COOLDOWN", {})
    monkeypatch.setattr(fetch_mod, "TOR_ROUTES", {
        "tor-fr": "proxy-fr.example:9050", "tor-de": "proxy-de.example:9050",
        "tor-gb": "proxy-gb.example:9050", "tor-xx": "proxy-xx.example:9050",
    })
    monkeypatch.setattr(fetch_mod, "BROWSER_FETCH_URL", "http://browser.example/internal/fetch")
    monkeypatch.setattr(fetch_mod, "CAPS", {
        name: fetch_mod.RateCap(cap.rate, cap.burst) for name, cap in fetch_mod.CAPS.items()})


@pytest.fixture
def transport(monkeypatch):
    """Send every httpx request of `fetch.py` to `handler`. Returns the requests seen."""
    class Seen(list):
        state: dict

    seen = Seen()
    state = {"handler": None}
    real = httpx.AsyncClient

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["handler"](request)

    def client(**kwargs):
        return real(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(fetch_mod.httpx, "AsyncClient", client)
    monkeypatch.setattr(fetch_mod, "_HTTPX", None)
    seen.state = state
    return seen


@pytest.fixture
def clients(monkeypatch):
    """Replace the wreq, curl_cffi and httpx clients. `answers` maps a route to a status,
    to a `FetchResponse`, or to an exception. Returns the attempts as (client, route, proxy)."""
    class Attempts(list):
        answers: dict[str, object]

    attempts = Attempts()
    answers: dict[str, object] = {}

    def fake(client_name):
        async def send(*args):
            proxy = args[0] if client_name != "curl" else args[1]
            route = "direct" if proxy is None else next(
                name for name, address in fetch_mod.TOR_ROUTES.items() if proxy.endswith(address))
            attempts.append((client_name, route, proxy))
            answer = answers.get(route, 200)
            if isinstance(answer, BaseException):
                raise answer
            if isinstance(answer, FetchResponse):
                return answer
            return FetchResponse(status=int(answer), text="<html>ok</html>",
                                 url="https://remote.example/")
        return send

    monkeypatch.setattr(fetch_mod, "_send_httpx", fake("httpx"))
    monkeypatch.setattr(fetch_mod, "_send_wreq", fake("wreq"))
    monkeypatch.setattr(fetch_mod, "_send_curl", fake("curl"))
    attempts.answers = answers
    return attempts


def _answer(**fields) -> httpx.Response:
    body = {"status": 0, "url": "", "content_type": "", "body": "", "truncated": False,
            "error": "", "error_kind": "", "slot_wait_s": 0.0, **fields}
    return httpx.Response(200, json=body)


def _run(coroutine):
    return asyncio.run(coroutine)


class TestRoutes:
    def test_each_source_names_a_known_client_route_order_and_cap(self):
        for name, transport in fetch_mod.TRANSPORTS.items():
            assert transport.client in (fetch_mod.WREQ, fetch_mod.CURL_CHROME,
                                        fetch_mod.CURL_EDGE, fetch_mod.HTTPX, fetch_mod.BROWSER)
            assert transport.routes in (fetch_mod.DIRECT_ONLY, fetch_mod.DIRECT_THEN_TOR,
                                        fetch_mod.TOR_ONLY)
            assert transport.cap == "" or transport.cap in fetch_mod.CAPS, name

    def test_every_registered_source_has_a_transport(self):
        assert set(sources_mod.SOURCES) <= set(fetch_mod.TRANSPORTS)

    def test_a_direct_answer_is_used_as_it_is(self, clients):
        out = _run(fetch_mod.fetch("brave", "https://search.brave.com/search?q=x", timeout=8))
        assert (out.status, out.route) == (200, "direct")
        assert clients == [("wreq", "direct", None)]

    def test_a_block_moves_to_a_tor_route_with_a_new_socks_user_name(self, clients):
        clients.answers["direct"] = 429
        out = _run(fetch_mod.fetch("brave", "https://search.brave.com/search?q=x", timeout=8))
        assert out.route in fetch_mod.TOR_ROUTES
        assert [route for _, route, _ in clients] == ["direct", out.route]
        proxy = clients[1][2]
        assert proxy.startswith("socks5h://") and proxy.endswith(fetch_mod.TOR_ROUTES[out.route])

    def test_each_attempt_has_its_own_circuit(self, clients):
        clients.answers.update({"direct": 403, **{r: 403 for r in fetch_mod.TOR_ROUTES}})
        with pytest.raises(FetchError):
            _run(fetch_mod.fetch("brave", "https://search.brave.com/", timeout=8))
        users = [proxy.split("//", 1)[1].split(":", 1)[0] for _, _, proxy in clients if proxy]
        assert len(users) == 2 and len(set(users)) == 2

    def test_a_given_circuit_keeps_its_socks_user_name(self, clients):
        clients.answers["direct"] = 429
        _run(fetch_mod.fetch("ddg_news", "https://duckduckgo.com/?q=x", timeout=8,
                             circuit="abc"))
        assert clients[1][2].startswith("socks5h://abc:x@")

    def test_at_most_three_routes_are_tried_and_each_cause_is_named(self, clients):
        clients.answers.update({"direct": 429, **{r: 403 for r in fetch_mod.TOR_ROUTES}})
        with pytest.raises(FetchError) as caught:
            _run(fetch_mod.fetch("brave", "https://search.brave.com/", timeout=8))
        assert len(clients) == fetch_mod.MAX_ATTEMPTS == 3
        message = str(caught.value)
        assert message.startswith("direct: HTTP 429; tor-") and message.count("HTTP 403") == 2

    def test_a_blocked_route_is_skipped_for_that_host_until_its_cooldown_ends(self, clients):
        clients.answers["direct"] = 429
        _run(fetch_mod.fetch("brave", "https://search.brave.com/a", timeout=8))
        clients.clear()
        out = _run(fetch_mod.fetch("brave", "https://search.brave.com/b", timeout=8))
        assert clients[0][1] != "direct" and out.route != "direct"
        # Another host still gets the direct route.
        clients.clear()
        clients.answers["direct"] = 200
        _run(fetch_mod.fetch("brave", "https://other.example/", timeout=8))
        assert clients[0][1] == "direct"
        assert "direct search.brave.com" in fetch_mod.cooldowns()

    def test_a_transport_failure_moves_on_without_a_cooldown(self, clients):
        clients.answers["direct"] = ConnectionError("refused")
        out = _run(fetch_mod.fetch("wikipedia", "https://en.wikipedia.org/w/api.php",
                                   timeout=8))
        assert out.route != "direct" and fetch_mod.cooldowns() == {}

    def test_every_route_in_cooldown_is_named(self, clients, monkeypatch):
        now = time.monotonic()
        for route in ["direct", *fetch_mod.TOR_ROUTES]:
            fetch_mod._COOLDOWN[(route, "search.brave.com")] = now + 100
        with pytest.raises(FetchError, match="every route is in cooldown for search.brave.com"):
            _run(fetch_mod.fetch("brave", "https://search.brave.com/", timeout=8))
        assert clients == []

    def test_a_tor_only_source_never_goes_direct(self, clients, monkeypatch):
        monkeypatch.setitem(fetch_mod.TRANSPORTS, "ddg_news",
                            fetch_mod.Transport(fetch_mod.CURL_CHROME, fetch_mod.TOR_ONLY))
        clients.answers.update({r: 403 for r in fetch_mod.TOR_ROUTES})
        with pytest.raises(FetchError):
            _run(fetch_mod.fetch("ddg_news", "https://duckduckgo.com/news.js", timeout=8))
        assert "direct" not in [route for _, route, _ in clients] and len(clients) == 3

    def test_a_preferred_route_goes_first(self, clients):
        _run(fetch_mod.fetch("ddg_news", "https://duckduckgo.com/news.js", timeout=8,
                             prefer="tor-gb"))
        assert clients[0][1] == "tor-gb"

    def test_a_direct_only_source_has_no_cooldown(self, clients):
        clients.answers["direct"] = 429
        with pytest.raises(FetchError, match="direct: HTTP 429"):
            _run(fetch_mod.fetch("mojeek", "https://www.mojeek.com/search?q=x", timeout=8))
        assert fetch_mod.cooldowns() == {}
        with pytest.raises(FetchError, match="direct: HTTP 429"):
            _run(fetch_mod.fetch("mojeek", "https://www.mojeek.com/search?q=x", timeout=8))
        assert len(clients) == 2

    def test_the_clients_of_the_sources(self, clients):
        for source, client in (("yahoo", "curl"), ("bing", "curl"), ("ddg", "wreq"),
                               ("crossref", "httpx"), ("archive_today", "wreq")):
            clients.clear()
            _run(fetch_mod.fetch(source, "https://remote.example/", timeout=8))
            assert clients[0][0] == client, source

    def test_params_are_added_to_the_url(self, clients, monkeypatch):
        seen = []

        async def send(proxy, method, url, *rest):
            seen.append(url)
            return FetchResponse(status=200, text="", url=url)

        monkeypatch.setattr(fetch_mod, "_send_httpx", send)
        _run(fetch_mod.fetch("crossref", "https://api.crossref.org/works",
                             params={"query": "a b", "rows": "5"}, timeout=8))
        assert seen == ["https://api.crossref.org/works?query=a+b&rows=5"]

    def test_a_spent_deadline_sends_nothing(self, clients):
        async def run():
            with fetch_mod.source_deadline(time.monotonic() + 0.1):
                await fetch_mod.fetch("crossref", "https://api.crossref.org/", timeout=8)

        with pytest.raises(FetchError, match="no time was left"):
            _run(run())
        assert clients == []

    def test_the_route_of_each_answer_is_recorded(self, clients):
        clients.answers["direct"] = 429

        async def run():
            with fetch_mod.record_routes() as routes:
                await fetch_mod.fetch("wikidata", "https://www.wikidata.org/", timeout=8)
            return routes

        routes = _run(run())
        assert len(routes) == 1 and routes[0] in fetch_mod.TOR_ROUTES


class TestBlocks:
    @pytest.mark.parametrize("status", [403, 429, 451, 500, 503])
    def test_a_refusal_status_is_a_block(self, status):
        assert fetch_mod.block_reason(FetchResponse(status, "", "https://a.example/")) == \
            f"HTTP {status}"

    def test_the_duckduckgo_challenge_is_a_block(self):
        assert fetch_mod.block_reason(FetchResponse(202, "", "https://a.example/")).startswith(
            "HTTP 202")
        page = '<div class="anomaly-modal__title">Select all squares</div>'
        assert "anomaly-modal" in fetch_mod.block_reason(
            FetchResponse(200, page, "https://html.duckduckgo.com/html/"))

    def test_a_google_sorry_page_is_a_block(self):
        assert fetch_mod.block_reason(
            FetchResponse(200, "", "https://www.google.com/sorry/index?continue=x"))

    def test_an_ordinary_page_is_not_a_block(self):
        assert fetch_mod.block_reason(FetchResponse(200, "<p>results</p>", "https://a/")) == ""
        assert fetch_mod.block_reason(FetchResponse(404, "", "https://a/")) == ""


class TestRateCaps:
    def test_the_burst_passes_and_the_next_request_waits(self):
        cap = fetch_mod.RateCap(rate=20.0, burst=3)

        async def run():
            started = time.monotonic()
            for _ in range(4):
                assert await cap.take(time.monotonic() + 5)
            return time.monotonic() - started

        assert 0.03 < _run(run()) < 1.0

    def test_no_token_before_the_deadline_is_refused_at_once(self):
        cap = fetch_mod.RateCap(rate=0.1, burst=1)

        async def run():
            assert await cap.take(time.monotonic() + 5)
            started = time.monotonic()
            assert not await cap.take(time.monotonic() + 1)
            return time.monotonic() - started

        assert _run(run()) < 0.1

    def test_a_capped_source_names_the_cap(self, clients, monkeypatch):
        monkeypatch.setitem(fetch_mod.CAPS, "brave", fetch_mod.RateCap(rate=0.01, burst=1))

        async def run():
            await fetch_mod.fetch("brave", "https://search.brave.com/a", timeout=8)
            with fetch_mod.source_deadline(time.monotonic() + 3):
                await fetch_mod.fetch("brave", "https://search.brave.com/b", timeout=8)

        with pytest.raises(FetchError, match="rate cap of brave"):
            _run(run())
        assert len(clients) == 1

    def test_the_duckduckgo_sources_share_one_cap(self):
        names = {fetch_mod.TRANSPORTS[n].cap for n in ("ddg", "ddg_api", "ddg_news")}
        assert names == {"duckduckgo"}
        assert fetch_mod.TRANSPORTS["google_goto"].cap != fetch_mod.TRANSPORTS["google"].cap

    def test_the_api_sources_have_no_cap(self):
        for name in ("crossref", "wikipedia", "wikidata"):
            assert fetch_mod.TRANSPORTS[name].cap == ""
            assert fetch_mod.TRANSPORTS[name].routes == fetch_mod.DIRECT_THEN_TOR


class TestBrowserClient:
    """Only `google` uses the browser fetch endpoint."""

    def test_the_request_goes_to_the_browser_endpoint(self, transport):
        transport.state["handler"] = lambda r: _answer(
            status=200, url="https://www.google.com/search?q=x", body="<html></html>")
        out = _run(fetch_mod.fetch("google", "https://www.google.com/search",
                                   params={"q": "x y"}, timeout=8))
        assert (out.status, out.route) == (200, "direct")
        request = transport[0]
        assert str(request.url) == fetch_mod.BROWSER_FETCH_URL and request.method == "POST"
        sent = json.loads(request.content)
        assert 6.5 < sent.pop("timeout_s") <= 8.0
        assert sent == {"url": "https://www.google.com/search?q=x+y", "method": "GET",
                        "params": {}, "headers": {}, "body": "dom"}

    def test_no_slot_is_a_fetch_error_that_names_it(self, transport):
        transport.state["handler"] = lambda r: _answer(
            error_kind="no_slot",
            error="no free tab of the _metasearch browser within 7.5 s: all 4 slots were in use")
        with pytest.raises(FetchError, match="no free tab of the _metasearch browser"):
            _run(fetch_mod.fetch("google", "https://www.google.com/", timeout=8))

    def test_an_endpoint_that_does_not_answer_is_a_fetch_error(self, transport):
        def refuse(request):
            raise httpx.ConnectError("connection refused")

        transport.state["handler"] = refuse
        with pytest.raises(FetchError, match="did not answer"):
            _run(fetch_mod.fetch("google", "https://www.google.com/", timeout=8))

    def test_a_refusal_of_the_endpoint_is_a_fetch_error(self, transport):
        transport.state["handler"] = lambda r: httpx.Response(
            403, json={"error": "only a client on 127.0.0.1", "error_kind": "refused"})
        with pytest.raises(FetchError, match="refused"):
            _run(fetch_mod.fetch("google", "https://www.google.com/", timeout=8))

    def test_the_source_deadline_shortens_the_browser_timeout(self, transport):
        transport.state["handler"] = lambda r: _answer(status=200, body="ok")

        async def run():
            with fetch_mod.source_deadline(time.monotonic() + 3.0):
                await fetch_mod.fetch("google", "https://www.google.com/", timeout=8)

        _run(run())
        timeout_s = json.loads(transport[0].content)["timeout_s"]
        assert 1.5 < timeout_s <= 3.0 - fetch_mod.DEADLINE_MARGIN_S

    def test_one_client_serves_the_fetches_of_a_loop(self, transport):
        transport.state["handler"] = lambda r: _answer(status=200, body="ok")

        async def run():
            await fetch_mod.fetch("google", "https://www.google.com/1", timeout=8)
            first = fetch_mod._HTTPX[1]
            await fetch_mod.fetch("google", "https://www.google.com/2", timeout=8)
            return first is fetch_mod._HTTPX[1]

        assert _run(run()) and len(transport) == 2


class TestSlotWaitInFanOut:
    def test_a_source_without_a_slot_names_it_in_its_reason(self, monkeypatch, transport):
        """The browser answers no_slot before the source deadline, so the reason is the
        slot wait and not a timeout."""
        sent = []

        def no_slot(request):
            budget = json.loads(request.content)["timeout_s"]
            sent.append(budget)
            return _answer(error_kind="no_slot",
                           error=f"no free tab of the _metasearch browser within {budget:g} s: "
                                 "all 4 slots were in use")

        transport.state["handler"] = no_slot
        monkeypatch.setattr(sources_mod, "SOURCE_TIMEOUT", 2.0)
        _, _, degraded, reasons, routes = _run(sources_mod.fetch_all("q", ["google"]))
        assert degraded == ["google"] and routes == {"google": ""}
        assert "no free tab of the _metasearch browser" in reasons["google"]
        assert sent and sent[0] <= 2.0 - fetch_mod.DEADLINE_MARGIN_S

    def test_the_fan_out_deadline_also_limits_the_fetch(self, monkeypatch, transport):
        sent = []

        def record(request):
            sent.append(json.loads(request.content)["timeout_s"])
            return _answer(status=200, body="<html></html>")

        transport.state["handler"] = record
        monkeypatch.setattr(sources_mod, "SOURCE_TIMEOUT", 8.0)
        _run(sources_mod.fetch_all("q", ["google"], overall_timeout=2.0))
        assert sent and sent[0] <= 2.0 - fetch_mod.DEADLINE_MARGIN_S


class TestGdeltPacing:
    def test_a_second_request_inside_the_gap_is_skipped_at_once(self, monkeypatch):
        calls = []

        async def request(query, max_results, timelimit):
            calls.append(query)
            return []

        monkeypatch.setattr(sources_mod, "_gdelt_request", request)
        monkeypatch.setattr(sources_mod, "_GDELT_PACE", {"busy": False, "next": 0.0})
        assert _run(sources_mod._fetch_gdelt("a", 5, None)) == []
        with pytest.raises(sources_mod.SourceUnavailable, match="gdelt paced"):
            _run(sources_mod._fetch_gdelt("b", 5, None))
        assert calls == ["a"]

    def test_one_request_in_flight(self, monkeypatch):
        monkeypatch.setattr(sources_mod, "_GDELT_PACE", {"busy": True, "next": 0.0})
        with pytest.raises(sources_mod.SourceUnavailable, match="another GDELT request"):
            _run(sources_mod._fetch_gdelt("a", 5, None))


class TestDiagnosticRows:
    @staticmethod
    def _rows(monkeypatch, diagnostics: bool) -> list[dict]:
        monkeypatch.setattr(server, "DIAGNOSTICS", diagnostics)
        response = server.WebSearchResponse(
            success=True, query="q", queries=["q"],
            results=[server.WebResult(title="t", url="https://a.example/", sources=["ddg", "yahoo"],
                                      kind="web", rrf_rank=2, rrf_score=0.03)])
        return response.model_dump()["results"]

    def test_the_rows_carry_the_ranking_fields_with_diagnostics(self, monkeypatch):
        row = self._rows(monkeypatch, True)[0]
        assert {k: row[k] for k in ("sources", "kind", "rrf_rank", "rrf_score")} == {
            "sources": ["ddg", "yahoo"], "kind": "web", "rrf_rank": 2, "rrf_score": 0.03}

    def test_the_rows_stay_short_without_diagnostics(self, monkeypatch):
        row = self._rows(monkeypatch, False)[0]
        assert not {"sources", "rrf_rank", "rrf_score"} & set(row)


class TestFailureReasons:
    """Every answer names each source without results, with its reason."""

    def test_each_answer_has_the_reasons_of_the_degraded_sources(self, monkeypatch):
        monkeypatch.setattr(server, "DIAGNOSTICS", False)
        response = server.WebSearchResponse(
            success=True, query="q", queries=["q"],
            results=[server.WebResult(title="t", url="https://a.example/")],
            degraded=["brave", "gdelt"],
            degraded_reasons={"brave": "direct: HTTP 429; tor-de: HTTP 429", "gdelt": "x" * 500})
        out = response.model_dump()
        assert out["degraded_reasons"]["brave"] == "direct: HTTP 429; tor-de: HTTP 429"
        assert len(out["degraded_reasons"]["gdelt"]) == server.REASON_CHARS
        assert "note" not in out and "no_results_from" not in out

    def test_an_answer_without_degraded_sources_has_no_reasons(self):
        response = server.WebSearchResponse(success=True, query="q", queries=["q"])
        assert "degraded_reasons" not in response.model_dump()

    def test_the_reasons_are_grouped_and_shortened(self):
        note = server.no_result_note({"ddg": "boom", "brave": "boom", "gdelt": "x" * 500})
        lines = note.splitlines()
        assert lines[0].startswith("No source returned a result.")
        assert lines[1] == "- boom (ddg, brave)"
        assert len(lines[2]) < server.REASON_CHARS + 20 and lines[2].endswith("... (gdelt)")

    def test_no_reason_still_says_that_nothing_was_found(self):
        assert server.no_result_note({}) == "No source returned a result for these queries."

    def test_a_closed_browser_port_reaches_the_agent(self, monkeypatch):
        """The case of the review: the browser fetch endpoint is a closed port."""
        monkeypatch.setattr(fetch_mod, "BROWSER_FETCH_URL", "http://127.0.0.1:1/internal/fetch")
        monkeypatch.setattr(fetch_mod, "_HTTPX", None)
        monkeypatch.setattr(server, "DIAGNOSTICS", False)
        tool = getattr(server.web_search, "fn", server.web_search)
        out = _run(tool(queries=["danube river length"], sources=["google"])).model_dump()
        assert out["results"] == []
        assert "http://127.0.0.1:1/internal/fetch did not answer: ConnectError" in (
            out["degraded_reasons"]["google"])
        lines = out["note"].splitlines()
        assert lines[0].startswith("No source returned a result.") and len(lines) == 2


class TestHealthProbe:
    @pytest.fixture(autouse=True)
    def tor_open(self, monkeypatch):
        async def probe():
            return {name: True for name in fetch_mod.TOR_ROUTES}

        monkeypatch.setattr(fetch_mod, "probe_tor_routes", probe)

    def test_a_closed_browser_port_makes_health_degraded(self, monkeypatch):
        monkeypatch.setattr(fetch_mod, "BROWSER_FETCH_URL", "http://127.0.0.1:1/internal/fetch")
        monkeypatch.setattr(fetch_mod, "_HTTPX", None)
        body = json.loads(_run(server.health(None)).body)
        assert body["status"] == "degraded" and body["browser_fetch_ok"] is False
        assert "did not answer: ConnectError" in body["browser_fetch_error"]

    def test_a_refusal_of_the_empty_probe_is_ok(self, transport):
        transport.state["handler"] = lambda r: httpx.Response(
            400, json={"error": "the body must be a JSON object with a string `url`",
                       "error_kind": "refused"})
        body = json.loads(_run(server.health(None)).body)
        assert (body["status"], body["browser_fetch_ok"], body["browser_fetch_error"]) == (
            "ok", True, "")
        assert json.loads(transport[0].content) == {}

    def test_an_answer_without_json_is_not_ok(self, transport):
        transport.state["handler"] = lambda r: httpx.Response(404, text="Not Found")
        body = json.loads(_run(server.health(None)).body)
        assert body["status"] == "degraded" and "HTTP 404" in body["browser_fetch_error"]

    def test_a_closed_tor_port_makes_health_degraded(self, monkeypatch, transport):
        transport.state["handler"] = lambda r: httpx.Response(400, json={"error": "x"})
        monkeypatch.setattr(fetch_mod, "probe_tor_routes", TestHealthProbe._real_probe)
        monkeypatch.setattr(fetch_mod, "TOR_ROUTES", {"tor-test": "127.0.0.1:1"})
        body = json.loads(_run(server.health(None)).body)
        assert body["status"] == "degraded" and body["tor_routes"] == {"tor-test": False}

    _real_probe = staticmethod(fetch_mod.probe_tor_routes)
