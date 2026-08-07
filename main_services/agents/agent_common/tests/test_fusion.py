"""Tests for the shared fusion machinery: generic RRF and the per-kind floor."""

import pytest

from agent_common.fusion import (
    SearchResult,
    fuse_ranked_lists,
    normalise_url,
    per_kind_floor,
    reciprocal_rank_fusion,
)


class TestFuseRankedLists:
    def test_agreement_across_sources_wins(self):
        # The RRF property: an item two sources rank 3rd beats an item one source
        # ranks 1st (1/(60+3)+1/(60+3) > 1/(60+1)).
        per_source = {
            "keyword": ["only-keyword", "shared"],
            "vector": ["only-vector", "shared"],
        }
        fused = fuse_ranked_lists(per_source, key_of=lambda x: x)
        assert fused[0].item == "shared"
        assert fused[0].source_ranks == {"keyword": 2, "vector": 2}

    def test_within_source_dedupe(self):
        # One source listing a key at ranks 1 and 2 contributes ONE rank — otherwise a
        # repeater beats two independent sources agreeing.
        fused = fuse_ranked_lists(
            {"a": ["x", "x", "y"], "b": ["y"]},
            key_of=lambda x: x,
        )
        scores = {f.item: f.score for f in fused}
        assert scores["y"] == pytest.approx(1 / 62 + 1 / 61)  # rank 2 in a, rank 1 in b
        assert scores["x"] == pytest.approx(1 / 61)

    def test_first_sources_payload_is_kept(self):
        keyword = {"kind": "page", "id": 1, "text": "full page text"}
        vector = {"kind": "chunk", "id": 1, "text": "chunk text"}
        fused = fuse_ranked_lists(
            {"keyword": [keyword], "vector": [vector]},
            key_of=lambda d: d["id"],
        )
        assert len(fused) == 1
        assert fused[0].item is keyword  # richer payload first in the dict

    def test_max_results_caps(self):
        fused = fuse_ranked_lists({"a": list(range(10))}, key_of=lambda x: x, max_results=3)
        assert len(fused) == 3


class TestPerKindFloor:
    @staticmethod
    def _items(spec):
        # spec: list of (kind, score-rank) — input order IS the rank order.
        return [{"kind": kind, "rank": i} for i, kind in enumerate(spec)]

    def test_minority_kind_is_reserved(self):
        ranked = self._items(["keyword"] * 12 + ["vector"] * 3)
        out = per_kind_floor(
            ranked, max_results=5, kind_of=lambda i: i["kind"],
            min_per_kind=10, max_per_kind=20,
        )
        # All 3 vector items are reserved even though the cap is 5 and every one of
        # them ranks below every keyword item.
        assert sum(1 for i in out if i["kind"] == "vector") == 3
        assert len(out) == 13  # reserved beats the cap: 10 keyword + 3 vector reserved
        assert [i["kind"] for i in out][:2] == ["keyword"] * 2  # input order kept

    def test_max_per_kind_caps_a_dominant_kind(self):
        ranked = self._items(["keyword"] * 30)
        out = per_kind_floor(
            ranked, max_results=100, kind_of=lambda i: i["kind"],
            min_per_kind=10, max_per_kind=20,
        )
        assert len(out) == 20

    def test_min_above_max_refused(self):
        with pytest.raises(ValueError):
            per_kind_floor([], 5, kind_of=lambda i: "x", min_per_kind=21, max_per_kind=20)


class TestMovedWebFusion:
    """The metasearch RRF now lives here; pin its behaviour at its new home."""

    def test_rrf_merges_on_normalised_url(self):
        per_engine = {
            "a": [SearchResult(title="t", url="https://www.example.com/p?utm_source=x")],
            "b": [SearchResult(title="t2", url="http://example.com/p")],
        }
        fused = reciprocal_rank_fusion(per_engine, max_results=10)
        assert len(fused) == 1
        assert sorted(fused[0].engines) == ["a", "b"]

    def test_normalise_url_strips_tracking_and_www(self):
        # The key keeps the "//host" form (urlunparse with an empty scheme) — only
        # its identity as a comparison key matters, never its display.
        assert normalise_url("https://www.example.com/a/?utm_source=x&b=2") == \
            "//example.com/a?b=2"
