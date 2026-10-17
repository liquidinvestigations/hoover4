# Website backend

The Rust server half of the Dioxus application: HTTP API, authentication, datastore access.

| path | holds |
|---|---|
| [src/api/](src/api) | endpoints grouped by feature, `search/`, `documents/`, `vfs/`, `chat/`, `admin/` |
| [src/auth/](src/auth), [src/db_auth/](src/db_auth) | identity, sessions and the collection permissions they resolve to |
| [src/db_chat/](src/db_chat) | chat persistence and the per-session turn lock |
| [src/db_utils/](src/db_utils) | datastore clients, query builders, and the single place a full-text match argument is constructed |
| [tests/](tests) | stack integration tests; fixture guard checks run without a live stack |
| [pdf-viewer/](pdf-viewer) | the viewer distribution this server hands to the client |

`target/` is this crate's build output, tens of gigabytes, and the reason every search here
must be scoped.

Every protected request requires an established identity.
[Session middleware](src/auth/session_middleware.rs) resolves the forwarded identity or an existing session cookie.
Website routes do not create sessions.
[The route policy](src/auth/route_policy.rs) defines the request requirements.
Every full-text match argument uses the [shared builder](src/db_utils/manticore_match.rs).

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
text are mirrored in [main_services/processing/tasks/temporal_readiness.py](../../main_services/processing/tasks/temporal_readiness.py), and a unit test
in each runtime compares them when the other file is reachable.

## Document processing state

The source response includes the document processing state.
One query reads its plan, completion, file errors, and latest listed operation.
An unfinished plan shows running only while its operation remains active.
An ended operation gives stopped and its recorded state.
A query failure remains an error beside any sources that loaded.
Table value and match queries exclude cells outside the current sheet dimensions.

## PDF source reading

PDF sources carry document page ranges from the current manifest.
The viewer requests one part through an access-checked route.
Borrowed OCR ranges resolve through the source manifest and its stored bucket.
Inline original ranges use `blob_values`.
PDF search reads each part and returns document page positions.
A partial source manifest uses the original or Office preview until all ranges exist.
A failed OCR manifest leaves other sources available and reports its error.

Complete multipart downloads use temporary files and qpdf with two concurrent assembly slots.
Cancellation stops qpdf and removes temporary files.
The response keeps temporary files until streaming ends or the client disconnects.
No complete multipart object is stored.
Retained direct OCR objects remain available for complete downloads.

The generated `HOOVER4_INTERNET_TOOLS_ENABLED` value limits chat and board internet settings.
Only an explicit true value permits internet tools. Stored enabled preferences also follow this deployment limit.
