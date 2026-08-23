# P_admin - Collection administration

Administrative workflows: per-collection ClickHouse database lifecycle, dataset purges,
the `change_ocr_languages` apply run, and the rolling ETA sampler for the admin processing
page. Not a pipeline stage: these run on demand (admin UI or CLI) or as a self-scheduling
singleton, rather than as part of ingestion.

## Key Responsibilities

- Provision a collection database (create if missing, then apply `db_collection_migrations/`).
- Drop a collection database when the collection is deleted.
- Purge a soft-deleted dataset's rows from its collection (Manticore shards and every
  collection-DB table with a `collection_dataset` column), then recompute the shard ledger.
- Report what such a purge would delete, per store and per table (`count_dataset_rows`),
  so a destructive command can say what it is about to do before it does it.
- Re-run a failed stage for the file hashes in `processing_errors`
  (`failed_file_retry.py`), which is the only recovery that does not re-ingest.
- Collect ETA samples for the admin processing page (`CollectEtaSamples`).
- Apply a dataset's new OCR languages end to end (`ChangeOcrLanguages`): write the
  settings, reopen the plans holding OCR candidates, re-run them, then purge the variants
  the change dropped — from ClickHouse, then Manticore, then Garage. The order is the
  point; `ocr_languages.py`'s module docstring says why each step cannot move.

The website backend never owns migration SQL; it triggers these workflows so the schema has
exactly one source of truth in Python.

## Entry Points

- Workflows: `EnsureCollectionDatabase`, `DropCollectionDatabase`, `PurgeDataset`,
  `ChangeOcrLanguages`, `CollectEtaSamples` in `workflows.py`
- Activities: `ensure_collection_database`, `drop_collection_database`,
  `purge_dataset_from_manticore`, `purge_dataset_from_clickhouse`,
  `recompute_shard_ledger_activity`, `collect_eta_samples` in `activities.py`
- OCR languages: `ocr_languages.py` (the variant diff, the purge, and the stage reports
  it merges into the operation row the admin form polls)
- ETA logic: `eta_collector.py` (SQL, rates, throttle — documented in its module docstring)
- File-level retry: `failed_file_retry.py` (which re-run recovers which task, and the
  ClickHouse reads and deletes it needs)
- Queue: `processing-common-queue`
- CLI: `main.py ensure-collection <collectionname>`, `main.py purge-dataset
  <collectionname> <collection_dataset> [--apply]`, `main.py retry-failed-files
  <collectionname> [--dataset X] [--task T] [--apply]`
- Website: every workflow here is reached as the child of an operation —
  `EnsureCollectionDatabase` and `DropCollectionDatabase` under the collection-lifecycle
  kinds, `PurgeDataset` under `purge_dataset` and `delete_dataset`, `ChangeOcrLanguages`
  under `change_ocr_languages`. Each run therefore carries the operation's timestamped id,
  which is what makes a second click run again: a reused id makes it a no-op, and two
  language changes are two different runs with two different before/after states.

## One run per dataset

The operations lock refuses a dispatch while a non-terminal `operations` row holds the same
kind and target. That row is also what the admin form polls, so what stops the second admin
is exactly what the first one can see. A stale row is *not* treated as free: a run that has
stopped reporting may still have activities in flight, and two workflows reopening the same
plans would purge each other's variants. Cancelling is what releases the lock early.

## The ETA estimate, in words

`CollectEtaSamples` is a singleton workflow (id `collect-eta-samples`, started at worker
bootstrap with `USE_EXISTING`). Each pass writes one row per (collection, dataset, stage)
into the global `processing_eta_samples` table (migration `00013`); the website only ever
*reads* that table — the expensive `uniqExact` scans never run in a request path.

- One rate per stage — P1 plan, P2/P3 execute, P4 NLP, P6 index — measured over the
  trailing **100 watermark events** (plans created, plans finished, segments
  NLP-processed, documents indexed), not over a wall-clock window.
- Each stage's rate is measured in every unit the schema offers: items/s (blobs, plans,
  segments, documents) and bytes/s (`blobs.blob_size_bytes`,
  `processing_plans.plan_size_bytes`, `nlp_processed.text_bytes`,
  `text_content.text_bytes`). P6 has no byte
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
  `continue_as_new` resets `passes` to 0 before carrying state into the next run, so the
  sleep remains reachable after the history bound.
- A collection whose every stage is complete is skipped entirely — no queries, no sample
  rows. It is re-validated once every 5 minutes so a rescan of a "finished" collection
  gets fresh estimates again.
- NLP byte totals come from `text_content.text_bytes` (and `nlp_processed.text_bytes` for
  the done side), never from `length(text)`. `text_bytes` is written at insert.
- `processing_eta_samples` retains rows for 3 days (`TTL sampled_at + INTERVAL 3 DAY`).
  The table is append-shaped (`ORDER BY` ends in `sampled_at`) so the admin processing
  page can still plot the newest 100 samples per stage.

The estimate is a best-effort hint, not a scheduling promise, and the UI labels it as
one. The chart on the processing page plots estimated deadline against sample time: a
converging estimate reads as a flattening line, a sawtooth means it is wandering.

## Retry semantics and the mutation caveat

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

`failed_file_retry.py` is the same recovery without the whole-plan cost, and it is what
`main.py retry-failed-files` drives. It re-runs the **stage** that failed for the
**hashes** that failed it: NER clears those hashes' `nlp_processed` watermarks (the only
reason P4 skips a page it has seen) and re-runs P4 + P6 for their plans, so the re-run
touches the failed documents and nothing else; index failures re-run P6; embedding
failures re-run P5 + P6; parse failures still need the whole plan, because they have no
per-file entry point that does not start by downloading the plan's blobs. Deletion order
is watermarks, then rows — a crash between the two leaves a page that is simply
re-extracted. Unlike the UI button it clears the error rows **after** the re-run and only
for the documents it can show are fixed.

**One `processing_errors` row per (document, task), however many retries it takes.** The
table is append-only and both `/file_browser/c/<name>` and the admin processing page count
its *rows*, so a retry that fails the same way and simply appends shows a visitor twice the
failures, and one more multiple on every further attempt. After the re-run each
retried hash is in exactly one of three states: recovered (its rows go), failed again with
a fresh row (the rows that row replaces go, the new one stays), or failed again with
nothing written because the run died first (the original row is the only evidence there is
and is left alone). A fresh error row outranks the stage's own verification: a document
that recorded a new failure is never counted as recovered.

## A finished plan is not a successful one

`processing_plan_finished` records that a plan's stages ran, not that every document
survived them. The admin processing page therefore counts failed documents per stage
(`api/admin/processing.rs::stage_for_task`) and a stage with any failures never renders
as complete — otherwise 4 792 documents can lose their entities to an NER outage while
every bar reads done.

## Technical Details

`ensure_collection_database` is idempotent - `clickhouse-migrations` keeps a `schema_versions`
table inside each database, so collections created at different times converge to the same
schema on the next run. `drop_collection_database` issues `DROP DATABASE IF EXISTS` and is
irreversible; `admin_delete_collection` gates it on the collection having no datasets and on
a typed confirmation in the UI.

## Navigation

- [Go Back](../Readme.md)
