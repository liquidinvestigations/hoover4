"""Search sources: one name, one kind, one fetch function.

This is the abstraction that let `hoover4-mcp-ddg` and `hoover4-mcp-wikipedia` be
retired. Before it, the full research agent carried three overlapping "search the web"
tools and had to guess which one to call; now there is exactly one, and choosing *where*
to look is a `sources` argument rather than a tool choice.

A source's `kind` is not decoration. :mod:`.pipeline` applies a per-kind floor so an
encyclopaedia entry or a news story is not buried by ten generic web results that RRF
happened to rank higher.

Registered sources:

===============  ===========  =========================================================
name             kind         what it is
===============  ===========  =========================================================
``ddg``          web          the HTML scraper in :mod:`.engines`
``brave``        web          "
``yahoo``        web          "
``ddg_api``      web          the ``ddgs`` library's ``text()``, from `ddg_search_server`
``ddg_news``     news         the ``ddgs`` library's ``news()``, same origin
``gdelt``        news         GDELT DOC 2.0, world news across languages and back years
``wikipedia``    reference    MediaWiki search + extracts, from `wikipedia_search_server`
``wikidata``     reference    structured entities: a company, a person, an identifier
``crossref``     reference    DOI metadata, resolving to doi.org
``factcheck``    reference    published fact-checks; **key-gated**, absent without one
``wayback``      archive      what a URL said before it changed, from the CDX index
``archive_today` archive      the second archive; no API, so the flakiest source here
===============  ===========  =========================================================

`ddg_api` is kept **alongside** the `ddg` HTML scraper rather than replacing it. They rot
independently (a selector change breaks one and a library bump breaks the other), and
the `degraded` list exists so that rot is visible rather than silent.
`startpage` was removed for the opposite reason: it never worked at all (see
:data:`.engines.ENGINES`), and a permanently-degraded source is a facade, not a metasearch.

**A source that fails or times out must never fail the tool.** Every fetch here returns a
list, empty on any failure, and names itself in `degraded`. A fetch that knows *why* it
came back empty may raise :class:`SourceUnavailable` instead; :func:`fetch_all` catches it
and puts the reason next to the name, because "brave returned nothing" reads the same for
selector rot, an HTTP 429 and an unreachable host, and those want three different fixes.

**A key-gated source with no key is not registered at all.** It is therefore absent from
:func:`describe_sources`, from the default set and from dispatch, rather than present and
failing on every call. A source the model is told about and cannot use costs a round trip
to discover that. The key is read from a file path in the environment and never from a
value, never defaulted, and never logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from metasearch_server.engines import (
    ENGINES,
    SearchResult,
    _fetch_engine,
    unwrap_tracking_url,
)

log = logging.getLogger(__name__)


class SourceUnavailable(RuntimeError):
    """A source came back empty and knows why. Caught by :func:`fetch_all`."""

KIND_WEB = "web"
KIND_NEWS = "news"
KIND_REFERENCE = "reference"
#: A snapshot of a page as it was, rather than a page as it is. Its own kind because the
#: per-kind floor is what keeps one archived copy visible next to twenty live pages, and
#: because "the version before it was edited" answers a different question from "the
#: current version".
KIND_ARCHIVE = "archive"

ALL_KINDS = (KIND_WEB, KIND_NEWS, KIND_REFERENCE, KIND_ARCHIVE)

#: Per-source deadline. Shorter than the overall one below, so one slow source costs the
#: search a few seconds rather than the whole budget.
SOURCE_TIMEOUT = float(os.getenv("METASEARCH_SOURCE_TIMEOUT", "8"))

#: Overall fan-out deadline. Anything still running when it expires is cancelled and
#: reported degraded.
OVERALL_TIMEOUT = float(os.getenv("METASEARCH_OVERALL_TIMEOUT", "20"))

#: How many results to ask each source for. Larger than the caller's `max_results`
#: because fusion and reranking both need candidates to work with, asking for 8 and
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
    #: Deadline for this source alone; 0 means :data:`SOURCE_TIMEOUT`. Only for a source
    #: whose *normal* answer is slower than the common deadline, a source that is merely
    #: unreliable belongs on the `degraded` list, not on a longer leash. It can never
    #: exceed :data:`OVERALL_TIMEOUT`, which bounds the whole fan-out either way.
    timeout: float = 0.0


# --------------------------------------------------------------- HTML scrapers (web)

def _html_engine_source(name: str) -> Source:
    async def fetch(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
        # The HTML endpoints take no time filter, so `timelimit` is ignored here rather
        # than faked, a filter that silently does nothing is worse than one that is
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
            results, reason = await _fetch_engine(client, name, query)
        if reason:
            raise SourceUnavailable(reason)
        for r in results:
            r.kind = KIND_WEB
        return results[:max_results]

    return Source(name=name, kind=KIND_WEB, fetch=fetch, description=f"{name} HTML results")


# ------------------------------------------------------------------- ddgs library

def _ddgs_call(method: str, query: str, max_results: int, timelimit: str | None) -> list[dict]:
    """Blocking `ddgs` call. Run through `asyncio.to_thread`. The library is sync, and
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
            # The `ddgs` library fans out over several back ends of its own, so a row can
            # arrive carrying another engine's click-tracker. See :func:`unwrap_tracking_url`.
            url=unwrap_tracking_url(row.get("href", "") or row.get("url", "") or ""),
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
        # News rows are the worst offenders: `ddgs` routes several of its news back ends
        # through `r.search.yahoo.com/_ylt=…`, and an un-unwrapped wrapper normalises to a
        # different key from the direct URL, so dedupe cannot merge the two and the model
        # ends up citing a tracking link to the user.
        url = unwrap_tracking_url(row.get("url") or row.get("href") or "")
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


# -------------------------------------------------------- the JSON-API sources

#: Every JSON API below identifies itself the same way. Several of these services run a
#: "polite pool" keyed on a recognisable agent string and throttle anonymous callers
#: harder, so this is not decoration.
API_USER_AGENT = "hoover4-metasearch/1.0 (research tool)"


async def _get_json(
    url: str, params: dict[str, str], source: str, timeout: float = 0.0
) -> Any:
    """One GET returning parsed JSON, or :class:`SourceUnavailable` saying why not.

    An HTTP status, a connection failure and a body that is not JSON are three different
    faults with three different fixes, and a source that answered `200 OK` with an error
    sentence in plain text (GDELT does this for a query it will not run) is otherwise
    indistinguishable from one that found nothing.
    """
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": API_USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            # The client's own deadline must match the one `fetch_all` will enforce, or a
            # source given a longer leash is cut off by its HTTP client instead and
            # reports a connect timeout it never had.
            response = await client.get(
                url, params=params, timeout=timeout or SOURCE_TIMEOUT
            )
    except Exception as exc:  # noqa: BLE001 - degradation, never a tool failure
        raise SourceUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise SourceUnavailable(f"HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise SourceUnavailable(
            f"answered {response.status_code} with a non-JSON body: "
            f"{response.text.strip()[:120]}"
        ) from None


#: GDELT indexes world news in over a hundred languages and is the single biggest news
#: coverage gain available without a key. `sort=hybridrel` is its relevance ordering;
#: the default is reverse chronological, which returns the newest article mentioning a
#: word rather than the most relevant one.
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"

#: GDELT's own deadline. See the registry entry for why it is not the common one.
GDELT_TIMEOUT = float(os.getenv("METASEARCH_GDELT_TIMEOUT", "15"))

#: GDELT's article dates are `YYYYMMDDTHHMMSSZ`, which nothing else parses.
_GDELT_TIMELIMIT = {"d": "1d", "w": "1w", "m": "1m", "y": "12m"}


async def _fetch_gdelt(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": str(max(1, min(max_results, 75))),
        "sort": "hybridrel",
    }
    span = _GDELT_TIMELIMIT.get(timelimit or "")
    if span:
        params["timespan"] = span
    payload = await _get_json(GDELT_API, params, "gdelt", timeout=GDELT_TIMEOUT)
    out = []
    for row in (payload or {}).get("articles", []):
        url = str(row.get("url") or "")
        if not url:
            continue
        domain = str(row.get("domain") or "")
        language = str(row.get("language") or "")
        # The outlet and the language are the two things a GDELT row carries that the
        # title does not, and a model choosing between forty headlines about one event
        # needs both to tell a wire copy from a local report.
        context = " · ".join(p for p in (domain, language) if p)
        out.append(
            SearchResult(
                title=str(row.get("title") or ""),
                url=url,
                snippet=context,
                kind=KIND_NEWS,
                published=_gdelt_date(str(row.get("seendate") or "")),
            )
        )
    return out


def _gdelt_date(stamp: str) -> str:
    if len(stamp) >= 15 and stamp[8] == "T":
        return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}:{stamp[13:15]}Z"
    return stamp


#: Wikidata's entity search. Returns the item itself (a company, a person, an
#: identifier) rather than an article about it, which is what makes it the reference
#: source for "who is this and what is it cross-referenced to".
WIKIDATA_API = "https://www.wikidata.org/w/api.php"


async def _fetch_wikidata(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    """Entity search, with the phrase search behind it.

    `wbsearchentities` matches an item's *label* by prefix, so it is exact for "Enron"
    and returns nothing at all for "Arthur Andersen accounting firm", which is the shape
    of query a model actually sends. The full-text `list=search` answers those, so it is
    the fallback, and its rows carry only Q-numbers: one `wbgetentities` call turns them
    into labels and descriptions. Two round trips, and only on a miss.
    """
    # Wikidata items have no publication date, so `timelimit` cannot be honoured and is
    # ignored rather than faked: a filter that silently does nothing is worse than one
    # documented as unsupported.
    limit = str(max(1, min(max_results, 50)))
    payload = await _get_json(
        WIKIDATA_API,
        {
            "action": "wbsearchentities",
            "search": query,
            "language": WIKIPEDIA_LANGUAGE,
            "uselang": WIKIPEDIA_LANGUAGE,
            "type": "item",
            "limit": limit,
            "format": "json",
        },
        "wikidata",
    )
    rows = [
        (str(row.get("id") or ""), str(row.get("label") or ""), str(row.get("description") or ""))
        for row in (payload or {}).get("search", [])
    ]
    if not rows:
        rows = await _wikidata_by_phrase(query, limit)

    out = []
    for item_id, label, description in rows:
        if not item_id:
            continue
        out.append(
            SearchResult(
                # The Q-number is carried in the title because it is the join key: it is
                # what a follow-up lookup and every cross-reference are addressed by, and
                # a label alone is ambiguous across a dozen people with one name.
                title=f"{label or item_id} ({item_id})",
                url=f"https://www.wikidata.org/wiki/{item_id}",
                snippet=description,
                kind=KIND_REFERENCE,
            )
        )
    return out


async def _wikidata_by_phrase(query: str, limit: str) -> list[tuple[str, str, str]]:
    """`(id, label, description)` for a phrase, through the full-text index."""
    payload = await _get_json(
        WIKIDATA_API,
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "formatversion": "2",
        },
        "wikidata",
    )
    ids = [
        str(row.get("title") or "")
        for row in ((payload or {}).get("query") or {}).get("search", [])
        if str(row.get("title") or "").startswith("Q")
    ]
    if not ids:
        return []
    labels = await _get_json(
        WIKIDATA_API,
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "labels|descriptions",
            "languages": WIKIPEDIA_LANGUAGE,
            "format": "json",
        },
        "wikidata",
    )
    entities = (labels or {}).get("entities") or {}
    out = []
    for item_id in ids:
        entity = entities.get(item_id) or {}
        label = ((entity.get("labels") or {}).get(WIKIPEDIA_LANGUAGE) or {}).get("value") or ""
        description = (
            (entity.get("descriptions") or {}).get(WIKIPEDIA_LANGUAGE) or {}
        ).get("value") or ""
        out.append((item_id, str(label), str(description)))
    return out


#: Crossref resolves the DOIs the entity extractor validates, so a checksum-valid DOI in
#: a document becomes a title, an author list and a journal here.
CROSSREF_API = "https://api.crossref.org/works"


async def _fetch_crossref(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    payload = await _get_json(
        CROSSREF_API,
        {
            "query": query,
            "rows": str(max(1, min(max_results, 50))),
            "select": "DOI,title,abstract,issued,container-title,author",
        },
        "crossref",
    )
    out = []
    for row in ((payload or {}).get("message") or {}).get("items", []):
        doi = str(row.get("DOI") or "")
        if not doi:
            continue
        titles = row.get("title") or []
        container = row.get("container-title") or []
        # Crossref abstracts are JATS XML, not prose; the tag stripper is the same one
        # the Wikipedia snippets go through.
        abstract = _strip_tags(str(row.get("abstract") or ""))
        journal = str(container[0]) if container else ""
        out.append(
            SearchResult(
                title=str(titles[0]) if titles else doi,
                url=f"https://doi.org/{doi}",
                snippet=" — ".join(p for p in (journal, abstract) if p),
                kind=KIND_REFERENCE,
                published=_crossref_date(row.get("issued")),
            )
        )
    return out


def _crossref_date(issued: Any) -> str:
    parts = ((issued or {}).get("date-parts") or [[]])[0]
    return "-".join(f"{int(p):02d}" if i else str(int(p)) for i, p in enumerate(parts) if p)


#: Google's Fact Check Tools API over the published claim reviews of every ClaimReview
#: publisher. The one key-gated source here; see the module docstring for the policy.
FACTCHECK_API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


def _factcheck_key() -> str:
    """The key, from the file the deployment mounted, or `""`.

    Read on every call rather than cached, so rotating the mounted file takes effect
    without a restart. The value is returned and never logged; nothing here ever puts it
    in a message, a default or an error.
    """
    path = os.getenv("FACTCHECK_API_KEY_FILE", "")
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


async def _fetch_factcheck(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    key = _factcheck_key()
    if not key:
        # Reachable only if the key file emptied after start-up: without a key the source
        # is never registered. Named as a rotation rather than as a configuration error.
        raise SourceUnavailable("the mounted key file is now empty")
    payload = await _get_json(
        FACTCHECK_API,
        {
            "query": query,
            "key": key,
            "pageSize": str(max(1, min(max_results, 50))),
            "languageCode": WIKIPEDIA_LANGUAGE,
        },
        "factcheck",
    )
    out = []
    for claim in (payload or {}).get("claims", []):
        text = str(claim.get("text") or "")
        claimant = str(claim.get("claimant") or "")
        for review in claim.get("claimReview") or []:
            url = str(review.get("url") or "")
            if not url:
                continue
            rating = str(review.get("textualRating") or "")
            publisher = str((review.get("publisher") or {}).get("name") or "")
            # The rating leads the snippet: "False" is the entire finding, and burying it
            # behind the claim text is how a model quotes the claim as if it were the
            # verdict.
            head = " — ".join(p for p in (rating, publisher) if p)
            out.append(
                SearchResult(
                    title=str(review.get("title") or text)[:300],
                    url=url,
                    snippet=" · ".join(p for p in (head, claimant, text) if p),
                    kind=KIND_REFERENCE,
                    published=str(review.get("reviewDate") or claim.get("claimDate") or ""),
                )
            )
    return out


# ------------------------------------------------------------------ the archives

#: The Wayback Machine's CDX index. It answers about a **URL**, not about a phrase
#: (there is no full-text search over the archive), so a query naming no host is a
#: question this source cannot be asked, and it says so rather than returning nothing.
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"

_HOST_RE = re.compile(
    r"\b((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,})\b", re.IGNORECASE
)


def host_in(query: str) -> str:
    """The first hostname in a query, or `""`. Public and tested: it is the whole of
    what decides whether the archives can answer a question at all."""
    for match in _HOST_RE.finditer(query.strip()):
        host = match.group(1).lower()
        # A sentence-ending "etc." or a file name reads as a host to any pattern loose
        # enough to accept a real one; a known TLD list is the wrong fix (it rots), a
        # length floor on the last label is enough to drop the common false positives.
        if len(host.rsplit(".", 1)[-1]) >= 2 and not host.endswith((".etc", ".eg")):
            return host
    return ""


async def _fetch_wayback(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    host = host_in(query)
    if not host:
        raise SourceUnavailable("the archive indexes URLs and this query names no host")
    payload = await _get_json(
        WAYBACK_CDX,
        {
            "url": host,
            "matchType": "domain",
            "output": "json",
            "fl": "timestamp,original",
            "filter": "statuscode:200",
            # One snapshot per month per URL. Without it a busy site returns the same
            # page a hundred times over and the whole result budget is one URL.
            "collapse": "timestamp:6",
            "limit": str(max(1, min(max_results, 50))),
        },
        "wayback",
    )
    rows = payload if isinstance(payload, list) else []
    out = []
    # The first row is the header the `fl` parameter asked for, not a result.
    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 2:
            continue
        stamp, original = str(row[0]), str(row[1])
        out.append(
            SearchResult(
                title=f"{original} as of {_wayback_date(stamp)}",
                url=f"https://web.archive.org/web/{stamp}/{original}",
                snippet=f"Wayback Machine snapshot of {original}",
                kind=KIND_ARCHIVE,
                published=_wayback_date(stamp),
            )
        )
    return out


def _wayback_date(stamp: str) -> str:
    if len(stamp) >= 8 and stamp[:8].isdigit():
        return f"{stamp[0:4]}-{stamp[4:6]}-{stamp[6:8]}"
    return stamp


#: archive.today's snapshot listing. **There is no API**: this parses the HTML of a page
#: behind a bot-detection front end, so it is expected to be the first source on the
#: `degraded` list and that is what it is here for. A second archive that answers
#: sometimes is worth more than no second archive, as long as its failure is visible.
ARCHIVE_TODAY_URL = os.getenv("ARCHIVE_TODAY_URL", "https://archive.ph")

#: A snapshot is a **short-code** link (`https://archive.ph/wCG1t`) carrying the page's
#: title as its anchor text. The same listing also links `/<host>`, `/*.<host>` and
#: `/<the full url>`, which are navigation into other views of the same listing and not
#: snapshots at all; requiring a single path segment of a few alphanumerics is what
#: separates them, and without it the first "result" is the page's link to itself.
_ARCHIVE_TODAY_ROW = re.compile(
    r'<a[^>]+href="(?P<url>https?://archive\.[a-z]+/[A-Za-z0-9]{4,10})"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

#: The capture-date anchor, `9 Dec 2025 17:45`. Recognised so it becomes the snapshot's
#: date rather than its title.
_ARCHIVE_TODAY_DATE = re.compile(r"^\d{1,2} [A-Z][a-z]{2} \d{4}")


async def _fetch_archive_today(
    query: str, max_results: int, timelimit: str | None
) -> list[SearchResult]:
    host = host_in(query)
    if not host:
        raise SourceUnavailable("the archive indexes URLs and this query names no host")
    try:
        async with httpx.AsyncClient(
            headers={
                "User-Agent": os.getenv("METASEARCH_USER_AGENT", API_USER_AGENT),
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        ) as client:
            # `/<host>` is the snapshot listing. A trailing `*` is the form the site's own
            # UI shows and it answers 404 to a request for it, which reads as "nothing
            # archived" rather than as a wrong URL.
            response = await client.get(f"{ARCHIVE_TODAY_URL}/{host}", timeout=SOURCE_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
        raise SourceUnavailable(f"HTTP {response.status_code}")

    # Each snapshot is linked twice in the listing (once from its capture date and once
    # from the page's own title), so the anchors are gathered per URL and the longest one
    # is the title. Taking the first match makes every result a bare timestamp.
    order: list[str] = []
    anchors: dict[str, list[str]] = {}
    for match in _ARCHIVE_TODAY_ROW.finditer(response.text):
        url = match.group("url")
        title = _strip_tags(match.group("title"))
        if not title:
            continue
        if url not in anchors:
            order.append(url)
            anchors[url] = []
        anchors[url].append(title)

    out = []
    for url in order[:max_results]:
        texts = sorted(anchors[url], key=len, reverse=True)
        dated = [t for t in texts if _ARCHIVE_TODAY_DATE.match(t)]
        out.append(
            SearchResult(
                title=texts[0],
                url=url,
                snippet=f"archive.today snapshot of {host}",
                kind=KIND_ARCHIVE,
                published=dated[0] if dated else "",
            )
        )
    if not out:
        # The bot wall answers 200 with a challenge page, so an empty parse is the
        # ordinary failure here and must not read as "the archive holds nothing".
        raise SourceUnavailable("no snapshot rows in the response; the page is a bot wall or the markup moved")
    return out


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
    "gdelt": Source(
        name="gdelt",
        kind=KIND_NEWS,
        fetch=_fetch_gdelt,
        description="GDELT world news monitoring, across languages and back years",
        # Measured: GDELT takes ten to twelve seconds to answer at all, including when it
        # answers 429, so the common eight-second deadline turns every call into a
        # timeout. It also rate-limits per address, so a batch of queries will degrade it
        # partway through, which the `degraded` list reports rather than hides.
        timeout=GDELT_TIMEOUT,
    ),
    "wikipedia": Source(
        name="wikipedia",
        kind=KIND_REFERENCE,
        fetch=_fetch_wikipedia,
        description="Wikipedia article search",
    ),
    "wikidata": Source(
        name="wikidata",
        kind=KIND_REFERENCE,
        fetch=_fetch_wikidata,
        description="Wikidata structured entities: companies, people, identifiers",
    ),
    "crossref": Source(
        name="crossref",
        kind=KIND_REFERENCE,
        fetch=_fetch_crossref,
        description="Crossref DOI metadata for academic and published work",
    ),
    "wayback": Source(
        name="wayback",
        kind=KIND_ARCHIVE,
        fetch=_fetch_wayback,
        description="Wayback Machine snapshots of a host named in the query",
    ),
    "archive_today": Source(
        name="archive_today",
        kind=KIND_ARCHIVE,
        fetch=_fetch_archive_today,
        description="archive.today snapshots of a host named in the query",
    ),
}

if _factcheck_key():
    # Registered only when the key file is mounted and non-empty. Absent, not disabled:
    # `describe_sources` never names it, so the model is not told about a capability the
    # deployment does not have.
    SOURCES["factcheck"] = Source(
        name="factcheck",
        kind=KIND_REFERENCE,
        fetch=_fetch_factcheck,
        description="Published fact-checks of a claim, from the ClaimReview publishers",
    )

#: Default set. Everything registered, a metasearch that leaves a source out by default
#: is a metasearch nobody benefits from. Derived from the registry rather than written out,
#: so retiring a source cannot leave a default naming one that no longer exists.
DEFAULT_SOURCES = ",".join(SOURCES)


def configured_sources() -> list[str]:
    """The sources this deployment uses, from `METASEARCH_SOURCES`.

    Unknown names are dropped with a warning rather than raising, exactly as
    `configured_engines()` has always done: the point of the env var is to disable a
    rotted source in a hurry, and a typo there must not take the server down.

    `METASEARCH_ENGINES` is still honoured for the four HTML scrapers so an existing
    deployment's setting keeps meaning what it meant.
    """
    # Empty is unset, not "no sources". A compose file renders an unset variable as an
    # empty string, so treating the two differently means an unset default silently
    # narrows the deployment to one scraper.
    raw = os.getenv("METASEARCH_SOURCES") or None
    if raw is None:
        legacy = os.getenv("METASEARCH_ENGINES")
        if legacy:
            # The legacy variable names only the HTML scrapers, so everything else in the
            # registry is added back. Derived rather than listed: a hand-written list here
            # is how a newly registered source silently never runs on the one deployment
            # that still sets the old variable.
            scrapers = [n.strip().lower() for n in legacy.split(",") if n.strip()]
            extra = [n for n in SOURCES if n not in ENGINES]
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

    A caller (that is, the model), asking for a source that does not exist gets the
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
) -> tuple[dict[str, list[SearchResult]], dict[str, float], list[str], dict[str, str]]:
    """Query every named source in parallel.

    Returns `(results per source, latency_ms per source, degraded names, reason per
    degraded name)`. A source that raised, timed out, or came back empty is degraded,
    from the *ordering's* point of view those are the same failure, but from a maintainer's
    they are not, so the reason travels with the name instead of only reaching the log.
    """
    import time

    async def run(name: str) -> tuple[str, list[SearchResult], float, str]:
        source = SOURCES[name]
        deadline = source.timeout or SOURCE_TIMEOUT
        started = time.monotonic()
        reason = ""
        try:
            results = await asyncio.wait_for(
                source.fetch(query, per_source_results, timelimit), timeout=deadline
            )
        except asyncio.TimeoutError:
            log.warning("source %s exceeded its %.0fs deadline", name, deadline)
            results, reason = [], f"timed out after {deadline:g}s"
        except SourceUnavailable as exc:
            log.warning("source %s unavailable: %s", name, exc)
            results, reason = [], str(exc)
        except Exception as exc:  # noqa: BLE001 - degradation, never a tool failure
            log.warning("source %s raised: %s", name, exc)
            results, reason = [], f"{type(exc).__name__}: {exc}"
        elapsed = (time.monotonic() - started) * 1000.0
        for r in results:
            r.kind = r.kind or source.kind
        return name, results, elapsed, reason

    try:
        gathered = await asyncio.wait_for(
            asyncio.gather(*(run(n) for n in names)), timeout=OVERALL_TIMEOUT
        )
    except asyncio.TimeoutError:
        log.warning("metasearch fan-out exceeded %.0fs overall", OVERALL_TIMEOUT)
        gathered = []

    per_source = {name: [] for name in names}
    latency = {name: 0.0 for name in names}
    reasons = {name: f"cancelled by the {OVERALL_TIMEOUT:g}s overall deadline" for name in names}
    for name, results, elapsed, reason in gathered:
        per_source[name] = results
        latency[name] = round(elapsed, 1)
        reasons[name] = reason

    degraded = [name for name in names if not per_source[name]]
    return per_source, latency, degraded, {n: reasons[n] for n in degraded if reasons[n]}


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
