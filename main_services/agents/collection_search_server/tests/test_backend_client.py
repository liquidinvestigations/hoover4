"""Tests for the collection MCP website client."""

from __future__ import annotations

import requests
import pytest
from pydantic import ValidationError

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


@pytest.mark.parametrize("failure, error", [
    (requests.ConnectionError("down"), "backend_unavailable"),
    (requests.Timeout(), "timed_out"),
    (Response(503, {"message": "busy"}), "backend_unavailable"),
    (Response(504, {"message": "gateway"}), "timed_out"),
])
def test_a_transport_failure_is_sent_once_and_marked_retryable(monkeypatch, failure, error):
    session = Session([failure, Response(200, {"collections": [], "source": ""})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    result = client.post("collections/list", request())

    assert result.error == error and result.retryable is True
    assert len(session.calls) == 1


def test_a_route_deadline_is_a_result_and_not_retryable(monkeypatch):
    session = Session([Response(504, {"error": "timed_out", "message": "the read took too long"})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    result = client.post("collections/list", request())

    assert result.error == "timed_out" and result.retryable is False


def test_does_not_retry_permission_failure(monkeypatch):
    session = Session([Response(403, {"message": "denied"})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})

    result = client.post("collections/list", request())

    assert result.error == "permission_denied" and result.retryable is False
    assert len(session.calls) == 1


def test_the_tool_text_names_retryable_only_when_true():
    import json

    from collection_search_server import paging

    retry = json.loads(paging.error_text(backend_client.AgentError(error="timed_out", message="m", retryable=True)))
    plain = json.loads(paging.error_text(backend_client.AgentError(error="not_found", message="m")))
    assert retry["retryable"] is True and "retryable" not in plain


def test_continuation_keeps_document_source(monkeypatch):
    session = Session([Response(200, {"documents": [], "source": "file:raw_text"})])
    client = backend_client.BackendClient("http://agent-api", session)
    monkeypatch.setattr(client, "caller_headers", lambda: {})
    request = backend_client.DocumentsReadRequest(
        collectionname="testdata", file_hash=["file"], source="raw_text"
    )

    client.post("documents/read", request, backend_client.DocumentsReadResponse, expected_source="file:raw_text")

    assert session.calls[0][1]["json"]["source"] == "raw_text"
    assert session.calls[0][1]["json"]["expected_source"] == "file:raw_text"


@pytest.mark.parametrize("values", [
    {"query": "bad\nquery"},
    {"sort": {"field": "invalid", "direction": "desc"}},
    {"sort": {"field": "date", "direction": "invalid"}},
    {"facet_filters": {"file_types": ["bad\x00value"]}},
    {"position": {"page": -1}},
])
def test_invalid_search_input_is_refused(values):
    with pytest.raises(ValidationError):
        backend_client.SearchResultsRequest.model_validate(values)


def test_invalid_table_filter_is_refused():
    with pytest.raises(ValidationError):
        backend_client.TablesPageRequest.model_validate({
            "collectionname": "c", "file_hash": "h", "sheet": 0,
            "filters": [{"column": 0, "contains": "x", "equals": "x"}],
        })


def test_node_key_fields_accept_only_the_separator_control_character():
    from collection_search_server.backend_client import FoldersListRequest

    key = "testdata_shapes\x1f\x1f/the-directory"
    assert FoldersListRequest(collectionname="testdata", dataset="shapes", node_id=key).node_id == key
    with pytest.raises(ValueError):
        FoldersListRequest(collectionname="testdata", dataset="shapes", node_id="a\x00b")
    with pytest.raises(ValueError):
        FoldersListRequest(collectionname="test\x1fdata", dataset="shapes")


def test_an_escaped_separator_in_a_node_key_is_the_separator():
    from collection_search_server.backend_client import FoldersListRequest, FoldersSearchRequest

    escaped = "textfiles_extra\\u001f\\u001F/"
    key = "textfiles_extra\x1f\x1f/"
    assert FoldersListRequest(collectionname="testdata", dataset="extra", node_id=escaped).node_id == key
    request = FoldersListRequest.model_validate({
        "collectionname": "testdata", "dataset": "extra",
        "position": {"kind": "NodeKey", "node_key": escaped},
    })
    assert request.position.node_key == key
    search = FoldersSearchRequest(collectionname="testdata", dataset="extra", query="a\\u001f", node_id=escaped)
    assert search.node_id == key and search.query == "a\\u001f"
