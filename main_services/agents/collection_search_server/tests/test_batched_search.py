"""Cross-query fusion and the batched document read.

The search itself needs Manticore and ClickHouse; what is tested here is the part that
can be wrong without either — how several queries' rankings become one, and how the three
argument shapes a model sends for a batch of documents are read.
"""

from __future__ import annotations

from collection_search_server.server import (
    SearchHit,
    _document_pairs,
    _fuse_across_queries,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def hit(file_hash: str, page_id: int = 1, snippet: str = "text") -> SearchHit:
    return SearchHit(
        collectionname="testdata",
        collection_dataset="ds",
        file_hash=file_hash,
        page_id=page_id,
        score=1.0,
        snippet=snippet,
    )


class TestFuseAcrossQueries:
    def test_every_hit_names_the_queries_that_found_it(self):
        out = _fuse_across_queries(
            {"alpha": [hit(HASH_A)], "beta": [hit(HASH_A), hit(HASH_B)]}, 10
        )
        by_hash = {h.file_hash: h for h in out}
        assert by_hash[HASH_A].matched_queries == ["alpha", "beta"]
        assert by_hash[HASH_B].matched_queries == ["beta"]

    def test_corroboration_outranks_one_querys_top_hit(self):
        # B is first for one query; A is second for two. A should win: that is the whole
        # reason for fusing on rank rather than on scores from incomparable queries.
        out = _fuse_across_queries(
            {
                "one": [hit(HASH_B), hit(HASH_A)],
                "two": [hit("c" * 64), hit(HASH_A)],
            },
            10,
        )
        assert out[0].file_hash == HASH_A

    def test_one_query_finding_a_page_twice_names_it_once(self):
        # A query's own ranking can carry the same page more than once, since shards are
        # searched independently. Listing it repeatedly would claim corroboration that
        # does not exist, which inverts the whole meaning of the field.
        out = _fuse_across_queries({"due date": [hit(HASH_A), hit(HASH_A)]}, 10)
        assert out[0].matched_queries == ["due date"]

    def test_a_single_query_is_not_a_special_case(self):
        out = _fuse_across_queries({"only": [hit(HASH_A), hit(HASH_B)]}, 10)
        assert [h.file_hash for h in out] == [HASH_A, HASH_B]
        assert out[0].matched_queries == ["only"]

    def test_the_fuller_snippet_survives_the_merge(self):
        out = _fuse_across_queries(
            {"a": [hit(HASH_A, snippet="short")],
             "b": [hit(HASH_A, snippet="a much longer passage")]},
            10,
        )
        assert out[0].snippet == "a much longer passage"

    def test_pages_of_one_document_stay_distinct(self):
        out = _fuse_across_queries({"a": [hit(HASH_A, 1), hit(HASH_A, 2)]}, 10)
        assert len(out) == 2

    def test_the_limit_is_honoured(self):
        many = {"a": [hit(f"{i:064x}") for i in range(20)]}
        assert len(_fuse_across_queries(many, 5)) == 5


class TestDocumentPairs:
    def test_a_list_of_objects(self):
        pairs, bad = _document_pairs(
            [{"collectionname": "testdata", "file_hash": HASH_A}], None, None
        )
        assert pairs == [("testdata", HASH_A)] and bad == []

    def test_a_json_encoded_list_of_objects(self):
        pairs, _ = _document_pairs(
            '[{"collectionname": "testdata", "file_hash": "%s"}]' % HASH_A, None, None
        )
        assert pairs == [("testdata", HASH_A)]

    def test_two_parallel_lists(self):
        pairs, _ = _document_pairs(None, ["testdata", "other"], [HASH_A, HASH_B])
        assert pairs == [("testdata", HASH_A), ("other", HASH_B)]

    def test_one_collection_spread_over_several_hashes(self):
        pairs, _ = _document_pairs(None, "testdata", [HASH_A, HASH_B])
        assert pairs == [("testdata", HASH_A), ("testdata", HASH_B)]

    def test_the_single_document_call_still_reads(self):
        # The shape the retired get_document_text took. It must not be a special case.
        pairs, bad = _document_pairs(None, "testdata", HASH_A)
        assert pairs == [("testdata", HASH_A)] and bad == []

    def test_a_bad_entry_is_reported_not_dropped(self):
        pairs, bad = _document_pairs([{"collectionname": "testdata"}], None, None)
        assert pairs == [] and len(bad) == 1

    def test_a_non_hash_is_malformed(self):
        pairs, bad = _document_pairs(None, "testdata", "not-a-hash")
        assert pairs == [] and len(bad) == 1
