"""HTML-scraping web search engines and Reciprocal Rank Fusion.

Modelled on `MikeLuu99/metasearch-rust`: several engines scraped in parallel, results
deduplicated on a normalised URL, then merged with RRF so a result several engines agree
on outranks one only a single engine returned.

No API keys anywhere. The cost of that is fragility — **assume at least one of these
selectors will break within months**. Two things make that failure visible instead of
silent: an engine returning zero results is reported in the response's `degraded` list
rather than swallowed, and the engine set is env-configurable so a rotted scraper can be
turned off without a rebuild.

This module is now the `kind = "web"` half of a wider set. :mod:`.sources` wraps each
engine here as a *source* alongside the `ddgs`-library and Wikipedia sources that used to
be their own MCP servers, and :mod:`.pipeline` is what orders the merged set.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse, urlunparse

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

ENGINE_TIMEOUT = float(os.getenv("METASEARCH_ENGINE_TIMEOUT", "8"))

#: RRF constant. 60 is the value from the original Cormack et al. paper and what
#: metasearch-rust uses; it damps the difference between ranks 1 and 2 so agreement
#: across engines matters more than one engine's confidence.
RRF_K = int(os.getenv("METASEARCH_RRF_K", "60"))

_USER_AGENT = os.getenv(
    "METASEARCH_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
)

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
    #: :mod:`.sources`; the raw scrapers here are all `web`.
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


def _text(node) -> str:
    return " ".join((node.text() if node else "").split())


def _unwrap_redirect(url: str, param: str) -> str:
    """Pull the real target out of an engine's click-tracking redirect."""
    try:
        values = parse_qs(urlparse(url).query).get(param)
    except ValueError:
        return url
    return values[0] if values else url


def _parse_duckduckgo(html: str) -> list[SearchResult]:
    out = []
    for row in HTMLParser(html).css("div.result__body, div.web-result"):
        link = row.css_first("a.result__a")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if not href:
            continue
        # DDG's html endpoint wraps every hit in /l/?uddg=<encoded target>.
        if "/l/?" in href or href.startswith("//duckduckgo.com/l/"):
            href = _unwrap_redirect(href, "uddg")
        out.append(
            SearchResult(title=_text(link), url=href, snippet=_text(row.css_first("a.result__snippet")))
        )
    return out


def _parse_brave(html: str) -> list[SearchResult]:
    out = []
    for row in HTMLParser(html).css("div.snippet[data-type='web'], div#results div.snippet"):
        link = row.css_first("a")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        title = row.css_first("div.title") or row.css_first(".snippet-title")
        out.append(
            SearchResult(
                title=_text(title) or _text(link),
                url=href,
                snippet=_text(row.css_first("div.snippet-description") or row.css_first(".snippet-content")),
            )
        )
    return out


def _parse_startpage(html: str) -> list[SearchResult]:
    out = []
    for row in HTMLParser(html).css("div.w-gl__result, section.w-gl div.result"):
        link = row.css_first("a.w-gl__result-title, a.result-link")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        out.append(
            SearchResult(
                title=_text(link),
                url=href,
                snippet=_text(row.css_first("p.w-gl__description, .description")),
            )
        )
    return out


def _parse_yahoo(html: str) -> list[SearchResult]:
    out = []
    for row in HTMLParser(html).css("div.algo, div.dd.algo"):
        link = row.css_first("h3 a") or row.css_first("a")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        # Yahoo routes clicks through r.search.yahoo.com/.../RU=<encoded>/RK=...
        if "r.search.yahoo.com" in href and "/RU=" in href:
            from urllib.parse import unquote

            href = unquote(href.split("/RU=", 1)[1].split("/R", 1)[0])
        out.append(
            SearchResult(title=_text(link), url=href, snippet=_text(row.css_first("div.compText, p")))
        )
    return out


#: name -> (url template, parser). `{q}` is filled with the url-encoded query.
ENGINES = {
    "ddg": ("https://html.duckduckgo.com/html/?q={q}", _parse_duckduckgo),
    "brave": ("https://search.brave.com/search?q={q}", _parse_brave),
    "startpage": ("https://www.startpage.com/sp/search?query={q}", _parse_startpage),
    "yahoo": ("https://search.yahoo.com/search?p={q}", _parse_yahoo),
}


def configured_engines() -> list[str]:
    """The engines this deployment uses, from `METASEARCH_ENGINES`.

    Unknown names are dropped with a warning rather than raising: the point of the env
    var is to let someone disable a rotted scraper in a hurry, and a typo there must not
    take the whole server down.
    """
    raw = os.getenv("METASEARCH_ENGINES", "ddg,brave,startpage,yahoo")
    names = []
    for name in (n.strip().lower() for n in raw.split(",")):
        if not name:
            continue
        if name not in ENGINES:
            log.warning("unknown engine %r in METASEARCH_ENGINES, ignoring", name)
            continue
        names.append(name)
    return names or ["ddg"]


async def _fetch_engine(client: httpx.AsyncClient, name: str, query: str) -> list[SearchResult]:
    template, parser = ENGINES[name]
    from urllib.parse import quote_plus

    url = template.format(q=quote_plus(query))
    try:
        response = await client.get(url, timeout=ENGINE_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - one dead engine must degrade, not fail
        log.warning("engine %s failed: %s", name, exc)
        return []
    try:
        results = parser(response.text)
    except Exception as exc:  # noqa: BLE001 - a selector change is a parse error
        log.warning("engine %s parse failed (selector rot?): %s", name, exc)
        return []
    if not results:
        log.warning("engine %s returned 0 results — selector may have rotted", name)
    return results


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


async def search_all(query: str, max_results: int, engines: list[str] | None = None):
    """Query every configured engine in parallel and RRF-merge the results.

    Returns `(results, degraded)` where `degraded` names the engines that came back
    empty — a broken scraper has to be visible in the response, not just in the log.
    """
    names = [e for e in (engines or configured_engines()) if e in ENGINES] or configured_engines()

    headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        gathered = await asyncio.gather(
            *(_fetch_engine(client, name, query) for name in names)
        )

    per_engine = dict(zip(names, gathered))
    degraded = [name for name, results in per_engine.items() if not results]
    return reciprocal_rank_fusion(per_engine, max_results), degraded
