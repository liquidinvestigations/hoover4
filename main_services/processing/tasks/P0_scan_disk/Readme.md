# P0 - Scan Disk

This stage discovers datasets on disk, enumerates directories and files, and populates ClickHouse VFS and blob tables. It is the entry point for ingestion and defines the initial dataset metadata.

## Key Responsibilities

- Walk filesystem paths and record `vfs_directories` and `vfs_files`.
- Hash file contents and create blob metadata with deduplication.
- Upload large blobs to MinIO and store small blobs inline in ClickHouse.
- Seed downstream processing by spawning child workflows for folders and file batches.

## Entry Points

- Workflow: `IngestDiskDataset` in `workflows.py`
- Activities: `list_disk_folder`, `insert_vfs_directories`, `ingest_files_batch` in `activities.py`
- CLI helper: `submit_job.py` (used by `main.py add-disk-dataset`)

## Technical Details

The workflow starts at the dataset root and recursively enumerates folders in batches of 10. Files are batched by count and total size to limit ingestion payloads. Hashing uses a single streaming pass to compute `sha3_256` (primary) plus `md5`, `sha1`, and `sha256`. Blob storage is split between ClickHouse (`blob_values`) for small files and MinIO (`blobs.s3_path`) for larger content.

## Usage

- Register and ingest a dataset via `python main.py add-disk-dataset <dataset_name> <path>`.
- The worker queue is `processing-common-queue` (see `tasks/run_worker.py`).

## Navigation

- [Go Back](../Readme.md)
- [P1 - Compute Plans](../P1_compute_plans/Readme.md)
