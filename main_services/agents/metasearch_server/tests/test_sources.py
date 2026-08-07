"""The source registry and its selection rules.

No network: the fetch functions are exercised elsewhere (and against the live web only by
the live-tool checks). What matters here is that a bad `sources` argument from a model
degrades gracefully rather than costing a search.
"""

from metasearch_server import sources as sources_mod


class TestRegistry:
    def test_every_registered_source_declares_a_known_kind(self):
        for source in sources_mod.SOURCES.values():
            assert source.kind in sources_mod.ALL_KINDS, source.name

    def test_the_retired_servers_sources_are_present(self):
        """hoover4-mcp-ddg and hoover4-mcp-wikipedia were retired into these three."""
        for name in ("ddg_api", "ddg_news", "wikipedia"):
            assert name in sources_mod.SOURCES

    def test_the_html_scrapers_are_all_web_kind(self):
        for name in ("ddg", "brave", "startpage", "yahoo"):
            assert sources_mod.SOURCES[name].kind == sources_mod.KIND_WEB

    def test_news_and_reference_are_distinguishable(self):
        assert sources_mod.SOURCES["ddg_news"].kind == sources_mod.KIND_NEWS
        assert sources_mod.SOURCES["wikipedia"].kind == sources_mod.KIND_REFERENCE


class TestConfiguration:
    def test_unknown_names_are_dropped_not_fatal(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg,nosuchsource,wikipedia")
        assert sources_mod.configured_sources() == ["ddg", "wikipedia"]

    def test_an_empty_setting_falls_back_rather_than_disabling_search(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_SOURCES", "")
        assert sources_mod.configured_sources() == ["ddg"]

    def test_the_legacy_engines_variable_still_narrows_the_scrapers(self, monkeypatch):
        """An existing deployment's METASEARCH_ENGINES must keep meaning what it meant —
        it names the HTML scrapers, and the three inherited sources come along."""
        monkeypatch.delenv("METASEARCH_SOURCES", raising=False)
        monkeypatch.setenv("METASEARCH_ENGINES", "brave,yahoo")
        assert sources_mod.configured_sources() == [
            "brave", "yahoo", "ddg_api", "ddg_news", "wikipedia",
        ]

    def test_the_default_is_everything(self, monkeypatch):
        monkeypatch.delenv("METASEARCH_SOURCES", raising=False)
        monkeypatch.delenv("METASEARCH_ENGINES", raising=False)
        assert set(sources_mod.configured_sources()) == set(sources_mod.SOURCES)


class TestResolveSources:
    def test_no_request_uses_the_configured_set(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg,wikipedia")
        assert sources_mod.resolve_sources(None) == (["ddg", "wikipedia"], [])

    def test_a_typo_from_the_model_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg,wikipedia")
        used, unknown = sources_mod.resolve_sources(["wikipedia", "wikpedia"])
        assert used == ["wikipedia"]
        assert unknown == ["wikpedia"]

    def test_an_entirely_unknown_request_falls_back_to_the_configured_set(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg")
        used, unknown = sources_mod.resolve_sources(["nope"])
        assert used == ["ddg"]
        assert unknown == ["nope"]

    def test_duplicates_are_collapsed(self):
        used, _ = sources_mod.resolve_sources(["ddg", "DDG", " ddg "])
        assert used == ["ddg"]

    def test_a_request_may_name_a_source_the_deployment_has_disabled(self, monkeypatch):
        """`sources` is the model's choice within what exists, not within what is on by
        default — narrowing to news must work even if news is not in the default set."""
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg")
        used, unknown = sources_mod.resolve_sources(["ddg_news"])
        assert used == ["ddg_news"] and unknown == []


class TestWikipediaSnippets:
    def test_mediawiki_search_markup_is_stripped(self):
        raw = 'The <span class="searchmatch">Danube</span> is a river &amp; a border'
        assert sources_mod._strip_tags(raw) == "The Danube is a river & a border"

    def test_stripping_is_safe_on_unbalanced_markup(self):
        """A stray `<` swallows up to the next `>` and nothing more. Not clever, but it
        cannot raise and cannot leak markup, which is all a snippet needs."""
        assert sources_mod._strip_tags("a < b > c") == "a c"
        assert sources_mod._strip_tags("unterminated <span") == "unterminated"
