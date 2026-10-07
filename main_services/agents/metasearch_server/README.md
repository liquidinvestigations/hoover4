# Metasearch MCP server

The metasearch server provides web search tools for chat with internet tools enabled.
Its HTML readers use the selectolax Lexbor parser.

One tool searches the open web, and there must never be a second. A small model faced with
several near-identical "search the web" descriptions picks badly and inconsistently, so
every source (the scrapers, DuckDuckGo text and news, world news, the encyclopaedias, DOI
metadata and the archives) is a `sources` entry here rather than a tool of its own.

Modelled on [`MikeLuu99/metasearch-rust`](https://github.com/MikeLuu99/metasearch-rust).
The design worth taking is: query several sources in parallel, deduplicate on a normalised
URL, and merge with RRF so agreement between sources beats any one source's confidence.

## Tools

| Tool | Returns |
|---|---|
| `web_search(queries=[…], sources=None, max_results=15, timelimit=None)` | titles, URLs, snippets, dates and result kinds, plus a `search_detail` artifact id |
| `list_search_sources()` | every source with its kind, and which are configured |

The result names sources with no results in `no_results_from`.
The server stores search detail separately and gives its artifact id in `_hoover4_artifacts`.

`timelimit` is `d`/`w`/`m`/`y` and only affects `ddg_news`, `ddg_api` and `gdelt`. The HTML
endpoints take no time filter and the reference sources have no publication date. A bad
value is **refused**, not ignored: a model that assumes it filtered to the last day and did
not will present stale results as fresh.

### One call, several angles

`queries` accepts several query angles. Each query searches the selected sources.
Reciprocal rank fusion merges their rankings and deduplicates their URLs.
Each result names the queries that found it in `matched_queries`.
The legacy `query` argument adds one query to that list.

## Sources

| name | kind | key | what it is |
|---|---|---|---|
| `ddg`, `brave`, `yahoo` | `web` | none | the HTML scrapers in `engines.py` |
| `ddg_api` | `web` | none | the `ddgs` library's `text()`, inherited from `hoover4-mcp-ddg` |
| `ddg_news` | `news` | none | the `ddgs` library's `news()`, same origin |
| `gdelt` | `news` | none | GDELT DOC 2.0, world news across languages and back years |
| `wikipedia` | `reference` | none | MediaWiki `list=search`, inherited from `hoover4-mcp-wikipedia` |
| `wikidata` | `reference` | none | structured entities: a company, a person, an identifier, by Q-number |
| `crossref` | `reference` | none | DOI metadata, resolving to `doi.org` |
| `factcheck` | `reference` | free key | published fact-checks; **absent unless a key file is mounted** |
| `wayback` | `archive` | none | Wayback Machine snapshots of a host named in the query |
| `archive_today` | `archive` | none | the second archive; no API, so the flakiest source here |

**A key-gated source with no key is not registered at all**. Absent from
`list_search_sources`, from the default set and from dispatch, rather than present and
failing. Telling a model about a capability the deployment does not have costs a round trip
to discover that. The key is a path to a chmod-600 file outside the repository,
bind-mounted read-only, and is never a value in a file, a default or a log.

**The archives answer about a URL, not about a phrase.** Neither has a full-text index, so a
query naming no host is a question they cannot be asked and they say so in
`degraded_reasons` rather than returning nothing. `archive_today` has no API at all: it
parses the HTML of a page behind a bot wall, and it is expected to be the first name on the
`degraded` list. That is what it is here for. A second archive that answers sometimes beats
no second archive, as long as its failure is visible.

**`wikidata` searches twice on a miss.** `wbsearchentities` matches an item's label by
prefix, so it is exact for `Enron` and returns nothing at all for `Arthur Andersen
accounting firm`, which is the shape of query a model actually sends. The full-text
`list=search` answers those, and one `wbgetentities` call turns its Q-numbers into labels.

**`gdelt` carries its own deadline.** It takes ten to twelve seconds to answer at all,
including when it answers `429`, so the common eight-second deadline turned every call into
a timeout. It also rate-limits per address, so a batch of queries will degrade it partway
through.

`ddg_api` is kept **alongside** the `ddg` HTML scraper rather than replacing it. They rot
independently (a selector change breaks one, a library bump breaks the other), and the
whole point of the `degraded` list is that rot is visible rather than silent.

**`startpage` was removed, not disabled.** It serves a Gatsby single-page app with a
`<noscript>` wall and a captcha field: there are no results in the HTML for any query, on
the first request from a cold container. There is no selector to repair, so there is no run
in which it can come back, and a permanently-degraded source inflates the source count the
tool advertises. Reporting rot is not the same as tolerating it.

`kind` is not decoration: it drives the per-kind floor below.

Wikipedia is called through the MediaWiki API directly rather than through the `wikipedia`
package the retired server used. That package is synchronous, fetches each article's full
HTML to produce a summary, and pins an ancient `requests`/`BeautifulSoup` pair; one
`list=search` call with `srprop=snippet` gives titles, snippets and canonical URLs in a
single round trip.

## Result ordering

The server fetches sources, deduplicates their URLs, merges rankings, and applies source-kind limits.
Reciprocal rank fusion uses source positions. Web search does not call a model reranker.

Each source first removes duplicate URLs from its own results.
Fusion then combines results with the same normalized URL across sources and query angles.
Each kind reserves its best `METASEARCH_MIN_PER_KIND` results in fused order.
The server fills remaining slots up to the total limit and the per-kind maximum.
Reserved slots can exceed a requested limit smaller than their combined count.

## Tool results and artifacts

Tool results contain selected titles, URLs, snippets, source names, query matches, and fused positions.
The search-detail artifact keeps complete candidates, selected results, and source timing.
The model receives the artifact identifier.

Legacy `rerank_rank` and `rerank_score` fields remain empty.
`rerank_applied` is false, `rerank_ms` is zero, and `rerank_error` is empty.
The artifact retains `before_rerank` and `after_rerank` for renderer compatibility.
These arrays now contain all fused candidates and selected fused results.
The health response reports reranking as disabled even when corpus reranking is configured.

## Expect a scraper to rot

Every HTML source is **CSS selectors and no API key**. That is what makes it free and what
makes it fragile: assume at least one selector breaks within months. In the run above, Brave
had already stopped matching. The search still worked, and said so. Two things keep that
visible:

* **The `degraded` field** on every response names the sources that returned nothing for
  **every** query in the call, and `degraded_reasons` says why each one did. One empty
  query out of five is a query with no results, not a broken source; counting it as one
  would degrade every source on any batch carrying a narrow angle. Those are different questions: "brave returned
  nothing" reads identically for a rotted selector, an `HTTP 429` and an unreachable host,
  and the three want three different fixes. Never swallow a zero-result source.
* **`METASEARCH_SOURCES`** turns a broken one off without a rebuild. Unknown names are
  dropped with a warning rather than raising, because a typo must not take the server down,
  and the same rule applies to the model's own `sources` argument.

If a scraper is degraded, the fix is in `engines.py`: one `_parse_<engine>` function, a
handful of CSS selectors. `tests/test_engines.py` has a captured fragment per engine so a
selector edit fails a test rather than production.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `METASEARCH_SOURCES` | every registered source | the set to query; empty means the default, not "none". `METASEARCH_ENGINES` is still honoured for the scrapers |
| `METASEARCH_MAX_QUERIES` | `5` | queries one call may fan out over; the surplus is named, not trimmed |
| `METASEARCH_SOURCE_TIMEOUT` | `8` | per source, seconds; a slow source degrades rather than delays |
| `METASEARCH_GDELT_TIMEOUT` | `15` | GDELT's own deadline; must stay under the overall one |
| `METASEARCH_OVERALL_TIMEOUT` | `20` | whole fan-out deadline |
| `FACTCHECK_API_KEY_FILE` | mounted path | a **path**, never a value; empty file means the fact-check source is not registered |
| `METASEARCH_PER_SOURCE_RESULTS` | `15` | This bounds results from each source before fusion. |
| `METASEARCH_RRF_K` | `60` | the RRF constant; larger flattens rank differences |
| `METASEARCH_MIN_PER_KIND` / `_MAX_PER_KIND` | `3` / `15` | the floor and ceiling per kind |
| `METASEARCH_FUSION_CANDIDATES` | `60` | This bounds fused candidates before source-kind limits. |
| `MAX_RESULTS` | `15` | default result count |
| `SEARCH_SNIPPET_CHARS` | `400` | snippets land in the agent's context, so they are capped |
| `CHAT_ARTIFACTS_ENABLED` | `true` | off means search works and produces no detail artifact |

## Tests

```bash
docker exec hoover4-mcp-metasearch python -m pytest tests/ -q
```

The tests verify URL normalization, deduplication, fusion, source-kind limits, and the payload/artifact split.
They verify that configured and disabled rerankers receive no web search calls.
Captured HTML verifies source parsers. Live source failures appear in `degraded` at runtime.
