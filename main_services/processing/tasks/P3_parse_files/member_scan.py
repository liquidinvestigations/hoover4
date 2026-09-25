"""The member scan of one group: every container folder that its stages extracted.

The email, archive, PDF and video stages of the group workflow each extract a file into a
temporary folder. `scan_container_folders` scans each of those folders in this process,
with the functions that the disk scan runs, and then removes it. It starts no workflow.

Only the scan of a folder removes that folder, after the scan. So a folder that is gone
when its scan starts was removed from outside the group, and the file gets a failed
result of type `ContainerFolderMissing`. A scan that fails leaves its folder on disk, and a
rerun of the file extracts into the same folder again.
"""

import logging
import os
from typing import Dict

from temporalio import activity
from temporalio.exceptions import ApplicationError

from tasks.heartbeat import with_heartbeat
from tasks.P0_scan_disk.activities import (
    ListDiskFolderParams,
    ScanFolderRangeParams,
    plan_folder_ranges,
    scan_folder_range,
)
from tasks.P3_parse_files.batch_runner import (
    BatchResult,
    ContainerFolder,
    ScanContainerFoldersParams,
    member_scan_seconds,
    run_batch,
)
from tasks.P3_parse_files.parse_archives import CleanupTempDirParams, cleanup_temp_dir

log = logging.getLogger(__name__)

#: The `ApplicationError.type` of a container folder that is gone before its scan.
CONTAINER_FOLDER_MISSING = "ContainerFolderMissing"


def scan_folder_tree(collectionname: str, collection_dataset: str, dataset_path: str,
                     container_hash: str) -> None:
    """Scan every folder under `dataset_path` as members of `container_hash`.

    This is the loop of `HandleFolders.run`, with the same two activity functions and the
    same arguments, called in this process. It plans the name ranges of one folder, scans
    each range, and adds the subfolders that a range returns. A folder whose plan stops at
    a boundary is planned again from that boundary.
    """
    pending = ["/"]
    while pending:
        folder_path = pending.pop()
        after_name = ""
        while True:
            plan = plan_folder_ranges(ListDiskFolderParams(
                collectionname, collection_dataset, dataset_path, folder_path,
                after_name, container_hash, "",
            ))
            edges = [after_name] + list(plan.boundaries)
            if not plan.more_after:
                edges.append("")
            for start, until in zip(edges[:-1], edges[1:]):
                result = scan_folder_range(ScanFolderRangeParams(ListDiskFolderParams(
                    collectionname, collection_dataset, dataset_path, folder_path,
                    start, container_hash, "",
                ), until))
                pending.extend(result.subfolders)
            if not plan.more_after:
                break
            after_name = plan.more_after


@activity.defn
@with_heartbeat
def scan_container_folders(params: ScanContainerFoldersParams) -> BatchResult:
    """Scan each container folder of a group, then remove it.

    The group matches each result to its folder by index, because one file can extract
    two folders with one container hash.
    """
    def scan_one(folder: ContainerFolder) -> Dict[str, str]:
        if not os.path.isdir(folder.out_dir):
            raise ApplicationError(
                f"container folder {folder.out_dir} is gone before its scan",
                type=CONTAINER_FOLDER_MISSING, non_retryable=True)
        log.info("[P3] Scanning container folder %s", folder.out_dir)
        scan_folder_tree(params.collectionname, params.collection_dataset,
                         folder.out_dir, folder.container_hash)
        cleanup_temp_dir(CleanupTempDirParams(out_dir=folder.out_dir))
        return {"status": "scanned"}

    return run_batch("scan_container_folders", params.folders,
                     key=lambda d: d.container_hash, size=lambda d: d.source_size_bytes,
                     step=scan_one, task_name="scan_folder_tree",
                     budget=member_scan_seconds)
