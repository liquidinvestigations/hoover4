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

Storage lives in the global ClickHouse database: `chat_sessions` (migration `00011`) and
`chat_messages` (`00012`), plus `chat_message_stream` (`00018`) for in-flight output. The
tool payload columns (`tool_input` / `tool_output` / `doc_refs` / `created_ms` /
`agent_duration_ms`), `retry_errors`, the per-message `model`, the session `summary` and
the frozen option flags were separate `ALTER` migrations until Part 2 Phase 0 folded them
back into the two `CREATE TABLE`s — do not look for them in their own files.

### The two switches are frozen at the first turn

`Deep Research` and `Internet tools` decide **which agent answers**, and therefore which
tools exist. Changing them mid-thread would produce a transcript where some answers had
web access and some did not, with nothing on screen saying which was which. So the first
message writes them to `chat_sessions` (`use_internet_tools`, `deep_research`,
`options_locked`) and the UI moves them out of the composer to a read-only bar above the
transcript.

The freeze is enforced **server-side** in `db_chat::lock_session_options`, not just by
hiding the checkboxes: later turns reuse the stored values whatever the client sends.

`Internet tools` defaults to **on** (`ChatOptions::default`). The chat is more useful with
them than without, and a user who wants a documents-only answer can untick before sending.

### Reaching the agents

Two services, and **both URLs must be set explicitly in compose**:

| Env | Service | Used when |
|---|---|---|
| `HOOVER4_AGENT_URL` | `hoover4-internal-search-agent` | Internet tools **off** |
| `HOOVER4_FULL_AGENT_URL` | `hoover4-full-research-agent` | Internet tools **on** |

The code defaults (`localhost:21936` / `localhost:21937`) are the loopback ports published
on the *host*, for running the website outside Docker. Inside the container `localhost` is
the container itself. `HOOVER4_FULL_AGENT_URL` being unset is what made every
internet-tools turn fail with `AI agent unreachable at http://localhost:21937` while the
agent itself was perfectly healthy — the same trap as `TEMPORAL_HTTP_URL`.

### Streaming a turn (Plan 2 Phase 1)

`send_message` no longer holds the request open for the whole agent run. It takes the
session's **turn lock**, writes the user row, registers the run and spawns the turn, then
returns the transcript *including* the message just sent. The turn consumes the agent's
`/chat/stream` SSE feed and mirrors it into `chat_message_stream`; the page follows it
with `chat_poll`.

The lock is `try_lock`: one turn at a time per session, and a second send is refused with
a message rather than blocking a request for the length of an agent run.

| Piece | Where |
|---|---|
| stream consumer | `api::chat::agent_client::ask_agent_stream_once` |
| fold into rows | `api::chat::handle_stream_event` + `TurnState` |
| stream table I/O | `db_chat::{append_stream_row, read_stream_rows, mark_stream_final}` |
| long-poll | `api::chat::poll_chat`, `RateLimitKind::ChatPoll` |
| Temporal twin | `main_services/processing/tasks/P_agent/stream_writer.py` |

Three rules that are easy to break and hard to notice:

- **`read_stream_rows` aggregates in a subquery.** `max(updated_at) AS updated_at`
  shadows the column, so sibling `argMax(…, updated_at)` calls become aggregates inside
  aggregates (`Code: 184`); but `clickhouse::Row` also matches columns **by name**, so
  the aliases cannot simply be renamed. Aggregate as `last_*` inside, rename outside.
- **Liveness comes from the transcript, not from an open stream row.** `ChatPollResult`
  carries `active`, computed from `db_chat::turn_boundaries` — a turn is open while the
  last user row has no assistant/error row after it. The writer finalises one row and
  opens the next as two separate inserts, and a poll landing in that gap used to report
  the turn as finished. Inline turns hid this behind their `live_runs` entry; Temporal
  research turns, which have none here, dropped the page out of its poll loop seconds in.
- **A turn always keeps exactly one non-final stream row open**, from before the agent
  call until finalisation. That is what the interrupted detector points at: a process
  killed with nothing open leaves a transcript that just stops, with no marker.

Poll cadence: holds up to 15 s when nothing changes, and every poll after the first takes
at least 500 ms — with content flowing each poll returns immediately, so without that
floor the client spins as fast as the network allows. Concurrently-held polls are capped
per user (`MAX_HELD_POLLS_PER_USER`).

Stop and interruption: the composer's stop button calls `live_runs::request_cancel_for`;
the turn notices within 200 ms and finalises whatever partial exists with an explicit
marker. A turn whose rows stop advancing for `CHAT_STREAM_STALL_SECONDS` (default 60)
with no live run behind it renders as **interrupted** with a Dismiss button — never a
spinner, and never promoted into `chat_messages`.

Deep research streams through the same table. `start_research_task` writes an empty
stream row when it accepts the task (the only thing that tells the poller a turn exists
before the worker picks the activity up) and the activity rewrites that seq, keepalive
included.

### Retries

Each turn gets `HOOVER4_AGENT_ATTEMPTS` attempts (default 4) with exponential backoff from
`HOOVER4_AGENT_RETRY_BASE_MS` (default 2 s, so 2/4/8 s). Retries cover *every* failure
class rather than a curated list — unreachable, 5xx, timeout, malformed body are one thing
from the user's seat, and this stack fails transiently in all four ways.

Failed attempts are kept in `chat_messages.retry_errors` even when the turn eventually
succeeds, and the transcript shows them behind a disclosure. A turn that only worked on
the third try is a healthy answer over an unhealthy agent tier, and that is worth seeing.

### Admin: live chats

`/admin/metrics` lists the agent runs this website process is holding open right now —
user, conversation, both switches, elapsed time, attempt number — with a **Kill** button.
The registry is in-process (`backend::api::chat::live_runs`), not in ClickHouse: a row
means "this process is doing this work now", and a persisted row would outlive the process
and show an admin ghosts to kill. Cancellation is cooperative — it lands between retry
attempts, and cannot abort a generation already in flight.

Deep-research turns run in a Temporal worker and are **not** listed there; the Temporal UI
owns that view.

### Q8 — Guests and LLM access (**revisit**)

Guests may chat when `HOOVER4_DEMO_MODE=true`, keyed by their `guest-*` username, with
the same persistence as any other user. A demo visitor driving a local GPU is a
**resource** question, not a permission question — the chat rate limiter
(`backend::api::rate_limit::check_and_record`, Plan 2) is the mitigation for
now. **Revisit whether guests should have LLM access at all.**

### `chat_messages.seq` race — closed

`seq` is still `max(seq)+1`, and three things stand behind it:

* **the session's `db_chat::turn_lock`**, held for the whole turn, which serialises
  allocation and stops a second turn reading a history the first has not finished writing.
  It is an in-process lock and it is released when the request handler returns;
* **`next_seq` counts `chat_message_stream` too**, not only `chat_messages`. Deep research
  allocates its answer seq up front and reserves it as a *stream* row — the transcript row
  appears minutes later, when the Temporal workflow finishes. The lock cannot cover that
  gap (it went with the handler), so a `next_seq` reading only `chat_messages` handed the
  reserved seq to the next inline send and ReplacingMergeTree silently kept one of the two
  messages. Both entry points also refuse outright while `stream_state(...).active` — the
  same question the poller asks;
* **`message_uuid`** (migration `00021`), shared by every row of a turn and now actually
  *read*: `db_chat::detect_seq_collision` looks for a second uuid at the seq just claimed
  and refuses the turn if it finds one, so the user resends instead of losing a message. It
  reads without `FINAL` on purpose — `FINAL` collapses away the evidence. A write-only
  detector, which is what this was, is worse than none: it reads as covered.

### Tool-event payload shapes

```
start  {"input": {}, "name": "list_collections"}
start  {"input": {"query": "…", "collections": ["…"]}, "name": "search_collections"}
end    {"output": {"content": …, "type": "tool", "name": "…", "tool_call_id": "…"}, …}
```

`name` on the **start** event is added by the agent (`research_agent/agent.py`);
LangGraph's raw `on_tool_start` data carries only `input`, and the tool's name first
appears under `output.name` on the end event. Without it every card rendered while a call
was still running was labelled "tool".

`search_collections` hits carry `collection_dataset` + `file_hash` (the
`DocumentIdentifier` key used by the document-preview stack).

Note there is **no tool name on a start event** — it appears only at `output.name` on the
end event, which is why the events have to be paired before a call can be labelled at all.

This format is parsed in two places, and they must agree: `api::chat::agent_client` for
inline chat, and `tasks/P_agent/trajectory.py` for the Temporal research path. The Python
side was for a while writing `json.dumps(event)[:400]` as the message body with the tool
name hardcoded to `"tool"` and none of the payload columns populated, so research
transcripts rendered as a wall of JSON in a card whose expand panel opened onto nothing.
If you change the shape, change both.

## Development Notes

For local development, bring up `main_services` and `ai_services` first. Configure the service URLs in `.env.development` using `.env.development.example` as a template.

## Navigation

-  [Go Back](../Readme.md)

  - [frontend/README.md](frontend/README.md)
  - [frontend/src/components/chat_components/README.md](frontend/src/components/chat_components/README.md)