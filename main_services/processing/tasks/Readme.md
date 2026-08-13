# Processing Tasks

This directory contains Temporal workflows and activities that implement the multi-stage Hoover4 ingestion pipeline. Each stage is organized as a separate submodule and executed via worker queues defined in `run_worker.py`.

## Pipeline Stages

### P0 - Scan Disk

Discovers datasets on disk, enumerates files, and writes the virtual filesystem (VFS) tables:

- Top-level workflow: `IngestDiskDataset`
- Outputs: `vfs_files` and `vfs_directories` in ClickHouse

### P1 - Compute Plans

Builds processing plans from VFS statistics to chunk work into manageable batches.

### P2 - Execute Plan

Schedules plan chunks for distributed execution and manages temporary download and cleanup steps.

### P3 - Parse Files

Parses files by type (archives, email, PDF, audio, video, images, OCR, and Tika-based extraction) and writes structured content.

### P4 - Extract Entities (NLP/NER)

Runs named-entity recognition over parsed text content via the remote NER service, before indexing. Writes `entity_hit` rows and `nlp_processed` watermarks (including `text_bytes`). Texts are sent to the NER service in batches of `NLP_BATCH_TEXTS = 64`. NER failures are retried and then recorded in `processing_errors` — never silently swallowed.

A variant that is a worse copy of another variant of the same document is not sent to the
model at all (`text_sources.ner_reads_variant`: a mail file's MIME envelope beside its
parsed body), and `entity_stoplist` drops the values that are extraction debris rather
than entities — header names, encoding fragments, letter-spaced PDF headings.

### P5 - Chunk and Embed

Splits `text_content` pages into `text_chunks` and embeds them into `text_chunk_vectors`,
on `processing-embed-queue`. Chunking is deterministic and byte-addressed, which is what
makes the left-anti join against `text_chunk_vectors` a correct idempotency key.

**Chunks that are not language are not embedded.** Text extraction is greedy on purpose —
a parser that skips what it does not understand loses real documents — so it also yields
an email attachment's base64, an XPM colour table and an XBM byte dump as "page text".
`text_quality.non_linguistic_reason` holds those back before the embeddings call: it cost
GPU time to produce a vector that then won searches it had no business winning (live,
`search_collections("Eiffel Tower height")` returned an image's pixel rows as its top hit,
because noise is close to everything in embedding space). `text_content` still holds every
byte — this filters what is *embedded*, never what is stored, and the count comes back as
`chunks_skipped_non_linguistic` so a heuristic that starts eating real documents is visible
rather than silent.

The number was freed by renaming indexing to P6 — indexing genuinely runs last, and
inserting a stage before it would otherwise have meant either an out-of-order number or
a second rename later.

### P6 - Index Data

Aggregates metadata and text content into search indexes, reading the entity rows and watermarks written by P4. Pure I/O — no remote model calls.

Search indexes are sharded: a single planner activity (`plan_shards`, on
`processing-index-planner-queue`, exactly one worker process) assigns every document
to a shard, persisting the `manticore_shards` ledger and `manticore_shard_assignments`
in the collection database, and creates the Manticore tables `<collectionname>_<n>_pages`
/ `<collectionname>_<n>_meta`. A shard stays open until the next document would push it
over `MAX_SHARD_TEXT_BYTES = 1_000_000_000` (1 GB of extracted text), then it is sealed
and a new shard opens. Re-indexing overwrites documents in place — a document never
moves between shards and never appears in two shards.

## Administrative Workflows

### P_admin - Collection database lifecycle, purges, ETA sampling

Not a pipeline stage. Creates and drops the per-collection ClickHouse databases
(`Hoover4_Collection_<collectionname>`) on demand, purges soft-deleted datasets, and
runs `CollectEtaSamples` — the self-scheduling singleton that writes
`processing_eta_samples` for the admin processing page (100-event rates, items/s and
bytes/s combined pessimistically, 20x-cost throttle, finished collections skipped).
Runs on `processing-common-queue`. See [P_admin/Readme.md](P_admin/Readme.md).

### P_agent - Long-running AI research

`ResearchTask` runs the full research agent for one question and writes the answer back
into the chat, so the run survives a browser reload, a website restart and a worker
crash. Two activities on purpose: the agent call is slow and retryable, the write is fast
and keyed, so a retried agent call cannot leave half a transcript.

`trajectory.py` turns the agent's raw event list into transcript rows. It is the **Python
twin** of `pair_tool_calls` / `extract_doc_refs` in the website's
`api::chat::agent_client` and `common::chat_types` — the synchronous chat path is Rust in
the website and this one is Python in a worker, and neither can call the other. They must
agree, and for a while they did not: this path wrote `json.dumps(event)[:400]` as the
message body with the tool name hardcoded to `"tool"` and none of `tool_input` /
`tool_output` / `doc_refs` populated, so a research transcript rendered as a wall of JSON
in a card whose expand panel opened onto nothing. **If you change the event format, change
both.**

The one shape fact that catches everyone: there is **no tool name on a start event**. It
appears only at `output.name` on the end event, so events have to be paired before a call
can be labelled at all.

## Temporal visibility

Every workflow the pipeline starts — top-level submissions and child workflows alike —
carries the `CollectionDataset` keyword search attribute (`visibility.py`), registered
idempotently at every worker startup. The admin workflow browser filters on it, so
child workflows (`HandleFolders-<hash>`, per-plan runs) show up in a collection-scoped
query.

Registration alone is **not** sufficient: the Temporal frontend caches the attribute
list, so after a fresh `./deploy --reset` there is a window where the attribute is
provably registered yet workflow starts using it are still rejected with
`search attribute CollectionDataset is not defined`. Submitting processes
(`main.py add-disk-dataset`, the P0/P1/P2 `submit_job.py` paths) therefore call
`ensure_search_attributes_ready` and wrap the start in `start_with_attribute_retry`
— polling cannot close the frontend-cache window, only retrying the start can.

## Activity liveness and outbound HTTP

Every activity declares `heartbeat_timeout = HEARTBEAT_TIMEOUT` (30 s) at all 55 call
sites, and every activity body is wrapped in `@with_heartbeat` (`heartbeat.py`), which
beats every 15 s from a pump thread. The blanket wrap is deliberate: at a 30 s deadline,
any activity whose real work legitimately exceeds it (ffprobe on a large video, a
Manticore batch write) would otherwise be killed and retried forever. Activities with a
real loop additionally beat a `HeartbeatClock` inside it — evidence of forward progress,
not just a live thread. `threading`/`contextvars`/`time` are imported lazily inside the
helpers, never at module scope, because workflow modules import `HEARTBEAT_TIMEOUT` from
here and the workflow sandbox restricts those modules.

Outbound HTTP from activities (NER, OCR, embeddings) goes through
`remote.py`: `(connect, read)` two-tuple timeouts (`GPU_CONNECT_TIMEOUT_MS`, default
2 s connect), an ordered endpoint list with an optional CPU twin, and a per-endpoint,
time-boxed circuit breaker (`GPU_CIRCUIT_BREAK_SECONDS`). A connect failure falls back;
a read timeout does not. `RemoteResult.provider` records which endpoint actually served.

## Where processing time goes (`task_timing.py`)

Every worker installs `TaskTimingInterceptor` — a Temporal **activity inbound
interceptor** — so one row lands in the collection's `processing_task_runs` per activity
execution: task name, dataset, artifact hash, wall duration, outcome, attempt, queue and
worker process. The interceptor is the hook rather than the 55 call sites or
`@with_heartbeat` for one reason: it cannot be forgotten by the next activity someone
adds. `tests/unit/test_task_timing.py` asserts every `Worker(...)` installs it.

Three properties are load-bearing:

- **Failures are in the same table.** An activity that raises is recorded with
  `outcome = 'error'` and its real duration, so "where did the time go" includes the time
  spent failing and retrying. `processing_errors` still holds the stack traces — the two
  are joined on `(collection_dataset, hash)`, not merged.
- **Batched.** Rows buffer in-process and a daemon thread drains them every 5 s or every
  500 rows. A ~200k-file ingest is millions of executions, and one insert each would
  distort the measurement it is taking.
- **Never silent.** Instrumentation may not fail an ingest, so every write is wrapped —
  but every drop is logged with a count: a failed insert, an overflowing buffer, and the
  handful of activities whose parameters carry no `collectionname`
  (`ensure_temp_dir_exists`, `cleanup_temp_dir`, the P_agent chat activities), which
  cannot be routed to a collection database and are therefore not recorded at all.

The same thread samples what is *running* into `processing_task_inflight`, because a
finished-rows table cannot show the twenty-minute activity that has not finished yet.
Samples are levels, not counters: a reader takes the newest per worker and sums those.

Read it back with `main_services/task-time-report.sh` (per-task totals, shares, p95, wall
clock, achieved parallelism) or on `/admin/collections/<name>/processing`, which has both
the after-the-fact breakdown and a live view.

## The AI tier is optional

The website and pipeline degrade rather than hard-fail when the AI services are down:
P4 records `processing_errors` and continues with empty entities, and chat writes the
failure into the transcript. This is confirmed as wanted behaviour — do not add a
startup-time hard dependency on the AI tier.

## Worker Queues

Workers are split into dedicated queues to control throughput and resource usage:

- `processing-common-queue` — all workflows plus the common activities.
- `processing-tika-queue` — Tika parsing.
- `processing-ocr-queue` — OCR.
- `processing-nlp-queue` — P4 entity extraction against the remote NER service
  (`main.py worker nlp`, concurrency 2 — concurrency here pipelines HTTP, not local CPU).
- `processing-indexing-queue` — P6 Manticore writes.
- `processing-index-planner-queue` — P6 shard planning (`plan_shards`). MUST run at
  exactly one worker process: the planner does a read-modify-write on the shard ledger
  and assignments, which is only race-free when serialized.

## Database Routing

Every params dataclass that carries `collection_dataset` also carries `collectionname`.
It is resolved once at the workflow entry point (or CLI submission, e.g.
`main.py add-disk-dataset <collectionname> <dataset_name> <path>`) and threaded through
every child workflow and activity — never re-derived inside an activity. Activities open
per-collection ClickHouse clients with `get_collection_client(params.collectionname)`;
global tables (dataset registry, collections) use `get_global_client()`.

## Navigation

-  [Go Back](../Readme.md)