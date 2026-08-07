"""HTML-scraping web search engines.

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

The fusion machinery itself (`SearchResult`, `normalise_url`, `dedupe_within_source`,
`reciprocal_rank_fusion`, `RRF_K`) lives in `agent_common.fusion` since Phase 4 —
collection search fuses with the same code, and a second copy would drift. The names are
re-exported here so existing imports keep working.
"""

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.parser import HTMLParser

from agent_common.fusion import (
    RRF_K,
    SearchResult,
    dedupe_within_source,
    normalise_url,
    reciprocal_rank_fusion,
)

__all__ = [
    "ENGINES",
    "RRF_K",
    "SearchResult",
    "configured_engines",
    "dedupe_within_source",
    "normalise_url",
    "reciprocal_rank_fusion",
    "search_all",
]

log = logging.getLogger(__name__)

ENGINE_TIMEOUT = float(os.getenv("METASEARCH_ENGINE_TIMEOUT", "8"))

_USER_AGENT = os.getenv(
    "METASEARCH_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36",
)


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
