# Hoover4 Processing

This directory contains the ingestion and processing pipeline that populates Hoover4’s data stores. It includes CLI entry points, Temporal workflows, worker processes, and database access utilities.

## Key Responsibilities

- Define and run data ingestion workflows for file-system datasets.
- Parse and normalize file content into ClickHouse tables.
- Build and refresh Manticore search indexes.
- Provide worker processes for common, Tika, OCR, and indexing queues.

## Entry Points

- `main.py` provides a Click CLI for migrations, dataset onboarding, and worker orchestration.
- `tasks/run_worker.py` defines worker types and task queues for Temporal.

## Subdirectories

- `database/` - ClickHouse migrations, Manticore index utilities, MinIO client helpers, and related scripts.
- `tasks/` - Temporal workflows and activities for the multi-stage processing pipeline.

## Technical Details

This service implements a multi-stage pipeline: P0 scans datasets and records files/blobs, P1 builds processing plans, P2 executes plan downloads and orchestration, P3 parses content by file type, and P4 indexes text and metadata into Manticore and ClickHouse.

Code is arranged by function: `tasks/` contains Temporal workflows/activities grouped by stage, `database/` contains ClickHouse/Manticore/MinIO helpers, and `main.py` with `tasks/run_worker.py` provide CLI and worker entry points.

Usage:
- Run migrations with `python main.py migrate`.
- Onboard a dataset with `python main.py add-disk-dataset <dataset_name> <path>`.
- Start workers with `python main.py worker [common|tika|easyocr|indexing]`.

## Navigation

-  [Go Back](../Readme.md)

- [database/Readme.md](database/Readme.md)
- [tasks/Readme.md](tasks/Readme.md)