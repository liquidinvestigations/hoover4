# Admin API

Backend entry points for the admin UI. Everything here is admin-gated with
`guard::require_admin` — the frontend `AdminGuard` hides the pages, but the backend is
the actual gate.

## Modules

- `collections.rs` / `datasets.rs` / `groups.rs` / `users.rs` / `settings.rs` — CRUD for
  the registry tables.
- `processing.rs` — collection processing status (stage bars derived from watermarks),
  the Temporal workflow browser, failure lists, retries, and reads of the stored
  `processing_eta_samples` (written by the `CollectEtaSamples` workflow in
  `main_services/processing/tasks/P_admin/` — the website never computes ETAs in a
  request path).
- `dataset_ocr.rs` — per-dataset OCR languages, the `change_ocr_languages` operation and
  the newest operation row a dataset page shows, the collection-level defaults new datasets
  inherit, and dataset **creation** (which was CLI-only). Two rules live here: one language
  change per dataset, refused by the operations lock rather than by a disabled button; and
  the creation form takes a folder *name* validated against the listing of
  `DATASETS_MOUNT_PATH`, never a path.
- `operations.rs` — the operations log behind `/admin/operations` and the scoped list on
  a collection page: reads of `operations FINAL`, the per-task error rates, and the
  dispatch path that writes the row and starts the `Operation` workflow on that row's id.
  Its `KINDS` table mirrors the processing side's registry, including which kinds are
  destructive; a kind added on one side must be added on the other. **Every long thing a
  button starts goes through here**, so each click gets its own timestamped workflow id
  and its own row — a fixed workflow id would make the second click resolve to the first
  click's execution and quietly do nothing.
- `metrics.rs` — aggregates for `/admin/metrics` and `/admin/users/:username/llm`.
- `llm.rs` — the model catalog, the defaults and the allowlist. See below.

## `llm_models` is a ReplacingMergeTree, and both rules that follow from that

The table is `ReplacingMergeTree(updated_at, is_deleted)` and every read takes
`argMax(col, updated_at)`. Two consequences, each of which has already cost a bug:

1. **A refresh must carry forward everything the provider does not tell it.** `/v1/models`
   returns ids and nothing else, and `is_allowed` defaults to `1`, so a refresh that simply
   wrote its rows produced a *fresher* "allowed" version than the admin's disallow — and
   the allowlist is enforced server-side against forged model ids, not a dropdown
   filter. `refresh_catalog_now` reads the current state first (`prior_catalog`) and
   preserves `is_allowed` plus the price and capability columns; a model never seen before
   is allowed. The Python catalog task (`tasks/llm_catalog.py::store_models`) does the same,
   because whichever writer runs last wins.
2. **Filter deleted rows in `HAVING`, never in `WHERE`.** Every version of a row is still in
   the part, so `WHERE is_deleted = 0` drops the *tombstone version* and keeps the live one
   — a deleted model reads back as present. The only meaningful test is
   `HAVING argMax(is_deleted, updated_at) = 0`.

Tombstones are written by the refresh: a model the provider has stopped listing gets one
`is_deleted = 1` version, keeping its admin state so it comes back intact if the provider
lists it again.

## Failure lists and `toUnixTimestamp`

`toUnixTimestamp()` is ClickHouse `UInt32`. RowBinary is positional and untyped, so
decoding it into an `i64` field eats four bytes too many and desynchronises the whole row —
the server fn 500s, but *only* on a collection that actually has rows, which is why it can
ship. Write `toInt64(toUnixTimestamp(...))` in the SQL whenever the struct field is `i64`.

## AI service telemetry (`ai_service_telemetry`)

A separate table from the two below, and a separate purpose: one row per **outbound** call
to an AI capability, feeding the use% strip and the recent-traffic table on
`/admin/ai_status`. Writers, all best-effort and all fire-and-forget:

| service | written by |
|---|---|
| `llm` | the research agent (`llm_events.py`) and this crate's summariser |
| `embeddings`, `rerank` | `agent_common/{embeddings,rerank}.py` — the MCP servers' clients |
| `ner`, `ocr`, `embeddings` | the worker, through `post_json(..., service=…)` |
| `browser` | the browser router, per forwarded tool call |

**Every outcome is recorded, not only the successes.** A capability that writes a row only
when it works renders as "no traffic", which reads as *idle* and is indistinguishable from
*broken* — precisely at the moment someone is looking at the panel to find out which. Until
this sweep only the LLM path wrote at all, so five of the six columns were permanently
empty.

Two things the panels deliberately do **not** do:

* **Synthetic rows are excluded, not deleted.** `phase5-smoke` and `test-model` are written
  by smoke tests and by `verify-stack.sh`; the rows are evidence the check ran, so they
  stay, but a single 12 ms synthetic call dominated the p50 of a panel whose job is showing
  how slow real turns are. `SYNTHETIC_MODEL_IDS` in `ai_status.rs` filters them out.
* **`circuit_open_remaining_s` is always 0 and means "n/a", not "closed".** The breakers
  live in the worker and inside each MCP server's process; the website has no channel to
  any of them. It is not rendered for that reason.

Reachability is probed **per capability**, never widened to "the main AI server answered
`/health`": that server hosts three capabilities behind independent model loads, so
`ner_model_loaded` can be false while the process is perfectly healthy, and a row deriving
its state from the server's liveness reports NER up in exactly the case it exists to report
it down.

**The `serving` column names the hardware that answered, never the slot it sits in.**
`serving_hardware` reads `cuda_available` out of the health body the endpoint returned; the
CPU twins do not publish that field and are not credited with a GPU for its absence.
`NER_URL` is a url and not a promise — a deployment with no GPU points it straight at
`hoover4-ner-spacy` — so a row printing the name of its own variable claims a GPU on a host
that has none, on the one page whose whole job is noticing that. For the same reason the
NER row's model and detail come from whichever endpoint actually served, not from the main
AI server's body.

`ai_server_present` separates the two reasons the AI-server config fingerprint is blank. A
deployment running without the GPU tier has no second fingerprint to compare and nothing is
wrong; one that expects a fingerprint and cannot reach it is a fault. Collapsing both into
an incomplete match put a permanent unexplained defect on the page of every CPU-only host.

## Telemetry (usage_events / api_events)

Two rolling 24h tables in the global database (migrations `00014`/`00015`), written by
`api/telemetry.rs` through a buffered, batch-inserted, fire-and-forget path — telemetry
must never be able to fail a request, so writes drop on overflow and log at debug.

**PRIVACY RULE — do not "improve" this away.** Record only:

- who (`username`, guests included),
- which broad route class (`usage_events.event_type`: `user_login`, `user_search`,
  `user_get_document`, `user_other_request`, `llm_chat_message`, `llm_mcp_tool_call`),
- when (`event_ts`),
- and, for the API table only: the Rust handler / server-function name (a bounded
  allowlist in `telemetry.rs`, never derived from the request path), error flag,
  duration, bytes in/out.

Never a URL, never a query string, never a document hash, never a result count. A
metrics table that accumulates search queries is a surveillance log.

The TTL is applied by background merges, so rows can outlive 24 h briefly; every read
query filters `event_ts >= now() - INTERVAL 24 HOUR` itself.

`user_login` counts **sign-ins, not requests**: only `/api/whoami` creates a session, so
only it records one. A fresh `set-cookie` on every response instead makes this page count
one login per cookie-less request, which a single crawler can run into the hundreds in a
24 h window.

A request that identified nobody is recorded under the constant username `anonymous`, and
**not** as an error — a 401 is a correct, complete answer to a request that proved nothing,
the same reasoning as the 404 rule below. Without the row a flood of refusals would be
invisible; with `is_error` set it would read as the site breaking.

Instrumentation points: logins in `auth/session_middleware.rs`, searches in
`api/search/`, document fetches in `api/documents/`, the `user_other_request` catch-all
and all `api_events` in the session middleware (it is the only choke point that sees
duration and byte counts), and the LLM events in the chat API via
`telemetry::record_event`.

**A 404 is not an error.** `is_error` is derived from the response status, and a bare
`anyhow` error out of a server function becomes a 500 — including "this chat session is
not yours", which is the normal answer to a stranger asking. One crawler with fresh guest
cookies walking chat URLs is enough to put double-digit error counts and a 20 %+ error
rate on this page overnight. `guard::is_not_found` maps those to 404, and the middleware
excludes 404 from `is_error`: a not-found is a correct, complete answer about something
that is not there.
The message stays indistinguishable from "does not exist at all" — an id that 404s only
for strangers is an existence oracle.

## Rate limiting (api/rate_limit.rs)

Three in-process sliding-window limiters: chat (`HOOVER4_RATE_CHAT_PER_MINUTE`, default
40), API (`HOOVER4_RATE_API_PER_MINUTE`, default 1000), and chat polling
(`HOOVER4_RATE_CHAT_POLL_PER_MINUTE`, default 600). The first two have a window ladder —
1 min at `X`, then 10 min / 30 min / 1 h / 6 h / 24 h at decaying factors (1.00 / 0.75
/ 0.50 / 0.30 / 0.20), every factor an env var, `0` disables a window. A request is
allowed only if every enabled window still has budget, so a burst is fine and sustained
abuse is not. Refusals are `429` with `Retry-After`. The limiter **fails open** on
internal errors. Counters are in-process — correct only while the website is one
container. Defaults, the measured numbers behind them, and the paste-ready env block
live in `main_services/ops/Readme.md`.

The poll limiter's ladder is **flat** (1.00 in every window) and its refusal is typed
(`rate_limited:<secs>`) rather than a 429, because it is consumed by a server function.
Polling is machine-paced — a tab watching a streaming answer polls at the 500 ms floor for
as long as the model generates — so the decay that separates a human burst from an hour of
one is simply wrong here: it put a single streaming tab on the 1 h window's ceiling. See
`docs/architecture/Chat_And_Agents.md`.

The chat API enforces the chat limiter and records the LLM events through:

```rust
backend::api::rate_limit::{check_and_record, RateLimitKind, RateLimitError};
backend::api::telemetry::record_event(username, event_type, metadata);
```

## Retry semantics and the mutation caveat

Retrying failed processing work reopens the plans containing the failed documents —
see `processing.rs::reopen_plans_for_hashes` and `tasks/P_admin/Readme.md`, which
documents why a bare `ExecutePlans` restart is a no-op. The accompanying
`ALTER TABLE processing_errors DELETE` is an asynchronous ClickHouse mutation, so a
row can briefly still appear in the failure list after a retry. Accepted, not a bug.

The button here is the coarse form: it re-runs whole plans, which for thousands of
failed documents means re-downloading and re-parsing the corpus. The cheap form is
`main.py retry-failed-files`, which re-runs only the stage that failed, only for the
hashes that failed it, and leaves one error row per (document, task) however many times it
is run — the counts on this page and on `/file_browser/c/<name>` are row counts, so an
append-only retry doubles them.

## A finished plan is not a successful one

`processing_plan_finished` records that a plan's stages ran, not that every document
survived them — the stages record per-document errors and carry on, deliberately, so one
unparseable file cannot stop a dataset. So the stage bars carry a per-stage
`failed_documents` count (`stage_for_task` maps a `processing_errors.task_name` onto the
bar it belongs to) and `StageProgress::is_complete` is false while any document failed.
Without that, a stage reads `done` over documents it never processed, which is how 4 792
documents lost their entities to an NER outage without a single bar changing colour.

## TODO — deferred, with the reason

### Verify the artifact ACL with two real users, outside demo mode

**Deferred deliberately: this stack stays in demo mode for now.**

`guest_permissions_mode = all` makes every visitor an admin, so a *signed-in* guest gets
`200` on **any** chat artifact. (An unauthenticated request gets nowhere: the
route requires a session and answers 401 without one. That closes the drive-by case and
changes nothing about the case below, which is one signed-in user reading another's.) The
code-level rule is
correct and was reviewed — `/_chat_artifact/{id}/{asset}` resolves the id to its
`session_id`/`username` and enforces owner-or-admin, returning **403 for someone else's
artifact and 404 only for one that does not exist** (collapsing those two would hide a real
permission failure behind an apparent missing row). What cannot be demonstrated in this
configuration is the *outcome*: the acceptance check "a second user gets 403" passes
vacuously because there is no second user — everyone is the admin.

So the acceptance run must record it as **not verifiable in demo mode**, never as passing.
To close it: set `guest_permissions_mode = none` on the settings page, create two real
users, have each open a chat that produces an artifact, and fetch the other's artifact id.
Expected: 403, and `api_events.is_error = 0` for it (a 403 is the system working).

Until that is done, treat "the ACL is fine" as a code review result, not a test result.

The same applies to the OCR'd-PDF route: `/_download_ocr_pdf/...` calls
`permissions::assert_can_read` on the *source document's* dataset before it looks anything
up, which is the same check `/_download_document/...` makes. In demo mode that check
passes for everyone, so it is likewise a code result rather than a test result, and it is
closed by the same two-real-users run.

## Navigation

- [Go Back](../mod.rs)
