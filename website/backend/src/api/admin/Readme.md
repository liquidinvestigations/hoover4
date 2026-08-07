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
- `temporal_trigger.rs` — starts pipeline workflows over the Temporal HTTP API,
  tagging dataset-scoped starts with the `CollectionDataset` search attribute.
- `metrics.rs` — aggregates for `/admin/metrics` and `/admin/users/:username/llm`.
- `llm.rs` — the model catalog, the defaults and the allowlist. See below.

## `llm_models` is a ReplacingMergeTree, and both rules that follow from that

The table is `ReplacingMergeTree(updated_at, is_deleted)` and every read takes
`argMax(col, updated_at)`. Two consequences, each of which has already cost a bug:

1. **A refresh must carry forward everything the provider does not tell it.** `/v1/models`
   returns ids and nothing else, and `is_allowed` defaults to `1`, so a refresh that simply
   wrote its rows produced a *fresher* "allowed" version than the admin's disallow — and
   the allowlist is enforced server-side against forged model ids (§9.3), not a dropdown
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

Instrumentation points: logins in `auth/session_middleware.rs`, searches in
`api/search/`, document fetches in `api/documents/`, the `user_other_request` catch-all
and all `api_events` in the session middleware (it is the only choke point that sees
duration and byte counts), and the LLM events in the chat API via
`telemetry::record_event`.

**A 404 is not an error.** `is_error` is derived from the response status, and every
`anyhow` error out of a server function used to become a 500 — including "this chat
session is not yours", which is the normal answer to a stranger asking. One crawler with
fresh guest cookies walking chat URLs put 11 errors and 22 % on this page overnight.
`guard::is_not_found` now maps those to 404, and the middleware excludes 404 from
`is_error`: a not-found is a correct, complete answer about something that is not there.
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
`website/Readme.md`.

The chat API enforces the chat limiter and records the LLM events through:

```rust
backend::api::rate_limit::{check_and_record, RateLimitKind, RateLimitError};
backend::api::telemetry::record_event(username, event_type, metadata);
```

## Retry semantics (Q4) and the mutation caveat (Q10)

Retrying failed processing work reopens the plans containing the failed documents —
see `processing.rs::reopen_plans_for_hashes` and `tasks/P_admin/Readme.md`, which
documents why a bare `ExecutePlans` restart is a no-op. The accompanying
`ALTER TABLE processing_errors DELETE` is an asynchronous ClickHouse mutation, so a
row can briefly still appear in the failure list after a retry. Accepted, not a bug.

## Navigation

- [Go Back](../mod.rs)
