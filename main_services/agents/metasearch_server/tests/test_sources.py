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
        for name in ("ddg", "brave", "yahoo"):
            assert sources_mod.SOURCES[name].kind == sources_mod.KIND_WEB

    def test_news_and_reference_are_distinguishable(self):
        assert sources_mod.SOURCES["ddg_news"].kind == sources_mod.KIND_NEWS
        assert sources_mod.SOURCES["wikipedia"].kind == sources_mod.KIND_REFERENCE

    def test_startpage_is_gone_rather_than_permanently_degraded(self):
        """It serves a JS app with a captcha and no results in the HTML for any query.
        Leaving it registered advertised seven sources where there were six."""
        assert "startpage" not in sources_mod.SOURCES
        assert "startpage" not in sources_mod.DEFAULT_SOURCES

    def test_the_default_set_names_only_sources_that_exist(self):
        """Written out by hand, this string outlived a source it named."""
        for name in sources_mod.DEFAULT_SOURCES.split(","):
            assert name in sources_mod.SOURCES


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


class TestTrackingUrlUnwrap:
    """C2: the `ddgs` library mixes back ends, so its rows carry other engines' wrappers.

    Not cosmetic. A wrapped URL normalises to a different dedupe key from the direct one,
    so the same article survives fusion twice and the model cites the tracker.
    """

    YAHOO = (
        "https://r.search.yahoo.com/_ylt=Awr123;_ylu=abc/RV=2/RE=1787337101/RO=10"
        "/RU=https%3a%2f%2fnews.example%2fstory/RK=2/RS=zzz-"
    )

    def test_a_news_row_is_unwrapped(self):
        rows = [{"url": self.YAHOO, "title": "T", "body": "b", "source": "Example"}]
        out = self._news(rows)
        assert out[0].url == "https://news.example/story"

    def test_a_text_row_is_unwrapped(self):
        rows = [{"href": self.YAHOO, "title": "T", "body": "b"}]
        out = self._text(rows)
        assert out[0].url == "https://news.example/story"

    def test_a_ddg_redirect_row_is_unwrapped(self):
        rows = [{"href": "https://duckduckgo.com/l/?uddg=https%3A%2F%2Freal.example%2Fp&rut=x"}]
        assert self._text(rows)[0].url == "https://real.example/p"

    def test_a_direct_url_is_left_alone(self):
        rows = [{"href": "https://direct.example/page?id=7"}]
        assert self._text(rows)[0].url == "https://direct.example/page?id=7"

    def test_the_wrapper_and_the_direct_url_now_dedupe_together(self):
        from agent_common.fusion import normalise_url

        from metasearch_server.engines import unwrap_tracking_url

        assert normalise_url(unwrap_tracking_url(self.YAHOO)) == normalise_url(
            "https://news.example/story"
        )

    # The two adapters are sync-inside-async; drive them through a stubbed `ddgs` call.
    @staticmethod
    def _run(method: str, rows: list[dict]):
        import asyncio

        import metasearch_server.sources as m

        original = m._ddgs_call
        m._ddgs_call = lambda *a, **k: rows
        try:
            fetch = m._fetch_ddg_news if method == "news" else m._fetch_ddg_api
            return asyncio.run(fetch("q", 10, None))
        finally:
            m._ddgs_call = original

    @classmethod
    def _news(cls, rows):
        return cls._run("news", rows)

    @classmethod
    def _text(cls, rows):
        return cls._run("text", rows)


class TestWikipediaSnippets:
    def test_mediawiki_search_markup_is_stripped(self):
        raw = 'The <span class="searchmatch">Danube</span> is a river &amp; a border'
        assert sources_mod._strip_tags(raw) == "The Danube is a river & a border"

    def test_stripping_is_safe_on_unbalanced_markup(self):
        """A stray `<` swallows up to the next `>` and nothing more. Not clever, but it
        cannot raise and cannot leak markup, which is all a snippet needs."""
        assert sources_mod._strip_tags("a < b > c") == "a c"
        assert sources_mod._strip_tags("unterminated <span") == "unterminated"
