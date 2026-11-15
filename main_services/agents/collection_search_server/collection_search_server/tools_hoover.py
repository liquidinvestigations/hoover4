"""The tools of the `hoover` pack (`agent_common.tool_packs`), backed by the website agent API.

These tools read Hoover items that need no document source, so a run without a collection
binds them too. `parse_link` gives the item and the reading tool call of each Hoover link,
with the parser and the read rule of the chat input (`website/backend/src/api/links.rs`).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import AgentError, BackendClient, LinksParseRequest
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
