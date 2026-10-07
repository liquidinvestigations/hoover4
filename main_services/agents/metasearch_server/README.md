# Metasearch MCP server

The server exposes one web search tool when internet tools are enabled.
It searches several sources, deduplicates URLs, and orders results with reciprocal rank fusion.
Each result kind reserves a configured share of the selected results.
Web search never calls a model reranker.

## Tools

`web_search` accepts `queries`, optional `sources`, `max_results`, and `timelimit`.
The legacy `query` argument adds one query to the batch.
The server removes repeated queries and names queries beyond the configured limit.
The time filter accepts `d`, `w`, `m`, or `y` for supported news and DuckDuckGo sources.

`list_search_sources` lists registered sources, their kinds, and their configured state.
A fact-check source requires a mounted key file before registration.

## Sources and transports

| Sources | Kind | Transport |
|---|---|---|
| DuckDuckGo HTML, Brave | `web` | wreq with browser emulation. |
| Yahoo, Bing | `web` | curl_cffi with source-specific browser emulation. |
| Google | `web` | A dedicated browser fetch queue. |
| Mojeek, Startpage | `web` | curl_cffi with bounded proof-of-work challenge handling. |
| DuckDuckGo Lite | `web` | wreq with browser emulation. |
| DuckDuckGo News | `news` | curl_cffi with a shared circuit for its token and result requests. |
| GDELT | `news` | HTTP API requests with separate pacing. |
| Wikipedia, Wikidata, Crossref | `reference` | HTTP API requests. |
| Fact-check publishers | `reference` | HTTP API requests when a key file is available. |
| Wayback Machine, archive.today | `archive` | HTTP API or HTML requests for a URL named in the query. |

Google tracking links resolve to their destination URLs before fusion.
Bing requests use cached engine cookies.
Mojeek and Startpage share one bounded challenge task for concurrent requests.
Challenge complexity, solve duration, worker count, and failure cooldown limit CPU use.
The server does not solve image or behavior challenges.

Direct routes run independently of configured Tor fallback routes.
A request tries at most three routes within its source deadline.
Blocked route and host pairs enter cooldown.
Each Tor attempt uses isolated SOCKS authentication unless a multi-request source needs one circuit.
Empty Tor configuration disables fallback.

## Capacity and deadlines

The admission gate bounds running searches and queued searches.
A full queue returns a busy error.
A waiting call has a separate deadline.
Cancellation releases its queue entry or running slot.

Sources run in parallel within each query.
Query angles run sequentially within one complete fetch budget.
Queries that cannot start before that budget expires appear in `skipped_queries`.
A source that finishes before the fan-out deadline retains its results.
The server cancels and drains unfinished source tasks before returning.

## Results and artifacts

The model receives selected titles, destination URLs, snippets, kinds, and query indexes.
Each failed source has a bounded diagnostic reason.
An empty result includes the available failure causes.
A result note requests page reads before another search and requires verification of requested constraints.

The artifact writer preserves caller identity and conversation ownership.
The search-detail artifact keeps complete candidates, selected results, source routes, counts, and timing.
The result retains the reserved `_hoover4_artifacts` marker.

Legacy rerank fields remain for stored transcripts and renderers.
`rerank_rank` and `rerank_score` are empty.
`rerank_applied` is false, `rerank_ms` is zero, and `rerank_error` is empty.
`before_rerank` contains fused candidates and `after_rerank` contains selected fused results.
The source result limit bounds fusion input without excluding minority kinds before their reservation.

## Configuration

Deployment generates configuration from `hoover4.ini`.
The service also reads these environment variables.

| Variable | Default | Behavior |
|---|---|---|
| `METASEARCH_SOURCES` | All registered sources. | Select the default source set. |
| `METASEARCH_MAX_QUERIES` | `5` | Bound query angles in one call. |
| `METASEARCH_MAX_CONCURRENT` | `4` | Bound running searches. |
| `METASEARCH_MAX_WAITING` | `16` | Bound queued searches. |
| `METASEARCH_QUEUE_WAIT_SECONDS` | `60` | Bound admission wait time. |
| `METASEARCH_FETCH_BUDGET` | `60` | Bound fetching across all query angles. |
| `METASEARCH_SOURCE_TIMEOUT` | `8` | Bound one source's fetch time. |
| `METASEARCH_OVERALL_TIMEOUT` | `20` | Bound one query's source fan-out. |
| `METASEARCH_ATTEMPT_TIMEOUT` | `6` | Bound an attempt when another route remains. |
| `METASEARCH_TOR_ROUTES` | Empty. | Configure named SOCKS routes. |
| `BROWSER_FETCH_URL` | Empty. | Configure the internal browser fetch route. |
| `METASEARCH_COOLDOWN_SECONDS` | `600` | Delay a blocked route for the same host. |
| `METASEARCH_SOLVE_TIMEOUT` | `30` | Bound a proof-of-work solve. |
| `METASEARCH_SOLVE_BACKOFF` | `300` | Delay a new solve after failure. |
| `METASEARCH_PER_SOURCE_RESULTS` | `15` | Bound results from each source. |
| `METASEARCH_MIN_PER_KIND` / `_MAX_PER_KIND` | `3` / `15` | Reserve and limit each result kind. |
| `MAX_RESULTS` | `15` | Set the default selected result count. |
| `SEARCH_SNIPPET_CHARS` | `400` | Bound each model snippet. |
| `METASEARCH_DIAGNOSTICS` | Disabled. | Include ranking and source timing in evaluation responses. |
| `CHAT_ARTIFACTS_ENABLED` | `true` | Store search-detail artifacts. |

The health response includes admission counts, route cooldowns, browser fetch state, and configured Tor connection state.
A failed browser or Tor probe reports degraded status.
The response reports web reranking as disabled.

## Verification

Run the source and shared tests in the service container.

```bash
docker exec hoover4-mcp-metasearch python -m pytest tests/ -q
```

Captured source responses verify parsers and destination URL handling.
Mock transports verify deadlines, cancellation, fallback, cooldowns, challenge limits, and failure reporting.
Live source access and answer accuracy require separate verification.
