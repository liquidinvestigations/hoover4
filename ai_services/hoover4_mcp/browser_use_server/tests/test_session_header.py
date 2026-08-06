"""Reading the chat session id off the request.

Small surface, but getting it wrong is invisible: a missed header does not error, it
silently drops every conversation into the shared anonymous session and the isolation
this module exists for stops happening with nothing in the logs.
"""

import pytest

from browser_use_server import server


@pytest.fixture
def headers(monkeypatch):
    """Patch the FastMCP header dependency with whatever the test wants."""

    def _set(value):
        monkeypatch.setattr(server, "get_http_headers", lambda: value)

    return _set


def test_the_session_id_is_read_from_the_header(headers):
    headers({"x-hoover4-chat-session": "chat-abc"})
    assert server._session_id() == "chat-abc"


def test_the_lookup_is_case_insensitive(headers):
    # Starlette lower-cases header names, a plain dict does not, and the agent sends
    # the canonical mixed-case spelling.
    headers({"X-Hoover4-Chat-Session": "chat-abc"})
    assert server._session_id() == "chat-abc"


def test_surrounding_whitespace_is_stripped(headers):
    headers({"x-hoover4-chat-session": "  chat-abc \n"})
    assert server._session_id() == "chat-abc"


def test_an_absent_header_means_the_anonymous_session(headers):
    headers({"authorization": "Bearer x"})
    assert server._session_id() is None


def test_an_empty_header_is_not_a_session_id(headers):
    headers({"x-hoover4-chat-session": "   "})
    assert server._session_id() is None


def test_no_request_context_is_not_an_error(monkeypatch):
    # `browse_page` is callable outside HTTP (tests, direct import). It must degrade to
    # the anonymous session rather than raise.
    def boom():
        raise RuntimeError("no active request")

    monkeypatch.setattr(server, "get_http_headers", boom)
    assert server._session_id() is None


def test_other_headers_do_not_leak_in(headers):
    headers({"x-hoover4-user": "ann", "x-hoover4-collections": "testdata"})
    assert server._session_id() is None
