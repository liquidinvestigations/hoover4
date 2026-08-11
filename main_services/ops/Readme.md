# Operations

This directory provides the runtime environment for Hoover4 main services. The `docker/` folder contains Docker Compose definitions and configuration overrides used to run processing dependencies.

## Serena (dev tooling, optional)

`docker/serena/` builds the Serena MCP server image and `docker/compose/serena.yaml` is
its optional overlay. Serena gives the host-side coding agent symbolic code navigation
(python + rust) over this repository. It can read and write the whole checkout, so it is
published on `127.0.0.1:21940` only. The repo is mounted at the identical absolute path
as on the host (`HOOVER4_REPO_ROOT`, set by `deploy.py`), and all language-server state
(venvs, cargo target/registry, Serena home) lives in the `serena_state` volume, never in
the checkout. Resets never remove that volume or the container. The MCP endpoint is
`http://127.0.0.1:21940/sse` (see `.mcp.json` at the repo root).

## Docker Compose Services

The stack includes:

- Workflow orchestration: Temporal with Cassandra and Elasticsearch backends, plus the Temporal UI.
- Primary data stores: ClickHouse for structured processing tables, Manticore for text search, MinIO for object storage, and Redis for auxiliary caching.
- Application services: the processing worker, the website, and the PDF-to-HTML renderer.
- Monitoring and admin UIs: ClickHouse monitoring and CH-UI.

## Common Endpoints (Local)

Ports are ini keys in `hoover4.ini` (rendered by `deploy.py`); the values below are the
defaults. The website stays on `12345`.

- Website: `http://localhost:12345`
- Temporal UI: `http://localhost:21909`
- Temporal gRPC / HTTP: `localhost:21907` / `http://localhost:21908`
- ClickHouse HTTP: `http://localhost:21900`
- ClickHouse Native: `localhost:21901`
- ClickHouse Monitoring: `http://localhost:21910`
- CH-UI: `http://localhost:21911`
- Manticore SQL: `localhost:21902`
- Manticore HTTP: `http://localhost:21903`
- MinIO Console: `http://localhost:21905` (`hoover4` / `hoover4-secret`)
- MinIO API: `http://localhost:21904`
- Redis: `tcp://localhost:21906`
- PDF-to-HTML renderer: `http://localhost:21920`

## Technical Details

This directory provides Docker Compose configuration and runtime overrides for the processing stack and its dependencies, including Temporal, ClickHouse, Manticore, MinIO, Redis, and supporting UIs.

Configuration lives in `hoover4.ini` at the repository root (see `hoover4.ini.example`);
`deploy.py` renders it into a generated `.env` in this directory — never edit that file
by hand. Deploy from the repo root with `./deploy` (see the root `Readme.md`); the base
`docker-compose.yaml` is the always-on core and `compose/*.yaml` are optional overlays
selected by ini flags.

## Manticore `_vectors` shards (HNSW)

Every logical shard has a third table, `<collection>_<n>_vectors`: the disposable HNSW
copy of ClickHouse `text_chunk_vectors` (the durable store). Two operational facts:

- **HNSW is RAM-resident.** 384 floats × 4 bytes ≈ 1.5 KB per chunk plus the graph
  overhead — call it ~2 KB per chunk. Budget a ceiling of a few million chunks per
  Manticore container: ten million chunks is well over 10 GB of Manticore memory, and
  the OOM killer does not ask which table. When memory gets tight, drop `_vectors`
  tables and rebuild them later from ClickHouse (`main.py reindex-collection
  <collection>`; ClickHouse keeps the vectors, so no re-embedding is needed).
- **`knn_dims` is fixed at table creation and cannot be altered.** Tables are created
  from the probed serving dimension (`server_settings.embeddings_serving_dim`), never
  the ini. Changing `embeddings_model` means dropping and rebuilding every `_vectors`
  shard (same `reindex-collection` path), and the P6 vector indexer refuses loudly —
  the activity fails and every affected document gets a `processing_errors` row — when
  the rows' dimension does not match a shard's `knn_dims`.

The shard byte budget (`MAX_SHARD_TEXT_BYTES`, 1 GB) counts **text bytes only**. With
per-variant fan-out a shard's real footprint is several times its budgeted size: each
OCR variant adds its own pages rows (Manticore disk), its own chunk rows (~1× the
corpus text, ClickHouse) and its own vectors (~2 KB per ~1.2 KB chunk, Manticore RAM).
Expect roughly 3–5× the ledger's `text_bytes` in total storage for a dataset with one
native and one OCR variant, more with more variants — do not be surprised by the shard
count.

KNN query shape, verified live against Manticore 14.1.0: attribute
filters in `WHERE` are applied **before** k selection (no over-fetch needed), and
`knn(embedding, K, (...))` bounds nothing by itself — the working shape is
`WHERE knn(embedding, K, (...)) ORDER BY <knn_dist alias> ASC LIMIT K`.

## Navigation

-  [Go Back](../Readme.md)
# Ops

## Docker

The docker containers start up the following services:

### Web Interfaces

- **Website**: [http://localhost:12345](http://localhost:12345) - the Hoover4 web UI
- **Temporal UI**: [http://localhost:21909](http://localhost:21909) - Temporal UI Dashboard
- **ClickHouse Monitoring**: [http://localhost:21910](http://localhost:21910) - ClickHouse monitoring dashboard
- **CH-UI (ClickHouse UI)**: [http://localhost:21911](http://localhost:21911) - ClickHouse web interface
- **Minio**: [http://localhost:21905](http://localhost:21905) - Minio S3 Dashboard
  - `hoover4` / `hoover4-secret`

### Processing services (HTTP, published on 127.0.0.1 only)

- **pdf-to-html**: `localhost:21920` - the PDF renderer used by the document viewer
- **tesseract-cpu**: `localhost:21921` - OCR over HTTP, `/health` lists the languages the
  image can actually serve
- **ocr-pdf**: `localhost:21922` - searchable-PDF assembly. Renders pages, calls the OCR
  tier above, writes the result under MinIO's `derived/` prefix with **no** `blobs` row
  (see `main_services/ocr_pdf/Readme.md` for why that absence is load-bearing)
- **ner-spacy**: `localhost:21923` - the CPU NER twin

### Search Engines

- **Manticore Search**: `localhost:21902` - Primary Manticore instance (SQL port)
- **Manticore Search HTTP**: [http://localhost:21903](http://localhost:21903) - Primary Manticore HTTP API

### Database Connections

- **Redis**: `localhost:21906` - Redis database (TCP, not HTTP)
- **ClickHouse Native**: `localhost:21901` - ClickHouse native protocol
- **ClickHouse HTTP Interface**: [http://localhost:21900](http://localhost:21900) - ClickHouse database HTTP API
- **Temporal**: `localhost:21907` - Temporal workflow engine
- **Temporal Cassandra**: `localhost:21912` - Temporal's Cassandra database
- **Temporal Elasticsearch**: [http://localhost:21913](http://localhost:21913) - Elasticsearch REST API

## Rate-limit environment (paste into the `hoover4-website` service)

The website rate limiter (`website/backend/src/api/rate_limit.rs`) defaults every knob
in Rust, so the stack runs unconfigured. These are the same names and values, ready to
paste into `docker/docker-compose.yaml` for the integrator to tune — **the block is not
in the compose file**, deliberately, so the Rust defaults stay the single source of truth
until someone needs to override them.

```yaml
    environment:
      # Chat messages per minute per user. Default 40: ~10x the fastest
      # substantive agent turn measured on the dev GPU (16.2 s for a full
      # research turn; a degenerate 4.4 s list_collections turn was ignored as
      # not a real question). Production hardware should re-measure.
      HOOVER4_RATE_CHAT_PER_MINUTE: "40"
      # API (server-function) calls per minute per user, guests included.
      # Default 1000. Measured baseline on this host: a scripted 5-minute
      # flood of representative calls (search + admin + document fetches)
      # recorded 1380 api_events = 276 calls/min sustained; a realistic
      # human sweep of every route is ~100 calls total. 1000 is ~10x the
      # human sweep and ~3.6x even the scripted flood.
      HOOVER4_RATE_API_PER_MINUTE: "1000"
      # Window ladder factors: budget in a window is X * minutes * factor, so
      # the sustained rate decays the longer the burst lasts. 0 disables the
      # window. Defaults shown.
      HOOVER4_RATE_CHAT_W10M_FACTOR: "1.00"
      HOOVER4_RATE_CHAT_W30M_FACTOR: "0.75"
      HOOVER4_RATE_CHAT_W1H_FACTOR: "0.50"
      HOOVER4_RATE_CHAT_W6H_FACTOR: "0.30"
      HOOVER4_RATE_CHAT_W24H_FACTOR: "0.20"
      HOOVER4_RATE_API_W10M_FACTOR: "1.00"
      HOOVER4_RATE_API_W30M_FACTOR: "0.75"
      HOOVER4_RATE_API_W1H_FACTOR: "0.50"
      HOOVER4_RATE_API_W6H_FACTOR: "0.30"
      HOOVER4_RATE_API_W24H_FACTOR: "0.20"
```

`HOOVER4_RATE_CHAT_POLL_*` exists too, and its ladder is **flat** — every window factor
defaults to `1.00` rather than decaying. Polling is machine-paced: a tab watching a
streaming answer polls at the 500 ms floor for as long as the model generates, so for
that limiter "sustained" is simply "working". Under the decaying ladder one tab sat
exactly on the 1 h window's ceiling and two tripped it, at which point the page declared
the chat lost mid-turn. The per-minute default is 600 (~5 streaming tabs); the expensive
half of a poll, the held request, has its own separate cap.

The counters are **in-process** (a `Mutex<HashMap>` in the website, pruned on access),
correct only while the website is a single container. Redis was considered and rejected
for now: the container runs with `--maxmemory-policy allkeys-lru`, which would silently
evict counters under memory pressure — a limiter that quietly stops limiting is worse
than none. Scaling the website out needs a shared store, and that is the point at which
Redis gets its own database index and eviction policy.

How to re-measure the API baseline once `api_events` is recording:

```bash
docker exec clickhouse clickhouse-client -u hoover4 --password hoover4 \
  -q "SELECT count() FROM Hoover4_Processing.api_events WHERE event_ts >= now() - INTERVAL 5 MINUTE"
```

Drive a browser across every page as fast as possible for 5 minutes, read the count,
and set `HOOVER4_RATE_API_PER_MINUTE` to 10x that rate (count / 5 * 10). The baseline
above was measured this way (scripted flood, 1380 calls / 5 min).

## How the website is served: `dx serve` vs a release build

`website_release_mode` in `hoover4.ini` picks between the two. It is `false` by default.

| | `false` — `dx serve` | `true` — `compose/website-release.yaml` |
|---|---|---|
| build | on start, and again on every source change | once, at boot |
| dev overlay | "Your app is being rebuilt." on every page | none |
| CORS | `access-control-allow-origin: *` added by the proxy | only what the app sets (nothing) |
| after a container recreate | every route 500s until the build finishes | same wait, then a clean site |
| editing code | hot rebuild | needs a restart |

**This is not a preference, it is a demo-versus-development split.** `dx serve` is a
development server and behaves like one in front of visitors — the toast is baked into
the served HTML for every fresh profile, not a session-local nag, and the boot rebuild
was observed 500ing `/admin/ai_status` for about five minutes. A visitor should get the
release build; whoever is writing the code should not.

Two related fixes landed with it:

* **The dx CLI version must equal the `dioxus` version in `Cargo.lock`** (0.7.9 today).
  A mismatch prints `ERROR 🚫dx and dioxus versions are incompatible!` at every boot and
  means the two halves disagree about the built app's manifest format.
* **The build-cache volume was mounted one directory too deep**
  (`/app/frontend/target`, while the workspace manifest is at `/app`, so cargo writes to
  `/app/target`). The named volume held nothing and the 3 GB build tree lived in the
  container's writable layer — which is precisely why recreating the container cost a
  multi-minute cold rebuild. Now mounted at `/app/target`.

### Known: the first release boot is a cold build

Switching `website_release_mode` on for the first time compiles the workspace in release
mode inside the container, with an empty release profile in the target volume. That is
minutes, and the site is down for all of them. Watch `docker logs -f hoover4-website`;
it prints `[website] release build starting` and then `[website] serving <path>`. If the
server binary cannot be found afterwards the container prints the tree it searched and
exits, rather than serving a blank page.
