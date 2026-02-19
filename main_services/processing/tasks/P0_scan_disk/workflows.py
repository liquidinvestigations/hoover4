"""Temporal workflows for recursive disk scanning and ingestion."""

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import List, Dict, Any
from dataclasses import dataclass
import asyncio
import hashlib
import json
import logging
log = logging.getLogger(__name__)

# Import our activities, passing them through the sandbox
with workflow.unsafe.imports_passed_through():
    from tasks.P0_scan_disk.activities import (
        list_disk_folder, insert_vfs_directories, ingest_files_batch,
        ListDiskFolderParams, InsertVfsDirectoriesParams, IngestFilesBatchParams,
    )


def _batch_seq(items: List[Any], batch_size: int) -> List[List[Any]]:
    return [items[i:i + batch_size] for i in range(0, len(items), batch_size)]


def _batch_files_by_size(files: List[Dict[str, Any]], max_count: int, max_bytes: int) -> List[List[Dict[str, Any]]]:
    batches: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_bytes = 0
    for f in files:
        size = int(f.get("size", 0))
        if size > max_bytes:
            if current:
                batches.append(current)
                current = []
                current_bytes = 0
            batches.append([f])
            continue
        if len(current) >= max_count or (current_bytes + size) > max_bytes:
            if current:
                batches.append(current)
            current = [f]
            current_bytes = size
        else:
            current.append(f)
            current_bytes += size
    if current:
        batches.append(current)
    return batches


def _child_workflow_id(prefix: str, params: Any) -> str:
    # Stable JSON for hashing. Accepts dicts or dataclass instances.
    try:
        from dataclasses import is_dataclass, asdict
        if is_dataclass(params):
            base = asdict(params)
        elif isinstance(params, dict):
            base = params
        else:
            # Best-effort fallback
            base = getattr(params, "__dict__", {"value": str(params)})
        payload = json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except Exception:
        payload = json.dumps({"value": str(params)}).encode("utf-8")
    digest = hashlib.md5(payload).hexdigest()[:32]
    return f"{prefix}-{digest}"


@dataclass
class HandleFilesParams:
    collection_dataset: str
    dataset_path: str
    file_paths: List[str]
    container_hash: str = ""
    root_path_prefix: str = ""


@workflow.defn
class HandleFiles:
    """Workflow that ingests a batch of files and inserts VFS rows."""
    @workflow.run
    async def run(self, params: HandleFilesParams) -> str:
        file_paths: List[str] = params.file_paths

        log.info("Handling %s files for %s", len(file_paths), params.collection_dataset)

        # Single batch activity call for performance (dedup and batch inserts inside)
        result = await workflow.execute_activity(
            ingest_files_batch,
            IngestFilesBatchParams(
                collection_dataset=params.collection_dataset,
                dataset_path=params.dataset_path,
                file_paths=file_paths,
                container_hash=(params.container_hash or ""),
                root_path_prefix=(params.root_path_prefix or ""),
            ),
            start_to_close_timeout=timedelta(hours=4),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        log.info("Handled %s files for %s", len(file_paths), params.collection_dataset)
        return result


@dataclass
class HandleFoldersParams:
    collection_dataset: str
    dataset_path: str
    folder_paths: List[str]
    container_hash: str = ""
    root_path_prefix: str = ""


@workflow.defn
class HandleFolders:
    """Workflow that lists folders, inserts dirs, and spawns child scans."""
    @workflow.run
    async def run(self, params: HandleFoldersParams) -> str:
        folder_paths: List[str] = params.folder_paths  # max 10
        log.info("Handling %s folders for %s", len(folder_paths), params.collection_dataset)

        # List each folder in parallel
        list_futs = []
        for folder_rel in folder_paths:
            list_futs.append(
                workflow.execute_activity(
                    list_disk_folder,
                    ListDiskFolderParams(
                        collection_dataset=params.collection_dataset,
                        dataset_path=params.dataset_path,
                        folder_path=folder_rel,
                    ),
                    start_to_close_timeout=timedelta(minutes=50),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            )

        listings = await asyncio.gather(*list_futs)

        # Aggregate dirs and files
        all_dirs: List[str] = []
        all_files_meta: List[Dict[str, Any]] = []
        for res in listings:
            for d in res.get("dirs", []):
                p = d["path"]
                all_dirs.append(p)
            for f in res.get("files", []):
                all_files_meta.append(f)

        # Insert directories at this level
        if all_dirs:
            await workflow.execute_activity(
                insert_vfs_directories,
                InsertVfsDirectoriesParams(
                    collection_dataset=params.collection_dataset,
                    dir_paths=all_dirs,
                    container_hash=(params.container_hash or ""),
                ),
                start_to_close_timeout=timedelta(minutes=40),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        # Batch child folders and files
        child_folder_batches = _batch_seq(all_dirs, 10)
        child_file_batches = _batch_files_by_size(all_files_meta, max_count=100, max_bytes=50 * 1024 * 1024)

        # Start children in parallel
        child_futs = []
        for folder_batch in child_folder_batches:
            params_obj = HandleFoldersParams(
                collection_dataset=params.collection_dataset,
                dataset_path=params.dataset_path,
                folder_paths=folder_batch,
                container_hash=(params.container_hash or ""),
                root_path_prefix=(params.root_path_prefix or ""),
            )
            child_futs.append(
                workflow.execute_child_workflow(
                    HandleFolders.run,
                    params_obj,
                    id=_child_workflow_id("HandleFolders", params_obj),
                    task_queue="processing-common-queue",
                )
            )

        for file_batch in child_file_batches:
            file_paths = [f["path"] for f in file_batch]
            params_obj = HandleFilesParams(
                collection_dataset=params.collection_dataset,
                dataset_path=params.dataset_path,
                file_paths=file_paths,
                container_hash=(params.container_hash or ""),
                root_path_prefix=(params.root_path_prefix or ""),
            )
            child_futs.append(
                workflow.execute_child_workflow(
                    HandleFiles.run,
                    params_obj,
                    id=_child_workflow_id("HandleFiles", params_obj),
                    task_queue="processing-common-queue",
                )
            )

        if child_futs:
            await asyncio.gather(*child_futs)

        log.info("Handled %s folders for %s", len(folder_paths), params.collection_dataset)
        return f"handled {len(folder_paths)} folders"


@dataclass
class IngestDiskDatasetParams:
    collection_dataset: str
    dataset_path: str


@workflow.defn
class IngestDiskDataset:
    """Workflow that starts a recursive disk ingestion from a dataset root."""
    @workflow.run
    async def run(self, params: IngestDiskDatasetParams) -> str:
        log.info("Starting ingestion for %s", params.collection_dataset)
        log.info("Dataset path: %s", params.dataset_path)

        # Seed with root folder
        args = {
            "collection_dataset": params.collection_dataset,
            "dataset_path": params.dataset_path,
            "folder_paths": ["/"],
        }
        await workflow.execute_child_workflow(
            HandleFolders.run,
            args,
            task_queue="processing-common-queue",
            id=_child_workflow_id("HandleFolders", args),
        )
        log.info("Finished disk ingestion for %s", params.collection_dataset)

        return f"started ingestion for {params.collection_dataset}"