"""Merge web sources with reciprocal rank fusion and per-kind result limits.

Each query supplies one ranking per source. Fusion deduplicates their URLs.
Web search does not call a model reranker. Each kind reserves results in fused order.
Legacy rerank fields remain empty for stored artifact and renderer compatibility.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from agent_common import fusion
from metasearch_server import sources as sources_mod
from metasearch_server.engines import SearchResult, reciprocal_rank_fusion

log = logging.getLogger(__name__)

#: Result limits for each source kind.
MIN_PER_KIND = int(os.getenv("METASEARCH_MIN_PER_KIND", "3"))
MAX_PER_KIND = int(os.getenv("METASEARCH_MAX_PER_KIND", "15"))

#: Bound the fused candidate pool before applying source-kind limits.
FUSION_CANDIDATES = int(os.getenv("METASEARCH_FUSION_CANDIDATES", "60"))

#: Snippet cap in what reaches the model.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "400"))


@dataclass
class Ranked:
    """One result with its fused position and legacy artifact fields."""

    result: SearchResult
    rrf_rank: int
    rrf_score: float
    rerank_rank: int | None = None
    rerank_score: float | None = None
    #: Which of the call's queries returned this URL. A page three queries agree on is
    #: better corroborated than one a single query found, and saying so on the result is
    #: what lets the model use it.
    matched_queries: list[str] = field(default_factory=list)


@dataclass
class SearchOutcome:
    """Everything one search produced. The model gets a subset, the artifact gets all."""

    #: The queries joined for display, and kept because the stored transcript rows and
    #: both renderers read a single `query` field.
    query: str
    #: The queries as asked, after de-duplication.
    queries: list[str] = field(default_factory=list)
    ranked: list[Ranked] = field(default_factory=list)
    #: Keep the complete fused order for the search-detail artifact.
    fused: list[Ranked] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    unknown_sources: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    #: Why each degraded source came back empty, HTTP status, timeout, selector rot.
    degraded_reasons: dict[str, str] = field(default_factory=dict)
    source_latency_ms: dict[str, float] = field(default_factory=dict)
    source_counts: dict[str, int] = field(default_factory=dict)
    total_before_dedupe: int = 0
    total_after_dedupe: int = 0
    rerank_applied: bool = False
    rerank_ms: float = 0.0
    rerank_error: str = ""
    fetch_ms: float = 0.0
    total_ms: float = 0.0


def display_url(url: str, max_chars: int = 60) -> str:
    """Host plus a truncated path. What a result row shows instead of a 300-char URL."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return url[:max_chars]
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    shown = host + (parsed.path or "")
    if len(shown) <= max_chars:
        return shown
    return shown[: max_chars - 1] + "…"


def apply_per_kind_floor(
    ranked: list[Ranked],
    max_results: int,
    min_per_kind: int = MIN_PER_KIND,
    max_per_kind: int = MAX_PER_KIND,
) -> list[Ranked]:
    """Reserve each kind's results and retain their fused order."""
    return fusion.per_kind_floor(
        ranked,
        max_results,
        kind_of=lambda item: item.result.kind or "web",
        min_per_kind=min_per_kind,
        max_per_kind=max_per_kind,
    )


#: Join query text for display and stored transcripts.
QUERY_JOIN = " ; "


async def run_search(
    queries: list[str],
    requested_sources: list[str] | None = None,
    max_results: int = 15,
    timelimit: str | None = None,
) -> SearchOutcome:
    """Fetch each query, fuse the results, and apply source-kind limits.

    Source failures remain visible in the result. `queries` is already de-duplicated and
    capped by the caller. This function fans out over exactly what it is given.
    """
    started = time.monotonic()
    names, unknown = sources_mod.resolve_sources(requested_sources)
    joined = QUERY_JOIN.join(queries)

    # Step 1: one fan-out per query. Sequential over queries and parallel within one,
    # because `fetch_all` already saturates every source at once and running the queries
    # concurrently too would multiply the load a single call puts on each host by the
    # batch size, which is how a scraper starts answering 429.
    fetch_started = time.monotonic()
    rankings: dict[str, list[SearchResult]] = {}
    latency: dict[str, float] = {name: 0.0 for name in names}
    counts: dict[str, int] = {name: 0 for name in names}
    answered: set[str] = set()
    reasons: dict[str, str] = {}
    matched: dict[str, list[str]] = {}
    for index, one in enumerate(queries):
        per_source, per_latency, degraded, degraded_reasons = await sources_mod.fetch_all(
            one, names, timelimit=timelimit
        )
        for name, rows in per_source.items():
            # One ranked list per (source, query) pair. The key has to carry both or two
            # queries' rankings from one source overwrite each other and the batch fuses
            # only its last query.
            rankings[f"{name}\x1f{index}"] = rows
            latency[name] = round(latency.get(name, 0.0) + per_latency.get(name, 0.0), 1)
            counts[name] = counts.get(name, 0) + len(rows)
            if rows:
                answered.add(name)
            for row in rows:
                key = fusion.normalise_url(row.url)
                if one not in matched.setdefault(key, []):
                    matched[key].append(one)
        for name, reason in degraded_reasons.items():
            # The first explanation is kept: a source that failed on query one and
            # returned nothing on query two is best described by the failure.
            reasons.setdefault(name, reason)
    fetch_ms = (time.monotonic() - fetch_started) * 1000.0

    # A source is degraded when it answered *no* query in the batch. One empty query out
    # of five is a query with no results, not a broken source, and reporting it as one
    # would put every source on the degraded list of any batch with a narrow angle in it.
    degraded_names = [name for name in names if name not in answered]

    outcome = SearchOutcome(
        query=joined,
        queries=list(queries),
        sources_used=names,
        unknown_sources=unknown,
        degraded=degraded_names,
        degraded_reasons={n: reasons[n] for n in degraded_names if reasons.get(n)},
        source_latency_ms=latency,
        source_counts=counts,
        total_before_dedupe=sum(len(rows) for rows in rankings.values()),
        fetch_ms=round(fetch_ms, 1),
    )

    # Step 2: fuse every (source, query) ranking into ONE pool. This is also the dedupe,
    # one SearchResult per normalised URL, carrying every source that returned it.
    fused = reciprocal_rank_fusion(rankings, max_results=FUSION_CANDIDATES)
    for result in fused:
        # The fusion keys are `source\x1fquery-index`; the model is shown source names, and
        # a name repeated once per query would read as corroboration it does not have.
        result.engines = sorted({name.split("\x1f", 1)[0] for name in result.engines})
    outcome.total_after_dedupe = len(fused)
    outcome.fused = [
        Ranked(
            result=r,
            rrf_rank=i,
            rrf_score=round(r.score, 6),
            matched_queries=matched.get(fusion.normalise_url(r.url), []),
        )
        for i, r in enumerate(fused, start=1)
    ]
    if not fused:
        outcome.total_ms = round((time.monotonic() - started) * 1000.0, 1)
        return outcome

    # Apply source-kind limits to the fused order.
    outcome.ranked = apply_per_kind_floor(list(outcome.fused), max_results=max(1, max_results))
    outcome.total_ms = round((time.monotonic() - started) * 1000.0, 1)
    log.info(
        "web_search %r queries=%d sources=%d candidates=%d returned=%d rerank=%s in %.0fms",
        joined, len(queries), len(names), outcome.total_after_dedupe, len(outcome.ranked),
        "yes" if outcome.rerank_applied else "no", outcome.total_ms,
    )
    return outcome


def result_payload(item: Ranked) -> dict:
    """One result as the **model** sees it."""
    r = item.result
    return {
        "title": r.title,
        "url": r.url,
        "display_url": display_url(r.url),
        "snippet": (r.snippet or "")[:SNIPPET_CHARS],
        "sources": sorted(set(r.engines)),
        "kind": r.kind or "web",
        "rrf_rank": item.rrf_rank,
        "rrf_score": item.rrf_score,
        "rerank_rank": item.rerank_rank,
        "rerank_score": item.rerank_score,
        "matched_queries": item.matched_queries,
        "published": r.published or "",
    }


def detail_document(outcome: SearchOutcome) -> dict:
    """Store complete fused and selected results with timing and legacy field names."""
    def row(item: Ranked) -> dict:
        r = item.result
        return {
            "title": r.title,
            "url": r.url,
            "display_url": display_url(r.url),
            "snippet": r.snippet or "",
            "sources": sorted(set(r.engines)),
            "source_ranks": r.source_ranks,
            "kind": r.kind or "web",
            "rrf_rank": item.rrf_rank,
            "rrf_score": item.rrf_score,
            "rerank_rank": item.rerank_rank,
            "rerank_score": item.rerank_score,
            "matched_queries": item.matched_queries,
            "published": r.published or "",
        }

    return {
        "query": outcome.query,
        "queries": outcome.queries,
        "before_rerank": [row(i) for i in outcome.fused],
        "after_rerank": [row(i) for i in outcome.ranked],
        "sources_used": outcome.sources_used,
        "degraded": outcome.degraded,
        "degraded_reasons": outcome.degraded_reasons,
        "unknown_sources": outcome.unknown_sources,
        "source_latency_ms": outcome.source_latency_ms,
        "source_counts": outcome.source_counts,
        "total_before_dedupe": outcome.total_before_dedupe,
        "total_after_dedupe": outcome.total_after_dedupe,
        "rerank_applied": outcome.rerank_applied,
        "rerank_ms": outcome.rerank_ms,
        "rerank_error": outcome.rerank_error,
        "fetch_ms": outcome.fetch_ms,
        "total_ms": outcome.total_ms,
    }
