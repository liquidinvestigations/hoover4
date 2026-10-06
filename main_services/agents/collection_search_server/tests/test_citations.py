"""The quote check and the handle table behind `cite_documents`."""

import json

import pytest

from collection_search_server.acl import CallerAcl
from collection_search_server.citations import (
    HandleTable,
    MAX_HANDLES_PER_SESSION,
    PAGE_JOIN,
    QUOTE_MATCH_VERIFIED,
    QUOTE_REASON_ABSENT,
    QUOTE_REASON_LOOKUP_FAILED,
    QUOTE_REASON_SHORT,
    citation_find_query,
    find_in_quote,
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
                # Pages are keyed ("raw_text", 1), ("raw_text", 2), ... and each batch
                # continues after the key of the last page read, with no OFFSET.
                assert "OFFSET" not in sql
                assert params["dataset"] == dataset
                after = (params["after_source"], int(params["after_page"]))
                limit = int(params.get("limit") or VERIFY_PAGE_BATCH)
                keyed = [("raw_text", index + 1, text) for index, text in enumerate(pages)]
                chunk = [row for row in keyed if (row[0], row[1]) > after][:limit]
                return [{"extracted_by": source, "page_id": page, "text": text} for source, page, text in chunk]
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
        assert result.page == 2 and result.extracted_by == "raw_text"
        assert result.quote_reason == ""
        assert result.error is None
        assert result.handle == "[D1]"
        assert result.path == "/doc.txt"

    def test_a_find_phrase_of_the_quote_becomes_the_find_query(self, monkeypatch):
        quote = "Your notes look great.  Best of luck today with the Hearings."
        self._stub_pages(monkeypatch, [quote])
        result = _cite_one(_acl(), "s1", Citation(
            collectionname="testdata", file_hash=HASH, quote=quote, find="Your notes look great"))
        assert result.quote_verified
        assert result.find_query == '"Your notes look great"'

    def test_a_search_term_stays_separate_from_the_quote_find(self, monkeypatch):
        quote = "The board approved the transfer on 3 March."
        self._stub_pages(monkeypatch, [quote])
        result = _cite_one(_acl(), "s1", Citation(
            collectionname="testdata", file_hash=HASH, quote=quote, term="board transfer"))
        assert result.term == "board transfer"
        assert result.find_query == '"The board approved the transfer on 3 March."'

    def test_a_find_phrase_outside_the_quote_falls_back_to_the_quote(self, monkeypatch):
        quote = "Your notes look great. Best of luck today."
        self._stub_pages(monkeypatch, [quote])
        result = _cite_one(_acl(), "s1", Citation(
            collectionname="testdata", file_hash=HASH, quote=quote, find="Something else entirely"))
        assert result.find_query == '"Your notes look great. Best of luck today."'

    def test_no_find_phrase_opens_at_the_quote(self, monkeypatch):
        quote = 'He wrote "approved" on the draft of the talking points.'
        self._stub_pages(monkeypatch, [quote])
        result = _cite_one(_acl(), "s1", Citation(
            collectionname="testdata", file_hash=HASH, quote=quote))
        # A double quote inside the text would end the phrase early.
        assert result.find_query == '"He wrote approved on the draft of the talking points."'

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


class TestFindPhrase:
    def test_a_phrase_of_the_quote_checks_after_folding(self):
        assert find_in_quote("YOUR NOTES  look great", "Your notes look great. Best of luck.")

    def test_a_short_phrase_fails(self):
        assert not find_in_quote("notes", "Your notes look great. Best of luck.")

    def test_an_empty_quote_and_find_give_no_query(self):
        assert citation_find_query("", "") == ""


class TestHashStart:
    """A file hash start of at least 12 characters names its document, in
    `cite_documents` and in `read_documents`."""

    FULL = "3f9a0c1b2d4e" + "5" * 52

    def _stub(self, monkeypatch, hashes, quote="the cited sentence of the memo"):
        import collection_search_server.server as srv

        asked = []

        def fake_query(sql, database, params=None):
            params = params or {}
            if "startsWith" in sql:
                asked.append(params["prefix"])
                return [{"hash": h} for h in hashes if h.startswith(params["prefix"])]
            if "text_content" in sql:
                after = (params["after_source"], int(params["after_page"]))
                if ("raw_text", 1) <= after:
                    return []
                return [{"extracted_by": "raw_text", "page_id": 1, "text": quote}]
            if "vfs_files" in sql:
                return [{"path": "/memo.txt", "collection_dataset": "testdata_ds"}]
            raise AssertionError(sql)

        monkeypatch.setattr(srv, "clickhouse_query", fake_query)
        return asked

    def test_a_unique_start_cites_the_whole_hash(self, monkeypatch):
        asked = self._stub(monkeypatch, [self.FULL, "b" * 64])
        result = _cite_one(_acl(), "s-start", Citation(
            collectionname="testdata", file_hash=self.FULL[:12],
            quote="the cited sentence of the memo"))
        assert asked == [self.FULL[:12]]
        assert (result.error, result.file_hash, result.handle) == (None, self.FULL, "[D1]")

    def test_an_ambiguous_start_is_refused_with_the_candidates(self, monkeypatch):
        other = self.FULL[:12] + "6" * 52
        self._stub(monkeypatch, [self.FULL, other])
        result = _cite_one(_acl(), "s-start", Citation(
            collectionname="testdata", file_hash=self.FULL[:12], quote="the cited sentence"))
        assert result.handle == ""
        assert self.FULL in result.error and other in result.error
        assert "start of more than one document" in result.error

    def test_a_start_shorter_than_12_is_not_looked_up(self, monkeypatch):
        asked = self._stub(monkeypatch, [self.FULL])
        result = _cite_one(_acl(), "s-start", Citation(
            collectionname="testdata", file_hash=self.FULL[:11], quote="the cited sentence"))
        assert asked == []
        assert result.error == "file_hash must be a content hash from search_collections"

    def test_read_documents_reads_the_whole_hash_of_a_start(self, monkeypatch):
        import json

        import collection_search_server.server as srv
        from collection_search_server import tools_document

        self._stub(monkeypatch, [self.FULL])
        monkeypatch.setattr(srv, "_caller", _acl)
        sent = []
        monkeypatch.setattr(tools_document, "_render",
                            lambda tool, values, **kwargs: sent.append(values) or "{}")
        result = json.loads(tools_document.read_documents.fn(
            collectionname="testdata", file_hash=[self.FULL[:12], "c" * 64]))
        # A whole hash that no document has is left out, and the result says so.
        assert sent[0]["file_hash"] == [self.FULL]
        assert "c" * 64 in result["file_hash_notes"][0]
        other = self.FULL[:12] + "6" * 52
        self._stub(monkeypatch, [self.FULL, other])
        refused = json.loads(tools_document.read_documents.fn(
            collectionname="testdata", file_hash=[self.FULL[:12]]))
        assert refused["error"] == "invalid_argument" and other in refused["message"]

    def test_read_documents_looks_up_no_start_in_a_collection_the_caller_cannot_read(
            self, monkeypatch):
        import collection_search_server.server as srv

        asked = self._stub(monkeypatch, [self.FULL])
        monkeypatch.setattr(srv, "_caller", _acl)
        assert srv.full_hashes("secret", [self.FULL[:12]]) == [self.FULL[:12]]
        assert asked == []


# ---------------------------------------------------------------- durable handles

from collection_search_server import binding_store  # noqa: E402
from collection_search_server.citations import (  # noqa: E402
    BindingStore,
    CitationNotStored,
    LoadedBindings,
    candidate_passage,
    merge_legacy,
)


class MemoryStore(BindingStore):
    """A store that keeps the bindings of every table that uses it, as the artifact rows
    keep them across a restart. `fail` makes the next persist raise, after or before it
    stores."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict[tuple[str, str], str]] = {}
        self.legacy: dict[tuple[str, str], list] = {}
        self.fail = ""
        self.loads = 0

    def load(self, owner, session_id):
        self.loads += 1
        return merge_legacy(dict(self.rows.get((owner, session_id), {})),
                            self.legacy.get((owner, session_id), []))

    def persist(self, owner, session_id, collectionname, file_hash, handle):
        if self.fail == "before":
            self.fail = ""
            raise RuntimeError("the store did not answer")
        self.rows.setdefault((owner, session_id), {})[(collectionname, file_hash)] = handle
        if self.fail == "after":
            self.fail = ""
            raise RuntimeError("the read back did not answer")


class TestDurableHandles:
    def test_a_new_process_keeps_the_stored_handles_and_numbers_after_them(self):
        store = MemoryStore()
        first = HandleTable(store=store)
        assert first.handle_for("s1", "c", "h1", owner="ann") == "[D1]"
        assert first.handle_for("s1", "c", "h2", owner="ann") == "[D2]"
        restarted = HandleTable(store=store)
        assert restarted.handle_for("s1", "c", "h2", owner="ann") == "[D2]"
        assert restarted.handle_for("s1", "c", "h3", owner="ann") == "[D3]"
        assert restarted.handle_for("s1", "c", "h1", owner="ann") == "[D1]"

    def test_a_failed_store_returns_no_handle_and_reuses_no_number(self):
        store = MemoryStore()
        table = HandleTable(store=store)
        store.fail = "before"
        with pytest.raises(CitationNotStored):
            table.handle_for("s1", "c", "h1", owner="ann")
        assert store.rows == {}
        assert table.handle_for("s1", "c", "h2", owner="ann") == "[D1]"

    def test_an_uncertain_store_reloads_and_keeps_the_stored_handle(self):
        """The row was written but its read back failed. The next call loads the session
        again, finds the handle, and gives the next document the next number."""
        store = MemoryStore()
        table = HandleTable(store=store)
        store.fail = "after"
        with pytest.raises(CitationNotStored):
            table.handle_for("s1", "c", "h1", owner="ann")
        loads = store.loads
        assert table.handle_for("s1", "c", "h1", owner="ann") == "[D1]"
        assert store.loads == loads + 1
        assert table.handle_for("s1", "c", "h2", owner="ann") == "[D2]"

    def test_two_owners_of_one_session_id_number_apart(self):
        table = HandleTable(store=MemoryStore())
        assert table.handle_for("s1", "c", "h1", owner="ann") == "[D1]"
        assert table.handle_for("s1", "c", "h9", owner="bob") == "[D1]"

    def test_unambiguous_legacy_handles_are_imported(self):
        store = MemoryStore()
        store.legacy[("ann", "s1")] = [("[D1]", ("c", "h1")), ("[D2]", ("c", "h2")),
                                       ("[D1]", ("c", "h1"))]
        table = HandleTable(store=store)
        assert table.handle_for("s1", "c", "h2", owner="ann") == "[D2]"
        assert table.handle_for("s1", "c", "h3", owner="ann") == "[D3]"

    def test_a_legacy_handle_of_two_documents_is_reserved_and_bound_to_neither(self):
        store = MemoryStore()
        store.legacy[("ann", "s1")] = [("[D1]", ("c", "h1")), ("[D1]", ("c", "h2"))]
        table = HandleTable(store=store)
        assert table.handle_for("s1", "c", "h1", owner="ann") == "[D2]"
        assert table.handle_for("s1", "c", "h2", owner="ann") == "[D3]"
        assert table.conflicts("s1", owner="ann") == [
            {"handle": "[D1]", "documents": [("c", "h1"), ("c", "h2")]}]

    def test_merge_reserves_every_number_and_lets_a_stored_binding_win(self):
        loaded = merge_legacy({("c", "h1"): "[D1]"},
                              [("[D1]", ("c", "h9")), ("[D4]", ("c", "h4")),
                               ("[D5]", ("c", "h4"))], {7})
        assert loaded.bindings == {("c", "h1"): "[D1]"}
        assert loaded.reserved == {1, 4, 5, 7}
        assert {"handle": "[D1]", "documents": [("c", "h1"), ("c", "h9")]} in loaded.conflicts
        assert {"document": ["c", "h4"], "handles": ["[D4]", "[D5]"]} in loaded.conflicts

    def test_cite_one_returns_a_citation_error_when_the_handle_is_not_stored(self, monkeypatch):
        import collection_search_server.server as srv

        store = MemoryStore()
        store.fail = "before"
        monkeypatch.setattr(srv, "_HANDLES", HandleTable(store=store))
        monkeypatch.setattr(srv, "get_http_headers", lambda: {"x-hoover4-user": "ann"})
        TestCiteOne()._stub_pages(monkeypatch, ["The board approved the transfer on 3 March."])
        result = _cite_one(_acl(), "s1", Citation(
            collectionname="testdata", file_hash=HASH, quote="approved the transfer on 3 March"))
        assert result.handle == ""
        assert result.quote_verified
        assert "not stored" in result.error


class TestBindingStore:
    def test_a_binding_is_a_required_artifact_with_a_fixed_id(self, monkeypatch):
        written = []
        monkeypatch.setattr(binding_store.artifacts, "write_required",
                            lambda request, artifact_id, key, body, ct: written.append(
                                (request, artifact_id, key, json.loads(body))))
        store = binding_store.ArtifactBindingStore()
        store.persist("ann", "s1", "c", HASH, "[D2]")
        store.persist("ann", "s1", "c", HASH, "[D2]")
        (request, artifact_id, key, body), again = written
        assert artifact_id == key == again[1]
        assert artifact_id == binding_store.binding_id("ann", "s1", "c", HASH)
        assert (request.kind, request.title, request.username) == (
            "citation_binding", "[D2]", "ann")
        assert body == {"owner": "ann", "session_id": "s1", "collectionname": "c",
                        "file_hash": HASH, "handle": "[D2]"}

    def test_a_call_with_no_session_or_owner_stores_nothing(self, monkeypatch):
        monkeypatch.setattr(binding_store.artifacts, "write_required",
                            lambda *a: pytest.fail("stored"))
        monkeypatch.setattr(binding_store, "clickhouse_query", lambda *a, **k: pytest.fail("read"))
        store = binding_store.ArtifactBindingStore()
        store.persist("", "s1", "c", HASH, "[D1]")
        store.persist("ann", binding_store.NO_SESSION, "c", HASH, "[D1]")
        assert store.load("", "s1") == LoadedBindings()

    def test_a_load_reads_stored_rows_transcript_refs_and_run_evidence(self, monkeypatch):
        other = "b" * 64

        def fake_query(sql, database, params=None):
            if "chat_artifacts" in sql:
                return [{"title": "[D1]",
                         "detail": json.dumps({"collectionname": "c", "file_hash": HASH})}]
            if "chat_messages" in sql:
                return [{"doc_refs": json.dumps([
                    {"handle": "[D2]", "collectionname": "c", "file_hash": other},
                    {"handle": "[D3]", "collectionname": "", "file_hash": "c" * 16}])}]
            if "agent_run_messages" in sql:
                return [
                    {"content": "{}", "usage_json": json.dumps({"evidence": [
                        {"kind": "citation", "status": "ok",
                         "reference": {"handle": "[D4]", "collectionname": "c",
                                       "file_hash": "d" * 64}}]})},
                    {"content": json.dumps({"citations": [{"handle": "[D6]"}]}),
                     "usage_json": json.dumps({"status": "ok"})},
                ]
            raise AssertionError(sql)

        monkeypatch.setattr(binding_store, "clickhouse_query", fake_query)
        loaded = binding_store.ArtifactBindingStore().load("ann", "s1")
        assert loaded.bindings == {("c", HASH): "[D1]", ("c", other): "[D2]",
                                   ("c", "d" * 64): "[D4]"}
        assert loaded.reserved == {1, 2, 3, 4, 6}
        assert loaded.conflicts == []


# -------------------------------------------------------------- candidate passage


class TestCandidatePassage:
    PAGE = ("Minutes of the meeting. The board approved the transfer of the lease on "
            "3 March 2019, after a short discussion. The next item was the budget.")

    def test_a_near_quote_gets_an_exact_passage_with_its_span(self):
        quote = "The board approved the transfer of the property on 3 March 2019"
        found = candidate_passage(quote, [("raw_text", 1, "Title page."),
                                          ("raw_text", 2, self.PAGE)])
        assert found is not None
        assert found["text"] in self.PAGE
        assert self.PAGE[found["start"]:found["end"]] == found["text"]
        assert (found["extracted_by"], found["page_id"]) == ("raw_text", 2)
        assert "approved the transfer" in found["text"]
        assert len(found["text"]) <= 400

    def test_a_quote_with_no_part_in_the_text_gets_none(self):
        assert candidate_passage("an entirely different sentence about the weather today",
                                 [("raw_text", 1, self.PAGE)]) is None

    def test_cite_one_keeps_the_quote_unverified_and_adds_the_candidate(self, monkeypatch):
        TestCiteOne()._stub_pages(monkeypatch, [self.PAGE])
        quote = "The board approved the transfer of the property on 3 March 2019"
        result = _cite_one(_acl(), "s-candidate", Citation(
            collectionname="testdata", file_hash=HASH, quote=quote))
        assert not result.quote_verified
        assert result.quote_reason == QUOTE_REASON_ABSENT
        assert result.quote == quote
        assert result.candidate["text"] in self.PAGE
        assert result.candidate["page_id"] == 1
        # The candidate verifies when it is cited as the quote.
        again = _cite_one(_acl(), "s-candidate", Citation(
            collectionname="testdata", file_hash=HASH, quote=result.candidate["text"]))
        assert again.quote_verified and again.candidate is None
