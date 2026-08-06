# P_admin - Collection administration

Administrative workflows: per-collection ClickHouse database lifecycle, dataset purges,
and the rolling ETA sampler for the admin processing page. Not a pipeline stage: these
run on demand (admin UI or CLI) or as a self-scheduling singleton, rather than as part
of ingestion.

## Key Responsibilities

- Provision a collection database (create if missing, then apply `db_collection_migrations/`).
- Drop a collection database when the collection is deleted.
- Purge a soft-deleted dataset's rows from its collection (Manticore shards and every
  collection-DB table with a `collection_dataset` column), then recompute the shard ledger.
- Collect ETA samples for the admin processing page (`CollectEtaSamples`).

The website backend never owns migration SQL; it triggers these workflows so the schema has
exactly one source of truth in Python.

## Entry Points

- Workflows: `EnsureCollectionDatabase`, `DropCollectionDatabase`, `PurgeDataset`,
  `CollectEtaSamples` in `workflows.py`
- Activities: `ensure_collection_database`, `drop_collection_database`,
  `purge_dataset_from_manticore`, `purge_dataset_from_clickhouse`,
  `recompute_shard_ledger_activity`, `collect_eta_samples` in `activities.py`
- ETA logic: `eta_collector.py` (SQL, rates, throttle — documented in its module docstring)
- Queue: `processing-common-queue`
- CLI: `main.py ensure-collection <collectionname>`
- Website: `api/admin/temporal_trigger.rs` kinds `ensure_collection` /
  `drop_collection_database` / `purge_dataset`

## The ETA estimate, in words

`CollectEtaSamples` is a singleton workflow (id `collect-eta-samples`, started at worker
bootstrap with `USE_EXISTING`). Each pass writes one row per (collection, dataset, stage)
into the global `processing_eta_samples` table (migration `00016`); the website only ever
*reads* that table — the expensive `uniqExact` scans never run in a request path.

- One rate per stage — P1 plan, P2/P3 execute, P4 NLP, P5 index — measured over the
  trailing **100 watermark events** (plans created, plans finished, segments
  NLP-processed, documents indexed), not over a wall-clock window.
- Each stage's rate is measured in every unit the schema offers: items/s (blobs, plans,
  segments, documents) and bytes/s (`blobs.blob_size_bytes`,
  `processing_plans.plan_size_bytes`, `nlp_processed.text_bytes`). P5 has no byte
  watermark, so documents/s is its only measure; P0 is not sampled at all (no timestamps,
  no knowable denominator — the live count stays on the stage bar).
- The remaining-time projections from the two units are combined by taking the **more
  pessimistic** (larger) one. A defensible simple rule: the units disagree most when item
  sizes are uneven, and an optimistic ETA hurts an admin more than a pessimistic one.
- Retries re-emit watermarks for work already counted, so every count is `uniqExact`
  over distinct watermark keys, never a row count. Recursion (archives fanning out into
  more blobs) raises the denominator mid-run, so `total` is re-read on every sample and
  never cached.
- Throttle: every pass is timed, the workflow keeps the last 10 pass durations, and waits
  at least **20 x mean(last 10)** before the next pass (floor 60 s). These queries scan
  the whole collection database; on a large collection one pass is seconds, and a naive
  poll would put the pipeline's own storage under load to report on the pipeline.
- A collection whose every stage is complete is skipped entirely — no queries, no sample
  rows. It is re-validated once every 5 minutes so a rescan of a "finished" collection
  gets fresh estimates again.

The estimate is a best-effort hint, not a scheduling promise, and the UI labels it as
one. The chart on the processing page plots estimated deadline against sample time: a
converging estimate reads as a flattening line, a sawtooth means it is wandering.

## Retry semantics (Q4) and the mutation caveat (Q10)

Retrying failed work **reopens the plans containing the failed documents** (deletes
their `processing_plan_finished` rows), clears the matching `processing_errors`, then
restarts `ExecutePlans`. The trap this avoids: a bare `ExecutePlans` restart is a no-op,
because a stage can record an error *without* failing the plan (P4 entity extraction is
the common case) — the plan still finishes and is then skipped as done. Any future retry
path must reopen the plan first. Reprocessing a whole plan to fix one document is coarse,
but the plan is the pipeline's unit of work and every stage is idempotent.

The retry deletes `processing_errors` rows with `ALTER TABLE ... DELETE`. ClickHouse
mutations are **asynchronous**, so a row can still appear in the failure list for a few
seconds after a retry. Accepted: it is the only way to remove rows from a plain
MergeTree. Do not re-file this as a bug.

## Technical Details

`ensure_collection_database` is idempotent - `clickhouse-migrations` keeps a `schema_versions`
table inside each database, so collections created at different times converge to the same
schema on the next run. `drop_collection_database` issues `DROP DATABASE IF EXISTS` and is
irreversible; `admin_delete_collection` gates it on the collection having no datasets and on
a typed confirmation in the UI.

## Navigation

- [Go Back](../Readme.md)
