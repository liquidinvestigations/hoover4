"""Activities of the upload queue and of the targeted upload ingest.

Every activity reads its batches and paths from `upload_batches` and `upload_files` by
id, and returns ids and counts only. `database/uploads.py` documents which states the
website writes and which the worker writes.

The queue activities run on `processing-common-queue` beside `UploadQueue`. The ingest
activities run there beside `IngestUploadBatches`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import posixpath
import stat as stat_module

from temporalio import activity
from temporalio.exceptions import ApplicationError

from tasks.heartbeat import send_heartbeat, stop_if_worker_is_stopping, with_heartbeat

from .params import (
    FinishUploadBatchesParams, UploadBatchLimitsResult, UploadBatchParams, UploadClaimResult,
    UploadOperationParams, UploadQueueParams,
)

log = logging.getLogger(__name__)

#: The workflow type, task queue and signal of the queue. The website names the same
#: values in `website/backend/src/uploads/mod.rs`. Change both together.
QUEUE_WORKFLOW_TYPE = "UploadQueue"
QUEUE_TASK_QUEUE = "processing-common-queue"
QUEUE_SIGNAL = "upload_committed"

#: The ingest time limit of a batch: this base, and one second for each
#: `INGEST_BYTES_PER_SECOND` bytes of the batch.
INGEST_BASE_SECONDS = 1800
INGEST_BYTES_PER_SECOND = 1024 * 1024

#: Directory rows per insert.
DIRECTORY_CHUNK = 500

DATASET_DELETED_ERROR = "The dataset was deleted before this upload was ingested."


def queue_workflow_id(upload_dataset: str) -> str:
    """The workflow id of the queue of one upload dataset."""
    return f"upload-queue-{upload_dataset}"


def _dataset_row(collection_dataset: str) -> dict | None:
    """The live registry row of a dataset, or None after its deletion."""
    from database.clickhouse import get_global_client

    with get_global_client() as client:
        rows = client.query(
            "SELECT collectionname, dataset_path FROM dataset FINAL "
            "WHERE collection_dataset = {cd:String} AND is_deleted = 0 LIMIT 1",
            parameters={"cd": collection_dataset},
        ).result_rows
    if not rows:
        return None
    return {"collectionname": str(rows[0][0]), "dataset_path": str(rows[0][1])}


def _require_collection(params, row: dict | None) -> None:
    if row is not None and row["collectionname"] != params.collectionname:
        raise ApplicationError(
            f"dataset {params.upload_dataset} is not in collection {params.collectionname}",
            non_retryable=True,
        )


# The queue ----------------------------------------------------------------------------

def _live_upload_operations(upload_dataset: str) -> list[dict]:
    from database.operations import _LIVE_SQL, _select

    return _select(
        f"kind = 'ingest_upload' AND collection_dataset = {{ds:String}} AND state IN ({_LIVE_SQL})",
        {"ds": upload_dataset},
    )


def _detail_batch_ids(row: dict) -> list[str]:
    import json

    try:
        detail = json.loads(row.get("detail") or "{}")
    except ValueError:
        return []
    ids = detail.get("batch_ids") if isinstance(detail, dict) else None
    return [str(i) for i in ids] if isinstance(ids, list) else []


@activity.defn
@with_heartbeat
def open_upload_operation(params: UploadOperationParams) -> UploadClaimResult:
    """Claim the next waiting batches under `params.op_id`, or recover an existing claim.

    Order of work, so that every interrupted write recovers on the next call:

    1. Batches claimed by an operation that ended are settled (`finish_upload_batches`).
    2. A live `ingest_upload` operation of the dataset wins. Its claim of the batch ids in
       its detail is completed, and its id and its actual claimed ids are returned. This
       repairs a crash between the operations row and the batch claims.
    3. After the dataset was deleted, every waiting batch is settled as `failed`.
    4. Otherwise up to `BATCHES_PER_OPERATION` waiting batches, oldest first, are claimed.
       The `pending` operations row with their ids in its detail is written first, then
       `op_id` on each batch. No waiting batch writes no row.
    """
    from database import operations, uploads

    registry = _dataset_row(params.upload_dataset)
    _require_collection(params, registry)

    owners: dict[str, list[str]] = {}
    for row in uploads.claimed_open_batches(params.collectionname, params.upload_dataset):
        owners.setdefault(row["op_id"], []).append(row["batch_id"])
    live = {row["op_id"]: row for row in _live_upload_operations(params.upload_dataset)}
    for op_id in sorted(set(owners) - set(live)):
        row = operations.get_operation(op_id)
        if row is not None and row["state"] not in operations.TERMINAL_STATES:
            live[op_id] = row
            continue
        _finish(params.collectionname, params.upload_dataset, op_id, owners[op_id],
                row["state"] if row else "errored", settles=True)

    if live:
        row = min(live.values(), key=lambda r: (r["started_at"], r["op_id"]))
        op_id = row["op_id"]
        claimed = uploads.claim_batches(params.collectionname, params.upload_dataset, op_id,
                                        _detail_batch_ids(row))
        open_ids = [b["batch_id"] for b in uploads.batches_of_operation(
            params.collectionname, params.upload_dataset, op_id)
            if b["state"] in uploads.OPEN_BATCH_STATES]
        if not open_ids and row["state"] == "pending":
            operations.finish_operation(op_id, "cancelled", "No upload batch was waiting.")
            log.info("upload operation %s claimed no batch and is cancelled", op_id)
            return UploadClaimResult(dataset_live=registry is not None)
        log.info("upload operation %s holds %d batches (%d claimed)", op_id, len(open_ids),
                 len(claimed))
        return UploadClaimResult(op_id=op_id, batch_ids=open_ids, op_state=row["state"],
                           dataset_live=registry is not None)

    if registry is None:
        failed = uploads.fail_waiting_batches(params.collectionname, params.upload_dataset,
                                              DATASET_DELETED_ERROR)
        log.info("upload dataset %s is deleted: %d waiting batches failed",
                 params.upload_dataset, failed)
        return UploadClaimResult(dataset_live=False)

    waiting = uploads.queued_batches(params.collectionname, params.upload_dataset)
    if not waiting:
        return UploadClaimResult()
    ids = [row["batch_id"] for row in waiting]
    owners_of_batches = sorted({row["username"] for row in waiting})
    operations.create_operation(
        "ingest_upload", params.collectionname, params.upload_dataset,
        detail={"batch_ids": ids}, user_id=owners_of_batches[0] if len(owners_of_batches) == 1
        else "uploads", op_id=params.op_id, check_lock=False,
    )
    claimed = uploads.claim_batches(params.collectionname, params.upload_dataset,
                                    params.op_id, ids)
    log.info("upload operation %s created for %d batches of %s", params.op_id, len(claimed),
             params.upload_dataset)
    return UploadClaimResult(op_id=params.op_id, batch_ids=claimed, op_state="pending")


@activity.defn
@with_heartbeat
def upload_operation_state(op_id: str) -> str:
    """The state of an operations row, or `missing`."""
    from database.operations import get_operation

    row = get_operation(op_id)
    return row["state"] if row else "missing"


@activity.defn
@with_heartbeat
def settle_upload_operation(params: UploadOperationParams) -> dict[str, int]:
    """Write the outcome of each batch that an ended operation left open.

    A live operation is left alone. Returns the count of each written state.
    """
    from database import operations, uploads

    row = operations.get_operation(params.op_id)
    state = row["state"] if row else "errored"
    if state not in operations.TERMINAL_STATES:
        return {}
    open_ids = [b["batch_id"] for b in uploads.batches_of_operation(
        params.collectionname, params.upload_dataset, params.op_id)
        if b["state"] in uploads.OPEN_BATCH_STATES]
    return _finish(params.collectionname, params.upload_dataset, params.op_id, open_ids, state,
                   settles=True)


@activity.defn
@with_heartbeat
def cancel_upload_operation(op_id: str) -> str:
    """Run the cancellation finalizer of an operation and return its terminal state.

    The finalizer is `CancelOperation` under the id `cancel-<op_id>`, the one that the
    command line and the admin page start. An existing finalizer is joined.
    """
    return asyncio.run(_cancel_operation(op_id))


async def _cancel_operation(op_id: str) -> str:
    import temporalio.common
    from temporalio.client import Client
    from temporalio.exceptions import WorkflowAlreadyStartedError

    client = await Client.connect("temporal:7233")
    finalizer_id = f"cancel-{op_id}"
    try:
        handle = await client.start_workflow(
            "CancelOperation", op_id, id=finalizer_id, task_queue="operations-queue",
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(finalizer_id)
    return str(await handle.result())


# The outcome --------------------------------------------------------------------------

#: The batch error of each operation state that ends a batch before its outcome.
ENDED_EARLY = {
    "errored": "The ingest of this upload failed before it finished.",
    "cancelled": "The operation was cancelled before this upload finished.",
    "missing": "The operation of this upload has no record.",
}

def _finish(collectionname: str, upload_dataset: str, op_id: str, batch_ids,
            operation_state: str, settles: bool = False) -> dict[str, int]:
    """Write the outcome of each batch that `op_id` owns and that has no terminal state.

    `settles` marks the settle of an ended operation. Its rows take the version step
    `uploads.SETTLE_VERSION_STEP`. A late finish of the child that read the same row then
    does not replace the settled state.
    """
    from database import uploads

    counts: dict[str, int] = {}
    for batch_id in batch_ids:
        row = uploads.read_batch(collectionname, upload_dataset, batch_id)
        if row is None or row["op_id"] != op_id or row["state"] in uploads.TERMINAL_BATCH_STATES:
            continue
        outcome = uploads.batch_outcome(collectionname, upload_dataset, batch_id,
                                        operation_state)
        # `cancelled` belongs to the website, which writes it when no file was placed.
        # A claimed batch had a placed file at commit, so here it ends `failed`.
        state = "failed" if outcome["state"] == "cancelled" else outcome["state"]
        error = uploads.outcome_error(outcome)
        if operation_state in ENDED_EARLY:
            error = f"{ENDED_EARLY[operation_state]} {error}".strip()
        uploads.write_batch(collectionname, upload_dataset, batch_id, current=row,
                            version_step=uploads.SETTLE_VERSION_STEP if settles else 1,
                            state=state, error=error, finished_at=uploads._now())
        counts[state] = counts.get(state, 0) + 1
        log.info("upload batch %s is %s: %d of %d files succeeded", batch_id, state,
                 outcome["succeeded"], outcome["files"])
    return counts


@activity.defn
@with_heartbeat
def finish_upload_batches(params: FinishUploadBatchesParams) -> dict[str, int]:
    """Write the terminal state of each given batch from its stored outcome.

    Idempotent: a batch with a terminal state, or one that another operation owns, is
    left unchanged. Returns the count of each written state.
    """
    return _finish(params.collectionname, params.upload_dataset, params.op_id,
                   params.batch_ids, params.operation_state)


# The targeted ingest ------------------------------------------------------------------

def _owned_batch(params: UploadBatchParams) -> dict | None:
    """The batch row when this operation owns it and it has no outcome, else None."""
    from database import uploads

    row = uploads.read_batch(params.collectionname, params.upload_dataset, params.batch_id)
    if row is None or row["op_id"] != params.op_id:
        return None
    if row["state"] not in uploads.OPEN_BATCH_STATES:
        return None
    return row


@activity.defn
@with_heartbeat
def upload_batch_limits(params: UploadBatchParams) -> UploadBatchLimitsResult:
    """The ingest time limit of one batch from its stored byte count."""
    row = _owned_batch(params)
    if row is None:
        return UploadBatchLimitsResult(skip=True)
    byte_count = int(row["byte_count"])
    return UploadBatchLimitsResult(
        ingest_seconds=INGEST_BASE_SECONDS + byte_count // INGEST_BYTES_PER_SECOND,
        file_count=int(row["file_count"]),
        byte_count=byte_count,
    )


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def open_dataset_root(dataset_path: str) -> int:
    """Open the dataset folder one name at a time from `/`, refusing symbolic links.

    The folder must be under a dataset mount of `HOOVER4_DATASET_MOUNTS`. Returns a
    directory descriptor that the caller closes.
    """
    from tasks.dataset_mounts import dataset_mounts

    path = posixpath.normpath(dataset_path)
    if not path.startswith("/") or not any(
            path == m.path or path.startswith(m.path.rstrip("/") + "/") for m in dataset_mounts()):
        raise ApplicationError("The dataset folder is not under a dataset mount.",
                               non_retryable=True)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for name in [n for n in path.split("/") if n]:
            child = os.open(name, _DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_file_beneath(root_fd: int, rel_path: str) -> int:
    """Open a regular file through directory descriptors without following symbolic links."""
    names = [n for n in rel_path.split("/") if n]
    if not names or any(n in (".", "..") for n in names):
        raise ValueError("The path is not a file path.")
    folder_fd = os.dup(root_fd)
    try:
        for name in names[:-1]:
            child = os.open(name, _DIR_FLAGS, dir_fd=folder_fd)
            os.close(folder_fd)
            folder_fd = child
        fd = os.open(names[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=folder_fd)
    finally:
        os.close(folder_fd)
    if not stat_module.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError("The path is not a regular file.")
    return fd


def stat_beneath(root_fd: int, rel_path: str) -> os.stat_result:
    """Read the metadata of a regular file without following symbolic links."""
    fd = open_file_beneath(root_fd, rel_path)
    try:
        return os.fstat(fd)
    finally:
        os.close(fd)


def _ancestors(paths) -> list[str]:
    """Every folder above the given file paths, without the root `/`.

    `build_vfs_nodes` writes the root node itself, and the folder scan writes no root row.
    """
    found = set()
    for path in paths:
        parent = posixpath.dirname(path)
        while parent not in ("", "/") and parent not in found:
            found.add(parent)
            parent = posixpath.dirname(parent)
    return sorted(found)


def _stored_hashes(collectionname: str, upload_dataset: str, paths: list[str]) -> dict[str, str]:
    """Live top-level `vfs_files` hashes of the given paths."""
    from database.clickhouse import get_collection_client
    from tasks.P0_scan_disk.activities import _path_table

    if not paths:
        return {}
    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT path, hash FROM vfs_files FINAL "
            "WHERE collection_dataset = {cd:String} AND container_hash = '' "
            "AND is_deleted = 0 AND path IN (SELECT path FROM lookup_paths)",
            parameters={"cd": upload_dataset},
            external_data=_path_table(paths),
        ).result_rows
    return {str(p): str(h) for p, h in rows}


def _rejection(reason: str) -> dict:
    from database.uploads import INGEST_REJECTION_PREFIX

    return {"state": "rejected", "error": f"{INGEST_REJECTION_PREFIX}{reason}"}


@activity.defn
@with_heartbeat
def ingest_upload_paths(params: UploadBatchParams) -> dict[str, int]:
    """Ingest the placed files of one batch, and only them.

    The manifest in `upload_files` is immutable after commit. Its entries are cut into
    chunks in `file_no` order with the count and byte limits of the folder scan, so a
    retry sees the same chunks. A chunk processes its `placed` entries. An entry that a
    previous attempt settled is `ingested` or `rejected` and is skipped, so durable file
    rows, not heartbeat details, decide where a retry resumes. A repeated chunk writes
    the same blob and VFS identities.

    Each path is checked through directory descriptors. Its parent folders get
    `vfs_directories` rows. The P0 ingest body then hashes and stores it, with
    `container_hash = ''`. The hash written to `upload_files` is the stored
    `vfs_files.hash` of the live top-level row of that path. An unreadable or missing
    file is `rejected` with its reason, and the other files continue.

    No folder is listed and no deletion is reconciled. Returns counts only.
    """
    from database import uploads
    from tasks.P0_scan_disk.activities import (
        FILE_BATCH_MAX_BYTES, FILE_BATCH_MAX_COUNT, IngestFilesBatchParams,
        InsertVfsDirectoriesParams, _batch_files_by_size, ingest_files,
        insert_vfs_directories,
    )

    batch = _owned_batch(params)
    if batch is None:
        return {"files": 0, "ingested": 0, "rejected": 0, "skipped": 0, "chunks": 0}
    registry = _dataset_row(params.upload_dataset)
    _require_collection(params, registry)
    if registry is None:
        raise ApplicationError(DATASET_DELETED_ERROR, non_retryable=True)
    dataset_path = registry["dataset_path"]
    if batch["state"] == "queued":
        uploads.write_batch(params.collectionname, params.upload_dataset, params.batch_id,
                            current=batch, state="ingesting")

    files = uploads.read_files(params.collectionname, params.batch_id)
    chunks = _batch_files_by_size(
        [{"file_no": int(f["file_no"]), "size": int(f["size_bytes"])} for f in files],
        FILE_BATCH_MAX_COUNT, FILE_BATCH_MAX_BYTES)
    counts = {"files": len(files), "ingested": 0, "rejected": 0, "skipped": 0,
              "chunks": len(chunks)}
    root_fd = open_dataset_root(dataset_path)
    pinned = {}
    try:
        current = {int(f["file_no"]): f for f in files}
        for index, chunk in enumerate(chunks):
            stop_if_worker_is_stopping(f"chunk {index} of batch {params.batch_id}")
            todo = [current[c["file_no"]] for c in chunk
                    if current[c["file_no"]]["state"] == "placed"]
            counts["skipped"] += len(chunk) - len(todo)
            if not todo:
                continue
            changes: dict[int, dict] = {}
            ready = []
            for f in todo:
                try:
                    fd = open_file_beneath(root_fd, f["path"])
                    pinned[f["path"]] = fd
                    found = os.fstat(fd)
                except (OSError, ValueError) as exc:
                    reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
                    changes[int(f["file_no"])] = _rejection(reason)
                    continue
                ready.append((f, found))
            paths = [f["path"] for f, _ in ready]
            directories = _ancestors(paths)
            for start in range(0, len(directories), DIRECTORY_CHUNK):
                insert_vfs_directories(InsertVfsDirectoriesParams(
                    params.collectionname, params.upload_dataset,
                    directories[start:start + DIRECTORY_CHUNK], ""))
            result = None
            if ready:
                result = ingest_files(IngestFilesBatchParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.upload_dataset,
                    dataset_path=dataset_path,
                    file_paths=paths,
                    container_hash="",
                    op_id=params.op_id,
                    file_mtimes=[int(found.st_mtime) for _, found in ready],
                    file_sizes=[int(found.st_size) for _, found in ready],
                ), rehash_known=True,
                    source_paths={path: f"/proc/self/fd/{fd}" for path, fd in pinned.items()})
            for fd in pinned.values():
                os.close(fd)
            pinned.clear()
            stored = _stored_hashes(params.collectionname, params.upload_dataset, paths)
            for f, _ in ready:
                reason = result.unreadable.get(f["path"]) if result else None
                if reason:
                    changes[int(f["file_no"])] = _rejection(reason)
                elif stored.get(f["path"]):
                    changes[int(f["file_no"])] = {
                        "state": "ingested", "file_hash": stored[f["path"]], "error": ""}
                else:
                    changes[int(f["file_no"])] = _rejection("No file row was stored.")
            uploads.write_files(params.collectionname, params.batch_id, changes)
            for file_no, change in changes.items():
                counts[change["state"]] += 1
                current[file_no] = {**current[file_no], **change}
            send_heartbeat({"batch_chunk": index + 1, "batch_chunks": len(chunks)})
    finally:
        for fd in pinned.values():
            os.close(fd)
        os.close(root_fd)
    uploads.write_batch(params.collectionname, params.upload_dataset, params.batch_id,
                        state="processing")
    log.info("upload batch %s ingested: %s", params.batch_id, counts)
    return counts


# Recovery -----------------------------------------------------------------------------

async def recover_upload_queues(client) -> int:
    """Signal-with-start the queue of every dataset with a waiting or claimed batch.

    The operations supervisor calls this on each pass, and its first pass follows the
    start of the worker that runs the ETA sampler. The queue reads its batches from
    ClickHouse, so the signal only wakes it. A collection without the upload tables is
    skipped. Returns the number of signals sent.
    """
    from database.clickhouse import list_collections
    from database.uploads import datasets_with_open_batches

    sent = 0
    for collectionname in list_collections():
        try:
            pairs = datasets_with_open_batches(collectionname)
        except Exception as exc:  # noqa: BLE001 -- one collection must not stop the rest.
            log.warning("upload recovery skipped %s: %s", collectionname, str(exc)[:200])
            continue
        for upload_dataset, batch_id in pairs:
            await client.start_workflow(
                QUEUE_WORKFLOW_TYPE, UploadQueueParams(collectionname, upload_dataset),
                id=queue_workflow_id(upload_dataset), task_queue=QUEUE_TASK_QUEUE,
                start_signal=QUEUE_SIGNAL, start_signal_args=[{"batch_id": batch_id}],
            )
            sent += 1
    if sent:
        log.info("upload recovery signalled %d queues", sent)
    return sent
