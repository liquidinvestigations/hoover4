"""FastMCP server driving a real browser, for pages the HTML scrapers cannot read.

The metasearch server finds pages; this one reads them. It exists because a growing
share of the web renders its body with JavaScript, and `httpx` + a CSS selector gets an
empty shell. nodriver talks CDP directly — no chromedriver binary, no Selenium — and is
async, which fits FastMCP.

Every URL goes through :mod:`.urlcheck` before Chromium sees it. Read that module's
docstring before changing anything here: this server is reachable by an LLM from inside
the network where ClickHouse and Temporal answer unauthenticated requests.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from browser_use_server.browser import NAV_TIMEOUT, with_page
from browser_use_server.urlcheck import UrlNotAllowed, check_url

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

#: The page text cap. Same reasoning as the collection server's MAX_DOCUMENT_CHARS: one
#: long article must not consume the agent's whole context window.
MAX_DOCUMENT_CHARS = int(os.getenv("MAX_DOCUMENT_CHARS", "20000"))

#: How many links to return. A navigation-heavy page has hundreds and they are mostly
#: chrome; the model needs enough to pick a next hop, not a sitemap.
MAX_LINKS = int(os.getenv("BROWSER_MAX_LINKS", "50"))

mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_browser"),
    instructions=os.getenv(
        "SERVER_INSTRUCTIONS",
        "Open a web page in a real browser and read it. Use this when a search result "
        "looks promising and you need the full text, or when a page renders its content "
        "with JavaScript and a plain fetch would return nothing. Text is truncated, so "
        "prefer a specific page over a site's front door. Only public http/https URLs "
        "are fetchable. This is slower than search — one page at a time — so pick the "
        "page you actually need rather than opening every result.",
    ),
)


class PageContent(BaseModel):
    success: bool
    url: str
    title: str = ""
    text: str = ""
    links: list[str] = Field(default_factory=list)
    truncated: bool = False
    error: str | None = None


#: Pulled out of the page in one CDP round trip. Strips the parts of the DOM that are
#: never content, then takes innerText, which is what a reader sees rather than raw
#: markup.
#:
#: **Returns a JSON string, not an object.** nodriver's `evaluate(return_by_value=True)`
#: hands back a plain Python value only for scalars; for an object it returns a raw
#: `cdp.runtime.RemoteObject` whose payload is buried in `deep_serialized_value`. Reading
#: that structure would couple this code to a CDP wire format, and the first version of
#: this file simply mis-detected it and reported `success=True` with empty text — a
#: silently blank page is the worst outcome for a tool an LLM relies on. A JSON string
#: crosses the boundary as a scalar and is parsed here.
#:
#: `innerText` is taken from a *clone* with the non-content elements removed, so nav and
#: footer boilerplate does not land in the agent's context; links come from the live
#: document because the clone is detached and its `a.href` would not be absolute.
_EXTRACT_JS = """
(() => {
  const drop = ['script','style','noscript','svg','nav','footer','header','aside','form'];
  const doc = document.cloneNode(true);
  drop.forEach(t => doc.querySelectorAll(t).forEach(n => n.remove()));
  const main = doc.querySelector('main,article,[role=main]') || doc.body;
  const text = (main ? main.innerText || main.textContent : '') || '';
  const links = Array.from(document.querySelectorAll('a[href]'))
    .map(a => a.href)
    .filter(h => h.startsWith('http'));
  return JSON.stringify({
    title: document.title || '',
    text: text,
    links: Array.from(new Set(links))
  });
})()
"""


@mcp.tool(
    name="browse_page",
    description=(
        "Open a public web page in a real browser and return its title, readable text "
        "and outgoing links. Use for pages that need JavaScript, or to read a search "
        "result in full. Text is capped, so pick a specific page."
    ),
)
async def browse_page(url: str, timeout_seconds: float = NAV_TIMEOUT) -> PageContent:
    try:
        checked = check_url(url)
    except UrlNotAllowed as exc:
        # Refusals are returned, not raised: the model should learn it cannot reach
        # internal hosts and move on, rather than see an opaque tool crash.
        return PageContent(success=False, url=url, error=f"refused: {exc}")

    async def extract(tab):
        return await tab.evaluate(_EXTRACT_JS, await_promise=False, return_by_value=True)

    try:
        payload = await with_page(checked, extract, timeout=timeout_seconds)
    except TimeoutError as exc:
        return PageContent(success=False, url=url, error=str(exc))
    except Exception as exc:  # noqa: BLE001 - surfaced to the model
        log.exception("browse_page failed for %s", url)
        return PageContent(success=False, url=url, error=f"could not load page: {exc}")

    # Anything that is not the JSON string the script promises means the extraction
    # did not run — report that rather than a cheerful empty page.
    if not isinstance(payload, str):
        log.error("unexpected evaluate() return for %s: %r", url, type(payload))
        return PageContent(
            success=False, url=url, error="page extraction returned no usable content"
        )
    try:
        data = json.loads(payload)
    except ValueError as exc:
        return PageContent(success=False, url=url, error=f"could not parse page content: {exc}")

    text = (data.get("text") or "").strip()
    links = [l for l in (data.get("links") or []) if isinstance(l, str)][:MAX_LINKS]
    title = (data.get("title") or "").strip()

    if not text and not title:
        return PageContent(
            success=False,
            url=url,
            error="page loaded but contained no readable text (JS-gated, blocked, or empty)",
        )

    return PageContent(
        success=True,
        url=url,
        title=title,
        text=text[:MAX_DOCUMENT_CHARS],
        links=links,
        truncated=len(text) > MAX_DOCUMENT_CHARS,
    )


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "hoover4-browser"})


def main() -> None:
    log.info("Starting Hoover4 browser MCP server")
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8087")),
    )


if __name__ == "__main__":
    main()
