# P_upload - targeted ingest of committed uploads

This package ingests the files of a committed upload batch, and only those files.
It lists no dataset folder, plans no folder range, scans no range and reconciles no deletion.
The website receiver writes the batch and its manifest (`website/backend/src/uploads/`).
The tables `upload_batches` and `upload_files` hold both, and [database/uploads.py](../../database/uploads.py) reads and writes them.

## Three workflows carry ids only

| Workflow | Queue | Input | Work |
|---|---|---|---|
| `UploadQueue` | `processing-common-queue` | `collectionname`, `upload_dataset`, optional `active_op_id` | One run for each upload dataset, id `upload-queue-<upload_dataset>`. Claims up to 50 waiting batches as one `ingest_upload` operation and waits for its terminal row. |
| `Operation` kind `ingest_upload` | `operations-queue` | the operation id, the dataset, `detail.batch_ids` | Passes admission, then runs `IngestUploadBatches` and verifies plan completion as the other ingest kinds do. |
| `IngestUploadBatches` | `processing-common-queue` | `collectionname`, `upload_dataset`, `op_id`, at most 50 batch ids | Ingest all claimed batches before selecting historical errors. Then plan, execute, and finish each batch. Reconcile selected errors after the last batch. |

The `upload-prepare-all-batches` patch preserves the activity order of older histories.
New runs record `paths_prepared` across continuation, so later batches have hashes before error selection.

No payload holds a path, a file name or a manifest.
The activities read paths from `upload_files` by batch id.

## The queue claims waiting batches

The website signals `upload_committed` with `{"batch_id": ...}` through signal-with-start after each commit.
It signals again at startup and every hour while the stored batch state is `queued`.
The signal only wakes the queue. The queue reads waiting batches from ClickHouse in `(committed_at, batch_id)` order.

The queue chooses a random operation id for each group in workflow code, so a replay and an activity retry use the same id.
`open_upload_operation` works in this order.

1. It settles the batches that an ended operation claimed.
2. It returns a live `ingest_upload` operation of the dataset, with its actual claimed batch ids. It first claims the remaining batch ids of the operation detail. This repairs a crash between the operation row and the batch claims.
3. After a dataset deletion it settles every waiting batch as `failed`.
4. Otherwise it writes the `pending` operation row with the batch ids in its detail, then writes the operation id on each batch. The state stays `queued` until the batch starts.

An empty claim writes no row and starts nothing.
The queue starts the `Operation` child with `ParentClosePolicy.ABANDON` and `REJECT_DUPLICATE`, so a continued queue run keeps it and never starts it twice.
It reads the operation row at most every 60 s, and wakes earlier when the child of the same run closes.
It continues as new at 1,000 history events, also while signals arrive, with the dataset ids and the active operation id only.
After the operation ends, `settle_upload_operation` writes the outcome of each batch that the operation left open.
With nothing to do for ten minutes the queue makes one more claim, and ends when that claim is empty and no signal arrived.
A cancellation of the queue runs the operation finalizer `CancelOperation` (`cancel_upload_operation`), settles the batches, and ends the queue as cancelled.

## One batch is ingested in fixed chunks

`ingest_upload_paths` reads the manifest in `file_no` order and cuts it into chunks with the limits of the folder scan, 100 files or 50 MB.
The manifest is immutable after commit, so each attempt sees the same chunks.
A chunk processes its `placed` entries. A settled entry is `ingested` or `rejected`, and a retry skips it.
Durable file rows decide where a retry resumes. The heartbeat details are progress hints.
The activity calls `stop_if_worker_is_stopping` between chunks.

For each placed file the activity opens the dataset folder one name at a time from `/` without following links, and requires a regular file.
It writes `vfs_directories` rows for the parent folders in chunks of 500. `build_vfs_nodes` writes the root node.
It keeps each file descriptor open while `ingest_files` from P0 reads its bytes.
A path replacement cannot redirect those reads.
The call uses `container_hash = ''` and `rehash_known`.
It writes `upload_files.file_hash` from the stored `vfs_files.hash` of the live top-level row of the path.
A missing, linked or unreadable file is `rejected` with a reason that starts with `Not ingested: `, and the other files continue.
A batch that cannot be ingested fails alone, and the next batch of the operation continues.

The time limit of the activity is 1,800 s plus one second for each MiB of the batch.

## The outcome counts manifest entries

`database.uploads.batch_outcome` counts manifest entries, and `finish_upload_batches` writes the result.
A file succeeded when all of these hold.

- It is `ingested`.
- Its path has a live top-level `vfs_files` row with its hash and a `vfs_nodes` file row.
- Its hash has a plan, and every plan of its hash and of each member below it finished.
- None of these hashes has a current error.

An error is current when the latest operation that listed a plan of the hash wrote it, the rule of the document viewer.
A supported file without text succeeds, because its plan finishes without an error.

| Condition, evaluated in this order | State |
|---|---|
| No file was placed. | `cancelled` from the website. A claimed batch ends `failed`. |
| The operation failed or was cancelled, or a placed file was neither ingested nor rejected. | `failed` |
| Every manifest file succeeded. | `completed` |
| Some file succeeded. | `completed_with_errors` |
| No file succeeded. | `failed` |

`not_sent` and rejected entries never succeed, so a stopped batch with unsent files ends `completed_with_errors` or `failed`.

## Recovery reads stored state

| Case | Recovery |
|---|---|
| A signal was lost, or the queue ended with waiting batches | The website signals queued batches at startup and every hour. The operations supervisor (`supervise_operations`) signals the queue of every dataset with a waiting or claimed batch on each pass, including its first pass after a worker start. |
| A crash during the claim | The next claim returns the live operation and completes its claim. |
| An operation ended without a batch outcome | The queue settles the batches after the terminal row, and the next claim settles batches of any ended operation. |
| The dataset was deleted | The website stops transfers and removes their bytes. The worker settles waiting batches as `failed`, and the ingest refuses a deleted dataset. |

The website hook `reconcile_claimed` does nothing. The worker owns every batch state after the claim.

## Each state has one writer

The website writes `uploading`, `committing`, `queued` and `cancelled`, and the file states up to placement.
The worker writes the claim, `ingesting`, `processing`, `completed`, `completed_with_errors` and `failed`, and the file states `ingested` and `rejected` with `file_hash`.
A writer reads the stored row and writes `row_version` one above it.
The worker refuses to write a batch in a website transfer state other than `queued`.

## Navigation

- [Go Back](../Readme.md)
- [P0 - Scan Disk](../P0_scan_disk/Readme.md)
- [P_ops - Operations](../P_ops/Readme.md)
