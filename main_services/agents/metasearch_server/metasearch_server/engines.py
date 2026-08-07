"""HTML-scraping web search engines.

Modelled on `MikeLuu99/metasearch-rust`: several engines scraped in parallel, results
deduplicated on a normalised URL, then merged with RRF so a result several engines agree
on outranks one only a single engine returned.

No API keys anywhere. The cost of that is fragility — **assume at least one of these
selectors will break within months**. Three things make that failure visible instead of
silent: an engine returning zero results is reported in the response's `degraded` list
rather than swallowed, that report carries the *reason* (see :func:`_fetch_engine`), and
the engine set is env-configurable so a rotted scraper can be turned off without a
rebuild.

Reporting rot is not the same as tolerating it. An engine that returns zero for every
query is not degraded, it is gone, and leaving it registered inflates the source count
the tool advertises. Startpage was removed on exactly that evidence — see :data:`ENGINES`.

This module is now the `kind = "web"` half of a wider set. :mod:`.sources` wraps each
engine here as a *source* alongside the `ddgs`-library and Wikipedia sources that used to
be their own MCP servers, and :mod:`.pipeline` is what orders the merged set.

The fusion machinery itself (`SearchResult`, `normalise_url`, `dedupe_within_source`,
`reciprocal_rank_fusion`, `RRF_K`) lives in `agent_common.fusion` since Phase 4 —
collection search fuses with the same code, and a second copy would drift. The names are
re-exported here so existing imports keep working.
"""

from __future__ import annotations

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
    "unwrap_tracking_url",
]

log = logging.getLogger(__name__)

ENGINE_TIMEOUT = float(os.getenv("METASEARCH_ENGINE_TIMEOUT", "8"))


def _text(node) -> str:
    return " ".join((node.text() if node else "").split())


def _first_text(row, *selectors: str) -> str:
    """Text of the first selector that matches and is non-empty."""
    for selector in selectors:
        text = _text(row.css_first(selector))
        if text:
            return text
    return ""


def _title_of(row, link, *selectors: str) -> str:
    """The result's own title node, never the whole clickable region.

    Yahoo nests the site name and a URL breadcrumb inside the same `<a>` as the title, so
    taking the link's text yields `eiffeltowertravel.comhttps://eiffeltowertravel.com ›
    height-and-factsEiffel Tower Height: …`. That mash is what the user reads, what the
    model cites — and, worst, what the **cross-encoder scores**, so a page with a
    keyword-stuffed breadcrumb outranks a clean title. Take the title element when the row
    has one; the link is only the fallback for engines whose anchor *is* the title.
    """
    return _first_text(row, *selectors) or _text(link)


def _unwrap_redirect(url: str, param: str) -> str:
    """Pull the real target out of an engine's click-tracking redirect."""
    try:
        values = parse_qs(urlparse(url).query).get(param)
    except ValueError:
        return url
    return values[0] if values else url


def unwrap_tracking_url(url: str) -> str:
    """The real destination behind an engine's click-tracking wrapper.

    Every engine here can hand back its own redirector instead of the page, and a wrapped
    URL is worse than ugly: it does not normalise to the same key as the direct URL, so
    :func:`dedupe_within_source` cannot merge the two and the fused list carries the same
    page twice — once cited to `r.search.yahoo.com/_ylt=…`, which is what the model then
    quotes at the user.

    The HTML parsers unwrap inline because they know their own engine's shape. This is the
    same rule for results arriving from the `ddgs` library, which mixes engines and so can
    return any of these forms (see :mod:`.sources`).
    """
    if not url:
        return url
    # Yahoo: r.search.yahoo.com/_ylt=…/RU=<percent-encoded target>/RK=…
    if "/RU=" in url and "r.search.yahoo.com" in url:
        from urllib.parse import unquote

        return unquote(url.split("/RU=", 1)[1].split("/R", 1)[0])
    # DuckDuckGo: //duckduckgo.com/l/?uddg=<percent-encoded target>
    if "duckduckgo.com/l/" in url or "/l/?uddg=" in url:
        return _unwrap_redirect(url, "uddg")
    return url


def _parse_duckduckgo(html: str) -> list[SearchResult]:
    out = []
    # One selector, not `div.result__body, div.web-result`: those are the inner and outer
    # element of the *same* hit, so the pair returned every result twice.
    for row in HTMLParser(html).css("div.result__body"):
        link = row.css_first("a.result__a")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if not href:
            continue
        out.append(
            SearchResult(
                title=_text(link),
                url=unwrap_tracking_url(href),
                snippet=_text(row.css_first("a.result__snippet")),
            )
        )
    return out


def _parse_brave(html: str) -> list[SearchResult]:
    tree = HTMLParser(html)
    # `data-type="web"` first and on its own. The generic `div.snippet` also matches
    # Brave's LLM-answer widget and the nested per-result snippet boxes, so combining the
    # two in one selector list returned each hit twice plus a widget.
    rows = tree.css("div.snippet[data-type='web']") or tree.css("div#results div.snippet")
    out = []
    for row in rows:
        link = row.css_first("a")
        if not link:
            continue
        href = link.attributes.get("href", "")
        if not href.startswith("http"):
            continue
        out.append(
            SearchResult(
                # The anchor wraps the favicon, the site name and a breadcrumb as well as
                # the title, so `div.title` is the only honest source here.
                title=_title_of(row, link, "div.title", ".snippet-title"),
                url=unwrap_tracking_url(href),
                # `.generic-snippet .content` is where the description lives now;
                # the two older names are kept so an A/B'd layout still parses.
                snippet=_first_text(
                    row,
                    "div.generic-snippet div.content",
                    "div.snippet-description",
                    ".snippet-content",
                ),
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
        out.append(
            SearchResult(
                # `h3` is the title; the enclosing anchor also holds the site name and the
                # `site.com › path › crumb` breadcrumb.
                title=_title_of(row, link, "h3"),
                url=unwrap_tracking_url(href),
                snippet=_first_text(row, "div.compText", "p"),
            )
        )
    return out


#: name -> (url template, parser). `{q}` is filled with the url-encoded query.
#:
#: **Startpage was removed, not disabled.** It serves a Gatsby single-page app with a
#: `<noscript>` wall and a captcha field: there are no results in the HTML for any query,
#: on the first request from a cold container, so there is no selector to repair. It
#: returned zero on every live query for the whole of phase 5 while still being counted as
#: one of seven sources — a facade is worse than a gap, because the `degraded` list is only
#: informative if a name on it can come off.
ENGINES = {
    "ddg": ("https://html.duckduckgo.com/html/?q={q}", _parse_duckduckgo),
    "brave": ("https://search.brave.com/search?q={q}", _parse_brave),
    "yahoo": ("https://search.yahoo.com/search?p={q}", _parse_yahoo),
}


def configured_engines() -> list[str]:
    """The engines this deployment uses, from `METASEARCH_ENGINES`.

    Unknown names are dropped with a warning rather than raising: the point of the env
    var is to let someone disable a rotted scraper in a hurry, and a typo there must not
    take the whole server down.
    """
    raw = os.getenv("METASEARCH_ENGINES", ",".join(ENGINES))
    names = []
    for name in (n.strip().lower() for n in raw.split(",")):
        if not name:
            continue
        if name not in ENGINES:
            log.warning("unknown engine %r in METASEARCH_ENGINES, ignoring", name)
            continue
        names.append(name)
    return names or ["ddg"]


async def _fetch_engine(
    client: httpx.AsyncClient, name: str, query: str
) -> tuple[list[SearchResult], str]:
    """Scrape one engine. Returns `(results, reason)`; `reason` is empty on success.

    The reason is the point of the second element. "brave returned nothing" is reported
    identically whether the selectors rotted, the engine answered `429 Too Many Requests`,
    or the host was unreachable — and those need three different responses from whoever
    reads it. Conflating them is how startpage stayed in the source list for a whole phase
    while returning zero on every query.
    """
    template, parser = ENGINES[name]
    from urllib.parse import quote_plus

    url = template.format(q=quote_plus(query))
    try:
        response = await client.get(url, timeout=ENGINE_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        log.warning("engine %s refused with HTTP %s", name, exc.response.status_code)
        return [], f"HTTP {exc.response.status_code}"
    except Exception as exc:  # noqa: BLE001 - one dead engine must degrade, not fail
        log.warning("engine %s failed: %s", name, exc)
        return [], f"{type(exc).__name__}: {exc}"
    try:
        results = parser(response.text)
    except Exception as exc:  # noqa: BLE001 - a selector change is a parse error
        log.warning("engine %s parse failed (selector rot?): %s", name, exc)
        return [], f"parse error: {exc}"
    if not results:
        log.warning("engine %s returned 0 results — selector may have rotted", name)
        return [], "answered with no results (selector rot?)"
    # One page listed by both an outer and an inner selector, or repeated by the engine
    # itself, must not take two RRF slots. Fusion dedupes too, but only after ranks are
    # assigned per source — doing it here is what makes those ranks mean anything.
    return dedupe_within_source(results), ""
