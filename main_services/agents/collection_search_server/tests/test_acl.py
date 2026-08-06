"""ACL and query-sanitisation tests.

These are the security-relevant parts of the server, so they are tested without any
database: everything here is pure.
"""

import pytest

from collection_search_server.acl import AccessDenied, CallerAcl, parse_acl
from collection_search_server.backends import (
    escape_manticore_string,
    prepare_match_query,
    sanitize_match_query,
)


def headers(**kwargs):
    return {k.replace("_", "-"): v for k, v in kwargs.items()}


class TestParseAcl:
    def test_reads_collections_and_user(self, monkeypatch):
        monkeypatch.delenv("MCP_SHARED_SECRET", raising=False)
        acl = parse_acl(
            {"X-Hoover4-Collections": "alpha,beta", "X-Hoover4-User": "ann"}
        )
        assert acl.collections == ("alpha", "beta")
        assert acl.username == "ann"

    def test_header_lookup_is_case_insensitive(self, monkeypatch):
        monkeypatch.delenv("MCP_SHARED_SECRET", raising=False)
        assert parse_acl({"x-hoover4-collections": "alpha"}).collections == ("alpha",)

    def test_missing_collections_header_is_denied(self, monkeypatch):
        monkeypatch.delenv("MCP_SHARED_SECRET", raising=False)
        with pytest.raises(AccessDenied, match="missing"):
            parse_acl({})

    def test_empty_collections_header_means_no_access(self, monkeypatch):
        """An empty list is a valid statement: this user may read nothing."""
        monkeypatch.delenv("MCP_SHARED_SECRET", raising=False)
        assert parse_acl({"X-Hoover4-Collections": ""}).collections == ()

    def test_bearer_token_is_required_when_configured(self, monkeypatch):
        monkeypatch.setenv("MCP_SHARED_SECRET", "s3cret")
        with pytest.raises(AccessDenied, match="bearer"):
            parse_acl({"X-Hoover4-Collections": "alpha"})
        with pytest.raises(AccessDenied, match="bearer"):
            parse_acl(
                {"X-Hoover4-Collections": "alpha", "Authorization": "Bearer wrong"}
            )
        ok = parse_acl(
            {"X-Hoover4-Collections": "alpha", "Authorization": "Bearer s3cret"}
        )
        assert ok.collections == ("alpha",)

    def test_bad_collectionname_is_rejected(self, monkeypatch):
        """A name reaching SQL must satisfy the shared collectionname rule."""
        monkeypatch.delenv("MCP_SHARED_SECRET", raising=False)
        for bad in ["Alpha", "al-pha", "al pha", "a" * 49, "al';DROP"]:
            with pytest.raises(AccessDenied, match="invalid collectionname"):
                parse_acl({"X-Hoover4-Collections": bad})


class TestCheck:
    def test_no_request_means_everything_permitted(self):
        acl = CallerAcl("ann", ("alpha", "beta"))
        assert acl.check(None) == ["alpha", "beta"]
        assert acl.check([]) == ["alpha", "beta"]

    def test_subset_request_is_honoured(self):
        assert CallerAcl("ann", ("alpha", "beta")).check(["beta"]) == ["beta"]

    def test_request_outside_the_acl_is_denied_not_filtered(self):
        acl = CallerAcl("ann", ("alpha",))
        with pytest.raises(AccessDenied, match="secret_docs"):
            acl.check(["alpha", "secret_docs"])

    def test_user_with_no_collections_cannot_search(self):
        with pytest.raises(AccessDenied, match="no collections"):
            CallerAcl("ann", ()).check(None)


class TestManticoreEscaping:
    def test_quote_and_backslash_are_escaped(self):
        assert escape_manticore_string("O'Brien") == "O\\'Brien"
        # The backslash pass must run first, or the escape it adds gets re-escaped.
        assert escape_manticore_string("a\\b") == "a\\\\b"
        assert escape_manticore_string("a\\'b") == "a\\\\\\'b"

    def test_injection_attempt_cannot_close_the_literal(self):
        """The escaping is the injection barrier and is unchanged by Q7.

        Operators are no longer stripped, so this is the *only* thing standing between
        caller text and the query. `'` must not survive unescaped in any form.
        """
        out = sanitize_match_query("x') OR 1=1 --")
        assert "')" not in out.replace("\\'", "")
        assert out.startswith("x")
        assert sanitize_match_query("a\\'; DROP").count("\\\\") == 1


class TestMatchOperatorsPassThrough:
    """Q7: the operators are the point, so they must survive sanitisation.

    Every expression here was run against the live `testdata_1_pages` shard and returns
    rows rather than an HTTP 500 — see the battery in `main_services/agents/README.md`.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "test document",
            "test | zzz",
            "test -zzz",
            '"test document"',
            '"test document"~5',
            '"one two three"/2',
            "test NEAR/3 document",
            "test SENTENCE document",
            "test PARAGRAPH document",
            "test MAYBE document",
            "(test | document) the",
            "test^3",
            "=test",
            "@page_text test",
            "@page_text ^test",
            "docum*",
            "*ocument*",
        ],
    )
    def test_operator_survives(self, query):
        assert sanitize_match_query(query) == query

    def test_whitespace_is_still_collapsed(self):
        assert sanitize_match_query("a  \n b\tc") == "a b c"


class TestMatchQueryRepairs:
    """The three shapes that come back as a 500 the model cannot interpret."""

    def test_unbalanced_quote_is_repaired_not_passed_through(self):
        # `"test` alone is `syntax error, unexpected $end` from Manticore.
        prepared = prepare_match_query('"test')
        assert prepared.expr == "test"
        assert prepared.repairs and "unbalanced" in prepared.repairs[0]

    def test_balanced_quotes_are_left_alone(self):
        assert prepare_match_query('"test document"').repairs == ()

    def test_missing_close_paren_is_closed(self):
        prepared = prepare_match_query("(test | document")
        assert prepared.expr == "(test | document)"
        assert "missing ')'" in prepared.repairs[0]

    def test_surplus_close_paren_is_dropped(self):
        prepared = prepare_match_query("test) document")
        assert prepared.expr == "test document"
        assert "unmatched ')'" in prepared.repairs[0]

    def test_not_only_query_is_refused_with_a_usable_message(self):
        # `-zzz` alone: `query is non-computable (single NOT operator)`.
        prepared = prepare_match_query("-zzz")
        assert prepared.expr == ""
        assert "negations alone" in prepared.error

    def test_a_positive_term_makes_a_negation_fine(self):
        assert prepare_match_query("test -zzz").expr == "test -zzz"

    def test_a_quoted_phrase_counts_as_positive(self):
        assert prepare_match_query('"test document" -zzz').error is None

    def test_boolean_keywords_alone_are_not_a_positive_term(self):
        assert prepare_match_query("NEAR/3 -zzz").expr == ""

    def test_empty_query_is_refused_rather_than_matching_everything(self):
        # MATCH('') is not an error — it returns every row in the shard, which is the
        # worst possible default for a tool an LLM drives.
        for empty in ["", "   ", "\t\n"]:
            prepared = prepare_match_query(empty)
            assert prepared.expr == ""
            assert prepared.error == "query is empty"


class TestFieldOperatorRewriting:
    """`page_text` is the only full-text field; every other `@name` is a hard 500."""

    def test_bare_at_word_in_prose_becomes_a_search_word(self):
        prepared = prepare_match_query("who paid @acme")
        assert prepared.expr == "who paid acme"
        assert "not a searchable field" in prepared.repairs[0]

    def test_unknown_field_is_rewritten(self):
        # `@title test` is `no field 'title' found in schema`.
        assert prepare_match_query("@title test").expr == "title test"

    def test_the_real_field_is_preserved(self):
        assert prepare_match_query("@page_text test").repairs == ()

    def test_all_fields_operator_is_preserved(self):
        assert prepare_match_query("@* test").expr == "@* test"

    def test_field_group_is_rewritten_when_any_name_is_unknown(self):
        assert prepare_match_query("@(title,body) test").expr == "title body test"


class TestCollectionArgumentCoercion:
    """`collections` must survive an XML-style tool-call parser.

    Qwen3.5 needs vLLM's `qwen3_xml` parser, which hands every argument across as a
    string — so a `list[str]` parameter arrives as the literal `'["testdata"]'`. Before
    this coercion, pydantic rejected it, the model retried the identical call, and the
    agent exhausted its 25-step recursion budget without ever running a search.
    """

    def test_a_json_encoded_list_is_parsed(self):
        from collection_search_server.server import _as_collection_list

        assert _as_collection_list('["testdata"]') == ["testdata"]
        assert _as_collection_list('["a", "b"]') == ["a", "b"]

    def test_a_real_list_is_untouched(self):
        from collection_search_server.server import _as_collection_list

        assert _as_collection_list(["a", "b"]) == ["a", "b"]

    def test_none_stays_none_because_it_means_every_permitted_collection(self):
        from collection_search_server.server import _as_collection_list

        assert _as_collection_list(None) is None

    def test_a_bare_name_becomes_a_single_element_list(self):
        from collection_search_server.server import _as_collection_list

        assert _as_collection_list("testdata") == ["testdata"]

    def test_a_comma_separated_string_is_split(self):
        from collection_search_server.server import _as_collection_list

        assert _as_collection_list("alpha, beta") == ["alpha", "beta"]

    def test_empty_and_malformed_do_not_raise(self):
        from collection_search_server.server import _as_collection_list

        assert _as_collection_list("") is None
        assert _as_collection_list("   ") is None
        assert _as_collection_list(7) is None
        # Unparseable JSON falls back to the comma split rather than blowing up.
        assert _as_collection_list('["unclosed') == ['["unclosed']


class TestHashValidation:
    """`_attach_paths` builds a ClickHouse array literal by hand, so only real content
    hashes may reach it."""

    def test_accepts_pipeline_hashes(self):
        from collection_search_server.server import _is_hash

        assert _is_hash("a" * 64)  # sha3-256, what the pipeline uses
        assert _is_hash("0" * 32)  # md5
        assert _is_hash("f" * 128)  # sha3-512

    def test_rejects_anything_that_could_break_the_literal(self):
        from collection_search_server.server import _is_hash

        for bad in ["", "short", "A" * 64, "'; DROP --", "a" * 129, "abc','xyz"]:
            assert not _is_hash(bad), f"should reject {bad!r}"
