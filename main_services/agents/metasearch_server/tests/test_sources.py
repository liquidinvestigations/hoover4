"""The source registry and its selection rules.

No network: the fetch functions are exercised elsewhere (and against the live web only by
the live-tool checks). This asserts that a bad `sources` argument from a model
degrades gracefully rather than costing a search.
"""

import asyncio

import pytest

from metasearch_server import engines, sources as sources_mod


class TestRegistry:
    def test_every_registered_source_declares_a_known_kind(self):
        for source in sources_mod.SOURCES.values():
            assert source.kind in sources_mod.ALL_KINDS, source.name

    def test_the_retired_servers_sources_are_present(self):
        """hoover4 replaced two separate search servers with these three sources."""
        for name in ("ddg_api", "ddg_news", "wikipedia"):
            assert name in sources_mod.SOURCES

    def test_the_html_scrapers_are_all_web_kind(self):
        for name in ("ddg", "brave", "yahoo", "bing", "google", "mojeek", "startpage"):
            assert sources_mod.SOURCES[name].kind == sources_mod.KIND_WEB

    def test_news_and_reference_are_distinguishable(self):
        assert sources_mod.SOURCES["ddg_news"].kind == sources_mod.KIND_NEWS
        assert sources_mod.SOURCES["wikipedia"].kind == sources_mod.KIND_REFERENCE

    def test_startpage_has_time_for_a_proof_of_work_solve(self):
        """A new Anubis solve and 2 more requests do not fit in the common deadline."""
        assert "startpage" in sources_mod.DEFAULT_SOURCES.split(",")
        assert sources_mod.SOURCES["startpage"].timeout == sources_mod.STARTPAGE_TIMEOUT
        assert sources_mod.STARTPAGE_TIMEOUT > sources_mod.SOURCE_TIMEOUT

    def test_the_default_set_names_only_sources_that_exist(self):
        """Written out by hand, this string outlived a source it named."""
        for name in sources_mod.DEFAULT_SOURCES.split(","):
            assert name in sources_mod.SOURCES


class TestConfiguration:
    def test_unknown_names_are_dropped_not_fatal(self, monkeypatch):
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg,nosuchsource,wikipedia")
        assert sources_mod.configured_sources() == ["ddg", "wikipedia"]

    def test_an_empty_setting_is_unset_not_no_sources(self, monkeypatch):
        """A compose file renders an unset variable as an empty string. Reading that as
        "no sources" narrows the deployment to one scraper on every default deploy."""
        monkeypatch.delenv("METASEARCH_ENGINES", raising=False)
        monkeypatch.setenv("METASEARCH_SOURCES", "")
        assert sources_mod.configured_sources() == list(sources_mod.SOURCES)

    def test_the_legacy_engines_variable_still_narrows_the_scrapers(self, monkeypatch):
        """An existing deployment's METASEARCH_ENGINES must keep meaning what it meant.
        It names the HTML scrapers, and every non-scraper source comes along."""
        monkeypatch.delenv("METASEARCH_SOURCES", raising=False)
        monkeypatch.setenv("METASEARCH_ENGINES", "brave,yahoo")
        assert sources_mod.configured_sources() == [
            "brave", "yahoo", *[n for n in sources_mod.SOURCES if n not in engines.ENGINES],
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
        default. Narrowing to news must work even if news is not in the default set."""
        monkeypatch.setenv("METASEARCH_SOURCES", "ddg")
        used, unknown = sources_mod.resolve_sources(["ddg_news"])
        assert used == ["ddg_news"] and unknown == []


class TestTrackingUrlUnwrap:
    """A news row can link through another engine's redirector.

    Not cosmetic. A wrapped URL normalises to a different dedupe key from the direct one,
    so the same article survives fusion twice and the model cites the tracker.
    """

    YAHOO = (
        "https://r.search.yahoo.com/_ylt=Awr123;_ylu=abc/RV=2/RE=1787337101/RO=10"
        "/RU=https%3a%2f%2fnews.example%2fstory/RK=2/RS=zzz-"
    )

    def test_a_news_row_is_unwrapped(self, monkeypatch):
        rows = [{"url": self.YAHOO, "title": "T", "excerpt": "b", "source": "Example"}]
        out = _news(monkeypatch, rows)
        assert out[0].url == "https://news.example/story"

    def test_a_lite_row_is_unwrapped(self):
        html = ('<table><tr><td><a class="result-link" href="//duckduckgo.com/l/?uddg='
                'https%3A%2F%2Freal.example%2Fp&rut=x">T</a></td></tr></table>')
        assert engines.parse_duckduckgo_lite(html)[0].url == "https://real.example/p"

    def test_the_wrapper_and_the_direct_url_now_dedupe_together(self):
        from agent_common.fusion import normalise_url

        from metasearch_server.engines import unwrap_tracking_url

        assert normalise_url(unwrap_tracking_url(self.YAHOO)) == normalise_url(
            "https://news.example/story"
        )


def _news(monkeypatch, rows, page='<script>vqd="4-123456789"</script>', calls=None):
    """Run `ddg_news` against a fake `fetch`: the result page, then `news.js` with `rows`."""
    import json

    from metasearch_server.fetch import FetchResponse

    async def fake_fetch(source, url, *, params=None, headers=None, timeout, **_):
        if calls is not None:
            calls.append((url, dict(params or {}), dict(headers or {})))
        if url == sources_mod.DDG_HOME_URL:
            return FetchResponse(status=200, text=page, url=url)
        return FetchResponse(status=200, text=json.dumps({"results": rows}), url=url)

    monkeypatch.setattr(sources_mod, "fetch", fake_fetch)
    return asyncio.run(sources_mod._fetch_ddg_news("q", 10, "w"))


class TestDuckDuckGoSources:
    """`ddg_api` and `ddg_news` fetch DuckDuckGo through `fetch`, without the `ddgs` library."""

    LITE = """
    <table>
      <tr class="result-sponsored"><td><a class="result-link"
          href="https://duckduckgo.com/y.js?ad=1">Advert</a></td></tr>
      <tr class="result-sponsored"><td class="result-snippet">Buy now</td></tr>
      <tr><td>1.</td><td><a rel="nofollow" href="https://one.example/" class='result-link'>One
          <b>title</b></a></td></tr>
      <tr><td></td><td class='result-snippet'>First <b>snippet</b></td></tr>
      <tr><td></td><td><span class='link-text'>one.example</span></td></tr>
      <tr><td>2.</td><td><a href="https://two.example/a" class="result-link">Two</a></td></tr>
      <tr><td></td><td class="result-snippet">Second</td></tr>
    </table>
    """

    def test_the_lite_parser_reads_links_and_snippets_and_skips_adverts(self):
        out = engines.parse_duckduckgo_lite(self.LITE)
        assert [(r.title, r.url, r.snippet) for r in out] == [
            ("One title", "https://one.example/", "First snippet"),
            ("Two", "https://two.example/a", "Second"),
        ]

    def test_ddg_api_sends_the_time_filter_and_names_no_other_host(self, monkeypatch):
        from metasearch_server.fetch import FetchResponse

        calls = []

        async def fake_fetch(source, url, *, params=None, headers=None, timeout, **_):
            calls.append((url, dict(params or {})))
            return FetchResponse(status=200, text=self.LITE, url=url)

        monkeypatch.setattr(sources_mod, "fetch", fake_fetch)
        out = asyncio.run(sources_mod._fetch_ddg_api("q", 1, "m"))
        # One request to DuckDuckGo. The `ddgs` library also asked a Wikipedia host made
        # from the region, `wt.wikipedia.org`, which does not exist.
        assert [url for url, _ in calls] == [sources_mod.DDG_LITE_URL]
        assert calls[0][1]["df"] == "m" and calls[0][1]["q"] == "q"
        assert [r.url for r in out] == ["https://one.example/"]
        assert out[0].kind == sources_mod.KIND_WEB

    def test_ddg_api_names_a_challenge_page(self, monkeypatch):
        from metasearch_server.fetch import FetchResponse

        async def fake_fetch(source, url, *, params=None, headers=None, timeout, **_):
            return FetchResponse(status=202, text="<html>captcha</html>", url=url)

        monkeypatch.setattr(sources_mod, "fetch", fake_fetch)
        with pytest.raises(sources_mod.SourceUnavailable, match="HTTP 202"):
            asyncio.run(sources_mod._fetch_ddg_api("q", 5, None))

    def test_ddg_news_takes_the_vqd_token_then_reads_the_rows(self, monkeypatch):
        calls = []
        rows = [{"url": "https://news.example/a", "title": "A <b>head</b>",
                 "excerpt": "Body", "source": "Wire", "date": 1700000000}]
        out = _news(monkeypatch, rows, calls=calls)
        assert [url for url, _, _ in calls] == [sources_mod.DDG_HOME_URL, sources_mod.DDG_NEWS_URL]
        news_params, news_headers = calls[1][1], calls[1][2]
        assert news_params["vqd"] == "4-123456789" and news_params["df"] == "w"
        assert news_headers["Referer"] == sources_mod.DDG_HOME_URL
        assert (out[0].title, out[0].snippet, out[0].kind) == ("A head", "Wire: Body",
                                                               sources_mod.KIND_NEWS)
        assert out[0].published == "2023-11-14T22:13:20Z"

    def test_ddg_news_without_a_token_says_why(self, monkeypatch):
        with pytest.raises(sources_mod.SourceUnavailable, match="vqd"):
            _news(monkeypatch, [], page="<html>no token</html>")


class TestCapturedNewsPage:
    """`news.js` rows from a captured DuckDuckGo News answer for the query `battlebots`."""

    @staticmethod
    def _rows():
        import json
        from pathlib import Path

        path = Path(__file__).parent / "fixtures" / "ddg_news.json"
        return json.loads(path.read_text(encoding="utf-8"))["results"]

    def test_character_references_become_characters(self, monkeypatch):
        out = _news(monkeypatch, self._rows())
        ringer = next(r for r in out if r.title == "You Can Talk About Robot Fight Club")
        assert ringer.snippet.startswith("The Ringer: Tombstone's primary weapon")
        for r in out:
            for text in (r.title, r.snippet):
                assert "&#x27;" not in text and "&quot;" not in text and "<b>" not in text

    def test_an_escaped_tag_stays_text(self):
        assert sources_mod._strip_tags("a &lt;b&gt; c &#x27;d&#x27;") == "a <b> c 'd'"


class TestWikipediaSnippets:
    def test_mediawiki_search_markup_is_stripped(self):
        raw = 'The <span class="searchmatch">Danube</span> is a river &amp; a border'
        assert sources_mod._strip_tags(raw) == "The Danube is a river & a border"

    def test_stripping_is_safe_on_unbalanced_markup(self):
        """A stray `<` swallows up to the next `>` and nothing more. A blunt fix, but it
        cannot raise and cannot leak markup, which is all a snippet needs."""
        assert sources_mod._strip_tags("a < b > c") == "a c"
        assert sources_mod._strip_tags("unterminated <span") == "unterminated"


class TestKeyGating:
    """A key-gated source with no key is absent, never present and failing."""

    def test_an_unregistered_source_is_named_nowhere(self):
        """Registration happens at import, and this suite runs without a key mounted, so
        the source must be missing from the registry, the default set and the description
        the model reads, all three, because absent from one of them is still a source a
        model can be told about or asked for."""
        assert "factcheck" not in sources_mod.SOURCES
        assert "factcheck" not in sources_mod.DEFAULT_SOURCES.split(",")
        assert not [s for s in sources_mod.describe_sources() if s["name"] == "factcheck"]

    def test_no_key_means_no_key(self, monkeypatch):
        monkeypatch.delenv("FACTCHECK_API_KEY_FILE", raising=False)
        assert sources_mod._factcheck_key() == ""

    def test_an_empty_mounted_file_is_no_key(self, monkeypatch, tmp_path):
        """The compose file mounts /dev/null when no key is configured, so "the file
        exists" is not the question. "The file has a key in it" is."""
        empty = tmp_path / "key"
        empty.write_text("   \n")
        monkeypatch.setenv("FACTCHECK_API_KEY_FILE", str(empty))
        assert sources_mod._factcheck_key() == ""

    def test_a_missing_file_is_no_key_rather_than_a_crash(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FACTCHECK_API_KEY_FILE", str(tmp_path / "nope"))
        assert sources_mod._factcheck_key() == ""


class TestArchiveQueries:
    """Neither archive has a full-text index: they answer about a URL."""

    def test_a_host_is_found_in_an_ordinary_question(self):
        assert sources_mod.host_in("what did enron.com say in 2001") == "enron.com"
        assert sources_mod.host_in("https://www.example.co.uk/a/b") == "www.example.co.uk"

    def test_a_question_naming_no_host_yields_nothing(self):
        assert sources_mod.host_in("who audited Enron") == ""
        assert sources_mod.host_in("") == ""

    def test_an_archive_asked_a_hostless_question_says_why(self):
        for name in ("wayback", "archive_today"):
            with pytest.raises(sources_mod.SourceUnavailable):
                asyncio.run(sources_mod.SOURCES[name].fetch("who audited Enron", 5, None))

    def test_the_archives_declare_their_own_kind(self):
        for name in ("wayback", "archive_today"):
            assert sources_mod.SOURCES[name].kind == sources_mod.KIND_ARCHIVE


class TestNewSourceParsers:
    """Response shapes, parsed without touching the network."""

    def test_a_gdelt_timestamp_becomes_a_readable_date(self):
        assert sources_mod._gdelt_date("20240115T093000Z") == "2024-01-15T09:30:00Z"
        assert sources_mod._gdelt_date("nonsense") == "nonsense"

    def test_a_crossref_date_part_list_becomes_a_date(self):
        assert sources_mod._crossref_date({"date-parts": [[2011, 3, 4]]}) == "2011-03-04"
        assert sources_mod._crossref_date({"date-parts": [[2011]]}) == "2011"
        assert sources_mod._crossref_date(None) == ""

    def test_a_wayback_timestamp_becomes_a_readable_date(self):
        assert sources_mod._wayback_date("19981212024715") == "1998-12-12"

    def test_only_short_code_links_are_archive_today_snapshots(self):
        """The listing also links `/<host>`, `/*.<host>` and `/<the full url>`, which are
        other views of the same page. Without the short-code rule the first result is the
        page's link to itself."""
        rows = list(
            sources_mod._ARCHIVE_TODAY_ROW.finditer(
                '<a href="https://archive.ph/enron.com">enron.com</a>'
                '<a href="https://archive.ph/wCG1t">9 Dec 2025 17:45</a>'
                '<a href="https://archive.ph/wCG1t">Enron Corporation</a>'
                '<a href="https://archive.ph/https://enron.com/">https://enron.com/</a>'
            )
        )
        assert [m.group("url") for m in rows] == [
            "https://archive.ph/wCG1t",
            "https://archive.ph/wCG1t",
        ]

    def test_a_capture_date_anchor_is_recognised(self):
        assert sources_mod._ARCHIVE_TODAY_DATE.match("9 Dec 2025 17:45")
        assert not sources_mod._ARCHIVE_TODAY_DATE.match("Enron Corporation")
