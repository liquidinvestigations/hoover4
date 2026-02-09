"""Archive extraction activities and workflow for scan orchestration."""

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Dict, Any, List
from dataclasses import dataclass
import os
import asyncio
import logging

log = logging.getLogger(__name__)

@dataclass
class ExtractArchiveParams:
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]
    archive_path: str


@activity.defn
def extract_archive_to_temp(params: ExtractArchiveParams) -> Dict[str, Any]:
    """Activity that extracts an archive to a temp directory using 7z."""
    import subprocess
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    out_dir = make_temp_dir(params.collection_dataset, "extract", params.archive_hash)

    log.info("[P3] Extracting archive to %s", out_dir)
    cmd = ["7z", "x", "-y", f"-o{out_dir}", params.archive_path]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode != 0:
        raise RuntimeError(f"7z extraction failed for {params.archive_path}: {res.stderr[:200]}\n{res.stdout[:200]}")

    return {"out_dir": out_dir}


@dataclass
class RecordArchiveContainerParams:
    collection_dataset: str
    archive_hash: str
    archive_types: List[str]


@activity.defn
def record_archive_container(params: RecordArchiveContainerParams) -> str:
    """Activity that inserts a single archive container row into ClickHouse."""
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa
    log.info("[P3] Recording archive container for %s", params.archive_hash)
    with get_clickhouse_client() as client:
        tbl_arch = pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "archive_hash": pa.array([params.archive_hash], type=pa.string()),
            # Store space-separated list of MIME types
            "archive_type": pa.array([" ".join([t for t in (params.archive_types or []) if t])], type=pa.string()),
        })
        client.insert_arrow("archives", tbl_arch)
    return params.archive_hash


@dataclass
class CleanupTempDirParams:
    out_dir: str


@activity.defn
def cleanup_temp_dir(params: CleanupTempDirParams) -> str:
    """Activity that deletes a temporary directory recursively."""
    import shutil
    log.info("[P3] Cleaning up temp dir: %s", params.out_dir)
    if os.path.isdir(params.out_dir):
        shutil.rmtree(params.out_dir, ignore_errors=True)
    return params.out_dir


@dataclass
class ArchiveExtractionWorkflowParams:
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
                collection_dataset=params.collection_dataset,
                archive_hash=params.archive_hash,
                archive_types=params.archive_types,
                archive_path=params.archive_path,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        out_dir = res.get("out_dir")

        # 2) Record archive container row
        await workflow.execute_activity(
            record_archive_container,
            RecordArchiveContainerParams(
                collection_dataset=params.collection_dataset,
                archive_hash=params.archive_hash,
                archive_types=params.archive_types,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 3) Coordinate P0 scan as child workflow, with container and root overrides

        # Import within sandbox
        with workflow.unsafe.imports_passed_through():
            from tasks.P0_scan_disk.workflows import HandleFolders, HandleFoldersParams
        await workflow.execute_child_workflow(
            HandleFolders.run,
            HandleFoldersParams(
                collection_dataset=params.collection_dataset,
                dataset_path=out_dir,
                folder_paths=["/"],
                container_hash=params.archive_hash,
                root_path_prefix="",
            ),
            id=f"scan-archive-{params.collection_dataset}-{params.archive_hash}",
            task_queue="processing-common-queue",
        )

        # 4) Cleanup temp dir
        await workflow.execute_activity(
            cleanup_temp_dir,
            CleanupTempDirParams(out_dir=out_dir),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        return out_dir
