"""Search sources: one name, one kind, one fetch function.

The server has one search tool. The `sources` argument selects where to look, so an agent
does not choose between several search tools.

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
``bing``         web          "
``google``       web          "
``mojeek``       web          "
``startpage``    web          "
``ddg_api``      web          DuckDuckGo Lite, ``lite.duckduckgo.com/lite/``
``ddg_news``     news         DuckDuckGo News, ``duckduckgo.com/news.js``
``gdelt``        news         GDELT DOC 2.0, world news across languages and back years
``wikipedia``    reference    MediaWiki search
``wikidata``     reference    structured entities: a company, a person, an identifier
``crossref``     reference    DOI metadata, resolving to doi.org
``factcheck``    reference    published fact-checks; **key-gated**, absent without one
``wayback``      archive      what a URL said before it changed, from the CDX index
``archive_today` archive      the second archive; no API, so the flakiest source here
===============  ===========  =========================================================

`ddg_api` is kept **alongside** the `ddg` HTML scraper rather than replacing it. They read
two different DuckDuckGo pages with different markup, so they rot independently, and
the `degraded` list exists so that rot is visible rather than silent. Only `ddg_api` takes
the `timelimit` filter.

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

Every source sends its HTTP requests through :func:`metasearch_server.fetch.fetch`, with
the client, the route order and the rate cap of :data:`metasearch_server.fetch.TRANSPORTS`.
See :mod:`.fetch`.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from metasearch_server import fetch as fetch_mod
from metasearch_server.engines import (
    ENGINES,
    SearchResult,
    _fetch_engine,
    dedupe_within_source,
    parse_duckduckgo_lite,
    unwrap_tracking_url,
)
from metasearch_server.fetch import FetchError, fetch

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
#: search a few seconds rather than the whole budget. It holds a refused direct attempt and
#: one attempt over Tor.
SOURCE_TIMEOUT = float(os.getenv("METASEARCH_SOURCE_TIMEOUT", "8"))

#: Overall fan-out deadline. Anything still running when it expires is cancelled and
#: reported degraded.
OVERALL_TIMEOUT = float(os.getenv("METASEARCH_OVERALL_TIMEOUT", "20"))

#: How many results to ask each source for. Larger than the caller's `max_results`
#: because fusion and the per-kind floor need candidates to work with.
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

#: The deadline of `startpage`. A new Anubis solve takes about 2 s on average with 4 worker
#: processes, and the search then needs 2 more requests.
STARTPAGE_TIMEOUT = float(os.getenv("METASEARCH_STARTPAGE_TIMEOUT", "15"))


def _html_engine_source(name: str) -> Source:
    async def fetch(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
        # The HTML endpoints take no time filter, so `timelimit` is ignored here rather
        # than faked, a filter that silently does nothing is worse than one that is
        # documented as unsupported.
        results, reason = await _fetch_engine(name, query)
        if reason:
            raise SourceUnavailable(reason)
        for r in results:
            r.kind = KIND_WEB
        return results[:max_results]

    return Source(name=name, kind=KIND_WEB, fetch=fetch, description=f"{name} HTML results",
                  timeout=STARTPAGE_TIMEOUT if name == "startpage" else 0.0)


# ------------------------------------------------------------------- DuckDuckGo

#: The DuckDuckGo endpoints of `ddg_api` and `ddg_news`. The `ddgs` library makes its own
#: HTTP requests and takes no HTTP client, so these sources fetch the endpoints through
#: :func:`fetch` and do not use the library. `news.js` refuses this host's address, so
#: `ddg_news` uses the Tor routes only.
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
DDG_HOME_URL = "https://duckduckgo.com/"
DDG_NEWS_URL = "https://duckduckgo.com/news.js"

#: The DuckDuckGo `kp` and `p` values of `DDG_DEFAULT_SAFESEARCH`.
_DDG_SAFESEARCH = {"on": "1", "moderate": "-1", "off": "-2"}

#: The `vqd` token that duckduckgo.com puts in its result page. `news.js` needs it.
_VQD = re.compile(r"""vqd=["']?([0-9-]+)""")


async def _fetch_ddg_api(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    """The result list of DuckDuckGo Lite. `timelimit` becomes its `df` filter."""
    params = {"q": query, "kl": DDG_REGION, "kp": _DDG_SAFESEARCH.get(DDG_SAFESEARCH, "-1")}
    if timelimit:
        params["df"] = timelimit
    try:
        response = await fetch("ddg_api", DDG_LITE_URL, params=params, timeout=SOURCE_TIMEOUT)
    except FetchError as exc:
        raise SourceUnavailable(str(exc)) from exc
    if response.status >= 400:
        raise SourceUnavailable(f"HTTP {response.status}")
    results = parse_duckduckgo_lite(response.text)
    if not results:
        raise SourceUnavailable(
            f"HTTP {response.status} with no results (a bot challenge page?)"
            if response.status != 200 else "answered with no results (selector rot?)")
    for r in results:
        r.kind = KIND_WEB
    return dedupe_within_source(results)[:max_results]


async def _fetch_ddg_news(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    """DuckDuckGo News: the result page gives the `vqd` token, then `news.js` the rows.

    Both requests use one SOCKS user name and the route of the first answer, so they go
    through one Tor circuit.
    """
    circuit = uuid.uuid4().hex
    try:
        page = await fetch("ddg_news", DDG_HOME_URL, params={"q": query}, circuit=circuit,
                           timeout=SOURCE_TIMEOUT)
    except FetchError as exc:
        raise SourceUnavailable(str(exc)) from exc
    if page.status >= 400:
        raise SourceUnavailable(f"HTTP {page.status} from the result page")
    token = _VQD.search(page.text)
    if not token:
        raise SourceUnavailable("the result page has no vqd token (a bot challenge page?)")
    params = {
        "l": DDG_REGION,
        "o": "json",
        "noamp": "1",
        "q": query,
        "vqd": token.group(1),
        "p": _DDG_SAFESEARCH.get(DDG_SAFESEARCH, "-1"),
    }
    if timelimit:
        params["df"] = timelimit
    payload = await _get_json(DDG_NEWS_URL, params, "ddg_news",
                              headers={"Referer": DDG_HOME_URL}, circuit=circuit,
                              prefer=page.route)
    out = []
    for row in (payload or {}).get("results", [])[:max_results]:
        # A news row can carry a click-tracker of another engine. See
        # :func:`unwrap_tracking_url`.
        url = unwrap_tracking_url(str(row.get("url") or ""))
        if not url:
            continue
        source_name = str(row.get("source") or "")
        snippet = _strip_tags(str(row.get("excerpt") or ""))
        out.append(
            SearchResult(
                title=_strip_tags(str(row.get("title") or "")),
                url=url,
                # The outlet is the most useful thing a news result carries beyond the
                # headline, and it is not recoverable from the URL for syndicated wires.
                snippet=f"{source_name}: {snippet}" if source_name else snippet,
                kind=KIND_NEWS,
                published=_unix_date(row.get("date")),
            )
        )
    return out


def _unix_date(value: Any) -> str:
    """An ISO 8601 UTC time from a Unix time in seconds, or the value as text."""
    from datetime import datetime, timezone

    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value or "")


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
        response = await fetch(
            "wikipedia", url, params=params, headers={"User-Agent": API_USER_AGENT},
            timeout=SOURCE_TIMEOUT,
        )
        if response.status != 200:
            raise SourceUnavailable(f"HTTP {response.status}")
        rows = response.json().get("query", {}).get("search", [])
    except SourceUnavailable:
        raise
    except FetchError as exc:
        # The message of a FetchError names the cause, as in the other sources.
        log.warning("source wikipedia failed: %s", exc)
        raise SourceUnavailable(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.warning("source wikipedia failed: %s", exc)
        raise SourceUnavailable(f"{type(exc).__name__}: {exc}") from exc

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
                # The markup is removed so that the model receives plain text.
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
    # The markup is removed first, so an escaped `&lt;b&gt;` stays text and is not removed.
    return " ".join(html_mod.unescape("".join(out)).split())


# -------------------------------------------------------- the JSON-API sources

#: Every JSON API below sends the same agent string. Crossref and the Wikimedia APIs give
#: more capacity to a caller with an identifiable agent string than to an anonymous one.
API_USER_AGENT = "from-the-cracks-metasearch/1.0 (research tool)"


async def _get_json(
    url: str, params: dict[str, str], source: str, timeout: float = 0.0,
    headers: dict[str, str] | None = None, circuit: str = "", prefer: str = "",
) -> Any:
    """One GET returning parsed JSON, or :class:`SourceUnavailable` saying why not.

    An HTTP status, a connection failure and a body that is not JSON are three different
    faults with three different fixes, and a source that answered `200 OK` with an error
    sentence in plain text (GDELT does this for a query it will not run) is otherwise
    indistinguishable from one that found nothing.
    """
    try:
        # The HTTP deadline must match the one `fetch_all` enforces. Otherwise a source
        # with a longer deadline stops at the HTTP timeout and reports a wrong cause.
        response = await fetch(
            source,
            url,
            params=params,
            headers=headers or {"User-Agent": API_USER_AGENT, "Accept": "application/json"},
            timeout=timeout or SOURCE_TIMEOUT,
            circuit=circuit,
            prefer=prefer,
        )
    except FetchError as exc:
        raise SourceUnavailable(str(exc)) from exc
    if response.status != 200:
        raise SourceUnavailable(f"HTTP {response.status}")
    try:
        return response.json()
    except ValueError:
        raise SourceUnavailable(
            f"answered {response.status} with a non-JSON body: "
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


#: GDELT pacing: at most one request in flight, and at least this many seconds from the end
#: of one request to the start of the next. GDELT answers HTTP 429 to a faster caller.
GDELT_GAP_S = float(os.getenv("METASEARCH_GDELT_GAP_SECONDS", "10"))

#: Whether a GDELT request runs, and the `time.monotonic()` value of the next allowed start.
_GDELT_PACE = {"busy": False, "next": 0.0}


async def _fetch_gdelt(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
    """GDELT articles. A call that is not due is skipped at once with the reason "gdelt paced"."""
    if _GDELT_PACE["busy"]:
        raise SourceUnavailable("gdelt paced: another GDELT request is running")
    wait = _GDELT_PACE["next"] - time.monotonic()
    if wait > 0:
        raise SourceUnavailable(f"gdelt paced: the next GDELT request can start in {wait:.0f} s")
    _GDELT_PACE["busy"] = True
    try:
        return await _gdelt_request(query, max_results, timelimit)
    finally:
        _GDELT_PACE["busy"] = False
        _GDELT_PACE["next"] = time.monotonic() + GDELT_GAP_S


async def _gdelt_request(query: str, max_results: int, timelimit: str | None) -> list[SearchResult]:
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
                snippet=". ".join(p for p in (journal, abstract) if p),
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
            head = ", ".join(p for p in (rating, publisher) if p)
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
        # `/<host>` is the snapshot listing. The site answers 404 to the form with a
        # trailing `*` that its own interface shows.
        response = await fetch("archive_today", f"{ARCHIVE_TODAY_URL}/{host}",
                               timeout=SOURCE_TIMEOUT)
    except FetchError as exc:
        raise SourceUnavailable(str(exc)) from exc
    if response.status != 200:
        raise SourceUnavailable(f"HTTP {response.status}")

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
        description="DuckDuckGo Lite results, with the time filter",
    ),
    "ddg_news": Source(
        name="ddg_news",
        kind=KIND_NEWS,
        fetch=_fetch_ddg_news,
        description="DuckDuckGo News",
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

    `METASEARCH_ENGINES` is still honoured for the HTML scrapers so an existing
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


#: The reason of a source that answered with an empty list and no error.
NO_RESULTS = "answered with no results"


async def fetch_all(
    query: str,
    names: list[str],
    per_source_results: int = PER_SOURCE_RESULTS,
    timelimit: str | None = None,
    overall_timeout: float | None = None,
) -> tuple[dict[str, list[SearchResult]], dict[str, float], list[str], dict[str, str],
           dict[str, str]]:
    """Query every named source in parallel.

    `overall_timeout` is the deadline in seconds for the whole fan-out. The default is
    :data:`OVERALL_TIMEOUT`. The pipeline gives a smaller value when the time budget of
    the call has less time left.

    Returns `(results per source, latency_ms per source, degraded names, reason per
    degraded name, routes per source)`. A source that raised, timed out, or came back empty
    is degraded. From the *ordering's* point of view those are the same failure, but from
    a maintainer's they are not, so each degraded name has a reason. The routes of a source
    are the routes of its answers, joined with `+`, for example `direct` or `tor-de`.
    """
    overall = OVERALL_TIMEOUT if overall_timeout is None else overall_timeout
    fan_out_end = time.monotonic() + max(0.0, overall)

    async def run(name: str) -> tuple[str, list[SearchResult], float, str, str]:
        source = SOURCES[name]
        deadline = source.timeout or SOURCE_TIMEOUT
        started = time.monotonic()
        reason = ""
        with fetch_mod.record_routes() as routes:
            try:
                # The fetches of this source end by the deadline of the source. The source
                # is cancelled `fetch.ANSWER_GRACE_S` later, so a fetch reports its own
                # cause, not a timeout, also when the event loop is busy.
                with fetch_mod.source_deadline(min(started + deadline, fan_out_end)):
                    results = await asyncio.wait_for(
                        source.fetch(query, per_source_results, timelimit),
                        timeout=deadline + fetch_mod.ANSWER_GRACE_S,
                    )
            except asyncio.TimeoutError:
                limit = deadline + fetch_mod.ANSWER_GRACE_S
                log.warning("source %s exceeded its %.0fs deadline", name, limit)
                results, reason = [], f"timed out after {limit:g}s"
            except SourceUnavailable as exc:
                log.warning("source %s unavailable: %s", name, exc)
                results, reason = [], str(exc)
            except Exception as exc:  # noqa: BLE001 - degradation, never a tool failure
                log.warning("source %s raised: %s", name, exc)
                results, reason = [], f"{type(exc).__name__}: {exc}"
        elapsed = (time.monotonic() - started) * 1000.0
        for r in results:
            r.kind = r.kind or source.kind
        return name, results, elapsed, reason or ("" if results else NO_RESULTS), "+".join(
            dict.fromkeys(routes))

    # A source that finished before the deadline keeps its results. Only the sources
    # still running at the deadline are cancelled.
    tasks = [asyncio.create_task(run(n)) for n in names]
    gathered = []
    try:
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=max(0.0, overall))
            if pending:
                log.warning("metasearch fan-out exceeded %.1fs overall", overall)
            gathered = [task.result() for task in done]
    finally:
        # Also runs when the caller is cancelled, so no fetch outlives its call.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    per_source = {name: [] for name in names}
    latency = {name: 0.0 for name in names}
    reasons = {name: f"cancelled by the {overall:.1f}s overall deadline" for name in names}
    routes = {name: "" for name in names}
    for name, results, elapsed, reason, route in gathered:
        per_source[name] = results
        latency[name] = round(elapsed, 1)
        reasons[name] = reason
        routes[name] = route

    degraded = [name for name in names if not per_source[name]]
    return per_source, latency, degraded, {n: reasons[n] for n in degraded}, routes


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
