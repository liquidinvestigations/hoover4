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

### Sessions: one route mints, every other endpoint requires

`/api/whoami` is the only route that creates a session — a `web_sessions` row, a `guest-*`
user, a `user_login` event and the `hoover4_session` cookie. Every other server function
and every custom route (`/_download_document/…`, `/_download_ocr_pdf/…`,
`/_chat_artifact/…`) answers **401** when nothing resolved an identity. The policy is one
file, `backend/src/auth/route_policy.rs`, and its tests enumerate the custom routes
literally so a route added to `main.rs` and forgotten there fails a test rather than
shipping open.

The app shell — page routes, `/assets/…`, the wasm bundle — stays open, because the browser
has to load the code that signs in. It carries no collection data; everything it renders
arrives through a checked route.

**The frontend blocks on it.** `components/session_gate.rs` wraps the router: no page
renders until `whoami` resolves. Rendering pages first and letting each page's resources
race the sign-in would hand every one of them a 401 to display on first paint.

**And it calls it once.** The gate publishes what it resolved as a context; anything under
it that needs the identity — the admin shell, the admin guard, both chat pages — reads it
with `use_session_user()` instead of running its own `use_resource(whoami)`. A component
that fetches for itself puts another request on the single endpoint that *writes* sessions,
once per page load — the count becomes "how many identity-aware components does this route
mount" rather than one.
`use_session_user()` answers `None` while the gate's call is in flight, which means "not
known yet" and never "guest" — a component that defaults an unknown identity to a concrete
answer draws the wrong control on first paint and then takes it away.

**Why it matters that only one route mints.** A response that attaches a fresh
`set-cookie` on any route lets every client that stores no cookies — a crawler, a `curl`
loop, a link checker — create a `guest-<hex>` user and a `user_login` row *per request*,
so the user list and the metrics page grow without bound and stop being readable. A guest name is derived
from the session id rather than randomised, so a browser holding a cookie whose session row
has expired re-anchors to the identity it already had instead of becoming a second user.

**`HOOVER4_DEMO_MODE` decides whether anonymous visitors exist at all.** With it on, the
mint route provisions a guest and treats them as an administrator — the public demo. With
it off, nothing is provisioned: `whoami` refuses, the session gate renders *Sign-in
required*, and the only way in is a reverse proxy setting `X-Forwarded-User`. A
proxy-authenticated identity is honoured on every route, because the proxy is what
authenticated it; what is confined to the mint route is writing a session for it.

That elevation is applied to the request and never written to the account, so a guest's
`users` row keeps `is_admin = false` while `whoami` reports true for the same session.
The disagreement is the design — the grant belongs to the deployment and lasts exactly as
long as the switch does, where a persisted flag would leave real administrators behind the
day it is turned off — and `/admin/users` states it on the page, because that is the one
screen where the stored flag and the live grant sit side by side.

A non-browser client must therefore hold a cookie jar and call `whoami` first. That is what
`main_services/verify-stack.sh` does, discovering both URLs from the served WASM bundle
because a server function's path carries a build hash.

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
  searchable reading. That error is `MatchQueryError` and it is carried out by TYPE:
  `auth::guard::is_bad_request` matches on it, so the endpoint answers **400** and the
  page renders the sentence it contains. Restating it anywhere along the way with
  `anyhow!("{e}")` leaves a bare string, and a rejected keystroke goes back to reading
  as the site falling over.

A pure string assertion is how this last reached production: the unit test asserted the
doubled form, so it passed while every search containing an apostrophe failed. Tests for
this helper assert against the character set measured to break a live Manticore, and a
change here is not verified until the query has run against a real one.

Non-`MATCH()` uses of `QuotedData` — attribute comparisons against hashes, dataset ids
and facet values — carry the same wrong quoting rule and are not yet converted.

### Search fan-out

Manticore holds no global search tables. Each collection's search data lives in a
dynamic number of shard tables, `<collectionname>_<n>_pages` (capped by the indexing
planner at 4 GB of text or 2.5 M rows, whichever binds first). Distributed tables are
deliberately not used: Manticore 14.1.0 cannot run this site's stored-field/FACET query
shape over them — measured, not assumed, and it fails by returning NULL stored fields
rather than by erroring.

**One table per shard, and no JOIN.** Each document's metadata is denormalized onto every
one of its pages rows by the indexer. The JOIN this replaced was the single most expensive
thing in the search path — a nested-loop lookup per left row, evaluated before any
predicate, so an unfiltered entity facet on the largest shard cost 13 s alone and 100 s
under the four-way concurrency of the Entities tab, which is what produced HTTP 504 there.
It was also silently wrong: Manticore's `LEFT JOIN` drops unmatched left rows, 0.28% of
documents on the corpus it was measured against. Denormalized, the same facet is ~1 s and
a `file_types` facet is ~0.27 s, for about 15% more disk. Do not reintroduce a join.

Every search — result list, hit count, string facets, MVA facets, the date histogram — is
therefore built once **per shard** (`backend/src/api/search/search_sql.rs`) and fanned out
through a PROCESS-WIDE gate of `MAX_PARALLEL_INDEX_QUERIES = 8` concurrent Manticore
queries (`backend/src/api/search/fanout.rs`, override with
`HOOVER4_SEARCH_MAX_PARALLELISM`, clamped to 1..=64; ini key `search_max_parallelism`).
Process-wide rather than per request because the Entities tab opens four fan-outs at once,
and a per-call limit multiplies by four against a daemon that has a dozen worker threads.
Size it to the daemon, not to the shard count.

Selecting datasets in the `collection_dataset` facet prunes whole collections from the
fan-out. One failing shard degrades the response to partial (the UI shows a "some
collections could not be searched" notice); an error is returned only when every shard
fails.

**A timeout is not a partial result.** Every query carries `max_query_time` and
`agent_query_timeout` of 30 s (`HOOVER4_SEARCH_TIMEOUT_SECONDS`, ini key
`search_timeout_seconds`), and the HTTP client applies the same budget plus five seconds
of grace — Manticore's own limit is best-effort and covers neither a connect nor a read
stall. A shard that hits either limit fails the whole request, is never written to the
search cache, and the facet pane offers a Retry button. That is deliberate asymmetry: a
shard that could not be reached is dropped with a visible amber notice, while a shard that
timed out answers with counts that are short by an unknown amount in a response shaped
exactly like a correct one. The retry is never automatic — retrying by itself doubles the
load on a Manticore that was already too slow.

What is exact, and what is approximate:

- **Exact:** per-shard results and per-shard counts; pagination stability (hits are
  merged by score with a deterministic `(collection_dataset, file_hash)` tie-break).
- **Approximate:** cross-shard/cross-collection **ranking** (BM25 statistics are
  per-table; there is no global IDF — accepted, deliberately not "fixed" with a
  normalisation hack); cross-shard **facet counts** (each shard only returns its top
  buckets, over-fetched to `21 × n_shards`, capped at 200, before the merge sums
  them); the **total hit count** (a sum of per-shard `count(distinct file_hash)`,
  which is an upper bound because the same file can exist in two collections).

The **Collections facet is intersected with the dataset registry** before it is offered
(`search_facets.rs::reconcile_dataset_facets`): a value that names no readable dataset is
dropped, and a readable dataset the index returned no bucket for is added at zero. The
index is not the authority on which datasets exist — `dataset` is — and Manticore keeps
whatever was written under a name until something deletes it, so an abandoned ingest goes
on producing buckets with real counts. Offering one hands the user a filter whose only
possible outcome is `0 documents found`. The guard is display-only: the orphan rows still
inflate unfiltered hit counts, and `main.py purge-dataset` is what removes them.

The four NER Entities facets (`ner_per`, `ner_org`, `ner_loc`, `ner_misc`) and the
document viewer's entities panel are filtered through `common/src/entity_stoplist.rs`,
which
rejects mail header names, encoding fragments and letter-spaced PDF headings. The
pipeline drops the same values before storing them
(`main_services/processing/tasks/entity_stoplist.py`), so on freshly extracted data this
finds nothing; it exists because a write-time rule governs only rows written after it,
and on a mail corpus the rows written earlier put `Content-Transfer-Encoding` at the top
of the facet. The duplication is deliberate and mirrors `document_sources.rs`: neither
runtime may depend on the other being right. The stop-list is applied to whatever maps to
the `ner` term field and to nothing else: it exists to drop what a *model* mislabels, and
against a checksummed identifier it would only do damage.

**A facet search box asks the corpus, not the buckets on screen.** A pane holds the top
twenty-one buckets of one query, so narrowing those client-side answers "nothing matches"
for a value that is present and merely unpopular. `search_entity_terms`
(`backend/src/api/search/entity_terms.rs`) resolves a needle against
`<collectionname>_entities` — the only table carrying both the text and the term id the
search columns are written in — and the ids narrow the facet query through
`search_string_facet`'s `restrict_to_ids`. `Some(vec![])` is a needle that matched
nothing and returns no buckets; `None` is no needle and returns the whole facet, and
collapsing the two answers a failed search with everything. `file_types` keeps
client-side narrowing: a handful of buckets, all visible, and no rows in the term table.

**One pane serves eleven of the Entities rail's twelve children**, so a rail click changes
that pane's `field` prop rather than building a new pane. Props are not reactive: a
`String` prop is read once into the hooks and never again, and a `use_resource` that
closed over it goes on asking about the column the reader left. The field is therefore a
`ReadSignal`, read *inside* the resource, and the search box empties when it changes — the
failure it prevents is a facet full of values answering "nothing matches" for a needle
typed against a different list.

Those queries are uncached, like the folder tree's, because the table changes while
ingestion runs. **Manticore 14.1.0's SQL grammar has no `EXCLUDE FILTERS` clause** in any
position a `FACET` accepts, so a facet drops its own selection by having it removed from
the query before the query is sent. That also removes the `collection_dataset` filter
permission sanitisation injected, which is safe only for as long as permissions are
collection-granular — a permitted collection implies all of its datasets. Dataset-level
permissions would make that line a leak.

The two copies are held together by a digest rather than by discipline. No path is
visible to both test runs — `hoover4-website` mounts only `website/` and `hoover4-worker`
only `main_services/processing` — so each side hashes its own header names, thresholds and
canonical cases into `STOPLIST_PARITY_DIGEST` and asserts the same literal. A rule changed
on one side alone fails that side's test; updating the digest then fails the other side
until the same change is made there.

Search responses are cached per sub-query in the global `search_manticore_cache`
table; the cache key includes the collection's shard-ledger generation
(`max(updated_at)` of its `manticore_shards` table, cached in-process for 30 s), so a
newly opened shard invalidates that collection's cached searches without touching the
others.

### Showing a failed server call

`ServerFnError` never reaches the DOM. `api::error_util::user_facing_message` extracts the
`message` the backend wrote for a person — both derived renderings are unusable, `Debug`
prints the struct and `Display` wraps the message in *error running server function: …
(details: …)* — and the `ServerErrorDisplay` component is the one place that renders it.
Formatting the error at the call site instead is how a Rust struct ends up printed across
a search page's pagination.

The status picks the presentation: a **4xx** is something the caller can fix and is shown
as a plain message, anything else is a failure of ours and is shown as the red component
error. Both carry `x-error-display`, which is how `tools/capture_screenshots.py` finds a
surfaced error structurally rather than by matching words.

A slot with no value has no error to report either: the hit-count position renders nothing
when the search failed, because the results panel below it already shows the message and
printing it in both put it across the pager and the page numbers.

### In-document PDF search

`/api/search_document_pdf` collects the matching words out of Manticore and asks a
**pdfium sidecar** where they sit on the page, so hits can be highlighted in the rendered
PDF. The sidecar is `backend/pdf-viewer/_server/server-search.js`, a node process this
server starts and supervises (`server_extra::run_pdf_search_server`) rather than a service
of its own, which is why `PDF_SEARCH_ENDPOINT` is loopback.

**The sidecar is handed the PDF's bytes** — `POST` the document as the body, keywords as a
`?keywords=<json array>` parameter — and never a URL. It cannot reach back into anything.
A sidecar told to fetch `http://127.0.0.1:<PORT>/_download_document/…` is this server
asking itself for a document it already knows how to read, over a request that carries no
session cookie; requiring a session on the download route kills it silently. The bytes are
read straight out of the blob store instead
(`api::documents::download_document::read_blob_bytes`), which also bounds the document by
its registered size before a byte is fetched — the whole PDF is buffered here, on the wire
and inside pdfium's wasm heap. Over that ceiling, the document still opens, downloads and
searches by text; only the in-page highlight overlay is unavailable.

That blob read runs on the server's multi-threaded runtime through
`startup::on_multi_thread_runtime`. The S3 SDK blocks internally while collecting the body,
and Dioxus server functions do not run on the runtime the axum routes do — a bare
`tokio::spawn` inherits the same context rather than escaping it.

Its directory is found by walking **up** from the working directory, never joined to it:
the built release binary serves from `target/dx/<pkg>/release/web/`, so a relative path
resolves inside the build output, the spawn fails with `No such file or directory`, and
in-PDF search is dead for the whole deployment while every other route looks healthy.
`PDF_SEARCH_SERVER_DIR` overrides the search outright.

The pid file at `/tmp/pdf-search-server.pid` outlives the process it names — it is on the
container's filesystem and a restart does not clear it — and pids are handed out from a
small range at boot. So "a process exists at this number" is never evidence that it is the
sidecar, and the supervisor reads `/proc/<pid>/cmdline` before signalling anything. Killing
on liveness alone SIGKILLs a stranger: it has killed *this server's own binary* seconds
after start, after which `dx serve` believes the app is running, every route answers 500
with nothing else in the log, and each restart reproduces it because the same pid is
issued again.

This is not `PDF_TO_HTML_ENDPOINT`. That names `hoover4-processing-pdf-to-html`, a
separate container that takes a POST of raw PDF bytes and returns HTML; it answers
`GET requests are not supported` to anything the search path sends.

The viewer's own bundle is vendored under `frontend/assets/embed-pdf/_viewer/` and is
pulled into the build by a `#[used] static … asset!(…folder…)` in
`components/pdf_viewer/mod.rs`. Nothing reads that binding, and the `<script>` tag loads
the entry point by literal URL — so the `with_hash_suffix(false)` option and the
`/assets/_viewer/…` path in the tag have to be changed together, and dropping the
declaration silently ships a site with no PDF viewer.

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

The same switch also picks the **model**. Each agent profile has a `server_settings` key
of its own — `llm_model_internal_search`, `llm_model_full_research`,
`llm_summarization_model` — resolved by `admin::llm::model_for_profile`. **Unset means
"use `llm_default_chat_model`"**, so a deployment that never touches these keys behaves
exactly as it did before they existed, and an empty string is the same as unset. It exists
because the profiles make different demands: one binds four tools and reads a handful of
passages, the other binds thirty and reads the open web, and the summariser writes a chat
title. Without it the only way to make one faster is to change the model for everything.

A model the user picked in the composer still wins over the profile's: the key configures
the deployment, not the conversation.

**`llm_models.supports_tools` is `0` for every row**, so nothing checks that a model
chosen here can call tools at all. The picker is a footgun until a capability probe
populates that column.

### Citations, and why they are not the search cards

`cite_documents` is the agent's own claim about which documents its answer rests on. The
search cards under a tool disclosure are everything a search returned; the **Sources
strip** beneath an answer is what the agent chose, and rendering the first in place of the
second is what turns an answer into a pile of links.

Each citation carries a handle — `[D1]`, `[D2]` — allocated per chat **session** by the
collection-search MCP server, so a handle from the first turn still resolves in the ninth.
`markdown_text.rs` renders a bare `[Dn]` in the prose as a chip that scrolls the strip's
entry into view and flashes it; `[D3](https://…)` is still a link, because the handle arm
only fires when no `(` follows the `]`. The anchor id is minted by `source_anchor_id` and
read by the strip — one function, because two spellings would scroll to nothing silently.

**A quote that does not verify is shown, marked, never dropped.** A model that stops citing
is a worse outcome than a citation the reader can see is unverified.

De-duplication of document cards is **within a group and never across one**. A search card
and a citation card for the same document are two different statements about it, and
collapsing them would hide that the agent chose one of the things it found.

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

### Timeouts

The agent connection is bounded by **silence**, not by duration:
`HOOVER4_AGENT_TIMEOUT_SECONDS` (default 300) is a `read_timeout` — the longest gap
between two bytes — and `HOOVER4_AGENT_TOTAL_TIMEOUT_SECONDS` (default 1800) is the
absolute ceiling for an agent that loops forever while still emitting events.

**A total-request timeout is the wrong bound for a streamed run**, and getting this wrong
is expensive to diagnose. A healthy internet-tools turn is a dozen provider calls at
50–120 s each; cutting it at a total makes `reqwest` report a body error whose `Display`
is `error decoding response body` — indistinguishable from a corrupt stream — while the
agent, which never learns the reader left, keeps working for another quarter of an hour
and writes a full set of `ok = 1` rows into `llm_call_events`. Every log line about a
broken stream therefore prints the error's whole `source` chain and its `is_timeout()`
flag, never `{e}` alone.

### Retries

Each turn gets `HOOVER4_AGENT_ATTEMPTS` attempts (default 4) with exponential backoff from
`HOOVER4_AGENT_RETRY_BASE_MS` (default 2 s, so 2/4/8 s). Retries cover *every* failure
class rather than a curated list — unreachable, 5xx, timeout, malformed body are one thing
from the user's seat, and this stack fails transiently in all four ways.

**Once the agent has streamed anything, an attempt is worth much more.** A replay repeats
every tool call and every provider call the turn has already made, so at most
`HOOVER4_AGENT_STREAM_RESUMES` (default 1, max 2) of the attempts may be spent after the
first event, and only for a transport break the connection caused — a deadline lands in
the same place on the replay and is never retried
(`agent_client::is_resumable_break`). Before a replay the prose already collected is
folded into the reasoning trace, so the second attempt's answer is not appended to half of
the first one's; tool rows keep their seqs and the replay's rows follow them, so the
transcript records both runs.

Failed attempts are kept in `chat_messages.retry_errors` even when the turn eventually
succeeds, and the transcript shows them behind a disclosure. A turn that only worked on
the third try is a healthy answer over an unhealthy agent tier, and that is worth seeing.
The list holds **one entry per attempt including the one that ended the turn**, so it is
labelled by its length and not as "earlier" attempts.

A turn that ends in an error also logs at ERROR with the session, the turn uuid and the
attempt count. A failure whose only record is a row in `chat_messages` is a failure nobody
finds while the user is asking why the assistant stopped answering.

### Admin: live chats

`/admin/metrics` lists the agent runs this website process is holding open right now —
user, conversation, both switches, elapsed time, attempt number — with a **Kill** button.
The registry is in-process (`backend::api::chat::live_runs`), not in ClickHouse: a row
means "this process is doing this work now", and a persisted row would outlive the process
and show an admin ghosts to kill. Cancellation is cooperative — it lands between retry
attempts, and cannot abort a generation already in flight.

Deep-research turns run in a Temporal worker and are **not** listed there; the Temporal UI
owns that view.

### Admin: the inline SVG charts

The events-per-hour bars on `/admin/metrics` and the ETA lines on a collection's
processing page are hand-written SVG, and two traps come with that.

**A `<title>` inside `<svg>` has to be built in the SVG namespace, and `dioxus-html` has
no such element.** It declares `title` in the HTML namespace only — the SVG twin collides
on the Rust identifier and is commented out in that crate — so `title { … }` written
inside a chart is created with `createElement` and lands in the document as an
`HTMLTitleElement`. Inside `<svg>` that is a foreign element: not rendered, not a tooltip,
and no warning on any build. `components::svg_title` declares the missing element by
shadowing the `dioxus_elements` module rsx resolves against, and the charts use
`svgtitle { … }`. The tooltip is the only place a bar's exact bucket timestamp and count
are readable, because the axis deliberately drops the date.

**Keys among SVG siblings are positions, never labels.** Two axis ticks can legitimately
carry the same text — three ticks all read `0s` on a finished pipeline, and the 24 h window
spans 25 hourly buckets so its two ends print the same `HH:MM` — and duplicate keys among
keyed siblings are a `debug_assert` in dioxus-core that kills the renderer on the next
re-diff, then puts *App panicked!* on the next page the operator opens. A release build
does not assert; it re-associates the wrong nodes instead. Both charts key by tick index.

The tick VALUES are chosen so they cannot collide in the first place: the count axis rounds
its top up to an even number, so the half-height rule is labelled with the value it is
actually drawn at rather than a rounded one, and a remaining-time axis whose whole range is
zero draws one baseline tick instead of three that all read `0s`.

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

**`email_headers.date_sent` is a `DateTime` whose fallback is the epoch, and the epoch is
also a real instant**, so nothing but `date_sent_known` separates "sent 1970-01-01" from
"never parsed". Every reader must consult the flag: the email source query emits an empty
string for an unknown date and `DocumentEmailSourceItem::sent_date` rejects the epoch
again on the client, because viewer state restored from a URL carries whatever was written
into it. Printing the sentinel puts a sent date on the preview of a document the Metadata
tab reports as having no confirmed date at all.

**An email's headers and its body are stored independently, and the second is not implied
by the first.** `email_headers` gets a row whenever the file parses at all; `text_content`
gets an `email_parser` row only if the message yielded body text worth storing, and the
text writer drops a page whose stripped text is under two characters. Mail whose whole
`text/plain` part is a single `,` clears the first bar and not the second, exactly like
mail whose only body part is HTML. `DocumentEmailSourceItem` therefore carries
`has_body` alongside the body's page range, and the preview renders the headers with an
explicit "no body text was extracted" line instead of asking for a page that has no row —
which the text endpoint answers, correctly, with a 404 the viewer rendered as *document
not found!* where the body belongs.

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

**The Sort control edits the PENDING query, like everything else in the search toolbar.**
It therefore names the order the results on screen are actually in, and draws an
unapplied choice after it as `applied → pending` in the accent colour; `Apply Filters` is
the one control that says whether anything is waiting, and it is disabled when nothing
is. Applying the sort on selection instead is not the small change it looks like: the
apply path pushes the whole pending query, so a sort click would commit filter edits the
user had not confirmed.

### Only the first 1 000 results are reachable

`MAX_PAGINATION_DOCUMENT_LIMIT` (`common/src/search_const.rs`) caps how deep the pager
and the next/previous-result buttons go. The hit count above them is the whole match, so
a corpus-wide query says "6 379 documents found" over a pager that ends at `1000` — two
numbers on one line that legitimately disagree. The `i` beside the count explains it
whenever the count exceeds the cap (`search_result_list_controls.rs::PaginationCapNotice`).

The cap is a property of the UI, not of the index: search itself will count and rank the
whole match. Deep paging over a merged, cross-shard result set costs a full re-merge per
page, and past a thousand hits refining the query is the answer rather than paging.

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
| `CHILDREN_PAGE_SIZE` (500) | what is FETCHED per request | `N more…`, fetches the NEXT page and appends |
| `MAX_SIBLINGS_EACH_SIDE` (10) | what is RENDERED either side of the folder you are in | `N more above/below…`, client-side only |
| `MAX_VISIBLE_ANCESTORS` (8) | how many levels of the path to that folder render at all | `N more levels…`, collapses the middle |

The tree asks for folder-like children ONLY (`folders_only`), so `total` counts what it
can draw: a folder holding nothing but files is a leaf rather than a row promising
thousands of children that never appear, and a folder's files can no longer fill the first
page and starve the archives behind them (`ORDER BY kind ASC` puts containers last). The
file-browser content pane asks without the flag, because files belong in the pane. The
server's own `MAX_CHILDREN_PER_PAGE` (2000) is a page-size cap and is deliberately larger
than what the tree asks for: while the two were the same number, a wider request was
clamped back to the page the caller already had.

The last two are measured from the tree's **focus** — the node the URL names — and are
inert in the filter pane, which has no "here". Only one of the first two is ever on screen
at once: while a sibling window is capping, the fetch row is suppressed, because raising
the fetch limit would not reveal anything the window is hiding. `elide_ancestors` and
`window_siblings` are pure functions with unit tests; the fixture that exercises them on
screen is `many-children` (a 42-level chain and a folder of 334 siblings), ingested by
`verify-stack.sh` as `testdata_shapes`.

**The indent counts ladder RUNGS, not tree depth**, and the third cap is what makes that
affordable. A row's rung is its position in the ladder on screen; ancestor elision hides
whole levels without spending rungs, so the deepest folder of a 43-row chain renders on
rung 11 rather than rung 45. Every visible row is therefore indented strictly more than the
row it hangs off, at any depth and at any pane width, which is the thing a tree has to
show. `indent_px` spends 16 px on the first four rungs and 8 px on every rung after them,
bounded by a pixel ceiling and — through a CSS `min()` — by a share of the pane, so
dragging the sidebar narrow tightens the ladder with no re-render. The 8 px step is small
because the app lays out at a 1920 px design width and `zoom`s it to the window
(`assets/main.css`): a 4 px step would be 2.5 device pixels at a 1280 px window, which is
not a step anyone can see. Past four rungs the row also states its true depth in a badge,
because the ladder does not count it.

**That pane share is scaled by the rung, not applied flat**, which is the difference
between a ladder that tightens and one that stops. A flat `min(Npx, 40%)` resolves to one
number for every rung above the percentage, so at the narrowest pane the drag offers, four
to five consecutive levels render at pixel-identical indent — the flat cap the ladder
replaced, reached from the other direction. `indent_style` emits
`min(Npx, calc(40% * f))` where `f` is the rung's share of the pixel ceiling, so the
narrow-pane branch is a proportional copy of the wide-pane one: bounded by the same share
of the pane, and still stepping at every rung.

**Refocusing collapses the subtree below the new focus** (`expansion_after_refocus`).
Elision only shortens the ladder ABOVE the focus, so an expanded chain left hanging below
it keeps taking a rung each until the pixel ceiling absorbs them: navigating up from a
44-deep folder to a 26-deep one otherwise leaves twenty-one nested levels rendered as
twenty-one siblings. The path to the focus stays open, including the levels elision hides,
and branches elsewhere in the tree keep whatever the user opened by hand.

**The storage sidebar is resizable and remembers its width**
(`components/resizable_sidebar.rs`). The unit is CSS pixels — a percentage or `vw` would
re-scale the pane on every window change, and the width a folder name needs is a number of
pixels, not a share of a screen. Those are LAYOUT pixels, before the app's scale, so the
drag divides the cursor's travel by the scale it measures off `#x-nav-container`; the
scale is a media-query ladder and cannot be a constant on the Rust side. A remembered
width is clamped to 240–720 px on the way in and on the way out, anything that is not a
plain positive integer falls back to the default, and `max-width: 50%` backstops both. The
720 px ceiling is 37 % of the design width, so no window size can put the pane off screen.

**The double-click that resets it is recognised from the two `mousedown`s**, because no
`click` or `dblclick` ever reaches the handle: the first press mounts the full-screen
overlay that catches the drag, the release lands on that overlay, and the overlay unmounts
in the same handler — so the browser has no live common ancestor for the two and drops the
whole activation sequence. `is_double_press` pairs two presses within 400 ms and 4 px of
each other, which is the only path that writes the default width back to storage.

Breadcrumbs resolve through `vfs_tree_path_to`, which walks `parent_key` and therefore
crosses container boundaries — `PathDescriptor` carries a single `container_hash`, so an
archive inside an archive used to render one hop and lose the rest. A container has no
`/` node: what is inside it hangs off the container FILE, so expanding `report.zip` shows
its contents and the trail reads `dataset › folder › report.zip › member`. The content
pane still addresses that level as the descriptor `container_hash + "/"` — a descriptor
and a tree node are different things. Past
`MAX_CRUMBS_SHOWN` (3) the leading crumbs collapse into a `…` chip whose popup lists them.

Every read of it goes through `manticore_search_sql_uncached`: the tree changes while
ingestion runs, watching a folder fill up is the normal case, and a stale tree is worse
than a slow one.

Filtering on a folder finds everything below it **including through containers**, and a
content-addressed container that sits at two paths contributes both ancestries — the
`zip-in-multiple-locations` fixture, which `verify-stack.sh` asserts on. `vfs_nodes.parent_key`
is single-valued and is only for breadcrumbs; membership always uses the full closure.

### Browsing a tabular document

A spreadsheet or delimited-text file that the pipeline read into cells has a
`table_documents` row and is `file_type = 'table'` in `file_type_canonical`. The viewer
offers it a **Table** source, declared before `Text` in `DocumentSourceItem` so a workbook
opens on its grid rather than on the tab-separated flattening of it that the text
extractor also produced.

`api/documents/table_browse.rs` is the whole query surface: `get_table_overview` (the
sheets, the columns and their statistics, the caps that fired), `get_table_page` (one
window of one sheet) and `get_table_column_values` (a filter popover's value list).

**`table_cells` is keyed by content hash alone.** It has no `collection_dataset` column,
because the same spreadsheet ingested into five datasets is one set of cells. So every one
of those three functions calls `permissions::assert_can_read`, then looks
`(collection_dataset, hash)` up in `table_documents` with `status = 'ok'`, and only then
touches `table_cells`. A hash with no manifest row for that dataset is a 404 that never
reaches a cell query; skipping the lookup would let a reader who may see one dataset read
the cells of a document that only exists in another by pasting its hash.

Three more rules those functions share:

* `limit` and the visible-column set are clamped server-side (`MAX_TABLE_PAGE_ROWS` 200,
  `MAX_TABLE_VISIBLE_COLUMNS` 60) and the clamp is **reported back** in `TablePage.clamps`.
  A grid that quietly returns 200 of the 5 000 rows it was asked for looks exactly like a
  grid whose document ends at row 200.
* every column id — visible, sorted, filtered — is validated against the sheet's own
  columns before it reaches SQL.
* every reader-supplied string is a bound parameter. This is ClickHouse, not Manticore:
  `db_utils/manticore_match.rs`'s escaping exists because Manticore has nothing to bind,
  and copying it here would be a second, worse escaping layer.

Sorting is two phases. Phase 1 orders one contiguous primary-key range — the sort column
of one sheet — and returns `row_id`s; phase 2 fetches those rows' cells by `row_id IN (…)`
and re-orders them into phase 1's order in Rust, so the two phases cannot disagree about
the comparator. Rows with **no cell in the sort column** are not in phase 1's range at all
and are appended after the sorted rows in `row_id` order, in both directions.

**The header row is not a data row.** The reader writes the first row that produces cells
into `table_columns.header`, records its `row_id` as `table_sheets.header_row`, and leaves
it out of every column statistic — but it is also stored as ordinary cells. So every read
here starts *after* `header_row`, and every row count a reader sees subtracts it: otherwise
the grid draws that row twice, once as its column labels and once as row 1, and disagrees
with the statistics the filter popovers and column type marks come from. `header_row = 0`
is a sheet with no header row and nothing is skipped. For a genuinely headerless file the
first data row becomes the column labels — its values are still on screen, and it is what
a spreadsheet application shows too.

The grid draws `source_row`, the row number the file itself gives, in its `#` column —
not the dense `row_id`, which is pagination arithmetic and would be off by every empty row
above. Sheet ordinals are the workbook's own and are not contiguous, so the sheet picker is
built from the stored sheet rows and never from a range.

The selected sheet, sort, filters, hidden columns and page live in
`DocViewerState::table_state` and therefore in the URL, not in the `DocumentSourceItem`
variant: that variant is the key of `ItemHitCounts` and the value the source selector
compares against the selected source, so one carrying view state would deselect the grid
on every click.

### The file-type glyph

`common/file_type_icons.rs` maps a canonical file type to a glyph name and a label, and
`components/file_type_icon.rs` maps that one enum to one icon. Five sites draw it: the
search result card, the storage browser's file rows, the viewer's title bar, an email's
attachment cards and the preview source selector. `SearchResultDocumentItem.file_type` and
`VfsFileEntry.file_type` are filled from `file_type_canonical` — one ClickHouse read per
dataset on the page — rather than decoded from Manticore's `file_types` term ids, because
the viewer draws its glyph from that same table and a symbol must not disagree with itself.

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
| hook order | `dx check --package frontend` inside `hoover4-website`; `./run-stack-tests.sh` and `./development.sh` both run it first |
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

**`dx check` runs before the suite because it is the only thing that catches a conditional
hook.** Such a hook traps the WebAssembly runtime on the render that adds it, leaving the
page painted and completely inert — a failure `cargo check` cannot see and the release build
reports only as `RuntimeError: unreachable`. See
[`frontend/README.md`](frontend/README.md).

**`cargo check` does not build test targets, so it cannot see a broken test binary.** A
signature change updated at every call site in `src/` leaves `cargo check` clean and
`cargo test` unable to compile, and nothing between the two says so — the tests do not fail,
they never get built. `cargo check --workspace --tests` (fast) or `cargo test --no-run`
(slower, and produces the binaries) is what closes that gap; run one of them alongside
`cargo check` whenever a public signature moves.

**Both fixture-driven suites are welded to the corpus `main_services/verify-stack.sh`
ingests** — `screenshots.ini`'s routes and `stack_integration.rs`'s `TESTFILES`, `SHAPES`,
`ZIPS` and `other`. On any other corpus they fail by naming a dataset that does not exist,
which reads as a broken page or a broken endpoint and is neither. Run `verify-stack.sh`
before either of them, or read their failures as a missing precondition rather than a
regression.

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

### Two single-question diagnostics next to it

`tools/count_whoami.py` prints the number of `/api/whoami` requests per navigation, and
`tools/check_session_gate.py` reports which of the gate's three states a page settled in.
Both run the same way — `docker cp` into `hoover4-mcp-browser`, then `docker exec`. They
answer questions the screenshot gate cannot: a page that costs three mint-route calls looks
identical to one that costs one, and a gate stuck on *Sign-in required* renders the same
clean page on every route.

## Development Notes

For local development, bring up `main_services` and `ai_services` first. Configure the service URLs in `.env.development` using `.env.development.example` as a template.

## Navigation

-  [Go Back](../Readme.md)

  - [frontend/README.md](frontend/README.md)
  - [frontend/src/components/chat_components/README.md](frontend/src/components/chat_components/README.md)