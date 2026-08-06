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

This service implements a multi-stage pipeline: P0 scans datasets and records files/blobs, P1 builds processing plans, P2 executes plan downloads and orchestration, P3 parses content by file type, P4 extracts named entities via the remote NER service, and P5 indexes text and metadata into Manticore.

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
- Start workers with `python main.py worker [common|tika|easyocr|nlp|indexing|index-planner]`. The `index-planner` worker must run at exactly one process (see [tasks/Readme.md](tasks/Readme.md)). Worker startup also registers the `CollectionDataset` Temporal search attribute and starts the singleton `CollectEtaSamples` ETA workflow — both idempotent, so restarts are safe.

## Navigation

-  [Go Back](../Readme.md)

- [database/Readme.md](database/Readme.md)
- [tasks/Readme.md](tasks/Readme.md)