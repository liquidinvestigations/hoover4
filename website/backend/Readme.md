# Website backend

The Rust server half of the Dioxus application: HTTP API, authentication, datastore access.

| path | holds |
|---|---|
| `src/api/` | endpoints grouped by feature, `search/`, `documents/`, `vfs/`, `chat/`, `admin/` |
| `src/auth/`, `src/db_auth/` | identity, sessions and the collection permissions they resolve to |
| `src/db_chat/` | chat persistence and the per-session turn lock |
| `src/db_utils/` | datastore clients, query builders, and the single place a full-text match argument is constructed |
| `tests/` | stack integration tests; fixture guard checks run without a live stack |
| `pdf-viewer/` | the viewer distribution this server hands to the client |

`target/` is this crate's build output, tens of gigabytes, and the reason every search here
must be scoped.

Two invariants worth knowing before touching anything here: one route mints a session and
every other endpoint requires one, and every full-text match argument goes through the shared
builder rather than being assembled at a call site.

## Workflow starts

Each route that starts a Temporal workflow calls `temporal_ready::wait_for_temporal()`
before its start request. This covers an operation start, the cancellation finalizer and a
chat or research turn. One monitor task starts at boot and probes Temporal's HTTP API every
1 s. A probe reads the system info, the namespace `default`, a list of one workflow and the
collector workflow `collect-eta-samples`. A 404 for the collector counts as good only when its `details` hold a
`NotFoundFailure`. The gate returns when every probe has been good for 5 s. After 60 s it
returns `Temporal did not stay ready for 5 s within 60 s, so the workflow was not started.
Last error: <text>`, and an operation start then writes its row `errored`. Each start request
goes through `temporal_ready::start_client()`, which has a 30 s timeout. The constants and the
text are mirrored in `main_services/processing/tasks/temporal_readiness.py`, and a unit test
in each runtime compares them when the other file is reachable.
