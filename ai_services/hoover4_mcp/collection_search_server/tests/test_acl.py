"""ACL and query-sanitisation tests.

These are the security-relevant parts of the server, so they are tested without any
database: everything here is pure.
"""

import pytest

from collection_search_server.acl import AccessDenied, CallerAcl, parse_acl
from collection_search_server.backends import escape_manticore_string, sanitize_match_query


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

    def test_operators_are_stripped_from_match_queries(self):
        assert sanitize_match_query("who paid @acme?") == "who paid acme?"
        assert sanitize_match_query('find "the money" | now') == "find the money now"
        assert sanitize_match_query("a  \n b\tc") == "a b c"

    def test_injection_attempt_cannot_close_the_literal(self):
        out = sanitize_match_query("x') OR 1=1 --")
        assert "') " not in out
        assert out.startswith("x")

    def test_query_of_only_operators_is_empty(self):
        assert sanitize_match_query("@|^~") == ""


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
