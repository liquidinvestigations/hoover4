"""Tests for the hybrid (keyword + vector) search pipeline in search_collections."""

import pytest

from agent_common import rerank as rerank_client
from collection_search_server import server
from collection_search_server.vectors import VectorCandidate

H1 = "a" * 32
H2 = "b" * 32
H3 = "c" * 32


def _keyword(hash_: str, page: int, score: float, text: str) -> server._Candidate:
    return server._Candidate(
        collectionname="coll", collection_dataset="coll_ds", file_hash=hash_,
        page_id=page, keyword_score=score, text=text,
    )


def _vector(hash_: str, page: int, dist: float, text: str) -> VectorCandidate:
    return VectorCandidate(
        collectionname="coll", collection_dataset="coll_ds", file_hash=hash_,
        extracted_by="tika", page_id=page, chunk_index=0, dist=dist, text=text,
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

        monkeypatch.setattr(
            rerank_client, "rerank",
            lambda query, documents, model=None: (
                [rerank_client.RerankScore(index=i, score=1.0 / (i + 1)) for i in range(len(documents))],
                5.0,
            ),
        )
        hits = server._fused_pipeline("q", keyword, vector, limit=5, notes=[])
        assert any(h.file_hash == H3 and h.match_sources == ["vector"] for h in hits)
