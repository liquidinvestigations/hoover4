"""The tools of the `hoover` pack (`agent_common.tool_packs`), backed by the website agent API.

These tools read Hoover items that need no document source, so a run without a collection
binds them too.

- `parse_link` gives the item and the reading tool call of each Hoover link, with the parser
  and the read rule of the chat input (`website/backend/src/api/links.rs`).
- `list_chats_and_boards`, `read_chat` and `read_board` read the chats and the boards that the
  user reads under the group rule (`website/backend/src/api/agent/items.rs`). One list tool
  covers both kinds, because a small model chooses badly between two list tools.
- `cite_chats_and_boards` gives the handle `[Cn]` of a chat and `[Bn]` of a board
  (`item_citations`). The chat page shows the chat list card or the board overview card.
- `search_manual` and `read_manual` read the manuals of the `/docs` page
  (`website/backend/src/api/agent/manual.rs`). Each section has its page link.

The user is the identity of the run (`x-hoover4-user`). The website applies the read rule of
that user to every route.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from agent_common import artifacts
from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import (
    AgentError, BackendClient, BoardsReadRequest, ChatsReadRequest, ItemsListRequest,
    LinksParseRequest, ManualReadRequest, ManualSearchRequest,
)
from collection_search_server import item_citations
from collection_search_server.paging import error_text
from collection_search_server import server
from collection_search_server.server import mcp

#: The most links in one call. The website route refuses more.
MAX_LINKS = 20

#: The description of `parse_link`. The research agent translates it by this exact text
#: (`research_agent/tool_texts/`).
PARSE_LINK_TEXT = (
    "Return the kind, the name and the reading tool call of each Hoover link. Use it when a "
    "message or a page holds a Hoover link. A marker such as [R1] in a message names a "
    "pasted link that the References block of the message already gives."
)
URLS_TEXT = "Copy 1 to 20 Hoover links or paths exactly as written."


def link_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """One row for each link of a `links/parse` response: the item and its tool call, or
    the error. The storage form of the link stays out, because the tool call holds what a
    model needs."""
    rows = []
    for link in response.get("links") or []:
        reference = link.get("reference")
        if not reference:
            rows.append({"url": link.get("url", ""), "error": link.get("error") or "the link is not readable"})
            continue
        row = {key: reference.get(key) for key in ("url", "kind", "label", "tool", "arguments")}
        if reference.get("note"):
            row["note"] = reference["note"]
        rows.append(row)
    return rows


@mcp.tool(name="parse_link", description=PARSE_LINK_TEXT)
def parse_link(urls: Annotated[list[str], Field(min_length=1, max_length=MAX_LINKS, description=URLS_TEXT)]) -> str:
    # The route reads no dataset item outside the collections of the run, so a run without
    # collections still reads the chats and the boards of a link.
    collections = list(server._caller().collections)
    result = BackendClient().post("links/parse", LinksParseRequest(urls=list(urls), collections=collections))
    if isinstance(result, AgentError):
        return error_text(result)
    return canonical_json({"success": True, "links": link_rows(result)})


# ---------------------------------------------------------------------------------
# Chats and boards
# ---------------------------------------------------------------------------------

#: The descriptions of the chat and board tools. The research agent translates each by
#: this exact text (`research_agent/tool_texts/`).
LIST_TEXT = (
    "List the earlier chats and boards that the user can read. Use it when the user asks about "
    "earlier chats, boards or work. The newest items come first."
)
LIST_QUERY_TEXT = "Words that the title or the summary must hold. Empty lists every item."
LIST_KIND_TEXT = "chat, board, or both."
PAGE_TEXT = "The page of the result, from 0. A result with next_page has more."
READ_CHAT_TEXT = (
    "Read the questions and final answers of one earlier chat. A page holds five turns. Labels "
    "such as (D1) name the sources of that chat. Cite the chat itself with cite_chats_and_boards."
)
SESSION_ID_TEXT = "The session_id from list_chats_and_boards or from a chat link."
READ_BOARD_TEXT = (
    "Read the background, goals, answers and findings of one investigation board. Give node to "
    "read one node with its sources. Labels such as (D1) name the sources of that board. Cite "
    "the board itself with cite_chats_and_boards."
)
BOARD_ID_TEXT = "The board_id from list_chats_and_boards or from a board link."
NODE_TEXT = "The node name of a goal, finding or question of the board. Empty reads the whole board."
CITE_ITEMS_TEXT = (
    "Create handles that cite earlier chats and boards: [C1] for a chat, [B1] for a board. Write "
    "the returned handle beside the claim that relies on the chat or board. Cite each chat or "
    "board that you read and use."
)
ITEMS_TEXT = "One to twelve items, each with kind chat or board, id, and why: what the item supports."

#: The most items that one citation call takes.
MAX_CITED_ITEMS = 12


def _result(result: Any) -> str:
    if isinstance(result, AgentError):
        return error_text(result)
    return canonical_json({"success": True, **result})


@mcp.tool(name="list_chats_and_boards", description=LIST_TEXT)
def list_chats_and_boards(
    query: Annotated[str, Field(description=LIST_QUERY_TEXT)] = "",
    kind: Annotated[Literal["both", "chat", "board"], Field(description=LIST_KIND_TEXT)] = "both",
    page: Annotated[int, Field(ge=0, description=PAGE_TEXT)] = 0,
) -> str:
    client = BackendClient()
    out: dict[str, Any] = {}
    more = False
    for name, route in (("chats", "chats/list"), ("boards", "boards/list")):
        if kind not in ("both", name[:-1]):
            continue
        result = client.post(route, ItemsListRequest(query=query, page=page))
        if isinstance(result, AgentError):
            return error_text(result)
        out[name] = result.get(name) or []
        out[f"{name}_total"] = result.get("total", 0)
        more = more or result.get("next_page") is not None
    if more:
        out["next_page"] = page + 1
    return canonical_json({"success": True, **out})


@mcp.tool(name="read_chat", description=READ_CHAT_TEXT)
def read_chat(
    session_id: Annotated[str, Field(min_length=1, description=SESSION_ID_TEXT)],
    page: Annotated[int, Field(ge=0, description=PAGE_TEXT)] = 0,
) -> str:
    return _result(BackendClient().post("chats/read", ChatsReadRequest(session_id=session_id, page=page)))


@mcp.tool(name="read_board", description=READ_BOARD_TEXT)
def read_board(
    board_id: Annotated[str, Field(min_length=1, description=BOARD_ID_TEXT)],
    node: Annotated[str, Field(description=NODE_TEXT)] = "",
) -> str:
    return _result(BackendClient().post("boards/read", BoardsReadRequest(board_id=board_id, node=node)))


class CitedItem(BaseModel):
    """One chat or board that an answer uses."""

    kind: Literal["chat", "board"]
    id: str = Field(min_length=1)
    why: str = ""


def _as_item_list(value: Any) -> list[CitedItem] | None:
    """The items of a call. A parser can send the list as a JSON string, and a single item
    without its list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return None
    out = []
    for item in value:
        try:
            out.append(item if isinstance(item, CitedItem) else CitedItem(**item))
        except Exception:  # noqa: BLE001 - a malformed entry is a caller error
            return None
    return out


def cite_items(items: list[CitedItem], owner: str, session_id: str, client: Any,
               store: item_citations.ItemHandleStore) -> dict[str, Any]:
    """The handle of each item that the user reads, and an error for each other item. The list
    routes with `ids` check that the user reads an item."""
    readable: dict[tuple[str, str], dict] = {}
    for kind, route, key, id_key in (("chat", "chats/list", "chats", "session_id"),
                                     ("board", "boards/list", "boards", "board_id")):
        ids = sorted({item.id for item in items if item.kind == kind})
        if not ids:
            continue
        result = client.post(route, ItemsListRequest(ids=ids))
        if isinstance(result, AgentError):
            return json.loads(error_text(result))
        for row in result.get(key) or []:
            readable[(kind, str(row.get(id_key) or ""))] = row
    citations, errors = [], []
    for item in items:
        row = readable.get((item.kind, item.id))
        if row is None:
            errors.append({"kind": item.kind, "id": item.id,
                           "error": f"No {item.kind} with this id that the user can read. "
                                    "Copy the id from list_chats_and_boards."})
            continue
        try:
            handle = item_citations.allocate(store, owner, session_id, item.kind, item.id)
        except artifacts.ArtifactWriteFailed as exc:
            errors.append({"kind": item.kind, "id": item.id, "error": f"The handle was not stored: {exc}"})
            continue
        if not handle:
            errors.append({"kind": item.kind, "id": item.id,
                           "error": "This conversation used every handle of this kind."})
            continue
        citations.append({"handle": handle, "kind": item.kind, "id": item.id,
                          "title": row.get("title", ""), "link": row.get("link", ""),
                          "why": item.why[:300]})
    out: dict[str, Any] = {"success": bool(citations), "citations": citations}
    if errors:
        out["errors"] = errors
    if citations:
        out["note"] = "Write each handle beside the claim that relies on the chat or board."
    return out


@mcp.tool(name="cite_chats_and_boards", description=CITE_ITEMS_TEXT)
def cite_chats_and_boards(
    items: Annotated[list[CitedItem] | str, Field(description=ITEMS_TEXT)],
) -> str:
    parsed = _as_item_list(items)
    if not parsed:
        return canonical_json({"success": False, "error": "items must be a list of {kind, id, why}"})
    if len(parsed) > MAX_CITED_ITEMS:
        return canonical_json({"success": False, "error": f"give at most {MAX_CITED_ITEMS} items in one call"})
    session_id = server._session_id()
    owner = server._caller().username
    if not owner or session_id == "_no_session":
        return canonical_json({"success": False, "error": "Chat and board citations need a chat session."})
    return canonical_json(cite_items(parsed, owner, session_id, BackendClient(), item_citations.ItemHandleStore()))


# ---------------------------------------------------------------------------------
# Manuals
# ---------------------------------------------------------------------------------

SEARCH_MANUAL_TEXT = (
    "Search the Hoover manual for a question about the use of Hoover. The manual covers search, "
    "filters, documents, storage, uploads, AI chat, boards and administration. Each section "
    "result has its link."
)
MANUAL_QUERY_TEXT = "The words of the question, for example: filter by date."
READ_MANUAL_TEXT = (
    "Read one section of the Hoover manual. The result holds its subsections. Link each section "
    "that you use as a Markdown link with its link, for example [Search](/docs#4-search)."
)
SECTION_TEXT = "The section from search_manual, or a /docs link. Empty reads the contents."
MANUAL_TEXT = "user, or admin for the administration manual."


@mcp.tool(name="search_manual", description=SEARCH_MANUAL_TEXT)
def search_manual(query: Annotated[str, Field(min_length=1, description=MANUAL_QUERY_TEXT)]) -> str:
    return _result(BackendClient().post("manual/search", ManualSearchRequest(query=query)))


@mcp.tool(name="read_manual", description=READ_MANUAL_TEXT)
def read_manual(
    section: Annotated[str, Field(description=SECTION_TEXT)] = "",
    manual: Annotated[Literal["user", "admin"], Field(description=MANUAL_TEXT)] = "user",
) -> str:
    return _result(BackendClient().post("manual/read", ManualReadRequest(section=section, manual=manual)))
