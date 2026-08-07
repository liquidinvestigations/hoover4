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

    def test_the_default_floor_leaves_the_cap_meaningful(self, monkeypatch):
        """C4/Q14: 15 results, always reranked. A floor of 10 across three kinds reserves
        30 slots and `max_results` stops meaning anything — the defect this pins.

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


class TestReserveScoreGate:
    """C4: a floor guarantees representation, and representation of nothing is padding.

    Live, an Eiffel Tower query returned "Yanam district" and "Aasta Hansteen spar" as
    reference results — reserved by the floor, scored around -5 by the cross-encoder,
    and indistinguishable to the model from a result that earned its place.
    """

    def test_a_kind_whose_best_result_scores_below_zero_is_not_padded_in(self):
        ranked = [_ranked("web", i, 6.0) for i in range(1, 11)]
        ranked += [_ranked("reference", i, -5.0) for i in range(11, 16)]
        kept = apply_per_kind_floor(ranked, max_results=5, min_per_kind=3, max_per_kind=15)
        assert [r.result.kind for r in kept] == ["web"] * 5

    def test_a_kind_that_scores_well_still_gets_its_floor(self):
        ranked = [_ranked("web", i, 8.0) for i in range(1, 21)]
        ranked += [_ranked("reference", 21, 4.0), _ranked("reference", 22, -6.0)]
        kept = apply_per_kind_floor(ranked, max_results=5, min_per_kind=3, max_per_kind=15)
        kinds = [r.result.kind for r in kept]
        # One reference result earned a slot; the irrelevant one did not get reserved.
        assert kinds.count("reference") == 1

    def test_a_low_scoring_result_can_still_be_filled_in_on_merit(self):
        """The gate blocks the reservation, not the result. With budget to spare it comes
        back in rank order like anything else."""
        ranked = [_ranked("web", 1, 8.0), _ranked("reference", 2, -5.0)]
        kept = apply_per_kind_floor(ranked, max_results=10, min_per_kind=3, max_per_kind=15)
        assert len(kept) == 2

    def test_with_no_rerank_score_the_floor_is_unconditional(self):
        """The GPU is down: no score is not a low score, and the floor is then the only
        protection a minority kind has."""
        ranked = [_ranked("web", i) for i in range(1, 21)] + [_ranked("reference", 21)]
        kept = apply_per_kind_floor(ranked, max_results=3, min_per_kind=3, max_per_kind=15)
        assert "reference" in [r.result.kind for r in kept]


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
        # "brave returned nothing" reads the same for rot, an HTTP 429 and a dead host.
        assert outcome.degraded_reasons["brave"]
        assert len(outcome.ranked) == 1

    def test_a_partial_rerank_response_does_not_delete_the_rest(self, monkeypatch):
        """C7: the reranker scored one of three candidates (a `top_k`, a truncated body).
        The two it skipped are real results with a real RRF position; dropping them turns
        a partial rerank into a partial search."""
        self._stub_sources(
            monkeypatch,
            {"ddg": [SearchResult(f"t{i}", f"https://{i}.example") for i in range(3)]},
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: ([rerank_client.RerankScore(index=2, score=9.0)], 3.0),
        )
        outcome = asyncio.run(pipeline.run_search("q", max_results=10))
        assert outcome.rerank_applied is True
        assert [r.result.url for r in outcome.ranked] == [
            "https://2.example",
            "https://0.example",
            "https://1.example",
        ]
        # The unscored two say so rather than claiming a rank they never got.
        assert outcome.ranked[0].rerank_rank == 1
        assert [r.rerank_rank for r in outcome.ranked[1:]] == [None, None]

    def test_a_repeated_index_in_a_rerank_response_is_not_duplicated(self, monkeypatch):
        self._stub_sources(
            monkeypatch,
            {"ddg": [SearchResult(f"t{i}", f"https://{i}.example") for i in range(2)]},
        )
        monkeypatch.setattr(
            rerank_client,
            "rerank",
            lambda q, d, model=None: (
                [
                    rerank_client.RerankScore(index=1, score=9.0),
                    rerank_client.RerankScore(index=1, score=8.0),
                ],
                3.0,
            ),
        )
        outcome = asyncio.run(pipeline.run_search("q", max_results=10))
        assert [r.result.url for r in outcome.ranked] == [
            "https://1.example",
            "https://0.example",
        ]


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
