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


class TestEngineConfiguration:
    def test_unknown_engine_names_are_dropped_not_fatal(self, monkeypatch):
        """A typo in METASEARCH_ENGINES must not take the server down."""
        monkeypatch.setenv("METASEARCH_ENGINES", "ddg,nosuchengine")
        assert configured_engines() == ["ddg"]

    def test_an_empty_setting_falls_back_rather_than_disabling_search(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_ENGINES", "")
        assert configured_engines() == ["ddg"]

    def test_the_set_can_be_narrowed_without_a_rebuild(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_ENGINES", "brave,yahoo")
        assert configured_engines() == ["brave", "yahoo"]


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

    def test_startpage_reads_title_and_description(self):
        html = """
        <div class="w-gl__result">
          <a class="w-gl__result-title" href="https://sp.example/x">SP Title</a>
          <p class="w-gl__description">SP snippet</p>
        </div>
        """
        results = ENGINES["startpage"][1](html)
        assert results[0].url == "https://sp.example/x"
        assert results[0].snippet == "SP snippet"

    def test_yahoo_unwraps_its_click_redirect(self):
        html = """
        <div class="algo">
          <h3><a href="https://r.search.yahoo.com/_ylt=x/RU=https%3a%2f%2freal.example%2fy/RK=2/RS=z">Y Title</a></h3>
          <div class="compText">Y snippet</div>
        </div>
        """
        results = ENGINES["yahoo"][1](html)
        assert results[0].url == "https://real.example/y"

    @pytest.mark.parametrize("name", sorted(ENGINES))
    def test_a_parser_returns_nothing_rather_than_raising_on_junk(self, name):
        """Selector rot must surface as an empty list (-> `degraded`), never a 500."""
        assert ENGINES[name][1]("<html><body><p>nothing here</p></body></html>") == []
