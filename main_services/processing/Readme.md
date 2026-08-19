# Hoover4 Processing

This directory contains the ingestion and processing pipeline that populates Hoover4’s data stores. It includes CLI entry points, Temporal workflows, worker processes, and database access utilities.

## Key Responsibilities

- Define and run data ingestion workflows for file-system datasets.
- Parse and normalize file content into ClickHouse tables.
- Build and refresh Manticore search indexes.
- Provide worker processes for common, Tika, OCR, NLP, and indexing queues.

## Entry Points

- `main.py` provides a Click CLI for migrations, dataset onboarding, and worker orchestration.
- `tasks/run_worker.py` defines worker types and task queues for Temporal.

## Subdirectories

- `database/` - ClickHouse migrations, Manticore index utilities, MinIO client helpers, and related scripts.
- `tasks/` - Temporal workflows and activities for the multi-stage processing pipeline.

## Technical Details

This service implements a multi-stage pipeline: P0 scans datasets and records files/blobs, P1 builds processing plans, P2 executes plan downloads and orchestration, P3 parses content by file type, P4 extracts named entities via the remote NER service, and P6 indexes text and metadata into Manticore.

Code is arranged by function: `tasks/` contains Temporal workflows/activities grouped by stage, `database/` contains ClickHouse/Manticore/MinIO helpers, and `main.py` with `tasks/run_worker.py` provide CLI and worker entry points.

ClickHouse storage is partitioned per collection: global tables (users, groups, collections,
the dataset registry, sessions, settings, search cache, chat, ETA samples, and the 24h
usage/API telemetry tables) live in `Hoover4_Processing`, and each
collection's ingested data lives in its own `Hoover4_Collection_<collectionname>` database.
See [database/Readme.md](database/Readme.md).

Usage:
- Run migrations with `python main.py migrate` - migrates the global database and then every collection's database.
- Create a collection with `python main.py create-collection <collectionname> [--fullname TEXT] [--public]`. The scripted equivalent of the admin UI's create action: it writes the `collections` row and then provisions the database, so one idempotent command leaves a collection that can be ingested into. Without `--public` the collection is restricted and is readable only through a group grant.
- Provision one collection's database with `python main.py ensure-collection <collectionname>`. Idempotent; creates the database if missing and applies `database/db_collection_migrations/`. It does **not** write the `collections` row — use `create-collection` for that, or the admin UI, which triggers the same provisioning as a Temporal workflow.
- Onboard a dataset with `python main.py add-disk-dataset <collectionname> <dataset_name> <path>` — the collection must already exist (admin UI or `create-collection`); the composed `collection_dataset` is `<collectionname>_<dataset_name>` and the collection assignment is fixed at creation.
- List collections with `python main.py list-collections`.
- Remove one dataset's data with `python main.py purge-dataset <collectionname> <collection_dataset> [--apply] [--registered]` — deletes its rows from every Manticore table of the collection and every collection-DB table that has a `collection_dataset` column, then recomputes the shard ledger. The recovery path for a dataset that was abandoned rather than deleted (a failed ingest, or a re-ingest under a new name), whose index rows otherwise keep answering searches and keep the Collections filter offering a dataset that no longer exists. It reports what it will delete and deletes nothing without `--apply`, refuses a dataset that still has a live registry row (deleting a live dataset belongs in the admin UI, which purges *and* removes the row) unless `--registered` is passed, and is idempotent — a second run finds nothing to purge.
- Retry the documents one stage failed on with `python main.py retry-failed-files <collectionname> [--dataset X] [--task P4_ExtractEntities] [--apply]` — reads the file hashes out of `processing_errors` and re-runs the stage that failed them, with no re-ingest. A plan is marked finished when its stages have *run*, not when every document succeeded, so `execute-plans` is a no-op for exactly these failures. NER failures clear the failed hashes' `nlp_processed` watermarks and re-run P4 + P6 for their plans; index failures re-run P6 alone; embedding failures re-run P5 + P6; parse failures have no per-file entry point and reopen the whole plan. The `processing_errors` rows are cleared only after the re-run has demonstrably fixed the document, so a second failure leaves the record it started from.
- Re-index a collection with `python main.py reindex-collection <collectionname>` — drops the collection's Manticore shard tables and shard ledger, then re-runs indexing for every finished plan (recovery path for a lost Manticore volume, a `MAX_SHARD_TEXT_BYTES` change, or shard fragmentation; files are not re-parsed).
- Start workers with `python main.py worker [common|tika|ocr|nlp|indexing|index-planner]`. The `index-planner` worker must run at exactly one process (see [tasks/Readme.md](tasks/Readme.md)). Worker startup also registers the `CollectionDataset` Temporal search attribute and starts the singleton `CollectEtaSamples` ETA workflow — both idempotent, so restarts are safe.

## Navigation

-  [Go Back](../Readme.md)

- [database/Readme.md](database/Readme.md)
- [tasks/Readme.md](tasks/Readme.md)

## Dates, email addresses and the folder tree

**P0 (`scan_disk`)** records `vfs_files.mtime` alongside a `mtime_source` that says
how far to trust it. The number alone means nothing: the same field carries "the archive
recorded this in 2013" in one row and "the worker wrote this temp file a second ago" in the
next.

| `mtime_source` | when | indexed as a date? |
|---|---|---|
| `archive` | the container is an `archives` row — 7z restores stored timestamps | **yes** |
| `untrusted` | the container is an email — attachments are re-written by the worker | no |
| `filesystem` | top level — the clone/save time of the corpus | no |
| `''` | a container we do not recognise (extracted PDF images, video frames) | no |

**P3 (`parse_files`)** owns `document_dates.py`: a pure `resolve_dates` plus the
`resolve_document_dates` activity that runs between parsing and indexing. It COLLECTS
every confirmed date rather than picking a best one, applies a `[1800-01-01, now + 1y]`
sanity window (outside → dropped and logged, never clamped), and records the metadata key
each date came from. `parse_email` writes structured `email_addresses` rows and sets
`date_sent_known` so the epoch stops meaning two things.

**P6 (`index_data`)** runs:

* `build_vfs_nodes` — materialises the dataset's tree into ClickHouse `vfs_nodes`.
  Dataset-scoped and idempotent, because a plan holds only a slice and a tree assembled
  slice by slice has holes. It is a REBUILD in both directions: rows written keep their
  key, and rows the rebuild did not produce are deleted afterwards by `updated_at`,
  because a ReplacingMergeTree never removes a key that stops being written.
  A file counts as a container only if something is inside it — being sniffed as an
  archive, or being an email, is a guess, and an email with no attachments rendered as a
  folder that opens onto nothing. What is inside a container hangs off the container FILE;
  there is no `/` node in between.
* `index_vfs_structure` — copies it into the collection's `<name>_vfs` Manticore table,
  clearing the dataset's rows first for the same reason.
* `index_text_pages` — one row per text segment plus one synthetic `filename_index` row
  per document carrying its basenames, each row also carrying the document's typed
  attributes (`dates`, `date_min`, `date_max`, `file_size_bytes`, `struct_flags`,
  `primary_filename`, `email_from`, `email_to`) and its `vfs_node` closure term ids.
  One writer, because every row of a document must carry the same metadata.
* `optimize_shard_tables` — compacts a shard whose killed rows or chunk count have
  built up. Storage, not latency.

### The ancestor closure, and its caps

`file_paths` holds every node a document can be reached THROUGH, and "through" crosses
container boundaries. Containers are content-addressed, so one container hash can sit at
several paths and the closure includes all of them.

The caps in `vfs_nodes.py` are not tuning knobs — the corpus contains an email that
contains itself (`eml-7-recursive`) and one archive in two places
(`zip-in-multiple-locations`):

* a `visited` set on `(container_hash, path)`;
* `MAX_ANCESTOR_DEPTH = 64` container hops;
* `MAX_ANCESTOR_TERMS = 4096` terms per document.

Hitting either cap sets `struct_flags` bit 1 (`truncated_ancestry`) and logs, rather than
silently returning a short closure.

### Two wire-format traps, both found on the live stack

* **Temporal deserialises an activity argument into its ANNOTATED type.** An unannotated
  `params` arrives as a raw dict and every attribute access fails at runtime.
* **ClickHouse `Enum8` takes the NAME on insert and returns the ORDINAL on read.**
  Comparing that int against `'container'` never raises; it silently makes every container
  a directory, and comparing `role` against `'from'` silently files every sender as a
  recipient. Pass every enum read through `database/enum_wire.py::enum_from_wire`, and
  select the column as `toString(col)` as well. `tests/unit/test_enum_wire.py` greps
  `P6_index_data` for the bare comparison and fails the suite if it reappears.
