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
