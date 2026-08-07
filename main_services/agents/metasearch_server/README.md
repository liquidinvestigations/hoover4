# Metasearch MCP server

**The** web search server. Port `21931`, container `hoover4-mcp-metasearch`, wired into the
**full research agent** only.

One tool searches the open web. Before plan 2 phase 2 the agent carried three overlapping
ones — `web_search` here, `ddg_text_search`/`ddg_news_search` on `hoover4-mcp-ddg`, and
`wikipedia_search` on `hoover4-mcp-wikipedia`. A small model faced with three near-identical
descriptions picks badly and inconsistently. Those two servers are retired and their sources
live here.

Modelled on [`MikeLuu99/metasearch-rust`](https://github.com/MikeLuu99/metasearch-rust) —
the design worth taking is: query several sources in parallel, deduplicate on a normalised
URL, and merge with RRF so agreement between sources beats any one source's confidence.

## Tools

| Tool | Returns |
|---|---|
| `web_search(query, sources=None, max_results=15, timelimit=None)` | the fused, reranked, floored result list plus the timing table and a `search_detail` artifact id |
| `list_search_sources()` | every source with its kind, and which are configured |

`timelimit` is `d`/`w`/`m`/`y` and only affects `ddg_news` and `ddg_api` — the HTML
endpoints take no time filter. A bad value is **refused**, not ignored: a model that thinks
it filtered to the last day and did not will present stale results as fresh.

## Sources

| name | kind | what it is |
|---|---|---|
| `ddg`, `brave`, `startpage`, `yahoo` | `web` | the HTML scrapers in `engines.py` |
| `ddg_api` | `web` | the `ddgs` library's `text()`, inherited from `hoover4-mcp-ddg` |
| `ddg_news` | `news` | the `ddgs` library's `news()`, same origin |
| `wikipedia` | `reference` | MediaWiki `list=search`, inherited from `hoover4-mcp-wikipedia` |

`ddg_api` is kept **alongside** the `ddg` HTML scraper rather than replacing it. They rot
independently — a selector change breaks one, a library bump breaks the other — and the
whole point of the `degraded` list is that rot is visible rather than silent.

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
already-truncated set — so a kind's genuinely best result could be cut before it was ever
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
and must stay visible on every call. A read timeout is likewise not a breaker failure — the
host answered, it was just slow, and skipping it for a minute would hide a model that needs
replacing.

## What the model gets, and what it does not

Per result: `title`, `url`, `display_url`, `snippet`, `sources[]`, `kind`, `rrf_rank`,
`rrf_score`, `rerank_rank`, `rerank_score`, `published`. Top level: `sources_used`,
`degraded`, `unknown_sources`, `total_before_dedupe`, `total_after_dedupe`,
`rerank_applied`, `rerank_ms`, per-source `source_latency_ms` and `source_counts`.

**The pre-rerank ordering of every candidate is not sent to the model.** It is search
bookkeeping, not evidence, and it would roughly double the tool's token cost. It goes to a
**`search_detail` chat artifact** instead — both orderings in full, with each source's own
rank per URL — and the tool result carries only that artifact's UUID. The card's popup
fetches it lazily. See `../README.md` for how artifacts are stored and served.

Measured on the live server (`danube water level drought 2026`):

```
sources_used: ['ddg','brave','startpage','yahoo','ddg_api','ddg_news','wikipedia']
degraded:     ['brave','startpage']
74 results in, 48 after dedupe, reranked in 256 ms, 30 returned
rerank moved RRF #26 to #1
detail artifact: 48 before_rerank rows / 30 after_rerank rows, 49 kB
```

## Expect a scraper to rot

Every HTML source is **CSS selectors and no API key**. That is what makes it free and what
makes it fragile: assume at least one selector breaks within months. In the run above, Brave
and Startpage had already stopped matching — the search still worked, and said so. Two
things keep that visible:

* **The `degraded` field** on every response names the sources that returned nothing. Never
  swallow a zero-result source.
* **`METASEARCH_SOURCES`** turns a broken one off without a rebuild. Unknown names are
  dropped with a warning rather than raising, because a typo must not take the server down —
  and the same rule applies to the model's own `sources` argument.

If a scraper is degraded, the fix is in `engines.py`: one `_parse_<engine>` function, a
handful of CSS selectors. `tests/test_engines.py` has a captured fragment per engine so a
selector edit fails a test rather than production.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `METASEARCH_SOURCES` | all seven | the set to query; `METASEARCH_ENGINES` is still honoured for the four scrapers |
| `METASEARCH_SOURCE_TIMEOUT` | `8` | per source, seconds; a slow source degrades rather than delays |
| `METASEARCH_OVERALL_TIMEOUT` | `20` | whole fan-out deadline |
| `METASEARCH_PER_SOURCE_RESULTS` | `15` | asked of each source; larger than `max_results` so fusion and reranking have candidates |
| `METASEARCH_RRF_K` | `60` | the RRF constant; larger flattens rank differences |
| `METASEARCH_MIN_PER_KIND` / `_MAX_PER_KIND` | `10` / `20` | the floor and ceiling per kind |
| `METASEARCH_RERANK_CANDIDATES` | `60` | how many fused candidates reach the cross-encoder |
| `MAX_RESULTS` | `15` | default result count |
| `SEARCH_SNIPPET_CHARS` | `400` | snippets land in the agent's context, so they are capped |
| `RERANK_URL` | rendered | empty means no reranking — search still works, in RRF order |
| `RERANK_TIMEOUT_SECONDS` | `25` | hard cap; a timeout is an error, not a silent skip |
| `CHAT_ARTIFACTS_ENABLED` | `true` | off means search works and produces no detail artifact |

## Tests

```bash
docker exec hoover4-mcp-metasearch python -m pytest tests/ -q   # 51 tests
```

They cover URL normalisation, both dedupes, the RRF merge, the per-kind floor, the rerank
fallback, the payload/artifact split, source selection, and the per-engine parsers against
captured HTML. They deliberately do **not** hit the live web: a suite that fails whenever an
engine changes its markup would be noise, and that event is what `degraded` reports at
runtime.
