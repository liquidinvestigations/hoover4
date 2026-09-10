"""The quote check and the handle table behind `cite_documents`."""

from collection_search_server.acl import CallerAcl
from collection_search_server.citations import (
    HandleTable,
    MAX_HANDLES_PER_SESSION,
    PAGE_JOIN,
    QUOTE_MATCH_VERIFIED,
    QUOTE_REASON_ABSENT,
    QUOTE_REASON_LOOKUP_FAILED,
    QUOTE_REASON_SHORT,
    normalise_for_match,
    quote_match_in_pages,
    quote_occurs_in,
)
from collection_search_server.server import (
    Citation,
    VERIFY_PAGE_BATCH,
    _cite_one,
)


HASH = "a" * 64
EXCERPT_LIMIT = 40000


def _acl() -> CallerAcl:
    return CallerAcl(username="tester", collections=("testdata",))


class TestQuoteVerification:
    def test_an_exact_quote_verifies(self):
        text = "The board approved the transfer on 3 March."
        assert quote_occurs_in("approved the transfer", text)

    def test_a_quote_the_document_does_not_contain_fails(self):
        text = "The board approved the transfer on 3 March."
        assert not quote_occurs_in("rejected the transfer", text)
        assert quote_match_in_pages("rejected the transfer", [text]) == QUOTE_REASON_ABSENT

    def test_a_line_break_inside_the_quoted_sentence_still_verifies(self):
        """A PDF wraps mid-sentence and a mail parser keeps `\\r\\n`. A model quoting what
        it read reproduces the words, not the extractor's line breaks, so an exact
        substring test rejects nearly every accurate quote."""
        text = "The board approved\nthe transfer\r\non 3 March."
        assert quote_occurs_in("approved the transfer on 3 March", text)

    def test_typographic_punctuation_folds_in_both_directions(self):
        assert quote_occurs_in("the board's decision", "The board’s decision stands.")
        assert quote_occurs_in("the board’s decision", "The board's decision stands.")

    def test_case_folds(self):
        assert quote_occurs_in("board approved", "The BOARD APPROVED it.")

    def test_a_quote_too_short_to_prove_anything_is_not_verified(self):
        """`the` occurs in every document. A check that always passes is not a check, and
        reporting it as verified would put a marker of confidence on nothing."""
        assert not quote_occurs_in("the", "The board approved the transfer.")
        assert not quote_occurs_in("", "The board approved the transfer.")
        assert quote_match_in_pages("the", ["The board approved the transfer."]) == (
            QUOTE_REASON_SHORT
        )

    def test_a_paraphrase_is_absent_wording(self):
        text = "The board approved the transfer on 3 March."
        assert quote_match_in_pages(
            "the committee rejected the plan", [text]
        ) == QUOTE_REASON_ABSENT

    def test_normalisation_collapses_runs_of_whitespace(self):
        assert normalise_for_match("  a \n\t b  ") == "a b"

    def test_pages_match_the_joined_document(self):
        pages = ["The board approved the", "transfer on 3 March."]
        joined = PAGE_JOIN.join(pages)
        quote = "approved the transfer on 3 March"
        assert quote_occurs_in(quote, joined)
        assert quote_match_in_pages(quote, pages) == QUOTE_MATCH_VERIFIED

    def test_a_quote_that_crosses_a_page_boundary_verifies(self):
        pages = ["prefix The board approved the", "transfer on 3 March. suffix"]
        assert quote_match_in_pages(
            "approved the transfer on 3 March", pages
        ) == QUOTE_MATCH_VERIFIED

    def test_a_quote_past_the_model_excerpt_still_verifies(self):
        filler = "word " * 9000
        assert len(filler) > EXCERPT_LIMIT
        quote = "unique cited sentence from the end"
        pages = [filler, quote]
        assert not quote_occurs_in(quote, filler)
        assert quote_match_in_pages(quote, pages) == QUOTE_MATCH_VERIFIED

    def test_absent_wording_after_the_excerpt_is_still_absent(self):
        filler = "word " * 9000
        pages = [filler, "unique cited sentence from the end"]
        assert quote_match_in_pages(
            "this wording is nowhere in the document", pages
        ) == QUOTE_REASON_ABSENT


class TestCiteOne:
    def _stub_pages(self, monkeypatch, pages, path="/doc.txt", dataset="testdata_ds"):
        import collection_search_server.server as srv

        monkeypatch.setattr(srv, "VERIFY_PAGE_BATCH", 2)

        def fake_query(sql, database, params=None):
            params = params or {}
            if "text_content" in sql:
                offset = int(params.get("offset") or 0)
                limit = int(params.get("limit") or VERIFY_PAGE_BATCH)
                chunk = pages[offset:offset + limit]
                return [{"text": text} for text in chunk]
            if "vfs_files" in sql:
                return [{"path": path, "collection_dataset": dataset}]
            raise AssertionError(sql)

        monkeypatch.setattr(srv, "clickhouse_query", fake_query)

    def test_a_quote_past_the_excerpt_is_verified(self, monkeypatch):
        filler = "word " * 9000
        quote = "unique cited sentence from the end"
        self._stub_pages(monkeypatch, [filler, quote])
        result = _cite_one(
            _acl(),
            "s1",
            Citation(
                collectionname="testdata",
                file_hash=HASH,
                quote=quote,
                why="names the ending",
            ),
        )
        assert result.quote_verified
        assert result.quote_reason == ""
        assert result.error is None
        assert result.handle == "[D1]"
        assert result.path == "/doc.txt"

    def test_a_short_quote_is_named(self, monkeypatch):
        self._stub_pages(monkeypatch, ["The board approved the transfer on 3 March."])
        result = _cite_one(
            _acl(),
            "s1",
            Citation(collectionname="testdata", file_hash=HASH, quote="the", why=""),
        )
        assert not result.quote_verified
        assert result.quote_reason == QUOTE_REASON_SHORT
        assert result.error is None

    def test_absent_wording_is_named(self, monkeypatch):
        self._stub_pages(monkeypatch, ["The board approved the transfer on 3 March."])
        result = _cite_one(
            _acl(),
            "s1",
            Citation(
                collectionname="testdata",
                file_hash=HASH,
                quote="the committee rejected the plan",
                why="",
            ),
        )
        assert not result.quote_verified
        assert result.quote_reason == QUOTE_REASON_ABSENT
        assert result.error is None

    def test_a_missing_document_is_a_lookup_failure(self, monkeypatch):
        self._stub_pages(monkeypatch, [])
        result = _cite_one(
            _acl(),
            "s1",
            Citation(
                collectionname="testdata",
                file_hash=HASH,
                quote="approved the transfer",
                why="",
            ),
        )
        assert not result.quote_verified
        assert result.quote_reason == QUOTE_REASON_LOOKUP_FAILED
        assert result.error == "no extracted text for this document"
        assert result.handle == ""

    def test_a_query_error_is_a_lookup_failure(self, monkeypatch):
        import collection_search_server.server as srv

        def boom(sql, database, params=None):
            raise RuntimeError("ClickHouse error 500: boom")

        monkeypatch.setattr(srv, "clickhouse_query", boom)
        result = _cite_one(
            _acl(),
            "s1",
            Citation(
                collectionname="testdata",
                file_hash=HASH,
                quote="approved the transfer",
                why="",
            ),
        )
        assert result.quote_reason == QUOTE_REASON_LOOKUP_FAILED
        assert result.error is not None and result.error.startswith("lookup failed:")

    def test_a_quote_that_crosses_a_fetch_batch_verifies(self, monkeypatch):
        pages = [
            "aaaa " * 10,
            "bbbb The board approved the",
            "transfer on 3 March. cccc",
            "dddd " * 10,
        ]
        self._stub_pages(monkeypatch, pages)
        result = _cite_one(
            _acl(),
            "s1",
            Citation(
                collectionname="testdata",
                file_hash=HASH,
                quote="approved the transfer on 3 March",
                why="",
            ),
        )
        assert result.quote_verified
        assert result.quote_reason == ""


class TestHandleTable:
    def test_handles_count_up_from_one_per_session(self):
        table = HandleTable()
        assert table.handle_for("s1", "c", "h1") == "[D1]"
        assert table.handle_for("s1", "c", "h2") == "[D2]"

    def test_the_same_document_keeps_its_handle(self):
        """Two paragraphs of one answer citing the same file must point at one card."""
        table = HandleTable()
        first = table.handle_for("s1", "c", "h1")
        table.handle_for("s1", "c", "h2")
        assert table.handle_for("s1", "c", "h1") == first

    def test_two_sessions_number_independently(self):
        table = HandleTable()
        assert table.handle_for("s1", "c", "h1") == "[D1]"
        assert table.handle_for("s2", "c", "h9") == "[D1]"

    def test_the_same_hash_in_two_collections_is_two_documents(self):
        table = HandleTable()
        assert table.handle_for("s1", "alpha", "h1") == "[D1]"
        assert table.handle_for("s1", "beta", "h1") == "[D2]"

    def test_a_full_session_returns_no_handle_rather_than_reusing_one(self):
        """Wrapping around would make `[D1]` mean two documents inside one conversation,
        which corrupts the citations already on screen."""
        table = HandleTable()
        for i in range(MAX_HANDLES_PER_SESSION):
            assert table.handle_for("s1", "c", f"h{i}")
        assert table.handle_for("s1", "c", "overflow") == ""

    def test_the_oldest_session_is_evicted_whole(self):
        """A session that falls out gets fresh numbering rather than a table with holes:
        `[D3]` meaning two things is worse than `[D1]` starting over."""
        table = HandleTable(max_sessions=2)
        table.handle_for("s1", "c", "h1")
        table.handle_for("s2", "c", "h1")
        table.handle_for("s3", "c", "h1")
        assert table.session_count() == 2
        assert table.handle_for("s1", "c", "h1") == "[D1]"
