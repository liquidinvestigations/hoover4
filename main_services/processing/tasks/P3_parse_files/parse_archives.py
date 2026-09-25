"""Archive extraction activities, and the archive stage activity of the group workflow."""

from temporalio import activity
from typing import Dict, Any, List
from dataclasses import dataclass
import os
import logging
from tasks.heartbeat import heartbeat_pump, with_heartbeat
from tasks.P3_parse_files.batch_runner import BatchFile, BatchResult, StageBatchParams, run_batch

log = logging.getLogger(__name__)

@dataclass
class ExtractArchiveParams:
    collectionname: str
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]
    archive_path: str


@activity.defn
@with_heartbeat
def extract_archive_to_temp(params: ExtractArchiveParams) -> Dict[str, Any]:
    """Activity that extracts an archive to a temp directory using 7z."""
    import os
    import shutil
    import subprocess
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    out_dir = make_temp_dir(params.collection_dataset, "extract", params.archive_hash)

    log.info("[P3] Extracting archive to %s", out_dir)
    cmd = ["7z", "x", "-y", f"-o{out_dir}", params.archive_path]
    # stdin=DEVNULL: 7z prompts interactively for missing volumes of split
    # archives and would block the worker thread forever waiting on stdin.
    # timeout: belt-and-braces so a wedged extractor fails instead of hanging.
    # KEEP THIS TIMEOUT. The heartbeat pump below proves the pump THREAD is
    # alive, which is not the same as proving 7z is making progress -- on a
    # corrupt archive the pump would keep heartbeating forever. Removing a
    # subprocess timeout because "we heartbeat now" is the one way this change
    # makes reliability worse.
    try:
        with heartbeat_pump(f"7z {params.archive_hash[:8]}"):
            res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=3600)
    except subprocess.TimeoutExpired:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise RuntimeError(f"7z extraction timed out for {params.archive_path}")
    except BaseException:
        # Heartbeating is how Temporal DELIVERS cancellation to a sync activity,
        # so this path is reachable on cancellation, not only on error. Without the
        # cleanup, a retry finds a half-extracted directory from the previous
        # attempt and two 7z processes write to the same path.
        shutil.rmtree(out_dir, ignore_errors=True)
        raise
    if res.returncode != 0:
        shutil.rmtree(out_dir, ignore_errors=True)
        # 7z's own, unambiguous statement that the bytes it read are not an archive of
        # any kind it recognises. The routing that calls into this module fires whenever
        # any one detector's guess includes "archive", even when the other detectors
        # disagree, so this is the expected shape for a document a weaker detector
        # mistyped: retrying does not change what 7z reads.
        if b"Cannot open the file as archive" in (res.stderr or b""):
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(
                f"7z extraction failed for {params.archive_path}: {res.stderr[:200]}\n{res.stdout[:200]}",
                non_retryable=True,
            )
        raise RuntimeError(f"7z extraction failed for {params.archive_path}: {res.stderr[:200]}\n{res.stdout[:200]}")

    # Counted here so the group gives the member scan no folder for an archive that
    # holds nothing. 7z exits 0 on an empty archive, so a zero count is not an error.
    entry_count = sum(len(files) for _root, _dirs, files in os.walk(out_dir))
    if entry_count == 0:
        shutil.rmtree(out_dir, ignore_errors=True)
    return {"out_dir": out_dir, "entry_count": entry_count}


@dataclass
class RecordArchiveContainerParams:
    collectionname: str
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]


@activity.defn
@with_heartbeat
def record_archive_container(params: RecordArchiveContainerParams) -> str:
    """Activity that inserts a single archive container row into ClickHouse."""
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa
    log.info("[P3] Recording archive container for %s", params.archive_hash)
    with get_collection_client(params.collectionname) as client:
        tbl_arch = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "archive_hash": pa.array([params.archive_hash], type=pa.string()),
            # Store space-separated list of MIME types
            "archive_type": pa.array([" ".join([t for t in (params.archive_types or []) if t])], type=pa.string()),
        })
        insert_arrow_idempotent(client, "archives", tbl_arch)
    return params.archive_hash


@dataclass
class CleanupTempDirParams:
    out_dir: str


@activity.defn
@with_heartbeat
def cleanup_temp_dir(params: CleanupTempDirParams) -> str:
    """Activity that deletes a temporary directory recursively."""
    import shutil
    log.info("[P3] Cleaning up temp dir: %s", params.out_dir)
    if os.path.isdir(params.out_dir):
        shutil.rmtree(params.out_dir, ignore_errors=True)
    return params.out_dir




def count_member_files(out_dir: str) -> int:
    """The files under `out_dir`, at every level. A folder that does not exist has none.

    An extraction stage puts this count in its value, and the member scan sets the time
    limit of the folder from it.
    """
    if not out_dir:
        return 0
    return sum(len(files) for _root, _dirs, files in os.walk(out_dir))


@activity.defn
@with_heartbeat
def extract_archive_batch(params: StageBatchParams) -> BatchResult:
    """Extract each archive of a group into its own temporary folder, then record it.

    The value of a file is the dictionary of `extract_archive_to_temp` with `member_count`
    added. A file whose extraction fails gets no archive row.
    """
    def step(file: BatchFile) -> Dict[str, Any]:
        value = extract_archive_to_temp(ExtractArchiveParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            archive_hash=file.item_hash,
            archive_types=list(file.mime_types),
            archive_path=file.file_path,
        ))
        record_archive_container(RecordArchiveContainerParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            archive_hash=file.item_hash,
            archive_types=list(file.mime_types),
        ))
        return {**value, "member_count": count_member_files(value.get("out_dir") or "")}

    return run_batch("extract_archive_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step,
                     task_name="extract_archive_to_temp")
