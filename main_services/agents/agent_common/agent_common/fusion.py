"""Reciprocal Rank Fusion and the per-kind floor — the shared ordering machinery.

This module is the single implementation of two things every search surface needs:

* **RRF fusion** of several ranked lists into one. `metasearch_server` fuses web
  sources with it and `collection_search_server` fuses its keyword and vector rankings
  with the same code — keep it here rather than copying it into either.
  A second copy would drift, and a drifted fusion is invisible — results just get
  quietly worse.
* **The per-kind floor.** RRF is a popularity measure: four web scrapers agreeing on a
  page beat one encyclopaedia entry every time, and a keyword match with exact terms
  beats a vector hit that is merely *about* the right thing. The floor reserves each
  kind's best results before the overall cap is applied, or one kind drowns the other.

`SearchResult` is the web-search payload shape; :func:`fuse_ranked_lists` is the generic
half for callers whose items are not URLs (collection search fuses `(dataset, document,
page)` keys, where `normalise_url` would be nonsense).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Hashable, Iterable, TypeVar
from urllib.parse import parse_qs, urlparse, urlunparse

#: RRF constant. 60 is the value from the original Cormack et al. paper; it damps the
#: difference between ranks 1 and 2 so agreement across sources matters more than one
#: source's confidence.
RRF_K = int(os.getenv("METASEARCH_RRF_K", "60"))

#: Tracking parameters stripped before two URLs are compared. Without this the same page
#: arrives from three engines as three different results and RRF never sees the
#: agreement it exists to reward.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src",
        "spm", "_ga", "igshid", "si",
    }
)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    #: Which engines returned this URL, and at what rank. Surfaced to the model so it can
    #: see corroboration rather than trusting one scraper.
    engines: list[str] = field(default_factory=list)
    score: float = 0.0
    #: `web` | `news` | `reference`, from the source that produced it. Set by
    #: metasearch's `sources` module; the raw scrapers are all `web`.
    kind: str = "web"
    #: Publication date when the source supplies one (the news sources do).
    published: str = ""
    #: Rank this URL took in each source's own list, 1-based. Search bookkeeping: it goes
    #: to the search-detail artifact, never to the model.
    source_ranks: dict[str, int] = field(default_factory=dict)


def normalise_url(url: str) -> str:
    """A comparison key for deduplication.

    Drops the scheme's variability (http/https), a leading `www.`, tracking parameters,
    the fragment and a trailing slash. The *original* URL is what gets returned to the
    caller — this is only the key.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    kept = {
        k: v
        for k, v in parse_qs(parsed.query, keep_blank_values=True).items()
        if k.lower() not in _TRACKING_PARAMS
    }
    query = "&".join(f"{k}={v[0]}" for k, v in sorted(kept.items()))

    path = (parsed.path or "/").rstrip("/") or "/"
    return urlunparse(("", host, path, "", query, ""))


def dedupe_within_source(results: list[SearchResult]) -> list[SearchResult]:
    """Collapse repeats inside **one** source's own list, keeping its first position.

    This runs *before* fusion, and skipping it is the subtle bug the plan calls out: a
    source that lists the same article at ranks 2, 5 and 9 would otherwise award that URL
    three separate RRF contributions and beat a page three independent sources agreed on.
    Cross-source merging is what :func:`reciprocal_rank_fusion` does; this is the other
    half.
    """
    seen: set[str] = set()
    out: list[SearchResult] = []
    for result in results:
        key = normalise_url(result.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(result)
    return out


def reciprocal_rank_fusion(
    per_engine: dict[str, list[SearchResult]], max_results: int
) -> list[SearchResult]:
    """Merge per-engine rankings: `score = sum over engines of 1 / (RRF_K + rank)`.

    Rank is 1-based. A URL two engines both put at rank 3 scores higher than one a single
    engine put at rank 1, which is the property that makes a metasearch worth running.

    Each input list is deduplicated first (see :func:`dedupe_within_source`), so one
    source can contribute at most one rank per URL.
    """
    merged: dict[str, SearchResult] = {}
    for engine, results in per_engine.items():
        for rank, result in enumerate(dedupe_within_source(results), start=1):
            key = normalise_url(result.url)
            existing = merged.get(key)
            if existing is None:
                existing = SearchResult(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    kind=result.kind,
                    published=result.published,
                )
                merged[key] = existing
            # Keep the longest snippet seen — engines truncate differently and the
            # fullest one is the most useful to the model.
            if len(result.snippet) > len(existing.snippet):
                existing.snippet = result.snippet
            if not existing.title:
                existing.title = result.title
            if not existing.published:
                existing.published = result.published
            # A page a reference source *and* a web scraper both returned is a reference:
            # the more specific kind wins, so the per-kind floor keeps encyclopaedic and
            # news results visible instead of drowning them in generic web hits.
            if existing.kind == "web" and result.kind != "web":
                existing.kind = result.kind
            existing.engines.append(engine)
            existing.source_ranks[engine] = rank
            existing.score += 1.0 / (RRF_K + rank)

    ordered = sorted(merged.values(), key=lambda r: r.score, reverse=True)
    return ordered[:max_results]


T = TypeVar("T")


@dataclass
class FusedItem:
    """One item of a generic fusion: the payload plus where it ranked.

    The collection-search half of the fusion story — same RRF rule as
    :func:`reciprocal_rank_fusion`, but keyed by an arbitrary identity rather than a
    normalised URL, because a chunk of a document is not a web page.
    """

    item: object
    key: Hashable
    score: float = 0.0
    #: Every source list the key appeared in, and its 1-based rank there.
    source_ranks: dict[str, int] = field(default_factory=dict)


def fuse_ranked_lists(
    per_source: dict[str, list[T]],
    key_of: Callable[[T], Hashable],
    max_results: int | None = None,
) -> list[FusedItem]:
    """RRF over arbitrary ranked lists. `score = sum over sources of 1 / (RRF_K + rank)`.

    Each source's list is deduplicated on `key_of` first (same rule as
    :func:`dedupe_within_source`): one source contributes at most one rank per key.
    When the same key appears in several sources the FIRST source's payload object is
    kept — order `per_source` so the richest payload wins (a keyword hit carries the
    page text; a vector hit only the chunk).
    """
    merged: dict[Hashable, FusedItem] = {}
    for source, items in per_source.items():
        seen: set[Hashable] = set()
        rank = 0
        for item in items:
            key = key_of(item)
            if key in seen:
                continue
            seen.add(key)
            rank += 1
            existing = merged.get(key)
            if existing is None:
                existing = FusedItem(item=item, key=key)
                merged[key] = existing
            existing.source_ranks[source] = rank
            existing.score += 1.0 / (RRF_K + rank)

    ordered = sorted(merged.values(), key=lambda f: f.score, reverse=True)
    return ordered[:max_results] if max_results is not None else ordered


def per_kind_floor(
    ranked: list[T],
    max_results: int,
    kind_of: Callable[[T], str],
    min_per_kind: int,
    max_per_kind: int,
    is_reservable: Callable[[T], bool] | None = None,
) -> list[T]:
    """Guarantee each kind a share of the answer, then fill the rest by rank.

    Two passes, and the first is the whole point:

    1. **Reserve.** Each kind keeps its own best `min_per_kind` results (or all of them,
       if it has fewer) whatever the overall cap says. Without this a query with an
       obvious encyclopaedia answer returns twenty blogs about it, because four web
       scrapers agreeing always outscores one reference source — and a keyword-heavy
       query would return no vector hits at all.
    2. **Fill.** Everything else in rank order, up to `max_per_kind` per kind and
       `max_results` overall — but never evicting a reserved slot.

    `is_reservable` bounds pass 1 to results that deserve the guarantee. A floor promises
    *representation*, and representation of nothing is padding: with no gate, a query whose
    reference source has one good answer and fourteen unrelated ones reserved slots for the
    unrelated ones too, and the model cannot tell a reserved slot from an earned one. A
    rejected item is not dropped — pass 2 can still pick it on merit.

    The returned list keeps the input's order, so a reranked ordering stays reranked.
    """
    if max_per_kind < min_per_kind:
        raise ValueError("max_per_kind must not be below min_per_kind")

    reserved: set[int] = set()
    per_kind: dict[str, int] = {}
    for index, item in enumerate(ranked):
        if is_reservable is not None and not is_reservable(item):
            continue
        kind = kind_of(item)
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
        kind = kind_of(item)
        if per_kind.get(kind, 0) >= max_per_kind:
            continue
        per_kind[kind] = per_kind.get(kind, 0) + 1
        chosen.add(index)

    return [item for index, item in enumerate(ranked) if index in chosen]
