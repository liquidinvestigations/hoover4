"""Archive extraction activities and workflow for scan orchestration."""

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Dict, Any, List
from dataclasses import dataclass
import os
import asyncio
import logging
from tasks.heartbeat import HEARTBEAT_TIMEOUT, heartbeat_pump, with_heartbeat

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
    # corrupt archive the pump would heartbeat happily forever. Removing a
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
        raise RuntimeError(f"7z extraction failed for {params.archive_path}: {res.stderr[:200]}\n{res.stdout[:200]}")

    # Counted here so the caller can skip the scan of an archive that turned out to
    # hold nothing -- a child workflow and a cleanup activity to discover an empty
    # directory. 7z exits 0 on an empty archive, so a zero count is not an error.
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


@dataclass
class ArchiveExtractionWorkflowParams:
    collectionname: str
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]
    archive_path: str
    timeout_seconds: int


@workflow.defn
class ArchiveExtractionAndScan:
    """Workflow that extracts an archive, scans it via P0, and cleans up."""
    @workflow.run
    async def run(self, params: "ArchiveExtractionWorkflowParams") -> str:
        # 1) Extract to temp dir
        res = await workflow.execute_activity(
            extract_archive_to_temp,
            ExtractArchiveParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                archive_hash=params.archive_hash,
                archive_types=params.archive_types,
                archive_path=params.archive_path,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        out_dir = res.get("out_dir")

        # 2) Record archive container row
        await workflow.execute_activity(
            record_archive_container,
            RecordArchiveContainerParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                archive_hash=params.archive_hash,
                archive_types=params.archive_types,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # An archive that extracted to nothing has already had its directory removed;
        # scanning it would cost a child workflow and a cleanup activity to find an
        # empty folder. `entry_count` is absent only on a result written by an older
        # worker mid-upgrade, where the old unconditional behaviour is still correct.
        if res.get("entry_count", 1) == 0:
            return out_dir

        # 3) Coordinate P0 scan as child workflow, with container and root overrides

        # Import within sandbox
        with workflow.unsafe.imports_passed_through():
            from tasks.P0_scan_disk.workflows import HandleFolders, HandleFoldersParams
            from tasks.visibility import dataset_search_attributes
        await workflow.execute_child_workflow(
            HandleFolders.run,
            HandleFoldersParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                dataset_path=out_dir,
                folder_paths=["/"],
                container_hash=params.archive_hash,
                root_path_prefix="",
            ),
            id=f"scan-archive-{params.collection_dataset}-{params.archive_hash}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        )

        # 4) Cleanup temp dir
        await workflow.execute_activity(
            cleanup_temp_dir,
            CleanupTempDirParams(out_dir=out_dir),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return out_dir
