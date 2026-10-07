"""Verify web fusion, source-kind limits, and payload fields without model reranking."""

import asyncio

import pytest

from agent_common import rerank as rerank_client
from metasearch_server import pipeline, sources as sources_mod
from metasearch_server.engines import SearchResult
from metasearch_server.pipeline import Ranked, apply_per_kind_floor


def _ranked(kind: str, index: int, rerank_score: float | None = None) -> Ranked:
    return Ranked(
        result=SearchResult(f"t{index}", f"https://e{index}.example", kind=kind),
        rrf_rank=index,
        rrf_score=1.0 / index,
        rerank_score=rerank_score,
    )


class TestPerKindFloor:
    def test_a_minority_kind_keeps_its_floor_against_a_dominant_one(self):
        """The reason the floor exists: four web scrapers agreeing always outscores one
        encyclopaedia entry, so without a reservation pass a query with a well-known
        Wikipedia answer returns nothing but blogs about it."""
        ranked = [_ranked("web", i) for i in range(1, 41)]
        ranked += [_ranked("reference", i) for i in range(41, 46)]
        kept = apply_per_kind_floor(ranked, max_results=15, min_per_kind=3, max_per_kind=20)
        kinds = [r.result.kind for r in kept]
        assert kinds.count("reference") == 3
        assert kinds.count("web") == 12

    def test_the_ceiling_caps_a_kind_even_with_budget_left(self):
        ranked = [_ranked("web", i) for i in range(1, 31)]
        kept = apply_per_kind_floor(ranked, max_results=30, min_per_kind=2, max_per_kind=5)
        assert len(kept) == 5

    def test_a_kind_with_fewer_results_than_the_floor_is_not_padded(self):
        ranked = [_ranked("web", 1), _ranked("news", 2)]
        kept = apply_per_kind_floor(ranked, max_results=10, min_per_kind=10, max_per_kind=20)
        assert len(kept) == 2

    def test_the_fused_order_survives_the_floor(self):
        ranked = [_ranked("web", 1), _ranked("news", 2), _ranked("web", 3)]
        kept = apply_per_kind_floor(ranked, max_results=3, min_per_kind=1, max_per_kind=20)
        assert [r.rrf_rank for r in kept] == [1, 2, 3]

    def test_reserved_slots_outlive_a_smaller_max_results(self):
        """`max_results` caps the total, but never at the cost of a reserved slot,
        otherwise the floor would be undone by the very next line."""
        ranked = [_ranked("web", i) for i in range(1, 11)] + [_ranked("news", 11)]
        kept = apply_per_kind_floor(ranked, max_results=2, min_per_kind=2, max_per_kind=20)
        kinds = [r.result.kind for r in kept]
        assert "news" in kinds

    def test_a_reversed_constant_pair_fails_loudly(self):
        with pytest.raises(ValueError):
            apply_per_kind_floor([], max_results=10, min_per_kind=20, max_per_kind=10)

    def test_the_default_floor_leaves_the_cap_meaningful(self, monkeypatch):
        """The default result limit is 15. A floor of 10 across three kinds reserves
        30 slots and `max_results` stops meaning anything. This test pins that defect.

        Reloaded with the env cleared because the *code* default is what is under test;
        a deployment is free to set the knob higher and live with the consequence.
        """
        import importlib

        for key in ("METASEARCH_MIN_PER_KIND", "METASEARCH_MAX_PER_KIND"):
            monkeypatch.delenv(key, raising=False)
        fresh = importlib.reload(pipeline)
        try:
            assert fresh.MIN_PER_KIND * len(("web", "news", "reference")) <= 15
            ranked = (
                [_ranked("web", i, 5.0) for i in range(1, 41)]
                + [_ranked("news", i, 5.0) for i in range(41, 61)]
                + [_ranked("reference", i, 5.0) for i in range(61, 81)]
            )
            assert len(fresh.apply_per_kind_floor(ranked, max_results=15)) == 15
        finally:
            importlib.reload(pipeline)




class TestRunSearch:
    """`run_search` end to end with stubbed sources."""

    @staticmethod
    def _stub_sources(monkeypatch, per_source):
        async def fetch_all(query, names, per_source_results=15, timelimit=None):
            latency = {n: 1.0 for n in names}
            degraded = [n for n in names if not per_source.get(n)]
            reasons = {n: "answered with no results (selector rot?)" for n in degraded}
            return {n: list(per_source.get(n, [])) for n in names}, latency, degraded, reasons

        monkeypatch.setattr(sources_mod, "fetch_all", fetch_all)
        monkeypatch.setattr(
            sources_mod, "resolve_sources", lambda requested: (list(per_source), [])
        )

    @pytest.mark.parametrize("configured", [False, True])
    def test_web_search_never_calls_reranker(self, monkeypatch, configured):
        self._stub_sources(monkeypatch, {"ddg": [
            SearchResult("a", "https://a.example"), SearchResult("b", "https://b.example"),
        ]})
        if configured:
            monkeypatch.setenv("RERANK_URL", "http://rerank.example/v1")
        else:
            monkeypatch.delenv("RERANK_URL", raising=False)
        def forbidden(*_args, **_kwargs):
            pytest.fail("Web search called the model reranker.")
        monkeypatch.setattr(rerank_client, "rerank", forbidden)
        outcome = asyncio.run(pipeline.run_search(["q"], max_results=10))
        assert outcome.rerank_applied is False
        assert outcome.rerank_error == ""
        assert outcome.rerank_ms == 0
        assert [r.result.url for r in outcome.ranked] == ["https://a.example", "https://b.example"]
        assert all(r.rerank_rank is None and r.rerank_score is None for r in outcome.ranked)



    def test_a_source_returning_nothing_is_degraded_not_fatal(self, monkeypatch):
        self._stub_sources(
            monkeypatch, {"ddg": [SearchResult("a", "https://a.example")], "brave": []}
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: (_ for _ in ()).throw(rerank_client.RerankUnavailable("no")),
        )
        outcome = asyncio.run(pipeline.run_search(["q"]))
        assert outcome.degraded == ["brave"]
        # "brave returned nothing" reads the same for rot, an HTTP 429 and a dead host.
        assert outcome.degraded_reasons["brave"]
        assert len(outcome.ranked) == 1




class TestBatchedQueries:
    """Each query contributes to one fused pool."""

    @staticmethod
    def _stub_per_query(monkeypatch, per_query):
        """`per_query` maps a query to `{source: [results]}`."""

        async def fetch_all(query, names, per_source_results=15, timelimit=None):
            table = per_query.get(query, {})
            latency = {n: 1.0 for n in names}
            degraded = [n for n in names if not table.get(n)]
            reasons = {n: "answered with no results" for n in degraded}
            return {n: list(table.get(n, [])) for n in names}, latency, degraded, reasons

        monkeypatch.setattr(sources_mod, "fetch_all", fetch_all)
        monkeypatch.setattr(
            sources_mod,
            "resolve_sources",
            lambda requested: (
                sorted({n for table in per_query.values() for n in table}), []
            ),
        )

    def test_the_merged_pool_never_calls_reranker(self, monkeypatch):
        self._stub_per_query(
            monkeypatch,
            {
                "one": {"ddg": [SearchResult("a", "https://a.example")]},
                "two": {"ddg": [SearchResult("b", "https://b.example")]},
            },
        )
        calls = []

        def record(query, documents, model=None):
            calls.append((query, len(documents)))
            return [
                rerank_client.RerankScore(index=i, score=float(len(documents) - i))
                for i in range(len(documents))
            ], 5.0

        monkeypatch.setattr(rerank_client, "rerank", record)

        outcome = asyncio.run(pipeline.run_search(["one", "two"], max_results=10))
        assert calls == []
        assert len(outcome.ranked) == 2

    def test_a_page_two_queries_found_names_both(self, monkeypatch):
        self._stub_per_query(
            monkeypatch,
            {
                "one": {"ddg": [SearchResult("a", "https://a.example")]},
                "two": {
                    "ddg": [
                        SearchResult("a", "https://a.example/"),
                        SearchResult("b", "https://b.example"),
                    ]
                },
            },
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: (_ for _ in ()).throw(rerank_client.RerankUnavailable("no")),
        )
        outcome = asyncio.run(pipeline.run_search(["one", "two"], max_results=10))
        by_url = {r.result.url: r for r in outcome.ranked}
        # The trailing slash is the same page: `matched_queries` is keyed on the
        # normalised URL, or a batch would claim corroboration it does not have.
        assert by_url["https://a.example"].matched_queries == ["one", "two"]
        assert by_url["https://b.example"].matched_queries == ["two"]
        # And the corroborated page outranks the one a single query found.
        assert outcome.ranked[0].result.url == "https://a.example"

    def test_a_source_answering_one_query_of_two_is_not_degraded(self, monkeypatch):
        """One empty query is a query with no results, not a broken source. Counting it
        as one degrades every source on any batch carrying a narrow angle."""
        self._stub_per_query(
            monkeypatch,
            {
                "broad": {"ddg": [SearchResult("a", "https://a.example")], "brave": []},
                "narrow": {"ddg": [], "brave": []},
            },
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: (_ for _ in ()).throw(rerank_client.RerankUnavailable("no")),
        )
        outcome = asyncio.run(pipeline.run_search(["broad", "narrow"], max_results=10))
        assert outcome.degraded == ["brave"]
        assert outcome.degraded_reasons["brave"]

    def test_the_model_is_shown_source_names_not_fusion_keys(self, monkeypatch):
        """Rankings are keyed by (source, query) so two queries do not overwrite each
        other. A key repeated once per query would read to the model as corroboration."""
        self._stub_per_query(
            monkeypatch,
            {
                "one": {"ddg": [SearchResult("a", "https://a.example")]},
                "two": {"ddg": [SearchResult("a", "https://a.example")]},
            },
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: (_ for _ in ()).throw(rerank_client.RerankUnavailable("no")),
        )
        outcome = asyncio.run(pipeline.run_search(["one", "two"], max_results=10))
        assert outcome.ranked[0].result.engines == ["ddg"]


class TestPayloadSplit:
    def test_the_model_gets_selected_fusion_fields(self):
        item = _ranked("web", 1)
        payload = pipeline.result_payload(item)
        assert "source_ranks" not in payload
        assert payload["rrf_rank"] == 1 and payload["rerank_rank"] is None

    def test_the_detail_document_carries_both_orderings(self):
        outcome = pipeline.SearchOutcome(query="q")
        outcome.fused = [_ranked("web", 1), _ranked("web", 2)]
        outcome.ranked = [outcome.fused[1]]
        doc = pipeline.detail_document(outcome)
        assert len(doc["before_rerank"]) == 2
        assert len(doc["after_rerank"]) == 1
        assert "source_ranks" in doc["before_rerank"][0]

    def test_display_url_drops_the_scheme_and_www(self):
        assert pipeline.display_url("https://www.example.com/a/b") == "example.com/a/b"

    def test_display_url_truncates_a_long_path(self):
        long = "https://example.com/" + "x" * 200
        assert len(pipeline.display_url(long)) <= 60


def test_health_reports_web_reranking_disabled(monkeypatch):
    import json
    from metasearch_server import server

    monkeypatch.setenv("RERANK_URL", "http://rerank.example/v1")
    response = asyncio.run(server.health(None))
    result = json.loads(response.body)
    assert result["rerank_endpoint"] == ""
    assert result["rerank_available"] is False
    assert result["rerank_circuits"] == {}
