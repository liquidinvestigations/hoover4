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

### Every `MATCH()` argument goes through `db_utils/manticore_match.rs`

Manticore has no parameter binding over its HTTP SQL endpoint, so a `MATCH()` argument
crosses two language boundaries at once and each has its own rule. `format_sql_query::
QuotedData` gets both wrong for this database and **must never be used to build a
`MATCH()` argument**:

- It escapes `'` by SQL-standard **doubling**. Manticore's parser wants a backslash and
  rejects the doubled form outright — `MATCH('it''s')` is `P01: syntax error`, while
  `MATCH('it\'s')` returns hits. `escape_manticore_string` does the backslash pass first
  and the quote pass second; the other order double-escapes the backslashes the quote
  pass introduces.
- It does nothing about the text *inside* the literal, which is a query expression.
  A dangling `"`, an unbalanced `(`, a bare `/` or `~`, and a query made only of
  negations are each a parser error rather than an empty result — `3/4` and `say"hi` are
  ordinary things to type into a search box. `prepare_match_query` repairs the first
  three, passes the real operators (`"exact phrase"`, `-exclude`, `term*`, `a | b`,
  `NEAR/3`) through untouched, and returns a typed error for the two shapes with no
  searchable reading, so the message reaches the search bar instead of a 500 reaching
  the user.

A pure string assertion is how this last reached production: the unit test asserted the
doubled form, so it passed while every search containing an apostrophe failed. Tests for
this helper assert against the character set measured to break a live Manticore, and a
change here is not verified until the query has run against a real one.

Non-`MATCH()` uses of `QuotedData` — attribute comparisons against hashes, dataset ids
and facet values — carry the same wrong quoting rule and are not yet converted.

### Search fan-out

Manticore holds no global search tables. Each collection's search data lives in a
dynamic number of shard table pairs, `<collectionname>_<n>_pages` /
`<collectionname>_<n>_meta` (capped at ~1 GB of text per shard by the indexing
planner). Distributed tables are deliberately not used: Manticore 14.1.0 cannot run
this site's JOIN/stored-field/FACET query shape over them — measured, not assumed, and
it fails by returning NULL stored fields rather than by erroring.

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
the frozen option flags are all declared in those two `CREATE TABLE`s — the migration set
is collapsed, so do not look for them in `ALTER` files of their own.

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

### Streaming a turn

`send_message` does not hold the request open for the agent run. It takes the
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

**Rate limiting a poll loop is not rate limiting a person.** `RateLimitKind::ChatPoll` has
a *flat* window ladder — factor 1.0 everywhere, unlike chat messages and API calls, whose
budget decays the longer a burst lasts. That decay distinguishes a burst of human activity
from an hour of it; a streaming turn polls at the 500 ms floor for as long as the model
generates, so for this limiter "sustained" is simply "working". Under the decaying ladder
one tab sat exactly on the 1 h window's ceiling and two or three tripped it. The refusal is
also typed — `rate_limited:<secs>`, parsed with `chat_types::rate_limited_seconds` — so the
poll loop waits and retries instead of counting it toward `failures >= 3` and declaring
"lost contact with the chat" while the turn is still running. The parser searches for the
marker rather than stripping a prefix: `ServerFnError` may wrap the message.

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

### Guests and LLM access (**revisit**)

Guests may chat when `HOOVER4_DEMO_MODE=true`, keyed by their `guest-*` username, with
the same persistence as any other user. A demo visitor driving a local GPU is a
**resource** question, not a permission question — the chat rate limiter
(`backend::api::rate_limit::check_and_record`) is the mitigation for
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


## Filters, sorting and the folder tree

### Dates are HISTORICAL dates only

There is no upload date and no index date anywhere in the schema, by decision. Every date
the UI shows or filters on came from the document's own metadata, or from an archive that
stored it:

* Tika's `dcterms:created` / `dcterms:modified`, `xmp:CreateDate` / `xmp:ModifyDate`,
  `pdf:docinfo:created` / `pdf:docinfo:modified`, `exif:DateTimeOriginal`;
* an email `Date:` header that actually parsed (`email_headers.date_sent_known = 1`);
* the mtime of an **archive member** — 7z restores the timestamps the archive stored.

Deliberately NOT dates: Tika's `File Modified Date` (the mtime of the worker's temp file,
which would date the whole corpus "today"), and the mtime of a top-level disk file (the
clone or save time of the corpus, recorded in `vfs_files.mtime_source = 'filesystem'` and
never indexed).

A document has a SET of dates, not one, and `document_dates` keeps each with the key it
came from. The viewer's **Dates** section shows all of them with provenance — that is
where a user finds out why a date filter did or did not match.

**Archive-mtime limitation.** An archive member's mtime is only as good as the archive.
Many archives store the extraction machine's clock rather than the document's, and nothing
in the file distinguishes the two. Those dates are indexed because a wrong-ish date is
more useful than none for narrowing a corpus, and the viewer names the source so the user
can discount it.

**A date range is an interval-overlap test.** The filter compiles to
`date_min <= hi AND date_max >= lo`, not `ANY(dates) BETWEEN lo AND hi` — Manticore 14.1.0
cannot evaluate `ANY(mva)` across the pages⋈meta join in any spelling (see
`search_sql.rs::range_predicate`). A document whose dates STRADDLE the range with none
inside it therefore matches: created 2007, modified 2020, filtered 2013–2016. The error is
one-sided — a superset, never a subset — and the viewer explains each result.

**Three range shapes, one filter.** `RangeFilter`'s bounds are `Option`s and an absent one
compiles to an open end, so a low-pass (`before X`), a high-pass (`after X`) and a
band-pass (`between X and Y`) are the same predicate with different bounds. The Date pane
names all three rather than expecting a user to discover that an empty box means "no
bound". The open low end is `i64::MIN + 1` and not `i64::MIN`, which is what keeps
`DATE_UNKNOWN` documents out of a pure low-pass; `Unknown only` is the separate mode that
asks for them.

### The date histogram

Under the date selector, one bar per computed bin, over **the query without its own date
filter** — a facet that filtered itself would be one solid block inside the cutoffs and
zero outside. The bars the cutoffs cover are drawn in the accent, so the picture is
"what you selected against what is there".

`search_date_histogram` (`api/search/date_histogram.rs`) does it in two fan-outs:

1. **Measure the domain.** `min(date_min)` and `max(date_max)` over the filtered set, plus
   the undated count. The bounds come from `ORDER BY … LIMIT 1` in each direction rather
   than from `min()`/`max()`, which is not a shape this codebase has ever got an answer
   out of Manticore for. There is no histogram, date-bucket or date-truncate function to
   use instead, and `date_min` is a signed `bigint` rather than a `timestamp` precisely
   because the timestamp type is 32-bit unsigned and cannot hold a 1936 date.
2. **Count the bins.** One `INTERVAL(date_min, e0, e1, …)` + `GROUP BY` per shard — the
   same shape as the size facet, with up to thirty edges instead of three.

Bins are computed, not fixed: a per-year bucket is unreadable for a corpus spanning a week
and useless for one spanning four centuries. The width is chosen off a ladder of durations
people name (hour, day, week, month, quarter, year, decade…), stepped up until the total
fits `HISTOGRAM_MAX_BUCKETS`. **The active cutoffs are forced to be bin edges**, so the
three intervals a band-pass creates each get their own run of bins at a comparable width
and no bar is half-selected. `histogram_edges` is a pure function and is where the tests
live.

Clicking a bar means whatever the active mode means — in `Before` it moves the upper
cutoff, in `After` the lower one, otherwise it selects that bin. Each bar's `title` says
which, because the answer is not visible from the bar.

### Sorting

Four keys: `Relevance` (BM25 `weight()`, unavailable without a query string and resolved
to Date server-side if one is asked for anyway), `Date`, `File size`, `Name`.

`Date` sorts on a different column per direction: newest-first on `date_max`, oldest-first
on `date_min`, because a document spanning 1990..2020 belongs at a different place in each.
Undated documents carry `DATE_UNKNOWN` (`i64::MIN`) and sort last descending, first
ascending.

Sorting is cross-shard, so the per-shard `ORDER BY` and the merge comparator must agree
exactly — the sort column is SELECTed for that reason alone. `merge_hits_sorted` is tested
over every key in both directions for page disjointness.

### Filename search

One synthetic pages row per document (`extracted_by = 'filename_index'`, `page_id = -1`)
carries its distinct basenames, so a query for a filename finds the document. It is built
from `vfs_files` paths and never from page text.

**It is not a page**, and every query over a pages table must exclude it — `page_id` is
deserialised as `u32` in the document endpoints, so a leak is a failed query rather than an
off-by-one. `EXCLUDE_FILENAME_ROW` is the predicate; `test_filename_row_excluded.py` greps
for readers that forget it.

Folder names are deliberately NOT in that row. They go through the structure index, where a
folder is one row rather than one row per document under it.

### The folder tree

`<collectionname>_vfs` is one Manticore table per collection (not per shard, not per
dataset) holding one row per VFS node. It powers the storage sidebar, the filter pane's
folder picker, and in-folder search.

**Three independent caps bound what it renders**, and they are separate because they
answer different questions (`components/search_components/vfs_tree.rs`):

| cap | bounds | overflow row |
|---|---|---|
| `MAX_CHILDREN_PER_NODE` (500) | what is FETCHED per expansion | `N more…`, raises the limit and refetches |
| `MAX_SIBLINGS_EACH_SIDE` (10) | what is RENDERED either side of the folder you are in | `N more above/below…`, client-side only |
| `MAX_VISIBLE_ANCESTORS` (8) | how many levels of the path to that folder render at all | `N more levels…`, collapses the middle |

The last two are measured from the tree's **focus** — the node the URL names — and are
inert in the filter pane, which has no "here". Only one of the first two is ever on screen
at once: while a sibling window is capping, the fetch row is suppressed, because raising
the fetch limit would not reveal anything the window is hiding. `elide_ancestors` and
`window_siblings` are pure functions with unit tests; the fixture that exercises them on
screen is `many-children` (a 42-level chain and a folder of 334 siblings), ingested by
`verify-stack.sh` as `testdata_shapes`.

Breadcrumbs resolve through `vfs_tree_path_to`, which walks `parent_key` and therefore
crosses container boundaries — `PathDescriptor` carries a single `container_hash`, so an
archive inside an archive used to render one hop and lose the rest. Past
`MAX_CRUMBS_SHOWN` (3) the leading crumbs collapse into a `…` chip whose popup lists them.

Every read of it goes through `manticore_search_sql_uncached`: the tree changes while
ingestion runs, watching a folder fill up is the normal case, and a stale tree is worse
than a slow one.

Filtering on a folder finds everything below it **including through containers**, and a
content-addressed container that sits at two paths contributes both ancestries — the
`zip-in-multiple-locations` fixture, which `verify-stack.sh` asserts on. `vfs_nodes.parent_key`
is single-valued and is only for breadcrumbs; membership always uses the full closure.

### Cache invalidation

Every search response is cached under a salt made of the collection's shard-ledger
generation AND `server_settings.cache_epoch`. The generation covers data changes; the epoch
is the manual lever for SEMANTICS changes, where every cached response is a correct answer
to a question the code no longer asks. Bump it (any new value) after changing a query
shape.

## Testing

| what | how |
|---|---|
| unit (Rust) | `cargo test --offline` inside `hoover4-website` — Rust is not on `$PATH` there, so `export PATH=/usr/local/cargo/bin:$PATH` first |
| live stack | `./run-stack-tests.sh` (fast only), `./run-stack-tests.sh --slow` (everything) |
| whole stack | `main_services/verify-stack.sh` |
| screenshots | `./take-screenshots.sh` |

**The stack tests are split by NAME, not by attribute.** Every test in
`backend/tests/stack_integration.rs` is `#[ignore]` already, because they all need a live
stack, so `#[ignore]` cannot also mean "slow". The ones that wait on something with its own
clock — the 30 s shard-state cache, a ClickHouse mutation — carry a `slow_` prefix and are
skipped by default. Every other test asserts its own wall time against
`HOOVER4_STACK_TEST_BUDGET_MS` (5 s), which is what notices when an endpoint quietly starts
doing a full scan: without it a test that grows from 0.3 s to 9 s still passes.

### Screenshots

`./take-screenshots.sh` walks `screenshots.ini` and writes a PNG, a text snapshot of the
rendered DOM and any console errors per page into `test_reports/screenshots/` (gitignored,
wiped each run), plus a `report.md` index.

It does **not** use the browser MCP endpoint. `hoover4-mcp-browser` refuses internal hosts
at two independent layers by design — a deny-list in `urlcheck.py` and a PAC script handed
to Chromium in `netfilter.py` — so `hoover4-website` is unreachable through it. The script
copies `tools/capture_screenshots.py` into that container and runs a plain Chromium with
neither filter, touching nothing about the MCP server's own behaviour. The container has no
bind mounts, so both the script and the output travel by `docker cp`.

Two traps the script exists to encapsulate: setting an input's `.value` is invisible to
Dioxus unless you go through the prototype's setter and dispatch a bubbling `input` event,
and the home box submits on `onkeypress`, so Enter has to be a real CDP key event. The long
base64 segments in the ini are CBOR route parameters (`data_definitions/url_param.rs`);
`9g==` is `None`.

## Development Notes

For local development, bring up `main_services` and `ai_services` first. Configure the service URLs in `.env.development` using `.env.development.example` as a template.

## Navigation

-  [Go Back](../Readme.md)

  - [frontend/README.md](frontend/README.md)
  - [frontend/src/components/chat_components/README.md](frontend/src/components/chat_components/README.md)