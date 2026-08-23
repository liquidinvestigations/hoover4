"""FastMCP server: **the** web search tool.

One tool searches the open web, and there must never be a second: a small model faced with
several near-identical "search the web" descriptions picks badly and inconsistently. Every
source lives in :mod:`.sources` (`ddg_api`, `ddg_news`, `wikipedia` and the scrapers)
selectable through the `sources` argument.

What the model gets back is deliberately richer than before (the old payload was a title,
a URL and 400 characters, which is not enough to decide what to read): full snippets,
which sources corroborated each result, both rankings, and the timing table. What it does
*not* get is the pre-rerank ordering of every candidate. That is bookkeeping, and it would
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

from agent_common import artifacts, batching, rerank as rerank_client
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
        "Search the OPEN WEB rather than the user's own documents. One tool covers several "
        "independent engines (DuckDuckGo, Brave, Yahoo), DuckDuckGo and GDELT news, "
        "Wikipedia, Wikidata, Crossref DOI metadata and the web archives at once. It "
        "takes a LIST of queries: every query is run across every source, the results are "
        "merged into one pool and ranked together, so ask a question's distinct angles in "
        "one call. Results are merged with reciprocal rank fusion and then reordered by a "
        "cross-encoder, so the top results are the ones most relevant to the question "
        "rather than the ones most engines happened to agree on. Each result names the "
        "sources that returned it and the queries that found it: a page three sources or "
        "three queries agree on is better corroborated than one found by one. Snippets "
        "are short by design, so use the browser tools to open a promising result and read "
        "it in full.",
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
        default_factory=list, description="Sources that returned this URL, which is the corroboration"
    )
    kind: str = Field(default="web", description="web | news | reference")
    rrf_rank: int = 0
    rrf_score: float = 0.0
    rerank_rank: int | None = None
    rerank_score: float | None = None
    matched_queries: list[str] = Field(
        default_factory=list,
        description=(
            "Which of your queries returned this page. A page several queries agree on "
            "is better corroborated than one only a single query found."
        ),
    )
    published: str = ""


class WebSearchResponse(BaseModel):
    success: bool
    #: The queries joined into one string. Kept alongside `queries` because stored
    #: transcript rows and both renderers read it, and a batch of one must not be a
    #: different shape from a batch of three.
    query: str
    queries: list[str] = Field(
        default_factory=list, description="The queries that were run, after de-duplication"
    )
    note: str | None = Field(
        default=None, description="What was de-duplicated or not run, and what to do instead"
    )
    results: list[WebResult] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    degraded: list[str] = Field(
        default_factory=list,
        description="Sources that returned nothing and are likely broken, so these results "
        "come from fewer sources than intended",
    )
    degraded_reasons: dict[str, str] = Field(
        default_factory=dict,
        description="Why each degraded source came back empty (HTTP status, timeout, "
        "no results). This is a diagnostic rather than evidence, and nothing here changes the answer.",
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
    #: The reserved key the website reads artifacts off, and the reason there is no
    #: top-level `artifact_id`: at the top level the model reads it as a field of the
    #: result and passes it to a collection tool as if it were a document id. It is a
    #: lookup key for the browser, never an identifier the model has any use for.
    hoover4_artifacts: list[dict[str, Any]] = Field(
        default_factory=list,
        alias=artifacts.ARTIFACTS_KEY,
        serialization_alias=artifacts.ARTIFACTS_KEY,
        description="Reserved for the interface. Nothing here is for you.",
    )
    error: str | None = None

    model_config = {"populate_by_name": True}


#: Queries one call may fan out over. Every extra query is a full fan-out across every
#: source plus its share of one cross-encoder pass, so this bounds what a single tool call
#: costs the sources and the GPU. The surplus is named rather than silently trimmed.
MAX_QUERIES = int(os.getenv("METASEARCH_MAX_QUERIES", "5"))


@mcp.tool(
    name="web_search",
    description=(
        "Search the open web from several angles at once. Pass `queries` as a list, for "
        "example `[\"arthur andersen enron\", \"andersen collapse 2002\"]`. Every query is "
        "run across every source, merged into one pool and ranked together, so ask the "
        "distinct angles of your question in one call rather than one per turn. Each "
        "result names the queries that found it. Covers several independent engines, "
        "world news, Wikipedia, Wikidata, DOI metadata and the web archives; results are "
        "fused across sources and reordered by a cross-encoder. Use for anything outside "
        "the user's own document collections. Optional `sources` narrows where to look "
        "(e.g. ['gdelt'] for news, ['wikidata'] for entities, ['wayback'] for what a page "
        "used to say); omit it to search everything. `timelimit` accepts 'd', 'w', 'm' or "
        "'y' and only affects the news sources and ddg_api."
    ),
)
async def web_search(
    queries: list[str] | str | None = None,
    query: str | None = None,
    sources: list[str] | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    timelimit: str | None = None,
) -> WebSearchResponse:
    """Search every source for every query, and rank the merged pool once.

    `query` is still accepted and is folded into `queries` rather than handled on its own
    path: a model that learned the single-query shape keeps working, and a batch of one is
    then not a special case anywhere below this line.
    """
    asked = batching.as_list(queries) + batching.as_list(query)
    wanted, repeats = batching.dedupe(asked)
    over_cap = wanted[MAX_QUERIES:]
    wanted = wanted[:MAX_QUERIES]

    note = batching.corrective_note(
        batching.repeats_note(repeats, "query"),
        (
            f"{len(over_cap)} quer{'y' if len(over_cap) == 1 else 'ies'} beyond the "
            f"{MAX_QUERIES}-per-call limit {'was' if len(over_cap) == 1 else 'were'} not "
            f"run: {', '.join(over_cap)}. Send the most distinct angles first."
            if over_cap
            else ""
        ),
    )

    if not wanted:
        return WebSearchResponse(
            success=False, query="", queries=[], note=note or None,
            error="no query was given; pass one or more search queries in `queries`",
        )

    limit = max(1, min(int(max_results), MAX_ALLOWED_RESULTS))
    if timelimit and timelimit not in ("d", "w", "m", "y"):
        # Refused rather than silently ignored: a model that thinks it filtered to the
        # last day and did not will present stale results as fresh.
        return WebSearchResponse(
            success=False,
            query=pipeline.QUERY_JOIN.join(wanted),
            queries=wanted,
            error="timelimit must be one of 'd', 'w', 'm', 'y'",
        )

    try:
        outcome = await pipeline.run_search(
            wanted,
            # Coerced for the same reason the queries are: an XML-style tool-call parser
            # hands `sources` across as the literal `'["gdelt"]'`.
            requested_sources=batching.as_list(sources) or None,
            max_results=limit,
            timelimit=timelimit,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not raised at it
        log.exception("metasearch failed")
        return WebSearchResponse(
            success=False, query=pipeline.QUERY_JOIN.join(wanted), queries=wanted, error=str(exc)
        )

    # `to_thread`: this is an S3 PUT plus a ClickHouse insert, both synchronous. On the
    # event loop they block every *other* in-flight search's source fan-out for the
    # duration, and the fan-out is the part with a deadline.
    artifact_id = await asyncio.to_thread(
        artifacts.write_json_detail,
        session_id=_header(SESSION_HEADER),
        username=_header(USER_HEADER),
        tool_name="web_search",
        detail=pipeline.detail_document(outcome),
        title=outcome.query[:200],
    )

    return WebSearchResponse(
        success=True,
        query=outcome.query,
        queries=outcome.queries,
        note=note or None,
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
        **artifacts.artifacts_field({"artifact_id": artifact_id, "kind": "json",
                                     "tool_name": "web_search"}),
    )


@mcp.tool(
    name="list_search_sources",
    description=(
        "The sources web_search can use, with their kind (web, news, reference or "
        "archive). Call this only if you need to narrow a search to particular sources. "
        "A source this deployment has no key for is not listed at all."
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
