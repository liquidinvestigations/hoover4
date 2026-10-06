"""Verify that both search endpoints use authentication."""

from collection_search_server import backends
import pytest


@pytest.mark.parametrize("endpoint", ["text", "vectors"])
def test_endpoint_authentication(monkeypatch, endpoint):
    monkeypatch.setenv("MANTICORE_VECTORS_URL", "http://vectors.invalid")
    calls = []

    class Response:
        status_code = 200
        def json(self):
            return [{"data": [{"id": 1}], "error": ""}]

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return Response()

    monkeypatch.setattr(backends.requests, "post", post)
    query = backends.manticore_query if endpoint == "text" else backends.manticore_vectors_query
    assert query("SELECT id FROM t") == [{"id": 1}]
    assert calls[0][1]["auth"] == ("manticore", "manticore")


def test_query_options_apply_expansion_only_to_pages(monkeypatch):
    monkeypatch.setenv("HOOVER4_SEARCH_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("HOOVER4_MANTICORE_EXPANSION_LIMIT", "500")
    assert backends.manticore_query_options(42) == "OPTION max_matches=42,max_query_time=12000,expansion_limit=500"
    assert "expansion_limit" not in backends.manticore_query_options(42, pages=False)
    monkeypatch.setenv("HOOVER4_MANTICORE_EXPANSION_LIMIT", "0")
    assert "expansion_limit" not in backends.manticore_query_options(42)


@pytest.mark.parametrize("query", ["*a*", "(*ab*)", "word | *é*", "-*xy*"])
def test_short_infix_has_an_explanation(query):
    prepared = backends.prepare_match_query(query)
    assert "Infix searches require at least three characters between the asterisks." in prepared.repairs
