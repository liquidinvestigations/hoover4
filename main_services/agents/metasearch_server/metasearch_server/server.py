"""FastMCP server: web search across several engines, merged with RRF.

Supersedes `hoover4-mcp-ddg` in the full research agent's tool list — one engine's view
of the web is one engine's opinion, and the `engines` list on each result lets the model
see how many independent scrapers agreed. Both servers are cheap, so the DDG one is kept
running; see `main_services/agents/README.md` for which agent uses which.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from metasearch_server.engines import ENGINES, configured_engines, search_all

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = int(os.getenv("MAX_RESULTS", "8"))
MAX_ALLOWED_RESULTS = int(os.getenv("METASEARCH_MAX_ALLOWED_RESULTS", "25"))

#: Snippets are what land in the agent's context, so they are capped for the same reason
#: the collection server caps its own.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "400"))

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_metasearch"),
    instructions=os.getenv(
        "SERVER_INSTRUCTIONS",
        "Search the public web across several independent engines at once "
        "(DuckDuckGo, Brave, Startpage, Yahoo). Results are merged with reciprocal rank "
        "fusion, so a page several engines agree on ranks highest; each result lists "
        "which engines returned it, and a page found by three engines is better "
        "corroborated than one found by one. Use `browse_page` from the browser tool to "
        "read a promising result in full — the snippets here are short by design. "
        "This searches the OPEN WEB, not the user's own documents.",
    ),
)


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str = ""
    engines: list[str] = Field(
        default_factory=list, description="Engines that returned this URL — corroboration"
    )
    score: float = Field(default=0.0, description="Reciprocal-rank-fusion score")


class WebSearchResponse(BaseModel):
    success: bool
    query: str
    results: list[WebResult] = Field(default_factory=list)
    engines_used: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(
        default_factory=list,
        description="Engines that returned nothing — likely a broken scraper, "
        "so these results are from fewer sources than intended",
    )
    error: str | None = None


@mcp.tool(
    name="web_search",
    description=(
        "Search the public web across several engines at once and return results merged "
        "by reciprocal rank fusion. Each result says which engines returned it. Use for "
        "anything outside the user's own document collections."
    ),
)
async def web_search(
    query: str,
    max_results: int = DEFAULT_MAX_RESULTS,
    engines: list[str] | None = None,
) -> WebSearchResponse:
    if not query or not query.strip():
        return WebSearchResponse(success=False, query=query, error="query cannot be empty")

    limit = max(1, min(int(max_results), MAX_ALLOWED_RESULTS))
    try:
        results, degraded = await search_all(query.strip(), limit, engines)
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not raised at it
        log.exception("metasearch failed")
        return WebSearchResponse(success=False, query=query, error=str(exc))

    used = [e for e in (engines or configured_engines()) if e in ENGINES] or configured_engines()
    return WebSearchResponse(
        success=True,
        query=query,
        results=[
            WebResult(
                title=r.title,
                url=r.url,
                snippet=r.snippet[:SNIPPET_CHARS],
                engines=sorted(set(r.engines)),
                score=round(r.score, 6),
            )
            for r in results
        ],
        engines_used=used,
        degraded=degraded,
    )


@mcp.tool(
    name="list_search_engines",
    description="The web search engines this server is configured to use.",
)
def list_search_engines() -> dict[str, Any]:
    return {
        "configured": configured_engines(),
        "available": sorted(ENGINES),
        "note": "Set METASEARCH_ENGINES to change the set without a rebuild.",
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "hoover4-metasearch"})


def main() -> None:
    log.info("Starting Hoover4 metasearch MCP server (engines: %s)", configured_engines())
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8086")),
    )


if __name__ == "__main__":
    main()
