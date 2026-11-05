"""The member scan of one group: every container folder that its stages extracted.

The email, archive, PDF and video stages of the group workflow each extract a file into a
temporary folder. `scan_container_folders` scans each of those folders in this process,
with the functions that the disk scan runs, and then removes it. It starts no workflow.

Only the scan of a folder removes that folder, after the scan. An earlier activity attempt
can remove a folder before its result is recorded. The retry reads `vfs_files` and reports a
recovered scan when that container already has stored members. A scan that fails leaves its
folder on disk. A new extraction attempt uses another folder.
Split archives reconcile removed members after the successful scan reaches storage.
A durable receipt identifies each completed reconciliation attempt.
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
    scan_folder_range_v2,
    subfolder_path,
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
                     container_hash: str, op_id: str = "") -> None:
    """Scan every folder under `dataset_path` as members of `container_hash`.

    This is the loop of `HandleFolders.run`, with the same two activity functions and the
    same arguments, called in this process. It plans the name ranges of one folder, scans
    each range, and adds the path of each subfolder name that a range returns. A folder
    whose plan stops at a boundary is planned again from that boundary.
    """
    pending = ["/"]
    while pending:
        folder_path = pending.pop()
        after_name = ""
        while True:
            plan = plan_folder_ranges(ListDiskFolderParams(
                collectionname, collection_dataset, dataset_path, folder_path,
                after_name, container_hash, "", op_id,
            ))
            edges = [after_name] + list(plan.boundaries)
            if not plan.more_after:
                edges.append("")
            for start, until in zip(edges[:-1], edges[1:]):
                result = scan_folder_range_v2(ScanFolderRangeParams(ListDiskFolderParams(
                    collectionname, collection_dataset, dataset_path, folder_path,
                    start, container_hash, "", op_id,
                ), until))
                pending.extend(subfolder_path(folder_path, name)
                               for name in result.subfolder_names)
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
            from database.clickhouse import get_collection_client

            if folder.reconcile_members:
                if archive_scan_receipt(params, folder):
                    return {"status": "scanned", "recovered": "published reconciliation receipt"}
                raise ApplicationError(
                    "The archive scan has no complete reconciliation receipt",
                    type=CONTAINER_FOLDER_MISSING, non_retryable=True)

            try:
                with get_collection_client(params.collectionname) as client:
                    rows = client.query(
                        "SELECT count() FROM vfs_files "
                        "WHERE collection_dataset = {cd:String} "
                        "AND container_hash = {ch:String}",
                        parameters={"cd": params.collection_dataset, "ch": folder.container_hash},
                    ).result_rows
            except Exception:
                rows = []
                log.warning("[P3] Could not read members for removed container folder %s",
                            folder.out_dir)
            member_count = int(rows[0][0]) if rows else 0
            if member_count:
                log.info("[P3] Recovered member scan for removed container folder %s", folder.out_dir)
                return {"status": "scanned", "recovered": "folder removed by an earlier attempt"}
            raise ApplicationError(
                f"container folder {folder.out_dir} is gone before its scan",
                type=CONTAINER_FOLDER_MISSING, non_retryable=True)
        log.info("[P3] Scanning container folder %s", folder.out_dir)
        scan_folder_tree(params.collectionname, params.collection_dataset,
                         folder.out_dir, folder.container_hash, params.op_id)
        from tasks.P3_parse_files.insert_batch import current_batch

        def finish():
            if folder.reconcile_members:
                from tasks.P3_parse_files.parse_archives import _tombstone_absent_members
                _tombstone_absent_members(params.collectionname, params.collection_dataset,
                                          folder.container_hash, folder.out_dir)
                archive_scan_receipt(params, folder, write=True)
            cleanup_temp_dir(CleanupTempDirParams(out_dir=folder.out_dir))

        current_batch().after_storage(finish)
        return {"status": "scanned"}

    return run_batch("scan_container_folders", params.folders,
                     key=lambda d: d.container_hash, size=lambda d: d.source_size_bytes,
                     step=scan_one, task_name="scan_folder_tree",
                     budget=member_scan_seconds)


def archive_scan_receipt(params, folder, *, write=False) -> bool:
    """Read or write the receipt of this exact extraction attempt."""
    import hashlib
    from database.clickhouse import get_collection_client, insert_durable
    identity = hashlib.sha256(folder.out_dir.encode()).hexdigest()
    fingerprint = "archive-reconciliation-1"
    with get_collection_client(params.collectionname) as client:
        if write:
            rows = [[params.collection_dataset, folder.container_hash, "archive", identity,
                     fingerprint, "reconcile", params.op_id]]
            if folder.archive_manifest_identity:
                from tasks.P_admin.updates.archive_members import contract
                rows.append([params.collection_dataset, folder.container_hash, "archive_manifest",
                             folder.archive_manifest_identity, contract(), "members_published", params.op_id])
            insert_durable(client, "processing_output_receipts", rows,
                           column_names=["collection_dataset", "file_hash", "output_kind", "output_identity",
                                         "fingerprint", "stage", "op_id"])
            return True
        rows = client.query(
            "SELECT count() FROM processing_output_receipts WHERE collection_dataset = {cd:String} "
            "AND file_hash = {hash:String} AND output_kind = 'archive' AND output_identity = {identity:String} "
            "AND fingerprint = {fingerprint:String} AND stage = 'reconcile'",
            parameters={"cd": params.collection_dataset, "hash": folder.container_hash,
                        "identity": identity, "fingerprint": fingerprint}).result_rows
        return bool(rows and rows[0][0])
