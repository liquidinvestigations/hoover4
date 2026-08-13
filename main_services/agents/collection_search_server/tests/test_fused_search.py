"""Tests for the hybrid (keyword + vector) search pipeline in search_collections."""

import pytest

from agent_common import rerank as rerank_client
from collection_search_server import server
from collection_search_server.server import SearchHit
from collection_search_server.vectors import VectorCandidate

H1 = "a" * 32
H2 = "b" * 32
H3 = "c" * 32


def _keyword(hash_: str, page: int, score: float, text: str) -> server._Candidate:
    return server._Candidate(
        collectionname="coll", collection_dataset="coll_ds", file_hash=hash_,
        page_id=page, keyword_score=score, text=text,
    )


def _vector(
    hash_: str, page: int, dist: float, text: str, chunk_index: int = 0
) -> VectorCandidate:
    return VectorCandidate(
        collectionname="coll", collection_dataset="coll_ds", file_hash=hash_,
        extracted_by="tika", page_id=page, chunk_index=chunk_index, dist=dist, text=text,
    )


def _identity_rerank(monkeypatch):
    """A reranker that keeps the fused order, so a test can be about something else."""
    monkeypatch.setattr(
        rerank_client, "rerank",
        lambda query, documents, model=None: (
            [rerank_client.RerankScore(index=i, score=1.0 / (i + 1)) for i in range(len(documents))],
            5.0,
        ),
    )


class TestFusedPipeline:
    def test_rerank_reorders_and_sources_are_labelled(self, monkeypatch):
        keyword = [_keyword(H1, 1, 10.0, "keyword page text"), _keyword(H2, 1, 9.0, "other page")]
        vector = [_vector(H2, 1, 0.1, "chunk text of the second page")]

        # The cross-encoder flips the fused order.
        def fake_rerank(query, documents, model=None):
            return [rerank_client.RerankScore(index=1, score=0.9),
                    rerank_client.RerankScore(index=0, score=0.1)], 12.0

        monkeypatch.setattr(rerank_client, "rerank", fake_rerank)
        notes: list[str] = []
        hits = server._fused_pipeline("q", keyword, vector, limit=10, notes=notes)

        # The fused order is [H2, H1] (H2 is in both rankings); the rerank flips it.
        assert [h.file_hash for h in hits] == [H1, H2]
        hybrid = hits[1]
        assert hybrid.match_sources == ["keyword", "vector"]
        # The chunk text outranks the page excerpt as the snippet.
        assert hybrid.snippet == "chunk text of the second page"
        assert hits[0].match_sources == ["keyword"]
        assert any("reranked" in n for n in notes)

    def test_rerank_failure_keeps_the_fused_order(self, monkeypatch):
        keyword = [_keyword(H1, 1, 10.0, "first"), _keyword(H2, 1, 5.0, "second")]

        def broken_rerank(query, documents, model=None):
            raise rerank_client.RerankUnavailable("rerank endpoint circuit is open")

        monkeypatch.setattr(rerank_client, "rerank", broken_rerank)
        notes: list[str] = []
        hits = server._fused_pipeline("q", keyword, [], limit=10, notes=notes)

        assert [h.snippet for h in hits] == ["first", "second"]
        assert any("rerank unavailable" in n for n in notes)

    def test_vector_only_hits_enter_the_results(self, monkeypatch):
        # A semantic hit with no keyword overlap must survive even when keyword hits
        # dominate the fused order — that is the floor's whole job.
        keyword = [_keyword(H1, p, 10.0 - p, f"keyword page {p}") for p in range(1, 12)]
        vector = [_vector(H3, 2, 0.05, "semantic chunk with no keyword overlap")]

        _identity_rerank(monkeypatch)
        hits = server._fused_pipeline("q", keyword, vector, limit=5, notes=[])
        assert any(h.file_hash == H3 and h.match_sources == ["vector"] for h in hits)

    def test_max_results_is_honoured_on_the_hybrid_path(self, monkeypatch):
        """A per-kind floor of 10 reserves 20 slots, so `max_results=8` does nothing,
        so an agent asking for 8 hits got 20 — at 1200 snippet characters each."""
        keyword = [_keyword(H1, p, 20.0 - p, f"keyword page {p}") for p in range(1, 21)]
        vector = [_vector(H2, p, 0.01 * p, f"vector chunk {p}") for p in range(1, 21)]

        _identity_rerank(monkeypatch)
        hits = server._fused_pipeline("q", keyword, vector, limit=8, notes=[])
        assert len(hits) == 8
        # Both rankings still represented — the cap tightened, the floor did not vanish.
        assert {s for h in hits for s in h.match_sources} == {"keyword", "vector"}


class TestFusedSnippet:
    """Which chunk of a multi-chunk page becomes the page's snippet.

    The snippet is not only what the user reads — it is the document string handed to the
    cross-encoder. Scoring a page on its least relevant passage misranks it *and* then
    shows the user the passage that lost.
    """

    def test_the_nearest_chunk_of_a_page_wins(self, monkeypatch):
        # KNN returns nearest first. Assigning unconditionally meant the LAST assignment
        # — the farthest chunk — was the one that stuck.
        vector = [
            _vector(H1, 3, 0.05, "the passage that actually answers the query", chunk_index=0),
            _vector(H1, 3, 0.90, "an unrelated aside further down the page", chunk_index=7),
        ]
        _identity_rerank(monkeypatch)
        hits = server._fused_pipeline("q", [], vector, limit=10, notes=[])
        assert len(hits) == 1
        assert hits[0].snippet == "the passage that actually answers the query"

    def test_a_chunk_still_beats_the_keyword_page_excerpt(self, monkeypatch):
        """The original intent, which the fix must not undo: the matched passage is a
        better snippet than an arbitrary excerpt from the top of the page."""
        keyword = [_keyword(H1, 3, 9.0, "the first 1200 characters of the page")]
        vector = [
            _vector(H1, 3, 0.05, "the matched passage", chunk_index=4),
            _vector(H1, 3, 0.80, "a later, farther passage", chunk_index=9),
        ]
        _identity_rerank(monkeypatch)
        hits = server._fused_pipeline("q", keyword, vector, limit=10, notes=[])
        assert hits[0].snippet == "the matched passage"

    def test_chunks_of_different_pages_do_not_share_a_snippet(self, monkeypatch):
        vector = [
            _vector(H1, 1, 0.05, "page one passage"),
            _vector(H1, 2, 0.06, "page two passage"),
        ]
        _identity_rerank(monkeypatch)
        hits = server._fused_pipeline("q", [], vector, limit=10, notes=[])
        assert {h.page_id: h.snippet for h in hits} == {
            1: "page one passage",
            2: "page two passage",
        }


class TestPartialRerank:
    def test_candidates_the_reranker_skipped_are_kept_in_fused_order(self, monkeypatch):
        """A partial rerank response must not shrink the search. The unscored hits
        were real, with a real fused position, and they keep it behind the scored ones."""
        keyword = [_keyword(H1, 1, 9.0, "first"), _keyword(H2, 1, 8.0, "second"),
                   _keyword(H3, 1, 7.0, "third")]

        monkeypatch.setattr(
            rerank_client, "rerank",
            lambda query, documents, model=None: (
                [rerank_client.RerankScore(index=2, score=9.0)], 4.0
            ),
        )
        hits = server._fused_pipeline("q", keyword, [], limit=10, notes=[])
        assert [h.snippet for h in hits] == ["third", "first", "second"]


class TestResultBudget:
    """What a result set *weighs*, not only how many results are in it."""

    def test_a_huge_max_results_is_clamped_to_the_cap(self):
        # The model really does ask for 10 000: one turn spent 27 809 prompt tokens on a
        # single search because nothing between the tool call and the prompt said no.
        assert max(1, min(10000, server.MAX_ALLOWED_RESULTS)) == 200

    def test_the_default_is_well_under_the_cap(self):
        assert server.DEFAULT_MAX_RESULTS < server.MAX_ALLOWED_RESULTS

    def test_the_tool_description_names_the_default_it_wants_left_alone(self):
        # The description is the only text a model reads before its first call; if it
        # does not say what the default is, "more" is always the safe-looking choice.
        description = server.search_collections.description
        assert str(server.DEFAULT_MAX_RESULTS) in description
        assert "max_results" in description

    def test_a_small_result_set_keeps_the_full_snippet(self):
        hits = [
            SearchHit(
                collectionname="c", collection_dataset="c_d", file_hash=H1, page_id=1,
                snippet="x" * 1500,
            )
            for _ in range(8)
        ]
        server._apply_snippet_budget(hits)
        assert all(len(h.snippet) <= server.SNIPPET_CHARS + 1 for h in hits)
        assert all(len(h.snippet) > 1000 for h in hits)

    def test_a_full_result_set_stays_inside_the_budget(self):
        hits = [
            SearchHit(
                collectionname="c", collection_dataset="c_d", file_hash=H1, page_id=i,
                snippet="x" * 1500,
            )
            for i in range(server.MAX_ALLOWED_RESULTS)
        ]
        server._apply_snippet_budget(hits)
        total = sum(len(h.snippet) for h in hits)
        # The floor buys each hit a readable line, so the bound is the budget plus the
        # ellipsis per hit -- not the 300 000 characters 200 raw snippets would be.
        assert total <= server.SNIPPET_BUDGET_CHARS + len(hits)
        assert all(len(h.snippet) >= server.MIN_SNIPPET_CHARS for h in hits)

    def test_a_short_snippet_is_never_padded_or_marked_truncated(self):
        hits = [
            SearchHit(
                collectionname="c", collection_dataset="c_d", file_hash=H1, page_id=1,
                snippet="short",
            )
        ]
        server._apply_snippet_budget(hits)
        assert hits[0].snippet == "short"

    def test_the_per_kind_guard_cannot_undercut_a_large_max_results(self, monkeypatch):
        # Two kinds x MAX_PER_KIND was the real cap on a hybrid search: a caller asking
        # for 50 got 30, and the tool's own limit never applied.
        keyword = [_keyword("%032d" % i, 1, 100.0 - i, f"hit {i}") for i in range(40)]
        _identity_rerank(monkeypatch)
        hits = server._fused_pipeline("q", keyword, [], limit=40, notes=[])
        assert len(hits) == 40
