# Hoover4 Website

The website is a full-stack Dioxus application that provides search and document viewing capabilities over the Hoover4 data plane. It is split into three Rust crates.

## Components

- `frontend/` - Dioxus UI compiled to WASM, with routed pages for search, document view, file browser, and chatbot.
- `backend/` - Server APIs for search queries, document retrieval, and dataset listing.
- `common/` - Shared types and constants used by both frontend and backend.

## Runtime Dependencies

The backend expects:

- ClickHouse (`CLICKHOUSE_URL`) for structured data.
- Manticore (`MANTICORE_URL`) for text search.

## Technical Details

The workspace contains three Rust crates: `backend` exposes HTTP APIs for datasets and search, `frontend` is a Dioxus UI that renders pages and components, and `common` provides shared models and constants used by both.

Code is arranged by feature area: backend API modules under `backend/src/api`, database helpers under `backend/src/db_utils`, and frontend UI components under `frontend/src/components` with pages in `frontend/src/pages`.

### ClickHouse database routing

ClickHouse is split into the global database `Hoover4_Processing` (users, groups,
collections, the dataset registry, sessions, settings, search cache) and one database
per collection, `Hoover4_Collection_<collectionname>` (blobs, VFS, parsed content, plans,
errors, term dictionaries). The backend picks the database per query in
`backend/src/db_utils/clickhouse_utils.rs`:

- `get_global_client()` for global tables;
- `get_collection_client(collectionname)` for per-collection tables;
- `get_client_for_dataset(collection_dataset)` resolves the owning collection via the
  global `dataset` registry (cached in-process; the mapping is immutable) and returns a
  collection client. Every per-collection read resolves immediately after
  `permissions::assert_can_read`, so an unauthorised dataset never reaches a database
  name.

A dataset's collection is **fixed when the dataset is created** and cannot be changed —
there is no assign/unassign/move in the admin UI; creating a collection provisions its
database, deleting one (only allowed when it has no datasets) drops it.

### Search fan-out

Manticore holds no global search tables. Each collection's search data lives in a
dynamic number of shard table pairs, `<collectionname>_<n>_pages` /
`<collectionname>_<n>_meta` (capped at ~1 GB of text per shard by the indexing
planner). Distributed tables are deliberately not used: Manticore 14.1.0 cannot run
this site's JOIN/stored-field/FACET query shape over them (see
`plans/2-collections/2-spike-manticore-results.md`).

Every search — result list, hit count, string facets, MVA facets — is therefore built
once **per shard** (`backend/src/api/search/search_sql.rs`) and fanned out with at most
`MAX_PARALLEL_INDEX_QUERIES = 8` requests in flight
(`backend/src/api/search/fanout.rs`, override with `HOOVER4_SEARCH_MAX_PARALLELISM`,
clamped to 1..=64). Selecting datasets in the `collection_dataset` facet prunes whole
collections from the fan-out. One failing shard degrades the response to partial (the
UI shows a "some collections could not be searched" notice); an error is returned only
when every shard fails.

What is exact, and what is approximate:

- **Exact:** per-shard results and per-shard counts; pagination stability (hits are
  merged by score with a deterministic `(collection_dataset, file_hash)` tie-break).
- **Approximate:** cross-shard/cross-collection **ranking** (BM25 statistics are
  per-table; there is no global IDF — accepted, deliberately not "fixed" with a
  normalisation hack); cross-shard **facet counts** (each shard only returns its top
  buckets, over-fetched to `21 × n_shards`, capped at 200, before the merge sums
  them); the **total hit count** (a sum of per-shard `count(distinct file_hash)`,
  which is an upper bound because the same file can exist in two collections).

Search responses are cached per sub-query in the global `search_manticore_cache`
table; the cache key includes the collection's shard-ledger generation
(`max(updated_at)` of its `manticore_shards` table, cached in-process for 30 s), so a
newly opened shard invalidates that collection's cached searches without touching the
others.

Usage:
- Build the frontend crate with `cargo serve ---package frontend`, and follow `frontend/README.md` for Dioxus-specific dev commands.

## AI Chat

Routes (see `frontend/src/routes.rs`):

- `/ai_chat` — homepage ("What are you researching?") with recent-session cards and composer
- `/ai_chat/history` — full conversation list
- `/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state` — transcript + document preview (60/40)

Storage lives in the global ClickHouse database (`chat_sessions`, `chat_messages`).
Migration `00014` adds `tool_input` / `tool_output` / `doc_refs` / `created_ms` /
`agent_duration_ms`; `00015` adds `chat_sessions.summary`.

### Q8 — Guests and LLM access (**revisit**)

Guests may chat when `HOOVER4_DEMO_MODE=true`, keyed by their `guest-*` username, with
the same persistence as any other user. A demo visitor driving a local GPU is a
**resource** question, not a permission question — the chat rate limiter
(`backend::rate_limit::check_and_record`, implemented by Plan 2) is the mitigation for
now. **Revisit whether guests should have LLM access at all.**

### Q6 — `chat_messages.seq` race

`seq` is assigned by reading `max(seq)+1`. ClickHouse has no sequences or row locks, so
two messages sent from two tabs in the same instant can collide and the
`ReplacingMergeTree` keeps one. Accepted. A real fix needs a per-session lock (Redis is
already in the stack) or a client-supplied monotonic id.

### Tool-event payload shapes

```
start  {"input": {}}
start  {"input": {"query": "…", "collections": ["…"]}}
end    {"output": {"content": …, "type": "tool", "name": "…", "tool_call_id": "…"}, …}
```

`search_collections` hits carry `collection_dataset` + `file_hash` (the
`DocumentIdentifier` key used by the document-preview stack).

## Development Notes

For local development, bring up `main_services` and `ai_services` first. Configure the service URLs in `.env.development` using `.env.development.example` as a template.

## Navigation

-  [Go Back](../Readme.md)

  - [frontend/README.md](frontend/README.md)
  - [frontend/src/components/chat_components/README.md](frontend/src/components/chat_components/README.md)