"""Verify caller authentication and request validation for the internal fetch route."""

import pytest
from starlette.testclient import TestClient

from browser_use_server import internal_fetch, server


@pytest.fixture
def route(monkeypatch, tmp_path):
    token = tmp_path / "token"
    token.write_text("test-only-token")
    monkeypatch.setenv("BROWSER_FETCH_TOKEN_FILE", str(token))
    calls = []
    async def fetch(pool, url, **kwargs):
        calls.append((pool.name, url, kwargs))
        return internal_fetch.FetchOutcome(status=200, url=url, body="Source response.")
    monkeypatch.setattr(internal_fetch, "fetch", fetch)
    return TestClient(server.mcp.http_app()), calls


def test_missing_or_incorrect_token_opens_no_tab(route):
    client, calls = route
    for headers in ({}, {"Authorization": "Bearer wrong-token"}):
        result = client.post("/internal/fetch", json={"url": "https://page.example"}, headers=headers)
        assert result.status_code == 403
    assert not calls


def test_non_ascii_token_is_refused(route):
    import asyncio
    from types import SimpleNamespace

    _, calls = route
    result = asyncio.run(server.fetch_for_search(SimpleNamespace(headers={"authorization": "Bearer é"})))
    assert result.status_code == 403 and not calls


def test_authorized_caller_uses_the_search_pool(route):
    client, calls = route
    result = client.post("/internal/fetch", json={"url": "https://page.example", "body": "dom"},
                         headers={"Authorization": "Bearer test-only-token"})
    assert result.status_code == 200 and result.json()["body"] == "Source response."
    assert calls[0][0] == "_metasearch" and calls[0][2]["body"] == "dom"


@pytest.mark.parametrize("extra", [{"method": "POST"}, {"timeout_s": "wrong"}, {"params": []}, {"headers": []}, {"body": "invalid"}])
def test_invalid_requests_open_no_tab(route, extra):
    client, calls = route
    result = client.post("/internal/fetch", json={"url": "https://page.example", **extra},
                         headers={"Authorization": "Bearer test-only-token"})
    assert result.status_code == 400 and not calls
