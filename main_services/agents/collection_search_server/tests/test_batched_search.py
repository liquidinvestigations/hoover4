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


class TestBatchedEntityListing:
    """The shared value budget, and the tier that survives when only one fits."""

    @staticmethod
    def _stub(monkeypatch, structured_count, ner_count, structured_width=6):
        import collection_search_server.server as srv

        monkeypatch.setattr(srv, "_caller", lambda: _AllowAll())
        monkeypatch.setattr(
            srv,
            "_structured_entities",
            lambda c, h: [
                srv.StructuredEntity(
                    entity_type="iban", value=f"{i}".rjust(structured_width, "X")
                )
                for i in range(structured_count)
            ],
        )
        monkeypatch.setattr(
            srv,
            "clickhouse_query",
            lambda *a, **k: [
                {"entity_type": "person", "values": [f"p{i}" for i in range(ner_count)]}
            ],
        )
        return srv

    def test_the_budget_divides_across_the_batch(self, monkeypatch):
        """Two documents share one budget, so each gets half — and both say they were cut
        rather than returning a full-looking list that is not one."""
        srv = self._stub(monkeypatch, structured_count=0, ner_count=2000)
        monkeypatch.setattr(srv, "LIST_ENTITIES_TOTAL_CHARS", 2000)
        out = srv.list_document_entities.fn(
            documents=[
                {"collectionname": "testdata", "file_hash": HASH_A},
                {"collectionname": "testdata", "file_hash": HASH_B},
            ]
        )
        kept = [len(d.entities["person"]) for d in out.documents]
        assert kept[0] == kept[1] and 0 < kept[0] < 2000
        assert all(d.truncated for d in out.documents)
        assert "cut to the most frequent" in (out.note or "")

    def test_the_validated_tier_survives_when_only_one_fits(self, monkeypatch):
        """A checksum-validated identifier is evidence and a model's guess at a span of
        prose is a lead. When only one tier fits, it is the evidence that stays."""
        # Ten identifiers wide enough to spend the whole per-document share, which is
        # never less than the shared floor however small the total is set.
        srv = self._stub(
            monkeypatch, structured_count=10, ner_count=2000, structured_width=48
        )
        monkeypatch.setattr(srv, "LIST_ENTITIES_TOTAL_CHARS", 500)
        out = srv.list_document_entities.fn(
            documents=[{"collectionname": "testdata", "file_hash": HASH_A}]
        )
        one = out.documents[0]
        assert len(one.structured) == 10
        assert one.entities.get("person", []) == []
        assert one.truncated is True

    def test_a_repeat_is_read_once_and_said_so(self, monkeypatch):
        srv = self._stub(monkeypatch, structured_count=1, ner_count=1)
        out = srv.list_document_entities.fn(
            documents=[
                {"collectionname": "testdata", "file_hash": HASH_A},
                {"collectionname": "testdata", "file_hash": HASH_A},
            ]
        )
        assert len(out.documents) == 1
        assert "repeated document" in (out.note or "")

    def test_the_single_document_call_still_works(self, monkeypatch):
        """The shape this tool took before it was batched. It must not be a special
        case — `_document_pairs` reads it as a batch of one."""
        srv = self._stub(monkeypatch, structured_count=1, ner_count=1)
        out = srv.list_document_entities.fn(collectionname="testdata", file_hash=HASH_A)
        assert [d.file_hash for d in out.documents] == [HASH_A]

    def test_no_document_at_all_names_the_parameters(self, monkeypatch):
        srv = self._stub(monkeypatch, structured_count=0, ner_count=0)
        out = srv.list_document_entities.fn(documents=[])
        assert out.success is False and "file_hash" in (out.error or "")


class _AllowAll:
    def check(self, collections):
        return None
