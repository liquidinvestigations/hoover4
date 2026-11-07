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
  ([failed_file_retry.py](failed_file_retry.py)).
- Collect ETA samples for the admin processing page (`CollectEtaSamples`).
- Apply a dataset's new OCR languages end to end (`ChangeOcrLanguages`): write the
  settings, reopen the plans holding OCR candidates, re-run them, then purge the variants
  the change dropped, from ClickHouse, then Manticore, then Garage. The order is the
  point; [ocr_languages.py](ocr_languages.py)'s module docstring says why each step cannot move.
- Bring every OCR target of a dataset to done with unchanged settings (`RerunOcr`). The
  OCR step of a processing update runs it. See "Run OCR" below.
- Bring the stored results of each dataset and collection up to date after a version,
  setting or input change (the processing updates in [updates/](updates)). See
  "Processing updates" below.

The website backend never owns migration SQL; it triggers these workflows so the schema has
exactly one source of truth in Python.

## Entry Points

- Workflows: `EnsureCollectionDatabase`, `DropCollectionDatabase`, `PurgeDataset`,
  `ChangeOcrLanguages`, `RerunOcr`, `OcrRunPlan`, `CollectEtaSamples` in [workflows.py](workflows.py)
- Processing updates: `ProcessingUpdates`, `RunProcessingUpdate` and `UpdateDatasetVectors`
  in [updates/workflows.py](updates/workflows.py), the steps in [updates/registry.py](updates/registry.py), the counts and
  settlement reads in [updates/selectors.py](updates/selectors.py), and the stage versions in
  [tasks/stage_versions.py](../stage_versions.py)
- A file that a table reader or the OCR detector cannot process stays selected by its update step,
  and settlement reports it. The other files of its plan continue. A service failure keeps its
  Temporal retry.
- Activities: `ensure_collection_database`, `drop_collection_database`,
  `purge_dataset_from_manticore`, `purge_dataset_from_clickhouse`,
  `recompute_shard_ledger_activity`, `collect_eta_samples` in [activities.py](activities.py)
- Run OCR: [ocr_rerun.py](ocr_rerun.py) (the activities `record_ocr_run_targets`,
  `list_ocr_run_plans`, `load_ocr_run_plan`, `settle_ocr_run_targets`,
  `ocr_text_pending_index` and `verify_ocr_run_completion`), the `OcrRunPlan` workflow in
  [workflows.py](workflows.py), and the target rule in [tasks/ocr_targets.py](../ocr_targets.py)
- OCR languages: [ocr_languages.py](ocr_languages.py) (the variant diff, the purge, and the stage reports
  it merges into the operation row the admin form polls)
- ETA logic: [eta_collector.py](eta_collector.py) (SQL, rates and throttle, documented in its module docstring)
- Error selection: [failed_file_retry.py](failed_file_retry.py) (the ClickHouse reads and deletes that prepare
  selected Error rows for plan execution)
- Collection backfill: [collection_backfill.py](collection_backfill.py) clears unattributed entities once and
  returns finished plans in pages of at most 100.
- Queue: `processing-common-queue`
- CLI: `main.py ensure-collection <collectionname>`, `main.py purge-dataset
  <collectionname> <collection_dataset> [--apply]`, `main.py retry-failed-files
  <collectionname> [--dataset X] [--task T] [--apply]`
- Website: every workflow here is reached as the child of an operation:
  `EnsureCollectionDatabase` and `DropCollectionDatabase` under the collection-lifecycle
  kinds, `PurgeDataset` under `purge_dataset` and `delete_dataset`, `ChangeOcrLanguages`
  under `change_ocr_languages`, `RerunOcr` under `rerun_ocr`, and `RunProcessingUpdate`
  under `update_dataset` and `update_collection`. The admin pages no longer start
  `change_ocr_languages` and `rerun_ocr`. The kinds stay for the CLI and for history. Each run therefore carries the operation's timestamped id,
  which is what makes a second click run again: a reused id makes it a no-op, and two
  language changes are two different runs with two different before/after states.

## Run OCR

New plan workflows recover stored text once before they read file descriptors in pages of 100.
They run at most three pages concurrently, with a separate temporary directory for each page.
This bound includes both PDF engines, image stages, and error recording in the workflow command budget.
PDF cursor children read stored part metadata and keep repeated part activity events out of the plan history.
Completion failures include at most five remaining file, stage, engine, and language identities.
Earlier workflow branches retain the complete descriptor activity and its original result schema.

`RerunOcr` makes no OCR request for a target that is already done. [tasks/ocr_targets.py](../ocr_targets.py)
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

## Processing updates

A processing update brings the stored results of existing data to what the current code,
settings and inputs produce. The admin dataset page and the collection page show the
steps, the counts, and the "Update processing" or "Update collection" button. The steps
are in [updates/registry.py](updates/registry.py), in run order.

| Step | Scope | Selects | Work | Settles when |
|---|---|---|---|---|
| `search_schema` | collection | Search tables that miss a column of the current page schema | `ALTER TABLE ADD COLUMN`. A type difference rebuilds the collection index. | No search table differs from the schema. |
| `unfinished` | dataset | Unfinished plans and live files without a plan | `ExecutePlans` with every stage | No unfinished plan or file without a plan remains. |
| `failed_files` | dataset | Files with a current processing error | The historical error selection, `ExecutePlans` on the failed stages, then the reconciliation | The reconciliation recorded the outcome of each selected pair. |
| `virus_scan` | dataset | With `clamav_enabled` on: live files of at most 500 MiB without a completed scan, except files whose last attempt is `skipped_size` or `incomplete`. Earlier `failed` and `skipped_disabled` attempts are selected. | `UpdateDatasetVirusScan`: `scan_update_files` for each plan on the ClamAV queue, then `stale_virus_attributes` lists the files whose search rows hold another `virus_hit` than their verdict, `IndexDatasetPlan` writes those rows again, and `retire_cached_searches` changes the search cache epoch | No selected file remains, and no search row of an infected file has `virus_hit` 0. |
| `tables` | dataset | Earlier or failed table readings, missing JSON or delimited readings, and published tables without complete matching receipts | `UpdateDatasetTables` resumes parsing, entities, signals, embedding, and both indexes for the published generation | Every selected file has complete matching output receipts. |
| `archive_members` | dataset | Successful split archives without a current complete manifest receipt | Re-extract, scan, reconcile removed descendants, and finish dependent processing | Current manifest receipts are complete. |
| `image_previews` | dataset | Live uncommon images without a published preview, except files with a `preview_undecodable_` skip | Create and read each missing preview without repeating settled OCR | No selected preview remains missing. |
| `ocr` | dataset | Files without OCR text for the effective languages, and text of removed languages | `RerunOcr`, then the purge of dropped variants and orphaned searchable PDFs | No variant of a removed language remains. |
| `pdf_text` | dataset | Files with a searchable PDF part of text layer version 1 for a current language pass that the PDF builder can build | `scan_pdf_text_layers` gives version 2 to the parts of language passes with Windows-1252 alphabets, to borrowed parts, and to parts whose `pdftotext` text has no black square. It removes the other parts, sets their variant to `text_complete = 0` and the `overlay` form, then `RerunOcr` builds the removed parts again. | No part of version 1 remains, and no removed part is without a new part. |
| `entities` | dataset | Earlier provider completion, missing current text coverage, or missing searchable publication | `UpdateDatasetEntities` lists 1,600 files, runs batches of 100 with up to 4 at once, replaces NER attributes, and writes the dataset terms once after the last batch | Current source completion and verified search receipts exist. |
| `text_rows` | dataset | Sources with `segment_version` 0 and more than one row, a PDF source that starts after page 1, or old rows beside rows of the current split | `UpdateDatasetTextRows`, which runs `rewrite_text_rows`, then P4, P5 and P6 on each plan | Every selected source has rows of the current split |
| `page_text` | dataset | Pages whose stored text has a NUL byte and whose index row differs from the current indexed text | `rewrite_page_text` replaces each such row and keeps its attributes. | No such row remains. |
| `vectors` | dataset | Files with text and no vectors of the served embedding model | `UpdateDatasetVectors`, which runs P5 and P6 vectors on 4 plans at a time | Each selected plan ran. |
| `folder_counts` | dataset | Folders without counts, or every folder when the stage version is newer than the applied one | `build_vfs_nodes` | No folder lacks counts. |
| `search_terms` | dataset | The applied term-index version is absent or earlier. | `index_entity_terms` publishes the current filter terms. | Each expected term has its current identity and value in the search table. |

The first observed stage version remains its baseline.
Historical archive errors on a direct release upgrade require explicit retry.
Successful old split archives use the separate member-reconciliation step.
An archive error clears only after a complete empty extraction or successful member scanning supplies matching operation evidence.

The state is in five global tables of migration `00051`.

- `processing_update_checks` holds the desired fingerprint and the counts of each step.
  The row with an empty `step_id` holds the totals of the scope.
- `processing_update_attempts` holds one row for each operation and step. Its
  `row_version` orders the states, so a late progress write cannot replace a terminal
  state.
- `processing_update_applied` holds the fingerprint of the last output that settled.
- `processing_retry_claims` holds each `(dataset, stage, version)` that a failed files
  step retried.
- `stage_versions` holds the version of each canonical stage, and whether the row is
  the first record of the stage (`baseline`).

The desired fingerprint of a step joins the step version, the versions of its stages,
its target (`target_key`) and the input revision for steps that declare this dependency.
These steps include `unfinished`, `failed_files`, `ocr`, and `ocr_detection`. The input revision is the newest terminal operation of the dataset or its
collection that is not an update. A new ingestion or an interrupted run therefore makes
these steps calculate again without a version change.

The coordinator `ProcessingUpdates` (id `processing-updates`) compares the fingerprints
every 2 minutes, and at once on a `request_check` signal. A settings save and "Check
again" send the signal. Only a changed fingerprint, or a request, runs the count queries
of a scope. A step with no automatic work records its fingerprint as applied and starts
no operation. When `[processing_updates] automatic` is true, the coordinator starts one
automatic operation at a time across the installation, collections first. A dataset
step that writes to the search index waits until the collection steps are applied. An
attempt that failed or was cancelled at a fingerprint does not start again automatically.
The button stays available for a manual run.

`RunProcessingUpdate` first recalculates the requested steps. It refuses a manual request
whose fingerprint changed (`ProcessingUpdatePreviewStale`), an empty or unknown step list
(`ProcessingUpdateInvalidRequest`), and a dataset request whose collection steps are not
applied (`ProcessingUpdatePrerequisitePending`). It then runs the steps in order. The
applied row gets the fingerprint of the snapshot, so a setting changed during the run
leaves the step waiting. A step that fails is recorded, and the next step runs.

The automatic failed files step retries a stage once for each new stage version. A
stage at its first recorded version (`baseline`) has no automatic retry. A manual retry
also writes the claim. Raise a stage version in [tasks/stage_versions.py](../stage_versions.py) with the
procedure in [.agents/rules/processing-versions.md](../../../../.agents/rules/processing-versions.md).

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

## Plan completion can include document errors.

`processing_plan_finished` records that a plan's stages ran, not that every document
survived them. The admin processing page therefore counts failed documents per stage
([api/admin/processing.rs::stage_for_task](../../../../website/backend/src/api/admin/processing.rs)) and a stage with any failures never renders
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

## Automatic OCR processing updates

The OCR update uses detected pages and installed model capabilities.
It completes unfinished plans before it selects automatic replacements.
It processes at most 32 file descriptors in one workflow iteration.
Each activity uses a private download directory.
Stored page plans and request results remain outside workflow history.
New ingestion verifies its operation-scoped prepared receipts after dependent indexing.
The historical update verifies the exact returned plan identities after strict dependent stages.
Both paths require durable output before they record applied state.
Retired manual-setting workflows remain available only for recorded legacy histories.

## Independent entity updates

The named-entity update follows table, archive, and OCR text-producing updates.
Existing recorded snapshots retain their stored step order during replay.
Provider enablement, model identity, and coverage contract form the desired target.
Entity stage version 2 selects earlier successful output without manual invalidation.
Failed indexing remains selected after successful inference.

Compatible table receipts preserve unchanged text, regex, signal, and embedding output during this independent NER correction.
The compatibility rule changes only the earlier NER coverage version.
An earlier table reader remains selected for its table rewrite.

Automatic OCR schedules each file independently within a four-file window.
Each activity retains its retry policy and pinned publication plan.
Valid files complete their dependent stages before the operation reports failed files.
Unsupported or failed files remain selectable and retain per-document errors.
The workflow records accumulated failures across bounded pages and continues after worker replacement.
