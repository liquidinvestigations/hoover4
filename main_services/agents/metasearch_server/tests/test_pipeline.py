"""The ordering pipeline: the per-kind floor, the rerank fallback, and the payload split.

Nothing here touches the network. The sources are stubbed, and the rerank client is
monkeypatched — the point is the *ordering*, which is where a silent wrong answer would
hide, not whether DuckDuckGo is up.
"""

import asyncio

import pytest

from agent_common import rerank as rerank_client
from metasearch_server import pipeline, sources as sources_mod
from metasearch_server.engines import SearchResult
from metasearch_server.pipeline import Ranked, apply_per_kind_floor


def _ranked(kind: str, index: int) -> Ranked:
    return Ranked(
        result=SearchResult(f"t{index}", f"https://e{index}.example", kind=kind),
        rrf_rank=index,
        rrf_score=1.0 / index,
    )


class TestPerKindFloor:
    def test_a_minority_kind_keeps_its_floor_against_a_dominant_one(self):
        """The reason the floor exists: four web scrapers agreeing always outscores one
        encyclopaedia entry, so without a reservation pass a query with an obvious
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

    def test_the_reranked_order_survives_the_floor(self):
        ranked = [_ranked("web", 1), _ranked("news", 2), _ranked("web", 3)]
        kept = apply_per_kind_floor(ranked, max_results=3, min_per_kind=1, max_per_kind=20)
        assert [r.rrf_rank for r in kept] == [1, 2, 3]

    def test_reserved_slots_outlive_a_smaller_max_results(self):
        """`max_results` caps the total, but never at the cost of a reserved slot —
        otherwise the floor would be undone by the very next line."""
        ranked = [_ranked("web", i) for i in range(1, 11)] + [_ranked("news", 11)]
        kept = apply_per_kind_floor(ranked, max_results=2, min_per_kind=2, max_per_kind=20)
        kinds = [r.result.kind for r in kept]
        assert "news" in kinds

    def test_a_reversed_constant_pair_fails_loudly(self):
        with pytest.raises(ValueError):
            apply_per_kind_floor([], max_results=10, min_per_kind=20, max_per_kind=10)


class TestRunSearch:
    """`run_search` end to end with stubbed sources."""

    @staticmethod
    def _stub_sources(monkeypatch, per_source):
        async def fetch_all(query, names, per_source_results=15, timelimit=None):
            latency = {n: 1.0 for n in names}
            degraded = [n for n in names if not per_source.get(n)]
            return {n: list(per_source.get(n, [])) for n in names}, latency, degraded

        monkeypatch.setattr(sources_mod, "fetch_all", fetch_all)
        monkeypatch.setattr(
            sources_mod, "resolve_sources", lambda requested: (list(per_source), [])
        )

    def test_a_dead_gpu_returns_rrf_order_and_says_so(self, monkeypatch):
        """The acceptance check from the plan: killing the GPU tier must degrade the
        ordering, not remove search."""
        self._stub_sources(
            monkeypatch,
            {"ddg": [SearchResult("a", "https://a.example"), SearchResult("b", "https://b.example")]},
        )

        def dead(query, documents, model=None):
            raise rerank_client.RerankUnavailable("circuit open")

        monkeypatch.setattr(rerank_client, "rerank", dead)

        outcome = asyncio.run(pipeline.run_search("q", max_results=10))
        assert outcome.rerank_applied is False
        assert outcome.rerank_error
        assert [r.result.url for r in outcome.ranked] == [
            "https://a.example",
            "https://b.example",
        ]

    def test_reranking_reorders_and_records_both_ranks(self, monkeypatch):
        self._stub_sources(
            monkeypatch,
            {"ddg": [SearchResult("a", "https://a.example"), SearchResult("b", "https://b.example")]},
        )

        def flip(query, documents, model=None):
            # Reverse the fused order, so a wrong "rerank did nothing" would be visible.
            return [
                rerank_client.RerankScore(index=1, score=9.0),
                rerank_client.RerankScore(index=0, score=1.0),
            ], 12.0

        monkeypatch.setattr(rerank_client, "rerank", flip)

        outcome = asyncio.run(pipeline.run_search("q", max_results=10))
        assert outcome.rerank_applied is True
        assert [r.result.url for r in outcome.ranked] == [
            "https://b.example",
            "https://a.example",
        ]
        top = outcome.ranked[0]
        assert top.rrf_rank == 2 and top.rerank_rank == 1

    def test_a_source_returning_nothing_is_degraded_not_fatal(self, monkeypatch):
        self._stub_sources(
            monkeypatch, {"ddg": [SearchResult("a", "https://a.example")], "brave": []}
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: (_ for _ in ()).throw(rerank_client.RerankUnavailable("no")),
        )
        outcome = asyncio.run(pipeline.run_search("q"))
        assert outcome.degraded == ["brave"]
        assert len(outcome.ranked) == 1


class TestPayloadSplit:
    def test_the_model_never_sees_the_pre_rerank_ordering(self):
        """§6.3: the fused order is bookkeeping and would roughly double the token cost.
        It belongs in the artifact, not in the tool result."""
        item = _ranked("web", 1)
        item.rerank_rank, item.rerank_score = 1, 4.5
        payload = pipeline.result_payload(item)
        assert "source_ranks" not in payload
        assert payload["rrf_rank"] == 1 and payload["rerank_rank"] == 1

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
