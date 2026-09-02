"""The ordering pipeline: fan out, fuse, rerank, floor.

**The order of these four steps is not interchangeable.**

    fan out  ->  RRF fuse (which dedupes across sources)  ->  rerank  ->  per-kind floor

**A batch of queries fans out once per query and then joins that single pipeline.** Each
(source, query) pair is one ranked list, all of them are fused together into one pool, and
that pool is reranked **once**. Reranking each query's results and then merging the
per-query orderings reads identically and is wrong: it ranks each query's results against
each other rather than against the question, so the best answer to the sharpest query
arrives interleaved with the best answer to the vaguest one, at the same rank.

Reranking *after* the floor reads identically and is wrong: the floor would pick each
kind's arbitrary RRF-ordered results and the cross-encoder would then reorder that
already-truncated set, so a kind's genuinely best result could have been cut before it
was ever scored. Rerank the whole candidate pool, then take the best per kind.

The per-kind floor exists because RRF is a popularity measure. Four web scrapers agreeing
on a page beats one encyclopaedia entry every time, so without a floor a query with an
well-known Wikipedia answer returns twenty blogs about it. Minimum
:data:`MIN_PER_KIND` and maximum :data:`MAX_PER_KIND` results per kind.

**A floor is a guarantee of representation, not of relevance.** A floor of ten reference
results on a query with one encyclopaedia answer padded the reply with whatever Wikipedia
ranked next ("Yanam district" and "Aasta Hansteen spar" for a query about the Eiffel
Tower), and the model has no way to tell a reserved slot from an earned one. So the
reservation pass only fires for results the cross-encoder scored at or above
:data:`RESERVE_MIN_SCORE`; below that a kind goes unrepresented, which is the correct
answer when it has nothing to say. Results with no rerank score at all (the GPU is down)
are always reservable, no score is not a low score.

A rerank failure is **reported, not hidden**: `rerank_applied` goes false, the RRF order
stands, and the reason lands in `rerank_error`. The tool still answers, a GPU outage
must degrade search quality, not remove search.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field

from agent_common import fusion, rerank as rerank_client
from metasearch_server import sources as sources_mod
from metasearch_server.engines import SearchResult, reciprocal_rank_fusion

log = logging.getLogger(__name__)

#: Per-kind floor and ceiling, applied after reranking. See the module docstring.
#:
#: The floor is **3**, not 10. The result policy is "go down to 15 results,
#: always use the re-ranker", and a floor of 10 across three kinds reserves 30 slots, which
#: silently overrides any smaller cap the caller asked for. Three is enough for a kind to
#: be visibly represented and small enough that the cap means what it says.
MIN_PER_KIND = int(os.getenv("METASEARCH_MIN_PER_KIND", "3"))
MAX_PER_KIND = int(os.getenv("METASEARCH_MAX_PER_KIND", "15"))

#: Lowest rerank score that still earns a reserved floor slot.
#:
#: The cross-encoder returns a raw logit, so 0 is its own decision boundary: at or above,
#: the model judged the document more relevant to the query than not. Anything below is a
#: result the floor would be *inventing* representation for. Overridable because the
#: number is only meaningful for the reranker model in use; a different one needs a
#: different threshold, and a wrong one here quietly empties a kind.
RESERVE_MIN_SCORE = float(os.getenv("METASEARCH_RESERVE_MIN_SCORE", "0"))

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
    #: The fused order before reranking, for the search-detail artifact's left column.
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
    reserve_min_score: float = RESERVE_MIN_SCORE,
) -> list[Ranked]:
    """Guarantee each kind a share of the answer, then fill the rest by score.

    The implementation is `agent_common.fusion.per_kind_floor`. Collection search
    applies the same rule to its keyword/vector kinds, and a second copy would drift.
    Two passes: each kind first reserves its own best `min_per_kind` results whatever
    the overall cap says (without this, four web scrapers agreeing always outscores one
    encyclopaedia entry), then everything else fills in rank order up to `max_per_kind`
    per kind and `max_results` overall, never evicting a reserved slot.

    A result the cross-encoder scored below `reserve_min_score` cannot take a reserved
    slot. See the module docstring. It can still be *filled* in on merit if the budget
    reaches it.

    The returned list keeps the input's order, so the reranked ordering the model sees is
    still the reranked ordering.
    """
    return fusion.per_kind_floor(
        ranked,
        max_results,
        kind_of=lambda item: item.result.kind or "web",
        min_per_kind=min_per_kind,
        max_per_kind=max_per_kind,
        # No rerank score means the reranker did not run; the floor is then the only
        # protection a minority kind has and must not be gated on a number we do not have.
        is_reservable=lambda item: item.rerank_score is None
        or item.rerank_score >= reserve_min_score,
    )


#: How the queries of one batch are joined into the single string the cross-encoder is
#: given. There is one rerank over the merged pool, so there has to be one query text to
#: rank it against, and the union of what was asked is the closest available stand-in for
#: the question behind it.
QUERY_JOIN = " ; "


async def run_search(
    queries: list[str],
    requested_sources: list[str] | None = None,
    max_results: int = 15,
    timelimit: str | None = None,
) -> SearchOutcome:
    """Fan out per query, fuse into one pool, rerank once, floor.

    Never raises for a source or rerank failure. `queries` is already de-duplicated and
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
    fused = reciprocal_rank_fusion(rankings, max_results=RERANK_CANDIDATES)
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

    # Step 3: rerank the whole candidate pool, before the floor, never after, and once
    # for the batch rather than once per query. See the module docstring for why both
    # reversals read identically and are wrong.
    ordered = list(outcome.fused)
    try:
        scores, rerank_ms = rerank_client.rerank(
            joined, [_rerank_document(item.result) for item in outcome.fused]
        )
        outcome.rerank_ms = round(rerank_ms, 1)
        if scores:
            ordered = []
            seen: set[int] = set()
            for position, score in enumerate(scores, start=1):
                if 0 <= score.index < len(outcome.fused) and score.index not in seen:
                    seen.add(score.index)
                    item = outcome.fused[score.index]
                    item.rerank_rank = position
                    item.rerank_score = round(score.score, 6)
                    ordered.append(item)
            # A response that scored only some of the candidates (a `top_k` the server
            # applied, a truncated body) must not *delete* the rest: they were real
            # results with a real RRF position, and dropping them turns a partial rerank
            # into a partial search. They keep their fused order, behind everything the
            # cross-encoder did score, with no rerank rank, which is exactly true.
            ordered += [item for i, item in enumerate(outcome.fused) if i not in seen]
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
    """The search-detail artifact: both orderings in full, plus the timing table.

    This is what `TOOL_PAYLOAD_CHARS` cannot carry. The pre-rerank ordering is search
    bookkeeping rather than evidence. Sending it to the model would roughly double the
    tool's token cost for nothing, so it lives here and the card fetches it lazily.
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
