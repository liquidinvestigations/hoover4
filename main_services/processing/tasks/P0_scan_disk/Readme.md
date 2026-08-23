# P0 - Scan Disk

This stage discovers datasets on disk, enumerates directories and files, and populates ClickHouse VFS and blob tables. It is the entry point for ingestion and defines the initial dataset metadata.

## Key Responsibilities

- Walk filesystem paths and record `vfs_directories` and `vfs_files`.
- Hash file contents and create blob metadata with deduplication.
- Upload large blobs to Garage and store small blobs inline in ClickHouse.
- Seed downstream processing by spawning child workflows for folders and file batches.

## Entry Points

- Workflow: `IngestDiskDataset` in `workflows.py`
- Activities: `list_disk_folder`, `insert_vfs_directories`, `ingest_files_batch`,
  `reconcile_deleted_files` in `activities.py`
- CLI helper: `submit_job.py` (used by `main.py add-disk-dataset`)

## Technical Details

The workflow starts at the dataset root and recursively enumerates folders in batches of 10. Files are batched by count and total size to limit ingestion payloads. Hashing uses a single streaming pass to compute `sha3_256` (primary) plus `md5`, `sha1`, and `sha256`. Blob storage is split between ClickHouse (`blob_values`) for small files and the collection's own Garage bucket (`blobs.s3_path`, a full `s3://<bucket>/<key>`) for larger content.

## A rescan detects change, and it detects deletion

`vfs_files` is keyed on `(collection_dataset, container_hash, path)` (no `hash`), so a
path has exactly one current row and an edited file replaces its predecessor in place.
That is what makes the rest of this possible; with `hash` in the sort key a changed file
inserts a second row beside the old one and the VFS holds two versions of one path with
nothing to say which is current.

Per file, from the size and mtime the scan already collected:

| observation | what happens |
|---|---|
| no row | new file, hash and ingest |
| same size **and** same mtime | unchanged, no read, no hash, `updated_at` touched |
| size differs | changed, settled without reading the file |
| mtime differs, size same | rehash; a different hash is a change, the same hash is a touch |
| row present, path not found by the scan | deleted, tombstoned and de-indexed |

Comparing paths alone (which is what a rescan did before there was anything else to
compare) is wrong in the direction that loses data: a file whose *content* changed at
the same path was skipped for ever, with no new blob, no new plan, and nothing
downstream noticing.

**Deletion is decided by timestamp, not by a second traversal.** Every path the walk
confirmed carries an `updated_at` later than the walk's start, so `reconcile_deleted_files`
tombstones exactly the top-level rows older than that. *Confirmed* means every path the
walk saw, including the ones that matched on size and mtime and were never read. Those
are the overwhelming majority, and touching only the rehashed subset makes the second
scan of a dataset tombstone and de-index every unmodified file in it, which presents as
the corpus deleting itself. It runs **only after a complete
walk**: a scan that failed part-way through has confirmed nothing about the paths it
never reached, and reconciling on it would delete them. Only `container_hash = ''` rows
are considered. An archive member is not a path on disk and disappears with its
container.

Subtree skipping by directory mtime is deliberately not done: a directory's mtime does
not change when a file inside it is edited in place, so it would make edited files
invisible.

**A deleted document's blob is kept; only its index rows go.** Search stops answering
with content that is no longer in the corpus immediately, while the blob, its extracted
text and its derived work stay where they are. A hash still reachable from a surviving
path is not de-indexed at all. The same content at two paths losing one of them must not
vanish from search. Reclaiming the orphaned bytes is a separate decision about storage,
and one that cannot be undone.

Everything downstream is already incremental and needs no change: a changed file is a new
blob, `ComputePlans` picks up any blob with no plan, and P2-P6 run only over it.

## Usage

- Register and ingest a dataset via `python main.py add-disk-dataset <collectionname> <dataset_name> <path>` (the collection must exist first). The dataset row is written to the global database; VFS/blob data goes to `Hoover4_Collection_<collectionname>`.
- **The same command rescans a dataset that already exists.** The registry row is written
  before the walk, so refusing on it made any interrupted ingest a dataset that could
  never be added again and could only be purged. The scan is idempotent, so re-running it
  over the same root is how an edited or deleted file is picked up. Each run gets its own
  Temporal workflow id. An id derived from the dataset alone can be started exactly once,
  and every later rescan either collides with it or silently attaches to the finished run.
- The worker queue is `processing-common-queue` (see `tasks/run_worker.py`).

## Navigation

- [Go Back](../Readme.md)
- [P1 - Compute Plans](../P1_compute_plans/Readme.md)
