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


# ---------------------------------------------------------------------------------
# Chats, boards and manuals
# ---------------------------------------------------------------------------------

class RouteClient:
    """Answers each route with a fixed body and records the calls."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def post(self, route, request, response_model=None, expected_source=None):
        self.calls.append((route, request.model_dump()))
        answer = self.answers[route]
        return answer(request) if callable(answer) else answer


class MemoryStore:
    """The binding rows of `item_citations.ItemHandleStore`, in memory."""

    def __init__(self):
        self.rows = {}

    def load(self, owner, session_id):
        return {key[2:]: handle for key, handle in self.rows.items() if key[:2] == (owner, session_id)}

    def persist(self, owner, session_id, kind, item_id, handle):
        self.rows[(owner, session_id, kind, item_id)] = handle


def test_one_list_tool_gives_chats_and_boards(monkeypatch):
    client = RouteClient({
        "chats/list": {"chats": [{"session_id": "s1", "title": "Budget"}], "total": 21, "page": 0, "next_page": 1},
        "boards/list": {"boards": [{"board_id": "b1", "title": "Who paid"}], "total": 1, "page": 0},
    })
    monkeypatch.setattr(tools_hoover, "BackendClient", lambda: client)
    body = json.loads(tools_hoover.list_chats_and_boards.fn(query="budget"))
    assert body["success"] is True
    assert body["chats"][0]["session_id"] == "s1" and body["boards"][0]["board_id"] == "b1"
    assert body["chats_total"] == 21 and body["next_page"] == 1
    assert [route for route, _ in client.calls] == ["chats/list", "boards/list"]
    assert client.calls[0][1] == {"query": "budget", "page": 0, "ids": []}
    client.calls.clear()
    body = json.loads(tools_hoover.list_chats_and_boards.fn(kind="board"))
    assert [route for route, _ in client.calls] == ["boards/list"] and "chats" not in body and "next_page" not in body


def test_the_read_tools_post_their_routes(monkeypatch):
    client = RouteClient({
        "chats/read": {"session_id": "s1", "turns": []},
        "boards/read": {"board_id": "b1", "findings": []},
        "manual/search": {"sections": [{"manual": "user", "section": "4-search", "link": "/docs#4-search"}]},
        "manual/read": {"section": "datasets", "link": "/docs/admin#datasets"},
    })
    monkeypatch.setattr(tools_hoover, "BackendClient", lambda: client)
    assert json.loads(tools_hoover.read_chat.fn(session_id="s1", page=2))["session_id"] == "s1"
    assert json.loads(tools_hoover.read_board.fn(board_id="b1", node="finding-cash"))["success"] is True
    assert json.loads(tools_hoover.search_manual.fn(query="filter by date"))["sections"][0]["link"] == "/docs#4-search"
    assert json.loads(tools_hoover.read_manual.fn(section="datasets", manual="admin"))["link"] == "/docs/admin#datasets"
    assert client.calls == [
        ("chats/read", {"session_id": "s1", "page": 2}),
        ("boards/read", {"board_id": "b1", "node": "finding-cash"}),
        ("manual/search", {"query": "filter by date"}),
        ("manual/read", {"section": "datasets", "manual": "admin"}),
    ]


def test_an_unreadable_board_is_the_tool_error(monkeypatch):
    client = RouteClient({"boards/read": AgentError(error="permission_denied", message="the board belongs to a group of which the user is not a member")})
    monkeypatch.setattr(tools_hoover, "BackendClient", lambda: client)
    body = json.loads(tools_hoover.read_board.fn(board_id="b2"))
    assert body["success"] is False and body["error"] == "permission_denied"


def test_citations_number_chats_and_boards_once_for_the_session():
    store = MemoryStore()
    client = RouteClient({
        "chats/list": lambda request: {"chats": [{"session_id": i, "title": f"Chat {i}", "link": f"/ai_chat/c/{i}/9g==/9g=="}
                                                 for i in request.ids if i != "hidden"]},
        "boards/list": lambda request: {"boards": [{"board_id": i, "title": f"Board {i}", "link": f"/ai_chat/boards/{i}"}
                                                   for i in request.ids]},
    })
    items = tools_hoover._as_item_list('[{"kind":"chat","id":"s1","why":"the budget"},{"kind":"board","id":"b1"},'
                                       '{"kind":"chat","id":"hidden"}]')
    first = tools_hoover.cite_items(items, "alice", "sess", client, store)
    assert [(c["handle"], c["id"]) for c in first["citations"]] == [("[C1]", "s1"), ("[B1]", "b1")]
    assert first["citations"][0]["why"] == "the budget" and first["citations"][1]["link"] == "/ai_chat/boards/b1"
    assert first["errors"][0]["id"] == "hidden"
    # A later call keeps the handle of an item and numbers a new item after it.
    second = tools_hoover.cite_items(tools_hoover._as_item_list([{"kind": "chat", "id": "s2"}, {"kind": "chat", "id": "s1"}]),
                                     "alice", "sess", client, store)
    assert [c["handle"] for c in second["citations"]] == ["[C2]", "[C1]"]
    # Another session numbers from 1.
    other = tools_hoover.cite_items(tools_hoover._as_item_list({"kind": "board", "id": "b9"}), "alice", "other", client, store)
    assert other["citations"][0]["handle"] == "[B1]"
    # The ids of one kind go to the route in one call.
    assert ("chats/list", {"query": "", "page": 0, "ids": ["hidden", "s1"]}) in client.calls


def test_a_citation_needs_a_chat_session_and_a_valid_list(monkeypatch):
    monkeypatch.setattr(tools_hoover.server, "_caller", lambda: CallerAcl("alice", ()))
    monkeypatch.setattr(tools_hoover.server, "_session_id", lambda: "_no_session")
    body = json.loads(tools_hoover.cite_chats_and_boards.fn(items=[{"kind": "chat", "id": "s1"}]))
    assert body == {"success": False, "error": "Chat and board citations need a chat session."}
    assert tools_hoover._as_item_list('[{"kind":"folder","id":"x"}]') is None
    assert tools_hoover._as_item_list("not json") is None


def test_the_handle_limit_of_a_kind(monkeypatch):
    from collection_search_server import item_citations

    store = MemoryStore()
    for n in range(1, item_citations.MAX_HANDLES + 1):
        store.rows[("alice", "sess", "chat", f"s{n}")] = f"[C{n}]"
    assert item_citations.allocate(store, "alice", "sess", "chat", "new") == ""
    assert item_citations.allocate(store, "alice", "sess", "board", "b1") == "[B1]"
    assert item_citations.binding_id("a", "s", "chat", "x") == item_citations.binding_id("a", "s", "chat", "x")
    assert item_citations.binding_id("a", "s", "chat", "x") != item_citations.binding_id("a", "s", "board", "x")


def test_the_descriptions_name_the_requests_that_they_answer():
    assert "earlier chats, boards or work" in tools_hoover.LIST_TEXT
    assert "[C1]" in tools_hoover.CITE_ITEMS_TEXT and "[B1]" in tools_hoover.CITE_ITEMS_TEXT
    assert "use of Hoover" in tools_hoover.SEARCH_MANUAL_TEXT
    assert "[Search](/docs#4-search)" in tools_hoover.READ_MANUAL_TEXT
