"""FastMCP server: **the** web search tool.

One tool searches the open web. Before Phase 2 the full research agent carried three
overlapping ones — `web_search` here, `ddg_text_search`/`ddg_news_search` on
`hoover4-mcp-ddg`, and `wikipedia_search` on `hoover4-mcp-wikipedia` — and a small model
faced with three near-identical descriptions picks badly and inconsistently. Those two
servers are retired; their sources live in :mod:`.sources` as `ddg_api`, `ddg_news` and
`wikipedia`, selectable through the `sources` argument.

What the model gets back is deliberately richer than before (the old payload was a title,
a URL and 400 characters, which is not enough to decide what to read): full snippets,
which sources corroborated each result, both rankings, and the timing table. What it does
*not* get is the pre-rerank ordering of every candidate — that is bookkeeping, it would
roughly double the token cost, and it goes to the search-detail artifact instead. The tool
result carries only that artifact's UUID.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from agent_common import artifacts, rerank as rerank_client
from metasearch_server import pipeline
from metasearch_server.sources import ALL_KINDS, configured_sources, describe_sources

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

DEFAULT_MAX_RESULTS = int(os.getenv("MAX_RESULTS", "15"))
MAX_ALLOWED_RESULTS = int(os.getenv("METASEARCH_MAX_ALLOWED_RESULTS", "40"))

#: Same headers the collection server reads. The session id scopes the search-detail
#: artifact to one conversation; the username is the ACL the website enforces on read.
SESSION_HEADER = "x-hoover4-chat-session"
USER_HEADER = "x-hoover4-user"

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_metasearch"),
    instructions=os.getenv(
        "SERVER_INSTRUCTIONS",
        "Search the OPEN WEB — not the user's own documents. One tool covers several "
        "independent engines (DuckDuckGo, Brave, Yahoo), DuckDuckGo News and "
        "Wikipedia at once. Results are merged with reciprocal rank fusion and then "
        "reordered by a cross-encoder, so the top results are the ones most relevant to "
        "the exact question rather than the ones most engines happened to agree on. Each "
        "result names the sources that returned it: a page three sources found is better "
        "corroborated than one found by one. Snippets are short by design — use the "
        "browser tools to open a promising result and read it in full.",
    ),
)


def _header(name: str) -> str:
    try:
        headers = get_http_headers()
    except Exception:  # noqa: BLE001 - called outside a request in tests
        return ""
    for key, value in dict(headers).items():
        if key.lower() == name:
            return (value or "").strip()
    return ""


class WebResult(BaseModel):
    title: str
    url: str
    display_url: str = ""
    snippet: str = ""
    sources: list[str] = Field(
        default_factory=list, description="Sources that returned this URL — corroboration"
    )
    kind: str = Field(default="web", description="web | news | reference")
    rrf_rank: int = 0
    rrf_score: float = 0.0
    rerank_rank: int | None = None
    rerank_score: float | None = None
    published: str = ""


class WebSearchResponse(BaseModel):
    success: bool
    query: str
    results: list[WebResult] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(
        default_factory=list,
        description="Sources that returned nothing — likely broken, so these results "
        "come from fewer sources than intended",
    )
    degraded_reasons: dict[str, str] = Field(
        default_factory=dict,
        description="Why each degraded source came back empty (HTTP status, timeout, "
        "no results). Diagnostic, not evidence — nothing here changes the answer.",
    )
    unknown_sources: list[str] = Field(
        default_factory=list, description="Names in `sources` that do not exist and were ignored"
    )
    total_before_dedupe: int = 0
    total_after_dedupe: int = 0
    rerank_applied: bool = False
    rerank_ms: float = 0.0
    rerank_error: str = ""
    source_latency_ms: dict[str, float] = Field(default_factory=dict)
    source_counts: dict[str, int] = Field(default_factory=dict)
    fetch_ms: float = 0.0
    total_ms: float = 0.0
    artifact_id: str | None = Field(
        default=None,
        description="Handle for the full before/after ranking detail. Shown to the user; "
        "there is nothing for you to do with it.",
    )
    error: str | None = None


@mcp.tool(
    name="web_search",
    description=(
        "Search the open web. Covers several independent engines, news and Wikipedia in "
        "one call; results are fused across sources and reordered by a cross-encoder. "
        "Use for anything outside the user's own document collections. Optional "
        "`sources` narrows where to look (e.g. ['ddg_news'] for recent news, "
        "['wikipedia'] for background); omit it to search everything. `timelimit` "
        "accepts 'd', 'w', 'm' or 'y' and only affects the news and ddg_api sources."
    ),
)
async def web_search(
    query: str,
    sources: list[str] | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    timelimit: str | None = None,
) -> WebSearchResponse:
    if not query or not query.strip():
        return WebSearchResponse(success=False, query=query, error="query cannot be empty")

    limit = max(1, min(int(max_results), MAX_ALLOWED_RESULTS))
    if timelimit and timelimit not in ("d", "w", "m", "y"):
        # Refused rather than silently ignored: a model that thinks it filtered to the
        # last day and did not will present stale results as fresh.
        return WebSearchResponse(
            success=False, query=query, error="timelimit must be one of 'd', 'w', 'm', 'y'"
        )

    try:
        outcome = await pipeline.run_search(
            query.strip(), requested_sources=sources, max_results=limit, timelimit=timelimit
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not raised at it
        log.exception("metasearch failed")
        return WebSearchResponse(success=False, query=query, error=str(exc))

    # `to_thread`: this is a MinIO PUT plus a ClickHouse insert, both synchronous. On the
    # event loop they block every *other* in-flight search's source fan-out for the
    # duration — and the fan-out is the part with a deadline.
    artifact_id = await asyncio.to_thread(
        artifacts.write_json_detail,
        session_id=_header(SESSION_HEADER),
        username=_header(USER_HEADER),
        tool_name="web_search",
        detail=pipeline.detail_document(outcome),
        title=query.strip()[:200],
    )

    return WebSearchResponse(
        success=True,
        query=query,
        results=[WebResult(**pipeline.result_payload(item)) for item in outcome.ranked],
        sources_used=outcome.sources_used,
        degraded=outcome.degraded,
        degraded_reasons=outcome.degraded_reasons,
        unknown_sources=outcome.unknown_sources,
        total_before_dedupe=outcome.total_before_dedupe,
        total_after_dedupe=outcome.total_after_dedupe,
        rerank_applied=outcome.rerank_applied,
        rerank_ms=outcome.rerank_ms,
        rerank_error=outcome.rerank_error,
        source_latency_ms=outcome.source_latency_ms,
        source_counts=outcome.source_counts,
        fetch_ms=outcome.fetch_ms,
        total_ms=outcome.total_ms,
        artifact_id=artifact_id,
    )


@mcp.tool(
    name="list_search_sources",
    description=(
        "The sources web_search can use, with their kind (web, news or reference). Call "
        "this only if you need to narrow a search to particular sources."
    ),
)
def list_search_sources() -> dict[str, Any]:
    return {
        "sources": describe_sources(),
        "kinds": list(ALL_KINDS),
        "configured": configured_sources(),
        "note": "Set METASEARCH_SOURCES to change the default set without a rebuild.",
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse(
        {
            "status": "ok",
            "service": "hoover4-metasearch",
            "sources": configured_sources(),
            "rerank_endpoint": rerank_client.endpoint(),
            "rerank_available": rerank_client.available(),
            "rerank_circuits": rerank_client.breaker_state(),
            "artifacts_enabled": artifacts.enabled(),
        }
    )


def main() -> None:
    log.info(
        "Starting Hoover4 metasearch MCP server (sources: %s, rerank: %s)",
        configured_sources(),
        rerank_client.endpoint() or "disabled",
    )
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8086")),
    )


if __name__ == "__main__":
    main()
