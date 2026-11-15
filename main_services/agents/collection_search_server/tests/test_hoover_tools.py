"""`parse_link` of the `hoover` pack: the rows that the model reads, and the route call."""

from __future__ import annotations

import json

from collection_search_server import tools_hoover
from collection_search_server.acl import CallerAcl
from collection_search_server.backend_client import AgentError


RESPONSE = {
    "links": [
        {
            "url": "https://hoover.example.org/ai_chat/boards/b1",
            "reference": {
                "handle": "",
                "link": {"kind": "board", "board_id": "b1", "node": ""},
                "label": "Lease review",
                "kind": "board",
                "tool": "read_board",
                "arguments": {"board_id": "b1"},
                "url": "/ai_chat/boards/b1",
                "note": "",
            },
            "error": None,
        },
        {"url": "/admin", "reference": None, "error": "the link names no Hoover item"},
        {
            "url": "/search/x/0/y/z",
            "reference": {
                "handle": "", "link": {"kind": "search"}, "label": "pipeline", "kind": "search",
                "tool": "search_collections", "arguments": {"query": "pipeline"},
                "url": "/search/x/0/y/z", "note": "The search page also filters by virus_hit, and the tool has no argument for it.",
            },
        },
    ]
}


def test_each_link_gives_its_tool_call_or_its_error():
    rows = tools_hoover.link_rows(RESPONSE)
    assert rows[0] == {"url": "/ai_chat/boards/b1", "kind": "board", "label": "Lease review",
                       "tool": "read_board", "arguments": {"board_id": "b1"}}
    assert rows[1] == {"url": "/admin", "error": "the link names no Hoover item"}
    assert rows[2]["note"].startswith("The search page also filters by virus_hit")
    assert "link" not in rows[0] and "handle" not in rows[0]


def test_the_tool_posts_the_links_to_the_route(monkeypatch):
    calls = []

    class Client:
        def post(self, route, request, response_model=None, expected_source=None):
            calls.append((route, request.model_dump()))
            return RESPONSE

    monkeypatch.setattr(tools_hoover, "BackendClient", Client)
    monkeypatch.setattr(tools_hoover.server, "_caller", lambda: CallerAcl("alice", ()))
    body = json.loads(tools_hoover.parse_link.fn(["https://hoover.example.org/ai_chat/boards/b1"]))
    # A run without collections sends an empty list, so the route reads no dataset item.
    assert calls == [("links/parse", {"urls": ["https://hoover.example.org/ai_chat/boards/b1"], "collections": []})]
    assert body["success"] is True and len(body["links"]) == 3


def test_a_route_error_is_the_tool_result(monkeypatch):
    class Client:
        def post(self, route, request, response_model=None, expected_source=None):
            return AgentError(error="invalid_argument", message="give at most 20 links in one call")

    monkeypatch.setattr(tools_hoover, "BackendClient", Client)
    monkeypatch.setattr(tools_hoover.server, "_caller", lambda: CallerAcl("alice", ("enron",)))
    body = json.loads(tools_hoover.parse_link.fn(["/x"]))
    assert body == {"success": False, "error": "invalid_argument", "message": "give at most 20 links in one call"}


def test_the_description_says_what_a_reference_marker_means():
    assert "[R1]" in tools_hoover.PARSE_LINK_TEXT
    assert "a message or a page holds a Hoover link" in tools_hoover.PARSE_LINK_TEXT
