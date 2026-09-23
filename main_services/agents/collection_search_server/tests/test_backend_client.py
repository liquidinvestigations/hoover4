"""Tests for the collection MCP website client."""

from __future__ import annotations

import requests

from collection_search_server import backend_client


class Response:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class Session:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


def request():
    return backend_client.CollectionsListRequest()


def test_success_forwards_only_agent_identity_headers(monkeypatch):
    session = Session([Response(200, {"collections": [], "source": ""})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {"x-hoover4-user": "ann", "X-Hoover4-Collections": "testdata"})

    result = client.post("collections/list", request(), backend_client.CollectionsListResponse)

    assert result.collections == []
    assert session.calls[0][1]["headers"] == {"x-hoover4-user": "ann", "X-Hoover4-Collections": "testdata"}


def test_retries_one_transport_failure_then_succeeds(monkeypatch):
    session = Session([requests.ConnectionError("down"), Response(200, {"collections": [], "source": ""})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    assert client.post("collections/list", request(), backend_client.CollectionsListResponse).collections == []
    assert len(session.calls) == 2


def test_returns_typed_error_after_two_transport_failures(monkeypatch):
    session = Session([requests.ConnectionError("one"), requests.ConnectionError("two")])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    result = client.post("collections/list", request())

    assert result.error == "backend_unavailable"
    assert len(session.calls) == 2


def test_does_not_retry_permission_failure(monkeypatch):
    session = Session([Response(403, {"message": "denied"})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    result = client.post("collections/list", request())

    assert result.error == "permission_denied"
    assert len(session.calls) == 1


def test_timeout_is_typed_and_retried(monkeypatch):
    session = Session([requests.Timeout(), requests.Timeout()])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    result = client.post("collections/list", request())

    assert result.error == "timed_out"
    assert len(session.calls) == 2
