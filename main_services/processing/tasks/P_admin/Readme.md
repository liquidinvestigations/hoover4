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
- Select historical Error rows for retry, then reconcile those rows after plan execution
  (`failed_file_retry.py`).
- Collect ETA samples for the admin processing page (`CollectEtaSamples`).
- Apply a dataset's new OCR languages end to end (`ChangeOcrLanguages`): write the
  settings, reopen the plans holding OCR candidates, re-run them, then purge the variants
  the change dropped, from ClickHouse, then Manticore, then Garage. The order is the
  point; `ocr_languages.py`'s module docstring says why each step cannot move.
- Bring every OCR target of a dataset to done with unchanged settings (`RerunOcr`, the
  "Run OCR" button). See "Run OCR" below.

The website backend never owns migration SQL; it triggers these workflows so the schema has
exactly one source of truth in Python.

## Entry Points

- Workflows: `EnsureCollectionDatabase`, `DropCollectionDatabase`, `PurgeDataset`,
  `ChangeOcrLanguages`, `RerunOcr`, `OcrRunPlan`, `CollectEtaSamples` in `workflows.py`
- Activities: `ensure_collection_database`, `drop_collection_database`,
  `purge_dataset_from_manticore`, `purge_dataset_from_clickhouse`,
  `recompute_shard_ledger_activity`, `collect_eta_samples` in `activities.py`
- Run OCR: `ocr_rerun.py` (the activities `record_ocr_run_targets`,
  `list_ocr_run_plans`, `load_ocr_run_plan`, `settle_ocr_run_targets`,
  `ocr_text_pending_index` and `verify_ocr_run_completion`), the `OcrRunPlan` workflow in
  `workflows.py`, and the target rule in `tasks/ocr_targets.py`
- OCR languages: `ocr_languages.py` (the variant diff, the purge, and the stage reports
  it merges into the operation row the admin form polls)
- ETA logic: `eta_collector.py` (SQL, rates and throttle, documented in its module docstring)
- Error selection: `failed_file_retry.py` (the ClickHouse reads and deletes that prepare
  selected Error rows for plan execution)
- Collection backfill: `collection_backfill.py` clears unattributed entities once and
  returns finished plans in pages of at most 100.
- Queue: `processing-common-queue`
- CLI: `main.py ensure-collection <collectionname>`, `main.py purge-dataset
  <collectionname> <collection_dataset> [--apply]`, `main.py retry-failed-files
  <collectionname> [--dataset X] [--task T] [--apply]`
- Website: every workflow here is reached as the child of an operation:
  `EnsureCollectionDatabase` and `DropCollectionDatabase` under the collection-lifecycle
  kinds, `PurgeDataset` under `purge_dataset` and `delete_dataset`, `ChangeOcrLanguages`
  under `change_ocr_languages`, `RerunOcr` under `rerun_ocr`. Each run therefore carries the operation's timestamped id,
  which is what makes a second click run again: a reused id makes it a no-op, and two
  language changes are two different runs with two different before/after states.

## Run OCR

`RerunOcr` makes no OCR request for a target that is already done. `tasks/ocr_targets.py`
defines the targets and the done rule. A run has these steps.

1. It runs the unfinished plans and the blobs without a plan through `ExecutePlans`, with
   every stage. A file in such a plan gets its OCR there.
2. `record_ocr_run_targets` writes each open target to `ocr_run_targets` under the
   operation id. From this point the operation's progress counts these rows.
3. `list_ocr_run_plans` reads the plans with an open target, in pages of 1,000. The run
   continues as new after each full page.
4. One `OcrRunPlan` child runs for each plan, at most 16 at a time. It downloads only the
   files with an open target and runs the preview, image OCR and PDF stages on them. Then
   it runs P4, P5 and P6 for the files whose new OCR text needs indexing, and settles the
   targets.
5. After the last page, the run refreshes the entity terms and compacts the shards.
6. `verify_ocr_run_completion` fails the run with `OcrRunIncomplete` while a target stays
   open. The error names at most five open targets.

New OCR text adds index targets during the run, so the progress total can increase. A
second press records the targets again and finds only the open ones. A cancelled run
leaves its stored results, and the next run continues from them. An OCR error newer than
the language setting settles its target. "Retry" on the processing page repeats those
files. A setting version copied from the earlier whole-second
column has no finer order. An error in the same second as such a setting counts as current.

An execution that started before the `run-ocr-targets` patch replays the earlier commands,
which reopen the plans and run `ExecutePlans`.

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
*reads* that table. The expensive `uniqExact` scans never run in a request path.

- Each stage measures its rate across the latest 100 distinct completion timestamps.
  Each timestamp includes all its distinct watermarks.
  Large completion batches therefore retain earlier timestamps in the rate sample.
  One timestamp alone gives no estimate because it has no measurable time span.
- Each stage's rate is measured in every unit the schema offers: items/s (blobs, plans,
  segments, documents) and bytes/s (`blobs.blob_size_bytes`,
  `processing_plans.plan_size_bytes`, `nlp_processed.text_bytes`,
  `text_content.text_bytes`). P6 has no byte
  watermark, so documents/s is its only measure; P0 is not sampled at all (no timestamps,
  no knowable denominator. The live count stays on the stage bar).
- The remaining-time projections from the two units are combined by taking the **more
  pessimistic** (larger) one. A defensible simple rule: the units disagree most when item
  sizes are uneven, and an optimistic ETA hurts an admin more than a pessimistic one.
- Retries re-emit watermarks for work already counted, so every count is `uniqExact`
  over distinct watermark keys, never a row count. Recursion (archives fanning out into
  more blobs) raises the denominator mid-run, so `total` is re-read on every sample and
  never cached.
- Throttle: every pass is timed, the workflow keeps the last 10 pass durations, and waits
  at least **20 x mean(last 10)** before the next pass (floor 300 s). These queries scan
  the whole collection database; on a large collection one pass is seconds, and a naive
  poll would put the pipeline's own storage under load to report on the pipeline.
  `continue_as_new` resets `passes` to 0 before carrying state into the next run, so the
  sleep remains reachable after the history bound.
- A collection whose every stage is complete is skipped entirely, no queries, no sample
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

The selector stores class events and a `selection_complete` marker before it changes state.
The marker stores the filtered count. A retry uses the complete snapshot.
The selector clears NLP and regex state and reopens selected plans.

Reconciliation requires a matching document outcome and an `ok` or `skipped` task run to count recovery.
It deletes older Error rows for every selected pair and every pair with a current Error.
Supported unresolved pairs count as still failing. Unsupported task names count separately.
ClickHouse mutations use `mutations_sync = 2`.

## A finished plan is not a successful one

`processing_plan_finished` records that a plan's stages ran, not that every document
survived them. The admin processing page therefore counts failed documents per stage
(`api/admin/processing.rs::stage_for_task`) and a stage with any failures never renders
as complete, otherwise 4 792 documents can lose their entities to an NER outage while
every bar reads done.

## Technical Details

`ensure_collection_database` is idempotent - `clickhouse-migrations` keeps a `schema_versions`
table inside each database, so collections created at different times converge to the same
schema on the next run. `drop_collection_database` issues `DROP DATABASE IF EXISTS` and is
irreversible; `admin_delete_collection` gates it on the collection having no datasets and on
a typed confirmation in the UI.

## Navigation

- [Go Back](../Readme.md)

The ETA collector skips collections without active operations.
It counts the NER stage as complete when NER is disabled.
Text byte totals use each segment's latest version.
