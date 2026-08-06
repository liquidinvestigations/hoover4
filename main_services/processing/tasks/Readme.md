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

### P5 - Index Data

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
query; the attribute is also what makes a bare `reset-docker.sh` need no manual step.

## The AI tier is optional (Q11)

The website and pipeline degrade rather than hard-fail when the AI services are down:
P4 records `processing_errors` and continues with empty entities, and chat writes the
failure into the transcript. This is confirmed as wanted behaviour — do not add a
startup-time hard dependency on the AI tier.

## Worker Queues

Workers are split into dedicated queues to control throughput and resource usage:

- `processing-common-queue` — all workflows plus the common activities.
- `processing-tika-queue` — Tika parsing.
- `processing-easyocr-queue` — OCR.
- `processing-nlp-queue` — P4 entity extraction against the remote NER service
  (`main.py worker nlp`, concurrency 2 — concurrency here pipelines HTTP, not local CPU).
- `processing-indexing-queue` — P5 Manticore writes.
- `processing-index-planner-queue` — P5 shard planning (`plan_shards`). MUST run at
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