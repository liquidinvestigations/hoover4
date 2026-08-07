"""The ordering pipeline: fan out, fuse, rerank, floor.

**The order of these four steps is not interchangeable.**

    fan out  ->  RRF fuse (which dedupes across sources)  ->  rerank  ->  per-kind floor

Reranking *after* the floor reads identically and is wrong: the floor would pick each
kind's arbitrary RRF-ordered results and the cross-encoder would then reorder that
already-truncated set, so a kind's genuinely best result could have been cut before it
was ever scored. Rerank the whole candidate pool, then take the best per kind.

The per-kind floor exists because RRF is a popularity measure. Four web scrapers agreeing
on a page beats one encyclopaedia entry every time, so without a floor a query with an
obvious Wikipedia answer returns twenty blogs about it. Minimum
:data:`MIN_PER_KIND` and maximum :data:`MAX_PER_KIND` results per kind.

A rerank failure is **reported, not hidden**: `rerank_applied` goes false, the RRF order
stands, and the reason lands in `rerank_error`. The tool still answers — a GPU outage
must degrade search quality, not remove search.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from agent_common import rerank as rerank_client
from metasearch_server import sources as sources_mod
from metasearch_server.engines import SearchResult, reciprocal_rank_fusion

log = logging.getLogger(__name__)

#: Per-kind floor and ceiling, applied after reranking. See the module docstring.
MIN_PER_KIND = int(os.getenv("METASEARCH_MIN_PER_KIND", "10"))
MAX_PER_KIND = int(os.getenv("METASEARCH_MAX_PER_KIND", "20"))

#: How many fused candidates are sent to the cross-encoder. Reranking is O(n) forward
#: passes, so this bounds the GPU cost of one search.
RERANK_CANDIDATES = int(os.getenv("METASEARCH_RERANK_CANDIDATES", "60"))

#: Snippet cap in what reaches the model.
SNIPPET_CHARS = int(os.getenv("SEARCH_SNIPPET_CHARS", "400"))


@dataclass
class Ranked:
    """One result with both orderings attached."""

    result: SearchResult
    rrf_rank: int
    rrf_score: float
    rerank_rank: int | None = None
    rerank_score: float | None = None


@dataclass
class SearchOutcome:
    """Everything one search produced — the model gets a subset, the artifact gets all."""

    query: str
    ranked: list[Ranked] = field(default_factory=list)
    #: The fused order before reranking, for the search-detail artifact's left column.
    fused: list[Ranked] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    unknown_sources: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
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
    """Host plus a truncated path — what a result row shows instead of a 300-char URL."""
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


def _rerank_document(result: SearchResult) -> str:
    """What the cross-encoder scores. Title first: it is the strongest signal and the
    model truncates, so burying it behind a snippet would cost accuracy."""
    parts = [result.title or "", result.snippet or "", display_url(result.url, 120)]
    return "\n".join(p for p in parts if p)


def apply_per_kind_floor(
    ranked: list[Ranked],
    max_results: int,
    min_per_kind: int = MIN_PER_KIND,
    max_per_kind: int = MAX_PER_KIND,
) -> list[Ranked]:
    """Guarantee each kind a share of the answer, then fill the rest by score.

    Two passes, and the first is the whole point:

    1. **Reserve.** Each kind keeps its own best `min_per_kind` results (or all of them,
       if it has fewer) whatever the overall cap says. Without this a query with an
       obvious encyclopaedia answer returns twenty blogs about it, because four web
       scrapers agreeing always outscores one reference source.
    2. **Fill.** Everything else in score order, up to `max_per_kind` per kind and
       `max_results` overall — but never evicting a reserved slot.

    The returned list keeps the input's order, so the reranked ordering the model sees is
    still the reranked ordering.
    """
    if max_per_kind < min_per_kind:
        raise ValueError("MAX_PER_KIND must not be below MIN_PER_KIND")

    reserved: set[int] = set()
    per_kind: dict[str, int] = {}
    for index, item in enumerate(ranked):
        kind = item.result.kind or "web"
        if per_kind.get(kind, 0) < min_per_kind:
            per_kind[kind] = per_kind.get(kind, 0) + 1
            reserved.add(index)

    chosen = set(reserved)
    budget = max(max_results, len(reserved))
    for index, item in enumerate(ranked):
        if len(chosen) >= budget:
            break
        if index in chosen:
            continue
        kind = item.result.kind or "web"
        if per_kind.get(kind, 0) >= max_per_kind:
            continue
        per_kind[kind] = per_kind.get(kind, 0) + 1
        chosen.add(index)

    return [item for index, item in enumerate(ranked) if index in chosen]


async def run_search(
    query: str,
    requested_sources: list[str] | None = None,
    max_results: int = 15,
    timelimit: str | None = None,
) -> SearchOutcome:
    """Fan out, fuse, rerank, floor. Never raises for a source or rerank failure."""
    started = time.monotonic()
    names, unknown = sources_mod.resolve_sources(requested_sources)

    fetch_started = time.monotonic()
    per_source, latency, degraded = await sources_mod.fetch_all(
        query, names, timelimit=timelimit
    )
    fetch_ms = (time.monotonic() - fetch_started) * 1000.0

    outcome = SearchOutcome(
        query=query,
        sources_used=names,
        unknown_sources=unknown,
        degraded=degraded,
        source_latency_ms=latency,
        source_counts={name: len(rows) for name, rows in per_source.items()},
        total_before_dedupe=sum(len(rows) for rows in per_source.values()),
        fetch_ms=round(fetch_ms, 1),
    )

    # Step 2: fuse. This is also the cross-source dedupe — one SearchResult per
    # normalised URL, carrying every source that returned it.
    fused = reciprocal_rank_fusion(per_source, max_results=RERANK_CANDIDATES)
    outcome.total_after_dedupe = len(fused)
    outcome.fused = [
        Ranked(result=r, rrf_rank=i, rrf_score=round(r.score, 6))
        for i, r in enumerate(fused, start=1)
    ]
    if not fused:
        outcome.total_ms = round((time.monotonic() - started) * 1000.0, 1)
        return outcome

    # Step 3: rerank the whole candidate pool — before the floor, never after. See the
    # module docstring for why the reverse reads identically and is wrong.
    ordered = list(outcome.fused)
    try:
        scores, rerank_ms = rerank_client.rerank(
            query, [_rerank_document(item.result) for item in outcome.fused]
        )
        outcome.rerank_ms = round(rerank_ms, 1)
        if scores:
            ordered = []
            for position, score in enumerate(scores, start=1):
                if 0 <= score.index < len(outcome.fused):
                    item = outcome.fused[score.index]
                    item.rerank_rank = position
                    item.rerank_score = round(score.score, 6)
                    ordered.append(item)
            outcome.rerank_applied = True
    except rerank_client.RerankUnavailable as exc:
        # Visible, never silent: the card shows an unreranked search as unreranked.
        log.warning("rerank unavailable, falling back to RRF order: %s", exc)
        outcome.rerank_error = str(exc)
    except Exception as exc:  # noqa: BLE001 - a search must still answer
        log.exception("rerank failed unexpectedly")
        outcome.rerank_error = str(exc)

    # Step 4: the per-kind floor, which also applies the caller's cap.
    outcome.ranked = apply_per_kind_floor(ordered, max_results=max(1, max_results))
    outcome.total_ms = round((time.monotonic() - started) * 1000.0, 1)
    log.info(
        "web_search %r sources=%d candidates=%d returned=%d rerank=%s in %.0fms",
        query, len(names), outcome.total_after_dedupe, len(outcome.ranked),
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
        "published": r.published or "",
    }


def detail_document(outcome: SearchOutcome) -> dict:
    """The search-detail artifact: both orderings in full, plus the timing table.

    This is what `TOOL_PAYLOAD_CHARS` cannot carry. The pre-rerank ordering is search
    bookkeeping rather than evidence — sending it to the model would roughly double the
    tool's token cost for nothing — so it lives here and the card fetches it lazily.
    """
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
            "published": r.published or "",
        }

    return {
        "query": outcome.query,
        "before_rerank": [row(i) for i in outcome.fused],
        "after_rerank": [row(i) for i in outcome.ranked],
        "sources_used": outcome.sources_used,
        "degraded": outcome.degraded,
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
