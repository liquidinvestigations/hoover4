# Website backend

The Rust server half of the Dioxus application: HTTP API, authentication, datastore access.

| path | holds |
|---|---|
| `src/api/` | endpoints grouped by feature — `search/`, `documents/`, `vfs/`, `chat/`, `admin/` |
| `src/auth/`, `src/db_auth/` | identity, sessions and the collection permissions they resolve to |
| `src/db_chat/` | chat persistence and the per-session turn lock |
| `src/db_utils/` | datastore clients, query builders, and the single place a full-text match argument is constructed |
| `tests/` | stack integration tests; they need a live stack |
| `pdf-viewer/` | the viewer distribution this server hands to the client |

`target/` is this crate's build output — tens of gigabytes, and the reason every search here
must be scoped.

Two invariants worth knowing before touching anything here: one route mints a session and
every other endpoint requires one, and every full-text match argument goes through the shared
builder rather than being assembled at a call site.
