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
- Primary data stores: ClickHouse for structured processing tables, Manticore for text search, Garage for object storage, and Redis for auxiliary caching.
- Application services: the processing worker, the website, and the PDF-to-HTML renderer.
- Monitoring and admin UIs: ClickHouse monitoring and CH-UI.

### Temporal's throughput knobs

Two settings decide how fast the cluster will hand work to the pipeline, and both ship
from the `auto-setup` image sized for a single-workflow demo.

`persistence.numHistoryShards` comes from `NUM_HISTORY_SHARDS`, rendered from
`[main_services] temporal_history_shards`. A history shard is a single-writer queue, so
their number caps every workflow-history write in the deployment regardless of how many
cores or worker processes exist. At the image default of 4 the pipeline dispatches about
a dozen activities a second while the workers consume a fraction of one core, and every
task type's queue wait shares the same p99 — the signature of a fleet that is waiting on
the server rather than on itself. **The count is fixed for the life of the persistence
store**: the server refuses to open a keyspace initialised with a different one.
`deploy.py` preflights the running cluster against the ini and names both numbers rather
than letting the server die with a Cassandra error, and `./deploy --reset-temporal` drops
Temporal's Cassandra keyspace and Elasticsearch index so a new count can take. That reset
loses workflow history, which retention already caps at 24 h with archival off, and
touches no other volume.

`temporal-dynamicconfig/` is bind-mounted over `/etc/temporal/config/dynamicconfig/`,
whose `docker.yaml` the image ships as a zero-byte file. The DIRECTORY is mounted, not
the file: a single-file bind mount follows the inode it was created with, so any editor
that writes-and-renames leaves the container silently reading the old contents. The file
is deliberately near-empty — measured against this pipeline, raising the task-queue
partition counts above their default of 4 made a fan-out across many concurrent
workflows slower, and `history.persistenceMaxQPS` already defaults above anything worth
writing there, so setting it would throttle rather than lift.

### Docker Compose rejects YAML podman-compose accepts

A duplicate mapping key is the one that bites: podman-compose takes the file and runs,
Docker Compose refuses it with `mapping key "driver" already defined`. The usual way to
create one is an edit that removes a volume's or service's name line and leaves the
indented line under it to attach to whatever came before. `deploy.py` preflights every
compose file it is about to use with a loader that rejects duplicates — note that
PyYAML's own `safe_load` does not, it silently keeps the last one — so the failure is
named on both hosts instead of only on the Docker one.

### `memswap_limit` is not the total here

Every service in this file sets `mem_limit` and `memswap_limit` to the same value.
Under Docker that spells "this much memory and no swap"; under podman-compose it does
not — the rendered container gets `MemorySwap = 2 x Memory`, i.e. that much RAM *plus*
that much swap. Nothing depends on the stricter reading today, but do not add something
that does without checking the container rather than the file:

```
docker inspect <container> --format '{{.HostConfig.Memory}} {{.HostConfig.MemorySwap}}'
```

`deploy.resources.limits`, which six services in this file still use, is ignored
entirely by the v2 compose spec outside Swarm — those services have no limit at all.

### Reading memory on the JVM services

`temporal-cassandra` runs with `MAX_HEAP_SIZE=4G` and `HEAP_NEWSIZE=512M`, and a JVM
commits its whole heap at startup. `docker stats` therefore reports the container at
almost its full memory limit from boot onwards, idle or not, and that number says nothing
about pressure. `temporal-elasticsearch` behaves the same way.

Ask the process instead:

```
docker exec temporal-cassandra nodetool info      # Heap Memory (MB): used / max
docker exec temporal-cassandra nodetool gcstats   # Total GC Elapsed vs uptime
docker exec temporal-cassandra nodetool tpstats   # dropped messages, per stage
```

A healthy node uses a small fraction of its heap, spends well under 1% of wall time in
GC, and drops nothing. If a container-side figure is wanted, read `anon` from
`/sys/fs/cgroup/memory.stat` — the `docker stats` total counts reclaimable page cache as
usage.

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
- Garage S3 API: `http://localhost:21904`
- Garage admin API: `http://127.0.0.1:21905` (no console; see `docker/garage/Readme.md`)
- Redis: `tcp://localhost:21906`
- PDF-to-HTML renderer: `http://localhost:21920`

## Technical Details

This directory provides Docker Compose configuration and runtime overrides for the processing stack and its dependencies, including Temporal, ClickHouse, Manticore, Garage, Redis, and supporting UIs.

Configuration lives in `hoover4.ini` at the repository root (see `hoover4.ini.example`);
`deploy.py` renders it into a generated `.env` in this directory — never edit that file
by hand. Deploy from the repo root with `./deploy` (see the root `Readme.md`); the base
`docker-compose.yaml` is the always-on core and `compose/*.yaml` are optional overlays
selected by ini flags.

[deployment.md](deployment.md) is the runbook for a host with a public IP: the
`website_bind_ip` / `infra_bind_ip` keys and what they protect, a worked no-GPU
`hoover4.ini`, the reset order, the staged ingest and the post-deploy assertions.

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

## Two facts about taking a Manticore table off this container

Both cost time the first time and neither is discoverable from the error.

- **`manticore-backup` needs `/etc/manticoresearch/manticore.conf.sh`, not
  `manticore.conf`.** Pointed at the latter it fails with a message about certificates
  and `max_connections`, which names neither the file nor the real cause: the tool takes
  the **first** `listen =` line it finds, and that file's first one is the binary
  protocol port. The `.conf.sh` variant lists the SQL port first.

- **`DROP TABLE` leaves the table's directory and a stale `.lock` behind.** It
  unregisters the table; it does not clean up after it. The data directory accumulates
  orphaned directories from every dropped table — the stack tests alone leave dozens of
  `test_x*` — and, more importantly, `IMPORT TABLE` refuses to import over one. Anything
  restoring a table has to remove the leftover directory first, or the restore fails
  naming a path that, as far as `SHOW TABLES` is concerned, belongs to nothing.

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
- **Garage admin API**: `http://127.0.0.1:21905` - cluster status over curl; there is no console
  - `hoover4` / `hoover4-secret`

### Processing services (HTTP, published on 127.0.0.1 only)

- **pdf-to-html**: `localhost:21920` - the PDF renderer used by the document viewer
- **tesseract-cpu**: `localhost:21921` - OCR over HTTP, `/health` lists the languages the
  image can actually serve
- **ocr-pdf**: `localhost:21922` - searchable-PDF assembly. Renders pages, calls the OCR
  tier above, writes the result under the blob store's `derived/` prefix with **no** `blobs` row
  (see `main_services/ocr_pdf/Readme.md` for why that absence is load-bearing)
- **ner-spacy**: `localhost:21923` - the CPU NER twin, only when
  `[main_services] ner_spacy_enabled = true` (off by default)

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
