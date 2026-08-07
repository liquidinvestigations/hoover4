"""Tests for URL normalisation, RRF and the degraded-engine reporting.

The scrapers themselves are not tested against the live web — that would make the suite
fail whenever an engine changes its HTML, which is precisely the event the `degraded`
field exists to report at runtime. What is tested here is the merging logic, which is
where a silent wrong answer would actually hide, plus each parser against a captured
fragment so a selector edit is caught.
"""

import pytest

from metasearch_server.engines import (
    ENGINES,
    SearchResult,
    configured_engines,
    normalise_url,
    reciprocal_rank_fusion,
)


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

    def test_source_ranks_are_recorded_for_the_detail_artifact(self):
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
        """A page both Wikipedia and a scraper returned is a reference result — otherwise
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
        """Deployments still carry `startpage` in their rendered env."""
        monkeypatch.setenv("METASEARCH_ENGINES", "ddg,startpage,yahoo")
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
    production. These are shapes, not live HTML — they will not catch the engine
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
        `.generic-snippet .content`, so every Brave result carried an empty snippet — and
        an empty snippet is a candidate the cross-encoder scores on its title alone."""
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
        """C1, captured live: the anchor wraps the favicon, the site name AND the URL
        breadcrumb as well as the `h3`, so the link's text was
        `Wikipediahttps://en.wikipedia.org › wiki › Eiffel_TowerEiffel Tower - Wikipedia`.
        That string is what the user reads and what the reranker scores — a page with a
        keyword-stuffed breadcrumb outranked the clean encyclopaedia entry because of it.
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

    @pytest.mark.parametrize("name", sorted(ENGINES))
    def test_a_parser_returns_nothing_rather_than_raising_on_junk(self, name):
        """Selector rot must surface as an empty list (-> `degraded`), never a 500."""
        assert ENGINES[name][1]("<html><body><p>nothing here</p></body></html>") == []

    def test_startpage_is_no_longer_registered(self):
        """Retired, not disabled: its HTML is a JS app behind a captcha for every query,
        so there is no selector to repair and no run in which it can come back."""
        assert "startpage" not in ENGINES
