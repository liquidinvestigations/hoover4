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
- Provision one collection's database with `python main.py ensure-collection <collectionname>`. Idempotent; creates the database if missing and applies `database/db_collection_migrations/`. The collection row itself is created in the admin UI, which triggers the same operation as a Temporal workflow.
- Onboard a dataset with `python main.py add-disk-dataset <collectionname> <dataset_name> <path>` — the collection must already exist (admin UI or `ensure-collection`); the composed `collection_dataset` is `<collectionname>_<dataset_name>` and the collection assignment is fixed at creation.
- List collections with `python main.py list-collections`.
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
  slice by slice has holes.
* `index_vfs_structure` — copies it into the collection's `<name>_vfs` Manticore table.
* `index_filenames_row` — one synthetic pages row per document carrying its basenames.
* a rewritten `index_metadata` emitting the typed attributes (`dates`, `date_min`,
  `date_max`, `file_size_bytes`, `struct_flags`, `primary_filename`, `email_from`,
  `email_to`) and the `vfs_node` closure term ids.

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
  a directory. Use `kind_from_wire` on every read.
