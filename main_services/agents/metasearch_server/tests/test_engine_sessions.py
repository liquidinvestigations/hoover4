"""`engine_sessions.py`: the solvers, the solve flows, the Bing cookies and the Google links.

No network. `fetch` is replaced by a fake that answers like the engine.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

from metasearch_server import engine_sessions as es
from metasearch_server.fetch import FetchError, FetchResponse


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(es, "_MOJEEK", es.SolvedCookies("Mojeek ALTCHA"))
    monkeypatch.setattr(es, "_STARTPAGE", es.SolvedCookies("Startpage Anubis"))
    monkeypatch.setattr(es, "_BING", {"cookies": {}, "at": float("-inf")})


def _altcha_challenge(cost: int = 5) -> dict:
    """A challenge whose key prefix is the first byte of the key at counter 7."""
    nonce, salt = "00" * 16, "11" * 16
    key = hashlib.pbkdf2_hmac("sha256", bytes.fromhex(nonce) + (7).to_bytes(4, "big"),
                              bytes.fromhex(salt), cost, 32)
    return {"parameters": {"algorithm": "PBKDF2/SHA-256", "nonce": nonce, "salt": salt,
                           "cost": cost, "keyLength": 32, "keyPrefix": key[:1].hex()},
            "signature": "sig"}


class TestSolvers:
    def test_the_altcha_solution_has_the_key_prefix(self):
        parameters = _altcha_challenge()["parameters"]
        key, counter = es.solve_altcha(parameters)
        assert counter <= 7 and key.startswith(parameters["keyPrefix"])
        expected = hashlib.pbkdf2_hmac("sha256", bytes(16) + counter.to_bytes(4, "big"),
                                       bytes.fromhex("11" * 16), 5, 32)
        assert key == expected.hex()

    @pytest.mark.parametrize("difficulty", [2, 3])
    def test_the_anubis_solution_has_the_leading_zeros(self, difficulty):
        digest, nonce = es.solve_anubis("data", difficulty, 0, 1_000_000)
        assert digest.startswith("0" * difficulty)
        assert digest == hashlib.sha256(f"data{nonce}".encode()).hexdigest()

    def test_the_anubis_search_covers_only_its_chunk(self):
        _, first = es.solve_anubis("data", 2, 0, 1_000_000)
        assert es.solve_anubis("data", 2, 0, first) is None
        _, later = es.solve_anubis("data", 2, first + 1, 1_000_000)
        assert later > first

    def test_the_worker_processes_find_a_solution(self, monkeypatch):
        monkeypatch.setattr(es, "ANUBIS_CHUNK", 1000)
        digest, nonce = asyncio.run(es._solve_anubis_in_pool("data", 3))
        assert digest.startswith("000")
        # The pool closes after the solve, so no idle worker holds memory.
        assert es._POOL is None

    def test_an_anubis_page_gives_its_challenge(self):
        page = ('<script id="anubis_challenge" type="application/json">'
                '{"challenge": {"id": "c1", "randomData": "ab"}, "rules": {"difficulty": 6}}'
                '</script>')
        assert es.anubis_challenge(page) == ("c1", "ab", 6)
        assert es.anubis_challenge("<html></html>") is None


class TestSolveLimits:
    """The remote page sets the work of a challenge, so each solve has limits."""

    def test_the_altcha_search_stops_at_its_deadline_and_at_max_number(self):
        parameters = _altcha_challenge()["parameters"]
        assert es.solve_altcha(parameters, deadline=0.0) is None
        assert es.solve_altcha({**parameters, "keyPrefix": "ffffff", "maxNumber": 50}) is None

    def test_an_altcha_cost_above_the_limit_is_refused_without_work(self, monkeypatch):
        challenge = _altcha_challenge()
        challenge["parameters"]["cost"] = es.MAX_ALTCHA_COST + 1
        engine = FakeEngine({"https://www.mojeek.com/captcha/challenge": FetchResponse(
            200, json.dumps(challenge), "https://www.mojeek.com/captcha/challenge")})
        monkeypatch.setattr(es, "fetch", engine)
        monkeypatch.setattr(es, "solve_altcha", lambda *a: pytest.fail("solved"))
        with pytest.raises(FetchError, match="above the limit"):
            asyncio.run(es._mojeek_solve(8))

    def test_an_anubis_difficulty_above_the_limit_is_refused_without_work(self, monkeypatch):
        page = ('<script id="anubis_challenge" type="application/json">'
                '{"challenge": {"id": "c1", "randomData": "ab"}, "rules": {"difficulty": %d}}'
                '</script>' % (es.MAX_ANUBIS_DIFFICULTY + 1))
        engine = FakeEngine({"https://www.startpage.com/": FetchResponse(200, page, "u")})
        monkeypatch.setattr(es, "fetch", engine)

        async def pool(*args):
            pytest.fail("solved")

        monkeypatch.setattr(es, "_solve_anubis_in_pool", pool)
        with pytest.raises(FetchError, match="difficulty 8 is above the limit 7"):
            asyncio.run(es._startpage_solve(8))

    def test_a_slow_solve_stops_and_the_engine_waits_before_the_next(self, monkeypatch):
        monkeypatch.setattr(es, "SOLVE_TIMEOUT_S", 0.1)
        state = es.SolvedCookies("Test")
        calls = []

        async def slow():
            calls.append(1)
            await asyncio.sleep(5)
            return {}

        with pytest.raises(FetchError, match="no solution within 0.1 s"):
            asyncio.run(es._solve_once(state, 0, slow))
        with pytest.raises(FetchError, match="the next solve can start in"):
            asyncio.run(es._solve_once(state, 0, slow))
        assert calls == [1] and state.generation == 0

    def test_a_timeout_closes_the_anubis_workers(self, monkeypatch):
        monkeypatch.setattr(es, "ANUBIS_CHUNK", 10_000_000)

        async def run():
            await asyncio.wait_for(es._solve_anubis_in_pool("data", 12), 1.0)

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(run())
        assert es._POOL is None


class FakeEngine:
    """A fake `fetch` that records each request and answers from `routes`."""

    def __init__(self, routes):
        self.routes = routes
        self.seen: list[tuple[str, str, dict]] = []

    async def __call__(self, source, url, *, timeout, method="GET", cookies=None, **kw):
        self.seen.append((method, url, dict(cookies or {}), kw))
        await asyncio.sleep(0)
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                return answer(url, dict(cookies or {}), kw) if callable(answer) else answer
        raise FetchError(f"no fake answer for {url}")


class TestMojeek:
    CAPTCHA = FetchResponse(200, '<div class="captcha-wrap"><altcha-widget></div>',
                            "https://www.mojeek.com/search?q=x")
    RESULTS = FetchResponse(200, '<ul class="results-standard"><li><h2><a href="https://a/">A'
                            '</a></h2></li></ul>', "https://www.mojeek.com/search?q=x")

    def _engine(self, monkeypatch):
        challenge = _altcha_challenge()

        def search(url, cookies, kw):
            return self.RESULTS if cookies.get("chllg") == "token" else self.CAPTCHA

        def verify(url, cookies, kw):
            payload = json.loads(base64.b64decode(kw["multipart"]["altcha"]))
            assert payload["challenge"] == challenge and payload["solution"]["derivedKey"]
            return FetchResponse(200, '{"ok":true,"verified":true}', url,
                                 cookies={"chllg": "token"})

        engine = FakeEngine({
            "https://www.mojeek.com/search": search,
            "https://www.mojeek.com/captcha/challenge":
                FetchResponse(200, json.dumps(challenge), "https://www.mojeek.com/captcha/challenge"),
            "https://www.mojeek.com/captcha/verify": verify,
        })
        monkeypatch.setattr(es, "fetch", engine)
        return engine

    def test_a_challenge_is_solved_and_the_search_is_sent_again(self, monkeypatch):
        engine = self._engine(monkeypatch)
        response = asyncio.run(es.mojeek_page("https://www.mojeek.com/search?q=x", 8))
        assert response is self.RESULTS
        assert [url.split("?")[0] for _, url, _, _ in engine.seen] == [
            "https://www.mojeek.com/search", "https://www.mojeek.com/captcha/challenge",
            "https://www.mojeek.com/captcha/verify", "https://www.mojeek.com/search"]
        assert engine.seen[-1][2] == {"lb": "en", "arc": "us", "chllg": "token"}

    def test_the_cookie_is_kept_for_the_next_search(self, monkeypatch):
        engine = self._engine(monkeypatch)
        asyncio.run(es.mojeek_page("https://www.mojeek.com/search?q=x", 8))
        engine.seen.clear()
        asyncio.run(es.mojeek_page("https://www.mojeek.com/search?q=y", 8))
        assert len(engine.seen) == 1

    def test_searches_at_the_same_time_share_one_solve(self, monkeypatch):
        engine = self._engine(monkeypatch)

        async def run():
            return await asyncio.gather(*(es.mojeek_page(f"https://www.mojeek.com/search?q={i}", 8)
                                          for i in range(4)))

        assert all(r is self.RESULTS for r in asyncio.run(run()))
        assert sum(1 for _, url, _, _ in engine.seen if "challenge" in url) == 1

    def test_a_second_challenge_is_returned_to_the_parser(self, monkeypatch):
        engine = self._engine(monkeypatch)
        engine.routes["https://www.mojeek.com/search"] = self.CAPTCHA
        assert asyncio.run(es.mojeek_page("https://www.mojeek.com/search?q=x", 8)) is self.CAPTCHA


class TestStartpage:
    ANUBIS = ('<script id="anubis_challenge" type="application/json">'
              '{"challenge": {"id": "c1", "randomData": "ab"}, "rules": {"difficulty": 2}}'
              '</script>')
    HOME = '<form id="search"><input name="sc" value="SC1"></form>'

    def _engine(self, monkeypatch):
        async def pool(random_data, difficulty):
            return es.solve_anubis(random_data, difficulty, 0, 1_000_000)

        monkeypatch.setattr(es, "_solve_anubis_in_pool", pool)

        def home(url, cookies, kw):
            text = self.HOME if cookies.get("spchal-auth") else self.ANUBIS
            return FetchResponse(200, text, url, cookies={"sp_session": "s"})

        def passed(url, cookies, kw):
            assert kw["params"]["response"].startswith("00")
            assert kw.get("follow_redirects") is False
            return FetchResponse(302, "", url, cookies={"spchal-auth": "auth"})

        def search(url, cookies, kw):
            if not cookies.get("spchal-auth"):
                return FetchResponse(200, self.ANUBIS, url)
            assert kw["data"]["sc"] == "SC1" and kw["data"]["query"] == "q"
            return FetchResponse(200, "results", url)

        engine = FakeEngine({
            "https://www.startpage.com/.within.website/": passed,
            "https://www.startpage.com/sp/search": search,
            "https://www.startpage.com/": home,
        })
        monkeypatch.setattr(es, "fetch", engine)
        return engine

    def test_the_first_search_solves_then_posts_the_query(self, monkeypatch):
        engine = self._engine(monkeypatch)
        response = asyncio.run(es.startpage_page("q", 15))
        assert response.text == "results"
        assert [(m, url.split("?")[0]) for m, url, _, _ in engine.seen] == [
            ("GET", "https://www.startpage.com/"),
            ("GET", "https://www.startpage.com/.within.website/x/cmd/anubis/api/pass-challenge"),
            ("GET", "https://www.startpage.com/"),
            ("POST", "https://www.startpage.com/sp/search")]
        sent = engine.seen[-1][2]
        assert sent["spchal-auth"] == "auth" and sent["sp_session"] == "s"
        assert sent["preferences"] == es.STARTPAGE_PREFERENCES

    def test_a_challenge_answer_to_the_search_solves_again(self, monkeypatch):
        engine = self._engine(monkeypatch)
        es._STARTPAGE.cookies = {"spchal-auth": ""}
        asyncio.run(es.startpage_page("q", 15))
        assert sum(1 for _, url, _, _ in engine.seen if "pass-challenge" in url) == 1
        assert engine.seen[-1][1] == "https://www.startpage.com/sp/search"


class TestStepNames:
    def test_a_failed_request_of_a_flow_names_its_step(self, monkeypatch):
        engine = FakeEngine({"https://www.startpage.com/.within.website/": FetchResponse(
            500, "", "u"), "https://www.startpage.com/": FetchResponse(
            200, TestStartpage.ANUBIS, "u", cookies={"sp_pow": "p"})})

        async def fetch(source, url, **kw):
            answer = await engine(source, url, **kw)
            if answer.status >= 500:
                raise FetchError(f"direct: HTTP {answer.status}")
            return answer

        async def pool(random_data, difficulty):
            return es.solve_anubis(random_data, difficulty, 0, 1_000_000)

        monkeypatch.setattr(es, "fetch", fetch)
        monkeypatch.setattr(es, "_solve_anubis_in_pool", pool)
        with pytest.raises(FetchError, match="^Startpage Anubis pass: direct: HTTP 500$"):
            asyncio.run(es._startpage_solve(8))


class TestBing:
    def test_the_home_cookies_are_fetched_once_and_sent_with_each_search(self, monkeypatch):
        engine = FakeEngine({
            "https://www4.bing.com/search": FetchResponse(200, "page", "https://www4.bing.com/"),
            "https://www4.bing.com/": FetchResponse(200, "", "https://www4.bing.com/",
                                                     cookies={"MUID": "m"}),
        })
        monkeypatch.setattr(es, "fetch", engine)
        for query in ("a", "b"):
            asyncio.run(es.bing_page(f"https://www4.bing.com/search?q={query}&form=QBRE", 8))
        assert [url for _, url, _, _ in engine.seen] == [
            "https://www4.bing.com/", "https://www4.bing.com/search?q=a&form=QBRE",
            "https://www4.bing.com/search?q=b&form=QBRE"]
        assert engine.seen[1][2] == engine.seen[2][2] == {"MUID": "m"}

    def test_a_failed_home_page_still_sends_the_search(self, monkeypatch):
        engine = FakeEngine({"https://www4.bing.com/search": FetchResponse(200, "page", "u")})
        monkeypatch.setattr(es, "fetch", engine)
        assert asyncio.run(es.bing_page("https://www4.bing.com/search?q=a", 8)).text == "page"


class TestGoogleLinks:
    def test_a_redirect_gives_the_target(self):
        answer = FetchResponse(302, "", "https://www.google.com/goto?url=x",
                               headers={"location": "https://dl.acm.org/doi/10.1145/311535.311548"})
        assert es.goto_target(answer) == "https://dl.acm.org/doi/10.1145/311535.311548"

    def test_a_google_target_is_not_a_result(self):
        answer = FetchResponse(302, "", "u", headers={"location": "https://www.google.com/sorry/"})
        assert es.goto_target(answer) == ""

    @pytest.mark.parametrize("target", [
        "http://10.0.0.1/", "http://169.254.169.254/latest/", "http://localhost/mcp",
        "http://[::1]/", "http://intranet/", "https://metadata.google.internal/",
        "http://printer.local/", "file:///etc/passwd"])
    def test_a_target_that_is_not_public_is_refused(self, target):
        answer = FetchResponse(302, "", "u", headers={"location": target})
        assert es.goto_target(answer) == ""

    def test_only_www_google_com_goto_links_are_resolved(self):
        assert es.is_goto_link("https://www.google.com/goto?url=abc")
        for url in ("https://evil.example/goto?url=abc", "https://www.google.com/url?q=x",
                    "http://www.google.com/goto?url=abc", "https://a.example/x/goto?url=b"):
            assert not es.is_goto_link(url), url

    def test_a_refresh_page_gives_the_target(self):
        page = '<meta http-equiv="refresh" content="0;url=https://example.org/a">'
        assert es.goto_target(FetchResponse(200, page, "u")) == "https://example.org/a"

    def test_only_the_first_links_resolve_and_a_failure_keeps_the_link(self, monkeypatch):
        def answer(url, cookies, kw):
            if url.endswith("=bad"):
                raise FetchError("direct: HTTP 429")
            return FetchResponse(302, "", url, headers={"location": f"https://t.example/{url[-1]}"})

        engine = FakeEngine({"https://www.google.com/goto": answer})
        monkeypatch.setattr(es, "fetch", engine)
        urls = ["https://www.google.com/goto?url=bad", "https://direct.example/"] + [
            f"https://www.google.com/goto?url={i}" for i in range(6)]
        out = asyncio.run(es.resolve_google_links(urls, 8))
        assert out[:2] == urls[:2]
        assert out[2:6] == [f"https://t.example/{i}" for i in range(4)]
        assert out[6:] == urls[6:]
        assert len(engine.seen) == es.GOOGLE_GOTO_LIMIT
