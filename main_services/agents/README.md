# Hoover4 agents: MCP servers + research agents

The tool servers the research agents connect to, and the agents themselves. These live
in **main_services** (they moved out of `ai_services` in plan 1 part 1): they read
ClickHouse and Manticore directly and serve the website's chat, and the one-way
dependency rule — `ai_services` never calls into `main_services` — is what makes the
GPU tier optional.

Each MCP server is a standalone FastMCP server in its own container, published on
`127.0.0.1` and joined to the `hoover4` podman network. The agents discover tools over
HTTP at `/mcp`. All of them come up with the main stack via the always-on overlay
[`../ops/docker/compose/agents.yaml`](../ops/docker/compose/agents.yaml) — `./deploy`
from the repo root, no separate tier to start.

| Server | Directory | Port | Used by | What it does |
|---|---|---|---|---|
| Collection search | [`collection_search_server/`](collection_search_server/README.md) | 21930 | both agents | ACL-bounded full-text search of the user's own documents (Manticore + ClickHouse) |
| Metasearch | [`metasearch_server/`](metasearch_server/README.md) | 21931 | full research | **The** web search: four HTML scrapers + DuckDuckGo text/news + Wikipedia, fused with RRF and reranked by the GPU cross-encoder |
| Browser | [`browser_use_server/`](browser_use_server/README.md) | 21932 | full research | Playwright's whole browser surface, routed to one Chromium **per chat**, with automatic page capture |
| WHOIS | [`whois_search_server/`](whois_search_server/) | 21934 | full research | Domain registration lookup |

**`hoover4-mcp-ddg` and `hoover4-mcp-wikipedia` were retired in plan 2 phase 2.** Three
overlapping "search the web" tools is a choice a small model makes badly and
inconsistently; their sources now live in
[`metasearch_server/metasearch_server/sources.py`](metasearch_server/metasearch_server/sources.py)
as `ddg_api`, `ddg_news` and `wikipedia`, selectable through `web_search(sources=[…])`.
The two directories stay in git as history — nothing builds or deploys them, and their
port keys (`mcp_ddg_port`, `mcp_wikipedia_port`) are gone from `hoover4.ini`.

### Shared code: `agent_common/`

[`agent_common/`](agent_common/) holds what more than one server needs and neither should
own: the chat-artifact writer, the MinIO helper both artifact writers sit on, and the
rerank client with its circuit breaker.

**It is vendored, not installed from an index.** The metasearch and browser Dockerfiles
build with `main_services/agents` as their **build context** and `COPY ./agent_common/`.
If you move either Dockerfile, move its `context:` in
[`../ops/docker/compose/agents.yaml`](../ops/docker/compose/agents.yaml) with it — a
Docker build cannot reach outside its context, and the failure is a missing-module
traceback at container start, not at build time.

### Chat artifacts

A tool that produces something too big for the model's context but worth showing the
*user* writes a **chat artifact**: bytes to MinIO under
`derived/chat-artifacts/<session>/<id>/`, one index row in `Hoover4_Processing.chat_artifacts`.

* `web_search` writes a `search_detail` — every candidate in both orderings, with
  per-source ranks and the timing table. The tool result carries only the UUID.
* The browser router writes a `page_capture` after every action that can change the
  screen, **including when the call failed**: a 1280x720 WebP screenshot plus the page
  archived as self-contained HTML.

The model receives only the id, under a reserved `_hoover4_artifacts` key. **It is a
lookup key, never a capability** — the website resolves it to `session_id`/`username` and
enforces owner-or-admin before serving a byte (`/_chat_artifact/{id}/{asset}`), and the
card refuses any id that is not a UUID before it builds that URL.

That rule is **not currently demonstrable**: this stack runs `guest_permissions_mode = all`,
which makes every visitor an admin, so any guest cookie gets 200 on any artifact. The code
is right and was reviewed; the *test* is deferred until someone runs it with two real users.
Written down in
[`website/backend/src/api/admin/Readme.md`](../../website/backend/src/api/admin/Readme.md)
so it is a known gap rather than an assumption.

Because the structured key does not survive LangGraph, the browser router also appends a
`[hoover4:artifacts] {"artifacts": [...]}` line to the result text — **always**, even when
it captured nothing, and always as the last block. That position is what the card
authenticates the marker by: a browser tool's text is the fetched page, so a hostile page
that plants the marker in its own body would otherwise get attacker-chosen titles and URLs
rendered in the trusted "Archived page" chrome.

The payload used to be a bare array and the card still reads that form for rows already in
transcripts. It became an object to carry one more thing the card cannot work out for
itself: `"failed": true` when the sidecar reported `is_error`. Playwright says a call
failed in prose, and by the time the result reaches the website that prose is
indistinguishable from the page it was trying to fetch — so the card rendered "opened
http://clickhouse:8123" for a navigation that never happened. The flag is written only
when true.

The router also strips links into playwright-mcp's own output directory
(`- [Snapshot](.playwright-mcp/page-….yml)`) from every text block. Nothing downstream can
open that path: the model cannot read files and the website renders it as a broken link.

`P0_scan_disk` must never walk the `derived/` prefix: an artifact the ingest walker can
see is ingested, captured again, and produces another artifact, forever. `verify-stack.sh`
asserts that no `blobs` row references it. Retention is a daily Temporal singleton
(`sweep-chat-artifacts`, in `tasks/P_admin/artifact_sweeper.py`) that deletes the objects
**before** the rows, because a ClickHouse TTL cannot touch MinIO.

The two research agents share one image built from [`research_agent/`](research_agent/README.md):

| Agent | Port | Profile | Callers |
|---|---|---|---|
| `hoover4-internal-search-agent` | 21936 | `internal_search` | AI Chat with **Internet tools off** — the collection server only, because a chat about the user's own documents must not quietly turn into a web search |
| `hoover4-full-research-agent` | 21937 | `full_research` | AI Chat with **Internet tools on**, and the Temporal `ResearchTask` (`RESEARCH_AGENT_URL` on the worker) |

> The published ports are for host-side debugging. Anything running *inside* the
> `hoover4` network must address these by container name —
> `http://hoover4-full-research-agent:8000`, not `http://localhost:21937`. The website
> needs **both** `HOOVER4_AGENT_URL` and `HOOVER4_FULL_AGENT_URL` set (the compose file
> does this); leaving the second unset is what made every internet-tools chat turn fail
> with "AI agent unreachable at http://localhost:21937" while the agent was healthy the
> whole time.

## How access control works

An agent answering for a user must only reach collections that user could read in the
search UI. The chain is:

1. The **website backend** resolves the user's permitted collections (group grants union
   public collections). It is the only component that can — it owns the auth tables.
2. It passes that list to the agent as `allowed_collections`.
3. The agent opens its MCP connections with `X-Hoover4-Collections: <list>` and
   `Authorization: Bearer <MCP_SHARED_SECRET>`, and caches one graph **per ACL** so a
   connection is never reused across users.
4. `hoover4-mcp-collections` enforces the header on every tool call. A request for a
   collection outside it is an error, not a silently-narrowed filter.

The model never sees or supplies its own permissions. The shared secret is a
bind-mounted file, never an env value: `[main_services] mcp_shared_secret_file` in
`hoover4.ini` names the host path, `deploy.py` mounts it at
`/run/secrets/mcp_shared_secret`, and both sides read it via their
`MCP_SHARED_SECRET_FILE` fallback. Without it the collection server accepts any caller
and logs a warning (the ports are bound to 127.0.0.1, which is the only reason that is
survivable locally).

A third header, `X-Hoover4-Chat-Session`, travels alongside those two but grants no
authority — it is an **isolation key**, used only by the browser server to give each
conversation its own Chromium context. Do not make anything an access decision on it: it
is a conversation id, and unlike the ACL headers nothing verifies who it belongs to.

## Where the system prompts live

Not in compose. A multi-paragraph prompt inlined as a YAML default was unreadable and
drifted from the tool descriptions it was supposed to agree with. There are two files:

* [`collection_search_server/collection_search_server/prompts.py`](collection_search_server/collection_search_server/prompts.py)
  — the MATCH syntax reference and search strategy. Reaches the model as the MCP server's
  FastMCP `instructions`, i.e. at tool-discovery time, for **whichever** agent connects,
  and is appended to the error text when a query is rejected.
* [`research_agent/research_agent/prompts.py`](research_agent/research_agent/prompts.py)
  — one system prompt per agent profile, selected by `AGENT_PROFILE`.

`SYSTEM_PROMPT` / `SERVER_INSTRUCTIONS` remain as thin env overrides for experiments;
empty means "use the canonical text".

**Keep the agent prompts short.** Qwen3.5-2B follows a long numbered prompt by doing all
of it forever — an earlier five-step draft made it search, search again, then re-run a
query it had already run until the request died. Detail belongs in tool descriptions,
which the model reads in context at the moment it picks a tool. Re-measure before
lengthening.

## Why search goes through Manticore, and where Milvus went

The ingestion pipeline writes extracted text to ClickHouse and search documents to
Manticore shards. It **never wrote vectors**, so the whole Milvus tier — three containers
(`milvus-standalone`, `milvus-etcd`, `milvus-minio`) holding ~39 GB of memory limit, an
MCP server that would have searched an empty index, a `pymilvus` dependency in three
packages, and the legacy `hoover4_rag` ingestion CLI — has been removed (Q1/Q3).

The `text_chunks_milvus`, `entity_hits_milvus` and `entity_hits_milvus_unique` ClickHouse
tables are gone. They were created by two collection migrations and dropped again by a
third for as long as the tree carried its migration history; the Part 2 re-collapse
deleted all three files, and `test_no_migration_recreates_a_removed_table` in
`tests/unit/test_migrations_parity.py` now keeps them from coming back.

**Vector search is being rebuilt without Milvus.** The schema for it landed with the
re-collapse — `text_chunks` and `text_chunk_vectors` are collection tables now — and the
three pieces that make it work are:

1. A **chunk-and-embed stage (`P5_chunk_embed`)**: `text_content` split per page into
   chunks and embedded, with the vectors written durably to `text_chunk_vectors`.
2. The vector store is **Manticore's own KNN index** — a `_vectors` shard table per
   collection, HNSW, RAM-resident and disposable. ClickHouse is the store of record, so
   the index can be dropped and rebuilt at will (and must be, if the embedding model
   changes: `knn_dims` cannot be altered).
3. Hybrid retrieval in the collection MCP server: BM25 from Manticore and vectors from the
   same engine, merged with RRF and then reranked by the cross-encoder.

Steps 1–3 are Part 2 Phase 3. Until they land, the tables exist and are empty.

**The stopped Milvus containers and their podman volumes are deliberately left on this
host.** Reclaiming the disk is your call:

```bash
podman rm milvus-standalone milvus-etcd milvus-minio
podman volume rm milvus_etcd milvus_minio milvus_standalone
```

## Manticore `MATCH()` syntax

Verified against the live `testdata_1_pages` shard, not taken from documentation —
several documented spellings are a hard 500 on this deployment.

| Syntax | Result | Notes |
|---|---|---|
| `test document` | works | implicit AND |
| `test \| zzz` | works | OR |
| `test -zzz` | works | NOT, **only with a positive term** |
| `-zzz` alone | 500 | `query is non-computable (single NOT operator)` |
| `"test document"` | works | exact phrase |
| `"test document"~5` | works | proximity |
| `"one two three"/2` | works | quorum |
| `test NEAR/3 document` | works | |
| `test SENTENCE document`, `… PARAGRAPH …` | works | |
| `test MAYBE document` | works | |
| `@page_text test` | works | the only valid field |
| `@title test` | 500 | `no field 'title' found in schema` |
| `who paid @acme` | 500 | a bare `@word` in prose reads as a field operator |
| `test^3` | works | boost |
| `(test \| document) the` | works | grouping |
| `@page_text ^test` | works | field-start |
| `=test` | works | exact form |
| `"test` / `(test` | 500 | `syntax error, unexpected $end` |
| `""` (empty) | works, **matches every row** | dangerous default |
| `docum*`, `*ocument*` | **works now** | see below — was silently wrong |

Two facts worth keeping:

* **`page_text` is the only full-text field.** Everything else in the shard schema
  (`collection_dataset`, `file_hash`, `extracted_by`, `page_id`, `ner_*`) is an attribute
  and belongs in `WHERE`, not `MATCH()`.
* **Wildcards used to fail silently.** Without infix indexing the star was dropped during
  tokenisation and the query became an exact search for a truncated word — `doc*` returned
  **7** where `document` returned 16. Not zero. Wrong.

`sanitize_match_query` no longer strips operators. It passes them through and repairs only
the shapes that 500 (unbalanced quote or paren, NOT-only, bare `@word`, empty), reporting
what it repaired in the response's `note` and returning Manticore's own error text in
`error` so the model can correct itself. The escaping of `\` and `'` is unchanged and is
the injection barrier.

### Infix indexing: what it cost

`min_infix_len='3'` was added to both `pages_table_ddl` and `meta_table_ddl` in
`main_services/processing/database/manticore.py`, and both collections reindexed.
Behaviour on the real `testdata` shard (156 pages, 26 MB of text):

| query | before | after |
|---|---|---|
| `document` | 16 | 16 |
| `docum*` | 0 | 19 |
| `*ocument*` | 0 | 42 |
| `doc*` | **7 (wrong)** | 34 |
| `te*t` | **3 (wrong)** | 28 |
| `wat*` | 0 | 14 |

**The storage cost could not be measured reliably**, and that is worth stating plainly
rather than quoting a number that does not reproduce. `SHOW TABLE ... STATUS` `disk_bytes`
on an RT table depends on chunk-merge state: the same no-infix configuration measured
16.6 MB, 33.6 MB and 65.4 MB at different points in the same session. Under *identical*
treatment — pipeline reindex, then `FLUSH` + `OPTIMIZE` — the numbers were:

| configuration | disk_bytes | ram_bytes |
|---|---|---|
| no infix | 33,588,034 | 35,407,056 |
| `min_infix_len='3'` | 26,013,634 | 17,537,550 |

i.e. the infix build measured **smaller**, which is not a credible causal effect and is
better read as "the metric is noisy at this corpus size". A controlled probe (two tables,
same 156 pages inserted row by row, same flush/optimise) put the difference at **+0.8%**
on disk. Whatever the true figure, it is not a cost worth trading the wrong answers for.
`min_infix_len` 2, 3 and 4 are identical in size and behaviour in this Manticore version —
it is an on/off switch, not a threshold, so do not spend time tuning the number.

**`ALTER TABLE` does not reindex.** It updates metadata only: `SHOW TABLE ... SETTINGS`
will report the new value while queries keep returning the old, wrong answers. Changing
the setting means `main.py reindex-collection <name>`. And the worker is long-running, so
it must be **restarted** after a DDL change or it will keep creating tables from the
module it imported at startup.

## Two patterns in this directory

New servers follow **`collection_search_server`**: a plain `python:3.12-slim` image,
`pip install .`, a `@mcp.custom_route("/health")` endpoint and `mcp.run(transport="http")`.
It builds in seconds and has no build toolchain.

`whois_search_server` is older and uses a Poetry multi-stage build. It works; do not copy
it for anything new.

`ddg_search_server/` and `wikipedia_search_server/` are **gone**, not disabled. Their
sources live in `metasearch_server` as `ddg_api`, `ddg_news` and `wikipedia`; the
directories sat unbuilt and unreferenced for two phases, which is long enough for someone
to read one and believe it describes something that runs.

## Running and testing

Everything comes up with the main stack:

```bash
./deploy                                          # from the repo root
./deploy --build                                  # rebuild images
```

`deploy.py --build` force-recreates for exactly the reason older docs warned about: a
`--build` alone can leave the old container running against the new image.

Each MCP image carries its own tests:

```bash
docker exec hoover4-mcp-collections python -m pytest tests/ -q   # 60 tests
docker exec hoover4-mcp-metasearch  python -m pytest tests/ -q   # 71 tests
docker exec hoover4-mcp-browser     python -m pytest tests/ -q   # 119 tests
```

## Driving these tools from the host

[`.mcp.json`](../../.mcp.json) at the repo root exposes the stateless servers to any MCP
client on this machine (Claude Code reads it automatically):

| Entry | URL | Tools |
|---|---|---|
| `hoover4-web-search` | `http://127.0.0.1:21931/mcp` | `web_search`, `list_search_sources` |
| `hoover4-browser` | `http://127.0.0.1:21932/mcp` | the 30 Playwright tools |
| `hoover4-whois` | `http://127.0.0.1:21934/mcp` | `whois_lookup` |

The browser entry sends a fixed `x-hoover4-chat-session: host-mcp-client`, so a host client
gets a browser of its own rather than sharing the anonymous one. Artifacts it produces are
filed under that session id and are not reachable through the website (no chat owns them);
the sweeper's prefix scan collects them.

**`hoover4-mcp-collections` is deliberately absent.** Its every tool requires
`X-Hoover4-Collections` naming the caller's permitted collections, and only the website
backend can resolve that — an entry here would be a server whose tools always deny.
