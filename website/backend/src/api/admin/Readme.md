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

## Telemetry (usage_events / api_events)

Two rolling 24h tables in the global database (migrations `00017`/`00018`), written by
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

## Rate limiting (api/rate_limit.rs)

Two in-process sliding-window limiters, chat (`HOOVER4_RATE_CHAT_PER_MINUTE`, default
40) and API (`HOOVER4_RATE_API_PER_MINUTE`, default 1000), each with a window ladder —
1 min at `X`, then 10 min / 30 min / 1 h / 6 h / 24 h at decaying factors (1.00 / 0.75
/ 0.50 / 0.30 / 0.20), every factor an env var, `0` disables a window. A request is
allowed only if every enabled window still has budget, so a burst is fine and sustained
abuse is not. Refusals are `429` with `Retry-After`. The limiter **fails open** on
internal errors. Counters are in-process — correct only while the website is one
container. Defaults, the measured numbers behind them, and the paste-ready env block
live in `main_services/ops/Readme.md`.

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
