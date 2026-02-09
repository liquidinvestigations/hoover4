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

### P4 - Index Data

Aggregates metadata and text content into search and vector indexes, and performs NER enrichment where needed.

## Worker Queues

Workers are split into dedicated queues for common processing, Tika parsing, OCR, and indexing to control throughput and resource usage.

## Navigation

-  [Go Back](../Readme.md)