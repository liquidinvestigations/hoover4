"""The quote check and the handle table behind `cite_documents`."""

from collection_search_server.citations import (
    HandleTable,
    MAX_HANDLES_PER_SESSION,
    normalise_for_match,
    quote_occurs_in,
)


class TestQuoteVerification:
    def test_an_exact_quote_verifies(self):
        text = "The board approved the transfer on 3 March."
        assert quote_occurs_in("approved the transfer", text)

    def test_a_quote_the_document_does_not_contain_fails(self):
        text = "The board approved the transfer on 3 March."
        assert not quote_occurs_in("rejected the transfer", text)

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

    def test_normalisation_collapses_runs_of_whitespace(self):
        assert normalise_for_match("  a \n\t b  ") == "a b"


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
