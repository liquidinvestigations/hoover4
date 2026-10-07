"""Tests for URL normalisation, RRF and the degraded-engine reporting.

The scrapers themselves are not tested against the live web. That would make the suite
fail whenever an engine changes its HTML, which is precisely the event the `degraded`
field exists to report at runtime. What is tested here is the merging logic, which is
where a silent wrong answer would actually hide, plus each parser against a captured
fragment so a selector edit is caught.
"""

from pathlib import Path

import pytest

from metasearch_server.engines import (
    ENGINES,
    SearchResult,
    configured_engines,
    normalise_url,
    reciprocal_rank_fusion,
    unwrap_tracking_url,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestNormaliseUrl:
    def test_scheme_and_www_do_not_distinguish(self):
        assert normalise_url("https://www.example.com/a") == normalise_url("http://example.com/a")

    def test_tracking_parameters_are_stripped(self):
        assert normalise_url("https://x.com/p?utm_source=ddg&id=7") == normalise_url(
            "https://x.com/p?id=7"
        )

    def test_real_query_parameters_are_kept(self):
        assert normalise_url("https://x.com/p?id=7") != normalise_url("https://x.com/p?id=8")

    def test_fragment_and_trailing_slash_are_ignored(self):
        assert normalise_url("https://x.com/a/#section") == normalise_url("https://x.com/a")

    def test_parameter_order_does_not_matter(self):
        assert normalise_url("https://x.com/p?b=2&a=1") == normalise_url("https://x.com/p?a=1&b=2")


class TestReciprocalRankFusion:
    def test_agreement_outranks_a_single_engines_top_hit(self):
        """The whole reason to run a metasearch: two engines at rank 3 beat one at rank 1."""
        merged = reciprocal_rank_fusion(
            {
                "a": [SearchResult("solo", "https://solo.example")],
                "b": [
                    SearchResult("x", "https://x.example"),
                    SearchResult("y", "https://y.example"),
                    SearchResult("agreed", "https://agreed.example"),
                ],
                "c": [
                    SearchResult("x", "https://x2.example"),
                    SearchResult("y", "https://y2.example"),
                    SearchResult("agreed", "https://agreed.example"),
                ],
            },
            max_results=10,
        )
        assert merged[0].url == "https://agreed.example"
        assert merged[0].engines == ["b", "c"]

    def test_the_same_page_from_two_engines_is_one_result(self):
        merged = reciprocal_rank_fusion(
            {
                "a": [SearchResult("t", "https://www.example.com/p?utm_source=a")],
                "b": [SearchResult("t", "https://example.com/p")],
            },
            max_results=10,
        )
        assert len(merged) == 1
        assert sorted(merged[0].engines) == ["a", "b"]

    def test_the_longest_snippet_wins(self):
        merged = reciprocal_rank_fusion(
            {
                "a": [SearchResult("t", "https://e.example", "short")],
                "b": [SearchResult("t", "https://e.example", "a much longer snippet")],
            },
            max_results=10,
        )
        assert merged[0].snippet == "a much longer snippet"

    def test_max_results_is_honoured(self):
        many = {"a": [SearchResult(f"t{i}", f"https://e{i}.example") for i in range(20)]}
        assert len(reciprocal_rank_fusion(many, max_results=5)) == 5

    def test_one_source_repeating_a_url_does_not_win_three_times(self):
        """The per-source dedupe. Without it, `solo` contributes three RRF terms and
        beats a page two independent sources agreed on."""
        merged = reciprocal_rank_fusion(
            {
                "a": [
                    SearchResult("solo", "https://solo.example"),
                    SearchResult("solo", "https://www.solo.example/?utm_source=x"),
                    SearchResult("solo", "https://solo.example#top"),
                    SearchResult("agreed", "https://agreed.example"),
                ],
                "b": [SearchResult("agreed", "https://agreed.example")],
            },
            max_results=10,
        )
        assert merged[0].url == "https://agreed.example"
        assert len([r for r in merged if "solo" in r.url]) == 1

    def test_source_ranks_are_recorded_per_source(self):
        merged = reciprocal_rank_fusion(
            {
                "a": [SearchResult("x", "https://x.example"), SearchResult("y", "https://y.example")],
                "b": [SearchResult("y", "https://y.example")],
            },
            max_results=10,
        )
        y = next(r for r in merged if r.url == "https://y.example")
        assert y.source_ranks == {"a": 2, "b": 1}

    def test_a_more_specific_kind_survives_the_merge(self):
        """A page both Wikipedia and a scraper returned is a reference result, otherwise
        the per-kind floor cannot see it and reference results get crowded out."""
        merged = reciprocal_rank_fusion(
            {
                "ddg": [SearchResult("Danube", "https://en.wikipedia.org/wiki/Danube", kind="web")],
                "wikipedia": [
                    SearchResult("Danube", "https://en.wikipedia.org/wiki/Danube", kind="reference")
                ],
            },
            max_results=10,
        )
        assert merged[0].kind == "reference"


class TestEngineConfiguration:
    def test_unknown_engine_names_are_dropped_not_fatal(self, monkeypatch):
        """A typo in METASEARCH_ENGINES must not take the server down."""
        monkeypatch.setenv("METASEARCH_ENGINES", "ddg,nosuchengine")
        assert configured_engines() == ["ddg"]

    def test_a_retired_engine_named_by_an_old_setting_is_dropped(self, monkeypatch):
        """An old setting can name an engine that is no longer registered."""
        monkeypatch.setenv("METASEARCH_ENGINES", "ddg,searx,yahoo")
        assert configured_engines() == ["ddg", "yahoo"]

    def test_an_empty_setting_falls_back_rather_than_disabling_search(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_ENGINES", "")
        assert configured_engines() == ["ddg"]

    def test_the_set_can_be_narrowed_without_a_rebuild(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_ENGINES", "brave,yahoo")
        assert configured_engines() == ["brave", "yahoo"]

    def test_the_default_is_every_registered_engine(self, monkeypatch):
        monkeypatch.delenv("METASEARCH_ENGINES", raising=False)
        assert configured_engines() == list(ENGINES)


class TestParsers:
    """One captured fragment per engine, so a selector edit fails here rather than in
    production. These are shapes, not live HTML. They will not catch the engine
    changing its markup, which is what `degraded` reports at runtime."""

    def test_duckduckgo_unwraps_its_click_redirect(self):
        html = """
        <div class="result__body">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Freal.example%2Fpage&amp;rut=x">Title</a>
          <a class="result__snippet">Some snippet</a>
        </div>
        """
        results = ENGINES["ddg"][1](html)
        assert len(results) == 1
        assert results[0].url == "https://real.example/page"
        assert results[0].title == "Title"
        assert results[0].snippet == "Some snippet"

    def test_duckduckgo_lists_each_hit_once(self):
        """`div.result__body, div.web-result` are the inner and outer element of the same
        hit; the pair returned every result twice and halved the value of its ranks."""
        html = """
        <div class="web-result"><div class="result__body">
          <a class="result__a" href="https://one.example/">One</a>
        </div></div>
        <div class="web-result"><div class="result__body">
          <a class="result__a" href="https://two.example/">Two</a>
        </div></div>
        """
        assert [r.url for r in ENGINES["ddg"][1](html)] == [
            "https://one.example/",
            "https://two.example/",
        ]

    def test_brave_reads_title_and_description(self):
        html = """
        <div id="results"><div class="snippet" data-type="web">
          <a href="https://brave.example/x"><div class="title">Brave Title</div></a>
          <div class="snippet-description">Brave snippet</div>
        </div></div>
        """
        results = ENGINES["brave"][1](html)
        assert results[0].url == "https://brave.example/x"
        assert results[0].title == "Brave Title"

    def test_brave_reads_the_current_generic_snippet_markup(self):
        """Captured live: `.snippet-description` is gone and the description moved into
        `.generic-snippet .content`, so every Brave result carried an empty snippet."""
        html = """
        <div class="snippet" data-type="web">
          <a class="l1" href="https://brave.example/x">
            <div class="site-name-content">brave.example &rsaquo; x &rsaquo; crumb</div>
            <div class="title search-snippet-title">Real Brave Title</div>
          </a>
          <div class="generic-snippet"><div class="content">
            <span class="t-secondary">February 23, 2026 -</span>
            The description as Brave renders it today.
          </div></div>
        </div>
        """
        results = ENGINES["brave"][1](html)
        assert len(results) == 1
        assert results[0].title == "Real Brave Title"
        assert "The description as Brave renders it today." in results[0].snippet

    def test_brave_lists_each_hit_once_and_skips_the_llm_widget(self):
        html = """
        <div id="results">
          <div class="snippet standalone" id="llm-snippet">
            <button>More</button>
          </div>
          <div class="snippet" data-type="web">
            <a href="https://brave.example/x"><div class="title">T</div></a>
          </div>
        </div>
        """
        assert [r.url for r in ENGINES["brave"][1](html)] == ["https://brave.example/x"]

    def test_yahoo_unwraps_its_click_redirect(self):
        html = """
        <div class="algo">
          <h3><a href="https://r.search.yahoo.com/_ylt=x/RU=https%3a%2f%2freal.example%2fy/RK=2/RS=z">Y Title</a></h3>
          <div class="compText">Y snippet</div>
        </div>
        """
        results = ENGINES["yahoo"][1](html)
        assert results[0].url == "https://real.example/y"

    def test_yahoo_title_is_the_title_not_the_breadcrumb_mash(self):
        """Captured live: the anchor wraps the favicon, the site name AND the URL
        breadcrumb as well as the `h3`, so the link's text was
        `Wikipediahttps://en.wikipedia.org › wiki › Eiffel_TowerEiffel Tower - Wikipedia`.
        That string is what the user reads and what the model cites.
        """
        html = """
        <div class="dd algo">
          <div class="compTitle">
            <a href="https://en.wikipedia.org/wiki/Eiffel_Tower">
              <div class="d-ib">
                <span><span class="fc-141414 d-b">Wikipedia</span>https://en.wikipedia.org &rsaquo; wiki &rsaquo; Eiffel_Tower</span>
              </div>
              <h3 class="title"><span>Eiffel Tower - Wikipedia</span></h3>
            </a>
          </div>
          <div class="compText"><p>During its construction, the Eiffel <b>Tower</b> …</p></div>
        </div>
        """
        results = ENGINES["yahoo"][1](html)
        assert results[0].title == "Eiffel Tower - Wikipedia"
        assert "wikipedia.org ›" not in results[0].title
        assert results[0].snippet.startswith("During its construction")

    def test_yahoo_falls_back_to_the_link_when_a_row_has_no_h3(self):
        html = """
        <div class="algo"><a href="https://plain.example/">Plain title</a></div>
        """
        assert ENGINES["yahoo"][1](html)[0].title == "Plain title"

    def test_bing_reads_a_captured_page(self):
        """`tests/fixtures/bing_eiffel_tower_height.html` is a live capture, cut to 4 rows."""
        results = ENGINES["bing"][1](_fixture("bing_eiffel_tower_height.html"))
        assert [r.url for r in results] == [
            "https://en.wikipedia.org/wiki/Eiffel_Tower",
            "https://www.toureiffel.paris/en/the-monument/key-figures",
            "https://eiffeltowertravel.com/height-and-facts",
            "https://www.britannica.com/topic/Eiffel-Tower-Paris-France",
        ]
        assert results[0].title == "Eiffel Tower - Wikipedia"
        assert results[0].snippet.startswith("It was the first structure in the world")
        assert all(r.title and r.snippet for r in results)

    def test_bing_keeps_a_direct_link(self):
        html = """
        <ol id="b_results"><li class="b_algo">
          <h2><a href="https://direct.example/a">Direct</a></h2>
          <div class="b_caption"><p>Old caption</p></div>
        </li></ol>
        """
        results = ENGINES["bing"][1](html)
        assert results[0].url == "https://direct.example/a"
        assert results[0].snippet == "Old caption"

    def test_google_reads_a_captured_page(self):
        """`tests/fixtures/google_eiffel_tower_height.html` is a live capture, cut to 4
        rows. Each link is an encrypted `/goto` token, so the URL stays on google.com."""
        results = ENGINES["google"][1](_fixture("google_eiffel_tower_height.html"))
        assert [r.title for r in results] == [
            "Eiffel Tower",
            "The Eiffel Tower facts, eight & weight",
            "The tower was the tallest man-made structure in the world ...",
            "Discover the Eiffel Tower, the greatest symbol of Paris!",
        ]
        assert all(r.url.startswith("https://www.google.com/goto?url=") for r in results)
        assert results[0].snippet.startswith("The tower is 330 metres (1,083 ft) tall")
        assert all(r.snippet for r in results)

    def test_google_unwraps_its_url_redirect(self):
        """The `/url?q=` link of the older and the no-script page."""
        html = """
        <div class="g"><a href="/url?q=https://real.example/g&amp;sa=U&amp;ved=x">
          <h3>G Title</h3></a><div class="VwiC3b">G snippet</div></div>
        """
        results = ENGINES["google"][1](html)
        assert results[0].url == "https://real.example/g"
        assert results[0].title == "G Title"
        assert results[0].snippet == "G snippet"

    def test_google_skips_a_row_without_a_result_title(self):
        html = """
        <div id="rso">
          <div class="MjjYud"><div>People also ask</div><a href="https://x.example/">x</a></div>
          <div class="MjjYud"><a href="https://real.example/"><h3>Real</h3></a></div>
        </div>
        """
        assert [r.url for r in ENGINES["google"][1](html)] == ["https://real.example/"]

    def test_mojeek_reads_its_result_list(self):
        """Not captured: Mojeek answered this host with its JavaScript challenge page
        (`tests/fixtures/mojeek_captcha.html`). The fragment follows the public markup of
        Mojeek result pages."""
        html = """
        <ul class="results-standard">
          <li class="r1">
            <a class="ob" href="https://en.wikipedia.org/wiki/Eiffel_Tower"><p class="i">en.wikipedia.org</p></a>
            <h2><a class="title" href="https://en.wikipedia.org/wiki/Eiffel_Tower">Eiffel Tower - Wikipedia</a></h2>
            <p class="s">The tower is 330 metres tall.</p>
          </li>
          <li class="r2">
            <h2><a class="title" href="https://www.toureiffel.paris/en">La tour Eiffel</a></h2>
            <p class="s">Official site.</p>
          </li>
        </ul>
        """
        results = ENGINES["mojeek"][1](html)
        assert [r.url for r in results] == [
            "https://en.wikipedia.org/wiki/Eiffel_Tower",
            "https://www.toureiffel.paris/en",
        ]
        assert results[0].title == "Eiffel Tower - Wikipedia"
        assert results[0].snippet == "The tower is 330 metres tall."

    @pytest.mark.parametrize(
        "engine, fixture",
        [("google", "google_js_redirect.html"), ("mojeek", "mojeek_captcha.html")],
    )
    def test_a_captured_challenge_page_has_no_results(self, engine, fixture):
        assert ENGINES[engine][1](_fixture(fixture)) == []

    def test_unwrap_bing_ck_redirect(self):
        url = ("https://www.bing.com/ck/a?!&&p=abc&ptn=3&ver=2&hsh=4"
               "&u=a1aHR0cHM6Ly9lbi53aWtpcGVkaWEub3JnL3dpa2kvRWlmZmVsX1Rvd2Vy&ntb=1")
        assert unwrap_tracking_url(url) == "https://en.wikipedia.org/wiki/Eiffel_Tower"

    def test_unwrap_leaves_an_unknown_bing_encoding(self):
        url = "https://www.bing.com/ck/a?!&&p=abc&u=zz&ntb=1"
        assert unwrap_tracking_url(url) == url

    @pytest.mark.parametrize("name", sorted(ENGINES))
    def test_a_parser_returns_nothing_rather_than_raising_on_junk(self, name):
        """Selector rot must surface as an empty list (-> `degraded`), never a 500."""
        assert ENGINES[name][1]("<html><body><p>nothing here</p></body></html>") == []

    def test_startpage_reads_the_result_object_of_its_script(self):
        """The web results come from the JSON object of the page script. The advert block
        is left out, and the `<b>` marks and character references become text."""
        results = ENGINES["startpage"][1](_fixture("startpage_stam_stable_fluids.html"))
        assert [r.url for r in results] == [
            "https://dl.acm.org/doi/10.1145/311535.311548",
            "https://www.researchgate.net/publication/2486965_Stable_Fluids",
            results[2].url,
        ]
        assert len(results) == 3 and "ads.example" not in results[2].url
        assert results[0].title.startswith("Stable fluids | Proceedings of the 26th")
        assert "<b>" not in results[0].snippet and "&nbsp;" not in results[0].snippet

    def test_startpage_with_a_broken_script_object_has_no_results(self):
        page = '<script>React.createElement(UIStartpage.AppSerpWeb, {"render": </script>'
        assert ENGINES["startpage"][1](page) == []


class TestFetchEngineReasons:
    """The reason names a challenge page apart from selector rot. No network."""

    @staticmethod
    def _run(monkeypatch, status, text):
        import asyncio

        from metasearch_server import engines
        from metasearch_server.fetch import FetchResponse

        async def fake_fetch(source, url, *, timeout, **_):
            return FetchResponse(status=status, text=text, url=url)

        monkeypatch.setattr(engines, "fetch", fake_fetch)
        return asyncio.run(engines._fetch_engine("ddg", "q"))

    def test_a_202_challenge_page_is_named(self, monkeypatch):
        results, reason = self._run(monkeypatch, 202, "<html>select all squares</html>")
        assert results == [] and reason.startswith("HTTP 202")

    def test_an_empty_200_page_is_selector_rot(self, monkeypatch):
        results, reason = self._run(monkeypatch, 200, "<html></html>")
        assert results == [] and "selector rot" in reason

    def test_an_empty_page_reason_names_the_page_title(self, monkeypatch):
        results, reason = self._run(monkeypatch, 200, _fixture("mojeek_captcha.html"))
        assert results == [] and reason.endswith("page title 'Captcha'")

    def test_a_refusal_is_its_status(self, monkeypatch):
        assert self._run(monkeypatch, 429, "")[1] == "HTTP 429"
