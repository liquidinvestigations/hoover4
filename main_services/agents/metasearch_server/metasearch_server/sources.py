"""Search sources: one name, one kind, one fetch function.

This is the abstraction that let `hoover4-mcp-ddg` and `hoover4-mcp-wikipedia` be
retired. Before it, the full research agent carried three overlapping "search the web"
tools and had to guess which one to call; now there is exactly one, and choosing *where*
to look is a `sources` argument rather than a tool choice.

A source's `kind` is not decoration — :mod:`.pipeline` applies a per-kind floor so an
encyclopaedia entry or a news story is not buried by ten generic web results that RRF
happened to rank higher.

Registered sources:

===============  ===========  =========================================================
name             kind         what it is
===============  ===========  =========================================================
``ddg``          web          the HTML scraper in :mod:`.engines`
``brave``        web          "
``startpage``    web          "
``yahoo``        web          "
``ddg_api``      web          the ``ddgs`` library's ``text()``, from `ddg_search_server`
``ddg_news``     news         the ``ddgs`` library's ``news()``, same origin
``wikipedia``    reference    MediaWiki search + extracts, from `wikipedia_search_server`
===============  ===========  =========================================================

`ddg_api` is kept **alongside** the `ddg` HTML scraper rather than replacing it. They rot
independently — a selector change breaks one and a library bump breaks the other — and
the whole point of the `degraded` list is that rot is visible rather than silent.

**A source that fails or times out must never fail the tool.** Every fetch here returns a
list, empty on any failure, and names itself in `degraded`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from metasearch_server.engines import (
    ENGINES,
    SearchResult,
    _fetch_engine,
)

log = logging.getLogger(__name__)

KIND_WEB = "web"
KIND_NEWS = "news"
KIND_REFERENCE = "reference"

ALL_KINDS = (KIND_WEB, KIND_NEWS, KIND_REFERENCE)

#: Per-source deadline. Shorter than the overall one below, so one slow source costs the
#: search a few seconds rather than the whole budget.
SOURCE_TIMEOUT = float(os.getenv("METASEARCH_SOURCE_TIMEOUT", "8"))

#: Overall fan-out deadline. Anything still running when it expires is cancelled and
#: reported degraded.
OVERALL_TIMEOUT = float(os.getenv("METASEARCH_OVERALL_TIMEOUT", "20"))

#: How many results to ask each source for. Larger than the caller's `max_results`
#: because fusion and reranking both need candidates to work with — asking for 8 and
#: returning 8 means the reranker has nothing to reorder.
PER_SOURCE_RESULTS = int(os.getenv("METASEARCH_PER_SOURCE_RESULTS", "15"))

DDG_REGION = os.getenv("DDG_DEFAULT_REGION", "wt-wt")
DDG_SAFESEARCH = os.getenv("DDG_DEFAULT_SAFESEARCH", "off")
WIKIPEDIA_LANGUAGE = os.getenv("WIKIPEDIA_LANGUAGE", "en")


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    #: `(query, max_results, timelimit) -> results`. Must not raise.
    fetch: Callable[[str, int, str | None], Awaitable[list[SearchResult]]]
    description: str = ""


# --------------------------------------------------------------- HTML scrapers (web)

def _html_engine_source(name: str) -> Source:
    async def fetch(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
        # The HTML endpoints take no time filter, so `timelimit` is ignored here rather
        # than faked — a filter that silently does nothing is worse than one that is
        # documented as unsupported.
        headers = {
            "User-Agent": os.getenv(
                "METASEARCH_USER_AGENT",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36",
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            results = await _fetch_engine(client, name, query)
        for r in results:
            r.kind = KIND_WEB
        return results[:max_results]

    return Source(name=name, kind=KIND_WEB, fetch=fetch, description=f"{name} HTML results")


# ------------------------------------------------------------------- ddgs library

def _ddgs_call(method: str, query: str, max_results: int, timelimit: str | None) -> list[dict]:
    """Blocking `ddgs` call. Run through `asyncio.to_thread` — the library is sync, and
    calling it on the event loop would stall every other source in the fan-out."""
    from ddgs import DDGS

    with DDGS(timeout=int(SOURCE_TIMEOUT)) as ddgs:
        return list(
            getattr(ddgs, method)(
                query,
                region=DDG_REGION,
                safesearch=DDG_SAFESEARCH,
                timelimit=timelimit,
                max_results=max_results,
            )
        )


async def _fetch_ddg_api(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    try:
        rows = await asyncio.to_thread(_ddgs_call, "text", query, max_results, timelimit)
    except Exception as exc:  # noqa: BLE001 - one dead source degrades, never fails
        log.warning("source ddg_api failed: %s", exc)
        return []
    return [
        SearchResult(
            title=row.get("title", "") or "",
            url=row.get("href", "") or row.get("url", "") or "",
            snippet=row.get("body", "") or "",
            kind=KIND_WEB,
            published=str(row.get("date") or ""),
        )
        for row in rows
        if (row.get("href") or row.get("url"))
    ]


async def _fetch_ddg_news(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    try:
        rows = await asyncio.to_thread(_ddgs_call, "news", query, max_results, timelimit)
    except Exception as exc:  # noqa: BLE001
        log.warning("source ddg_news failed: %s", exc)
        return []
    out = []
    for row in rows:
        url = row.get("url") or row.get("href") or ""
        if not url:
            continue
        source_name = row.get("source") or ""
        snippet = row.get("body", "") or ""
        out.append(
            SearchResult(
                title=row.get("title", "") or "",
                url=url,
                # The outlet is the most useful thing a news result carries beyond the
                # headline, and it is not recoverable from the URL for syndicated wires.
                snippet=f"{source_name}: {snippet}" if source_name else snippet,
                kind=KIND_NEWS,
                published=str(row.get("date") or ""),
            )
        )
    return out


# --------------------------------------------------------------------- Wikipedia

#: MediaWiki's own API, called directly rather than through the `wikipedia` package the
#: retired server used. That package is synchronous, fetches each article's full HTML to
#: produce a summary, and pins an ancient `requests`/`BeautifulSoup` pair. One
#: `list=search` call with `srprop=snippet` gives titles, snippets and the data to build
#: the canonical URL in a single round trip.
WIKIPEDIA_API = "https://{lang}.wikipedia.org/w/api.php"


async def _fetch_wikipedia(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": str(max(1, min(max_results, 30))),
        "srprop": "snippet|timestamp",
        "format": "json",
        "formatversion": "2",
    }
    url = WIKIPEDIA_API.format(lang=WIKIPEDIA_LANGUAGE)
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "hoover4-metasearch/1.0 (research tool)"},
            follow_redirects=True,
        ) as client:
            response = await client.get(url, params=params, timeout=SOURCE_TIMEOUT)
            response.raise_for_status()
            rows = response.json().get("query", {}).get("search", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("source wikipedia failed: %s", exc)
        return []

    out = []
    for row in rows:
        title = row.get("title") or ""
        if not title:
            continue
        out.append(
            SearchResult(
                title=title,
                url=f"https://{WIKIPEDIA_LANGUAGE}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                # MediaWiki marks the matched terms with <span class="searchmatch">.
                # These snippets are rendered as text nodes by the card, but stripping
                # the markup here keeps the model's context free of HTML it would
                # otherwise try to interpret.
                snippet=_strip_tags(row.get("snippet") or ""),
                kind=KIND_REFERENCE,
                published=str(row.get("timestamp") or ""),
            )
        )
    return out


def _strip_tags(html: str) -> str:
    out = []
    depth = 0
    for char in html:
        if char == "<":
            depth += 1
        elif char == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(char)
    return " ".join("".join(out).replace("&quot;", '"').replace("&amp;", "&").split())


# ------------------------------------------------------------------- the registry

SOURCES: dict[str, Source] = {
    **{name: _html_engine_source(name) for name in ENGINES},
    "ddg_api": Source(
        name="ddg_api",
        kind=KIND_WEB,
        fetch=_fetch_ddg_api,
        description="DuckDuckGo through the ddgs library",
    ),
    "ddg_news": Source(
        name="ddg_news",
        kind=KIND_NEWS,
        fetch=_fetch_ddg_news,
        description="DuckDuckGo News through the ddgs library",
    ),
    "wikipedia": Source(
        name="wikipedia",
        kind=KIND_REFERENCE,
        fetch=_fetch_wikipedia,
        description="Wikipedia article search",
    ),
}

#: Default set. Everything registered — a metasearch that leaves a source out by default
#: is a metasearch nobody benefits from.
DEFAULT_SOURCES = "ddg,brave,startpage,yahoo,ddg_api,ddg_news,wikipedia"


def configured_sources() -> list[str]:
    """The sources this deployment uses, from `METASEARCH_SOURCES`.

    Unknown names are dropped with a warning rather than raising, exactly as
    `configured_engines()` has always done: the point of the env var is to disable a
    rotted source in a hurry, and a typo there must not take the server down.

    `METASEARCH_ENGINES` is still honoured for the four HTML scrapers so an existing
    deployment's setting keeps meaning what it meant.
    """
    raw = os.getenv("METASEARCH_SOURCES")
    if raw is None:
        legacy = os.getenv("METASEARCH_ENGINES")
        if legacy:
            scrapers = [n.strip().lower() for n in legacy.split(",") if n.strip()]
            extra = [n for n in ("ddg_api", "ddg_news", "wikipedia")]
            raw = ",".join(scrapers + extra)
        else:
            raw = DEFAULT_SOURCES

    names = []
    for name in (n.strip().lower() for n in raw.split(",")):
        if not name:
            continue
        if name not in SOURCES:
            log.warning("unknown source %r in METASEARCH_SOURCES, ignoring", name)
            continue
        if name not in names:
            names.append(name)
    return names or ["ddg"]


def resolve_sources(requested: list[str] | None) -> tuple[list[str], list[str]]:
    """`(names to use, names dropped as unknown)`.

    A caller — that is, the model — asking for a source that does not exist gets the
    configured set instead of an error. It is a hint, not a contract, and a typo in a
    tool argument must not cost a search.
    """
    configured = configured_sources()
    if not requested:
        return configured, []
    wanted, unknown = [], []
    for name in (str(n).strip().lower() for n in requested):
        if not name:
            continue
        if name not in SOURCES:
            unknown.append(name)
        elif name not in wanted:
            wanted.append(name)
    return (wanted or configured), unknown


async def fetch_all(
    query: str,
    names: list[str],
    per_source_results: int = PER_SOURCE_RESULTS,
    timelimit: str | None = None,
) -> tuple[dict[str, list[SearchResult]], dict[str, float], list[str]]:
    """Query every named source in parallel.

    Returns `(results per source, latency_ms per source, degraded names)`. A source that
    raised, timed out, or came back empty is degraded — from the caller's point of view
    those are the same failure, and the log distinguishes them.
    """
    import time

    async def run(name: str) -> tuple[str, list[SearchResult], float]:
        source = SOURCES[name]
        started = time.monotonic()
        try:
            results = await asyncio.wait_for(
                source.fetch(query, per_source_results, timelimit), timeout=SOURCE_TIMEOUT
            )
        except asyncio.TimeoutError:
            log.warning("source %s exceeded its %.0fs deadline", name, SOURCE_TIMEOUT)
            results = []
        except Exception as exc:  # noqa: BLE001 - degradation, never a tool failure
            log.warning("source %s raised: %s", name, exc)
            results = []
        elapsed = (time.monotonic() - started) * 1000.0
        for r in results:
            r.kind = r.kind or source.kind
        return name, results, elapsed

    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(*(run(n) for n in names)), timeout=OVERALL_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("metasearch fan-out exceeded %.0fs overall", OVERALL_TIMEOUT)
        gathered = []

    per_source = {name: [] for name in names}
    latency = {name: 0.0 for name in names}
    for name, results, elapsed in gathered:
        per_source[name] = results
        latency[name] = round(elapsed, 1)

    degraded = [name for name in names if not per_source[name]]
    return per_source, latency, degraded


def describe_sources() -> list[dict]:
    """What `list_search_sources` reports."""
    configured = set(configured_sources())
    return [
        {
            "name": s.name,
            "kind": s.kind,
            "description": s.description,
            "configured": s.name in configured,
        }
        for s in sorted(SOURCES.values(), key=lambda s: (s.kind, s.name))
    ]
