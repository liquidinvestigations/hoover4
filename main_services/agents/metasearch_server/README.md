# Metasearch MCP server

**The** web search server. Port `21931`, container `hoover4-mcp-metasearch`, wired into the
**full research agent** only.

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
| `web_search(queries=[…], sources=None, max_results=15, timelimit=None)` | the fused, reranked, floored result list plus the timing table and a `search_detail` artifact id |
| `list_search_sources()` | every source with its kind, and which are configured |

`timelimit` is `d`/`w`/`m`/`y` and only affects `ddg_news`, `ddg_api` and `gdelt`. The HTML
endpoints take no time filter and the reference sources have no publication date. A bad
value is **refused**, not ignored: a model that thinks it filtered to the last day and did
not will present stale results as fresh.

### One call, several angles

`queries` is a list. Every query is run across every source, all of those rankings fuse into
**one** pool, and that pool is reranked **once**; each result carries `matched_queries`, the
queries that found it. `query` is still accepted and folds into `queries`, so a batch of one
is not a special case.

**Reranking per query and then merging the orderings is the wrong shape**, and it looks
correct from the outside. It ranks each query's results against each other rather than
against the question, so the best answer to the sharpest angle arrives interleaved with the
best answer to the vaguest one at the same rank.

`METASEARCH_MAX_QUERIES` caps the batch, and the surplus is **named** in `note` rather than
trimmed silently. `note` also reports de-duplicated repeats. A list arrives coerced through
`agent_common.batching.as_list`, so a bare string and a JSON-encoded list both work.

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

## The order of operations is not interchangeable

```
fan out  →  RRF fuse (which dedupes across sources)  →  rerank  →  per-kind floor
```

**Reranking after the floor reads identically and is wrong.** The floor would pick each
kind's arbitrary RRF-ordered results and the cross-encoder would then reorder that
already-truncated set, so a kind's genuinely best result could be cut before it was ever
scored. Rerank the whole candidate pool, then take the best per kind.

There are two dedupes and both are needed:

* **within a source, before fusion** (`dedupe_within_source`): a source that lists the same
  article at ranks 2, 5 and 9 would otherwise award that URL three RRF contributions and
  beat a page three independent sources agreed on;
* **across sources**, which is what the RRF merge itself does.

The **per-kind floor** exists because RRF is a popularity measure. Four web scrapers
agreeing on a page beats one encyclopaedia entry every time, so without a floor a query with
an obvious Wikipedia answer returns twenty blogs about it. Each kind keeps its own best
`METASEARCH_MIN_PER_KIND` results whatever the overall cap says, then the rest fills by
score up to `METASEARCH_MAX_PER_KIND` per kind. A page both Wikipedia and a scraper returned
keeps the *more specific* kind, or the floor could not see it.

**A floor guarantees representation, not relevance**, and representation of nothing is
padding. A floor of ten reference results on a query with one encyclopaedia answer filled
the rest with whatever Wikipedia ranked next (live, "Yanam district" and "Aasta Hansteen
spar" for an Eiffel Tower query), and the model cannot tell a reserved slot from an earned
one. So a result the cross-encoder scored below `METASEARCH_RESERVE_MIN_SCORE` cannot take a
reserved slot; it can still be filled in on merit. The threshold defaults to `0`, which is
the cross-encoder's own decision boundary (it returns a raw logit). A result with **no**
rerank score is always reservable: the GPU being down is not evidence against a result.

The floor is `3`, not `10`. The result policy is fifteen results, always reranked, and
a floor of ten across three kinds reserves thirty slots: `max_results` then means nothing,
because a reserved slot is never evicted.

## Reranking

`POST /v1/rerank` on the GPU tier (`RERANK_URL`, rendered by `deploy.py` from the same
setting as `EMBEDDINGS_URL`). Same shape as the OCR and NER clients: a **2 s connect
timeout** so a dead host is noticed in seconds, and a **circuit breaker** so it is noticed
once rather than once per search. Without the breaker every query pays a connect timeout
while the GPU box is down, and the point of reranking inverts.

A rerank failure is **reported, never hidden**: `rerank_applied` goes false, the RRF order
stands, `rerank_error` says why, and the card shows a "not reranked" pip. Killing the GPU
tier must degrade search quality, not remove search.

The breaker counts **connect** failures only. A model returning 500 is a different problem
and must stay visible on every call. A read timeout is likewise not a breaker failure. The
host answered and was slow, and skipping it for a minute would hide a model that needs
replacing.

## What the model gets, and what it does not

Per result: `title`, `url`, `display_url`, `snippet`, `sources[]`, `matched_queries[]`,
`kind`, `rrf_rank`, `rrf_score`, `rerank_rank`, `rerank_score`, `published`. Top level:
`query`, `queries`, `note`, `sources_used`,
`degraded`, `degraded_reasons`, `unknown_sources`, `total_before_dedupe`,
`total_after_dedupe`, `rerank_applied`, `rerank_ms`, per-source `source_latency_ms` and
`source_counts`.

A result the reranker did not score keeps its fused position rather than disappearing: a
partial rerank response must not silently shrink the search.

**The pre-rerank ordering of every candidate is not sent to the model.** It is search
bookkeeping, not evidence, and it would roughly double the tool's token cost. It goes to a
**`search_detail` chat artifact** instead, both orderings in full, with each source's own
rank per URL, and the tool result carries only that artifact's UUID. The card's popup
fetches it lazily. See `../README.md` for how artifacts are stored and served.

Measured on the live server (`danube water level drought 2026`):

```
sources_used: ['ddg','brave','yahoo','ddg_api','ddg_news','wikipedia']
degraded:     ['brave']
degraded_reasons: {'brave': 'HTTP 429'}
74 results in, 48 after dedupe, reranked in 256 ms, 15 returned
rerank moved RRF #26 to #1
detail artifact: 48 before_rerank rows / 15 after_rerank rows, 49 kB
```

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
| `METASEARCH_PER_SOURCE_RESULTS` | `15` | asked of each source; larger than `max_results` so fusion and reranking have candidates |
| `METASEARCH_RRF_K` | `60` | the RRF constant; larger flattens rank differences |
| `METASEARCH_MIN_PER_KIND` / `_MAX_PER_KIND` | `3` / `15` | the floor and ceiling per kind |
| `METASEARCH_RESERVE_MIN_SCORE` | `0` | rerank logit below which a result no longer earns a reserved floor slot |
| `METASEARCH_RERANK_CANDIDATES` | `60` | how many fused candidates reach the cross-encoder |
| `MAX_RESULTS` | `15` | default result count |
| `SEARCH_SNIPPET_CHARS` | `400` | snippets land in the agent's context, so they are capped |
| `RERANK_URL` | rendered | empty means no reranking, search still works, in RRF order |
| `RERANK_TIMEOUT_SECONDS` | `25` | hard cap; a timeout is an error, not a silent skip |
| `CHAT_ARTIFACTS_ENABLED` | `true` | off means search works and produces no detail artifact |

## Tests

```bash
docker exec hoover4-mcp-metasearch python -m pytest tests/ -q   # 71 tests
```

They cover URL normalisation, both dedupes, the RRF merge, the per-kind floor, the rerank
fallback, the payload/artifact split, source selection, and the per-engine parsers against
captured HTML. They deliberately do **not** hit the live web: a suite that fails whenever an
engine changes its markup would be noise, and that event is what `degraded` reports at
runtime.
