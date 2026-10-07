"""HTML-scraping web search engines.

Modelled on `MikeLuu99/metasearch-rust`: several engines scraped in parallel, results
deduplicated on a normalised URL, then merged with RRF so a result several engines agree
on outranks one only a single engine returned.

There are no API keys anywhere, and the cost of that is fragility. **Assume at least one of these
selectors will break within months**. Three things make that failure visible instead of
silent: an engine returning zero results is reported in the response's `degraded` list
rather than swallowed, that report carries the *reason* (see :func:`_fetch_engine`), and
the engine set is env-configurable so a rotted scraper can be turned off without a
rebuild.

Reporting rot is not the same as tolerating it. An engine that returns zero for every
query is gone rather than degraded, and leaving it registered inflates the source count
the tool advertises.

Each engine fetches its page through :mod:`.fetch` with the client and the routes of
:data:`metasearch_server.fetch.TRANSPORTS`. Bing, Google, Mojeek and Startpage need more than
one request, see :mod:`.engine_sessions`.

This module is now the `kind = "web"` half of a wider set. :mod:`.sources` wraps each
engine here as a *source* alongside the DuckDuckGo, news, reference and archive sources, and :mod:`.pipeline` is what orders the merged set.

The fusion machinery itself (`SearchResult`, `normalise_url`, `dedupe_within_source`,
`reciprocal_rank_fusion`, `RRF_K`) lives in `agent_common.fusion`, not here. Collection
search fuses with the same code, and a second copy would drift. The names are re-exported
here so both import paths work.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from urllib.parse import parse_qs, quote_plus, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from agent_common.fusion import (
    RRF_K,
    SearchResult,
    dedupe_within_source,
    normalise_url,
    reciprocal_rank_fusion,
)
from metasearch_server import engine_sessions
from metasearch_server.fetch import FetchError, FetchResponse, fetch

__all__ = [
    "ENGINES",
    "parse_duckduckgo_lite",
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
    height-and-factsEiffel Tower Height: …`. That mash is what the user reads and what the
    model cites. Take the title element when the row has one. The link is only the
    fallback for engines whose anchor *is* the title.
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
    URL is a correctness defect: it does not normalise to the same key as the direct URL, so
    :func:`dedupe_within_source` cannot merge the two and the fused list carries the same
    page twice, once cited to `r.search.yahoo.com/_ylt=…`, which is what the model then
    quotes at the user.

    The HTML parsers call it for each link. The news sources in :mod:`.sources` call it too,
    because a news row can link through another engine's redirector.
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
    # Bing: www.bing.com/ck/a?!&&p=…&u=a1<base64url target>&ntb=1
    if "bing.com/ck/a" in url:
        encoded = _unwrap_redirect(url, "u")
        if encoded.startswith("a1"):
            payload = encoded[2:]
            try:
                target = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
                return target.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return url
        return url
    # Google: /url?q=<target>&sa=… or /url?url=<target>, relative or on a Google host.
    # The `/goto?url=<token>` links of the current result page carry an encrypted token,
    # not the target. Only a request to Google finds the target, so they stay as they are
    # here. `_fetch_engine` resolves them with `engine_sessions.resolve_google_links`.
    parsed = urlparse(url)
    if parsed.path == "/url" and (not parsed.netloc or "google." in parsed.netloc):
        for param in ("q", "url"):
            target = _unwrap_redirect(url, param)
            if target != url and target.startswith("http"):
                return target
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
                # the title, so `div.title` is the only accurate source here.
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


def _parse_bing(html: str) -> list[SearchResult]:
    """The results of a Bing page: one `li.b_algo` for each result.

    The title link is `h2 a`. Its URL is a `bing.com/ck/a` redirect with the target in the
    `u` parameter. The snippet is the `p.b_lineclamp<n>` element, or a paragraph of
    `div.b_caption` in an older layout.
    """
    out = []
    for row in HTMLParser(html).css("li.b_algo"):
        link = row.css_first("h2 a")
        if not link:
            continue
        href = unwrap_tracking_url(link.attributes.get("href", "") or "")
        if not href.startswith("http"):
            continue
        out.append(
            SearchResult(
                title=_text(link),
                url=href,
                snippet=_first_text(
                    row,
                    "p.b_lineclamp1, p.b_lineclamp2, p.b_lineclamp3, p.b_lineclamp4",
                    "div.b_caption p",
                ),
            )
        )
    return out


#: The prefix that makes a relative Google link absolute.
_GOOGLE_ORIGIN = "https://www.google.com"


def _parse_google(html: str) -> list[SearchResult]:
    """The results of a Google page: one `div.MjjYud` in `#rso` for each result.

    The title is the `h3` inside the result link. The snippet is `div.VwiC3b`. A row
    without an `h3` is a panel, such as "People also ask", and is left out. `div.g` is the
    result row of an older layout.

    The current page links each result through `/goto?url=<token>`. The token is
    encrypted, so the page does not contain the target URL. This parser keeps the absolute
    `https://www.google.com/goto?url=…` link. :func:`_fetch_engine` then resolves the first
    links with :func:`.engine_sessions.resolve_google_links`.
    """
    tree = HTMLParser(html)
    rows = tree.css("#rso div.MjjYud") or tree.css("div.g")
    out = []
    for row in rows:
        heading = row.css_first("h3")
        if heading is None:
            continue
        link = heading.parent
        while link is not None and link.tag != "a":
            link = link.parent
        if link is None:
            continue
        href = link.attributes.get("href", "") or ""
        if href.startswith("/"):
            href = _GOOGLE_ORIGIN + href
        href = unwrap_tracking_url(href)
        if not href.startswith("http"):
            continue
        out.append(
            SearchResult(
                title=_text(heading),
                url=href,
                snippet=_first_text(row, "div.VwiC3b", "div[data-sncf='1']"),
            )
        )
    return out


def _parse_mojeek(html: str) -> list[SearchResult]:
    """The results of a Mojeek page: one `li` in `ul.results-standard` for each result.

    The title link is `h2 a`, and `a.ob` has the same URL. Mojeek links to the target
    directly. The snippet is `p.s`.
    """
    out = []
    for row in HTMLParser(html).css("ul.results-standard > li"):
        link = row.css_first("h2 a") or row.css_first("a.ob")
        if not link:
            continue
        href = unwrap_tracking_url(link.attributes.get("href", "") or "")
        if not href.startswith("http"):
            continue
        out.append(
            SearchResult(
                title=_title_of(row, link, "h2 a"),
                url=href,
                snippet=_first_text(row, "p.s"),
            )
        )
    return out


#: The script call that holds the result object of a Startpage page.
_STARTPAGE_DATA = "React.createElement(UIStartpage.AppSerpWeb, "


def _parse_startpage(html: str) -> list[SearchResult]:
    """The web results of a Startpage page.

    The page script passes one JSON object to `UIStartpage.AppSerpWeb`. Its
    `render.presenter.regions.mainline` list holds blocks, and the blocks with
    `display_type` `web-google` hold the results: `title` and `description` with `<b>`
    marks, and `clickUrl`, the target itself. The advert blocks are left out.
    """
    start = html.find(_STARTPAGE_DATA)
    if start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(html, start + len(_STARTPAGE_DATA))
        blocks = data["render"]["presenter"]["regions"]["mainline"]
    except (ValueError, KeyError, TypeError):
        return []
    out = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get("display_type") != "web-google":
            continue
        for row in block.get("results") or []:
            url = str(row.get("clickUrl") or "")
            if not url.startswith("http"):
                continue
            out.append(SearchResult(
                title=_markup_text(str(row.get("title") or "")),
                url=url,
                snippet=_markup_text(str(row.get("description") or "")),
            ))
    return out


def _markup_text(markup: str) -> str:
    """The text of an HTML fragment, with its character references decoded."""
    return _text(HTMLParser(f"<p>{markup}</p>").css_first("p"))


def parse_duckduckgo_lite(html: str) -> list[SearchResult]:
    """The results of a DuckDuckGo Lite page, `lite.duckduckgo.com/lite/`.

    The page is one table. A result is a row with the link `a.result-link`, then a row
    with the cell `td.result-snippet`. An advert links to `duckduckgo.com/y.js` and is
    left out. The `ddg_api` source in :mod:`.sources` uses this parser.
    """
    out: list[SearchResult] = []
    current: SearchResult | None = None
    for row in HTMLParser(html).css("tr"):
        link = row.css_first("a.result-link")
        if link is not None:
            current = None
            href = unwrap_tracking_url(link.attributes.get("href", "") or "")
            if href.startswith("//"):
                href = "https:" + href
            if not href.startswith("http") or "duckduckgo.com/y.js" in href:
                continue
            current = SearchResult(title=_text(link), url=href, snippet="")
            out.append(current)
            continue
        cell = row.css_first("td.result-snippet")
        if cell is not None and current is not None and not current.snippet:
            current.snippet = _text(cell)
    return out


#: name -> (url template, parser). `{q}` is filled with the url-encoded query.
#:
#: Bing uses `www4.bing.com` and `form=QBRE` with the cookies of its home page, see
#: :func:`.engine_sessions.bing_page`. Startpage takes the query in a form POST, so its
#: template has no `{q}`, see :func:`.engine_sessions.startpage_page`.
ENGINES = {
    "ddg": ("https://html.duckduckgo.com/html/?q={q}", _parse_duckduckgo),
    "brave": ("https://search.brave.com/search?q={q}", _parse_brave),
    "yahoo": ("https://search.yahoo.com/search?p={q}", _parse_yahoo),
    "bing": ("https://www4.bing.com/search?q={q}&form=QBRE", _parse_bing),
    # `udm=14` is the "Web" tab: only web results, without the AI overview and the other
    # panels. `hl=en` sets the language of the page text, such as the dates of snippets.
    "google": ("https://www.google.com/search?q={q}&udm=14&hl=en", _parse_google),
    "mojeek": ("https://www.mojeek.com/search?q={q}", _parse_mojeek),
    "startpage": ("https://www.startpage.com/sp/search", _parse_startpage),
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


def _page_title(html: str) -> str:
    """The `<title>` text of a page, cut to 80 characters, or `""`."""
    try:
        return _text(HTMLParser(html).css_first("title"))[:80]
    except Exception:  # noqa: BLE001 - the title only adds detail to a reason
        return ""


async def _engine_page(name: str, url: str, query: str) -> FetchResponse:
    """The result page of `query` from engine `name`."""
    if name == "bing":
        return await engine_sessions.bing_page(url, ENGINE_TIMEOUT)
    if name == "mojeek":
        return await engine_sessions.mojeek_page(url, ENGINE_TIMEOUT)
    if name == "startpage":
        return await engine_sessions.startpage_page(query, ENGINE_TIMEOUT)
    return await fetch(name, url, timeout=ENGINE_TIMEOUT)


async def _fetch_engine(name: str, query: str) -> tuple[list[SearchResult], str]:
    """Scrape one engine. Returns `(results, reason)`; `reason` is empty on success.

    The reason tells selector rot, a refusal such as `HTTP 429` and an unreachable host
    apart. Each of these needs a different repair, and the `degraded_reasons` field
    gives the reason to the reader. A refusal names each route that was tried.
    """
    template, parser = ENGINES[name]
    url = template.format(q=quote_plus(query))
    try:
        response = await _engine_page(name, url, query)
    except FetchError as exc:
        log.warning("engine %s failed: %s", name, exc)
        return [], str(exc)
    if response.status >= 400:
        log.warning("engine %s refused with HTTP %s", name, response.status)
        return [], f"HTTP {response.status}"
    try:
        results = parser(response.text)
    except Exception as exc:  # noqa: BLE001 - a selector change is a parse error
        log.warning("engine %s parse failed (selector rot?): %s", name, exc)
        return [], f"parse error: {exc}"
    if not results:
        # The page title names a challenge page, such as Mojeek's "Captcha".
        title = _page_title(response.text)
        suffix = f", page title {title!r}" if title else ""
        if response.status != 200:
            log.warning("engine %s answered HTTP %s with no results", name, response.status)
            return [], f"HTTP {response.status} with no results (a bot challenge page?){suffix}"
        log.warning("engine %s returned 0 results, so the selector may have rotted%s",
                    name, suffix)
        return [], f"answered with no results (selector rot?){suffix}"
    if name == "google":
        urls = await engine_sessions.resolve_google_links([r.url for r in results],
                                                          ENGINE_TIMEOUT)
        for result, url in zip(results, urls):
            result.url = url
    # One page listed by both an outer and an inner selector, or repeated by the engine
    # itself, must not take two RRF slots. Fusion dedupes too, but only after ranks are
    # assigned per source. Doing it here is what makes those ranks mean anything.
    return dedupe_within_source(results), ""
