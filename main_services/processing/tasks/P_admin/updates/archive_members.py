"""Rewrite successful split archive manifests without changing historical error policy."""

import hashlib
import json
import os
import tempfile

from temporalio import activity
from tasks.heartbeat import with_heartbeat
from tasks.P_admin.updates.params import TablePlansParams


def contract() -> str:
    from tasks.stage_versions import STAGE_VERSIONS
    return f"archive={STAGE_VERSIONS['archive']}"


def pending_archives(client, collection_dataset, *, stage="complete") -> dict:
    from tasks.P3_parse_files.split_volumes import group_volume_sets
    candidates = {row[0] for row in client.query(
        "SELECT DISTINCT archive_hash FROM archives WHERE collection_dataset = {cd:String} "
        "AND archive_hash IN (SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0) "
        "AND archive_hash NOT IN (SELECT hash FROM processing_errors FINAL WHERE collection_dataset = {cd:String} "
        "AND task_name IN ('archive_scan', 'extract_archive_to_temp', 'extract_archive_batch') "
        "AND hash NOT IN (SELECT file_hash FROM processing_output_receipts WHERE collection_dataset = {cd:String} "
        "AND output_kind = 'archive_manifest' AND fingerprint = {contract:String} AND stage = 'attempt'))",
        parameters={"cd": collection_dataset, "contract": contract()}).result_rows}
    if not candidates:
        return {}
    rows = client.query(
        "SELECT f.container_hash, f.path, f.hash, f.file_size_bytes, b.s3_path FROM vfs_files AS f FINAL "
        "LEFT JOIN (SELECT blob_hash, any(s3_path) AS s3_path FROM blobs WHERE collection_dataset = {cd:String} "
        "GROUP BY blob_hash) AS b ON b.blob_hash = f.hash WHERE f.collection_dataset = {cd:String} AND f.is_deleted = 0",
        parameters={"cd": collection_dataset}).result_rows
    groups = {}
    for volume_set in group_volume_sets(rows, collection_dataset):
        entry = volume_set.entry
        if entry and entry[2] in candidates and volume_set.has_siblings():
            groups.setdefault(entry[2], []).append(volume_set)
    receipts = {(row[0], row[1]) for row in client.query(
        "SELECT file_hash, output_identity FROM processing_output_receipts "
        "WHERE collection_dataset = {cd:String} AND output_kind = 'archive_manifest' "
        "AND fingerprint = {contract:String} AND stage = {stage:String}",
        parameters={"cd": collection_dataset, "contract": contract(), "stage": stage}).result_rows}
    pending = {}
    for file_hash, sets in groups.items():
        complete = {value.manifest_identity(): value for value in sets if not value.missing()}
        identities = sorted(complete) if complete else sorted({value.manifest_identity() for value in sets})
        identity = identities[0] if len(identities) == 1 else hashlib.sha256(json.dumps(identities).encode()).hexdigest()
        if (file_hash, identity) not in receipts:
            pending[file_hash] = identity, max(value.size for value in sets)
    return pending


@activity.defn
@with_heartbeat
def restore_archive_members(params: TablePlansParams) -> int:
    from database.clickhouse import get_collection_client
    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files.batch_runner import BatchFile, ContainerFolder, ScanContainerFoldersParams, StageBatchParams
    from tasks.P3_parse_files.member_scan import scan_container_folders
    from tasks.P3_parse_files.parse_archives import extract_archive_batch
    with get_collection_client(params.collectionname) as client:
        pending = pending_archives(client, params.collection_dataset, stage="members_published")
        hashes = sorted(pending)[:100]
        if not hashes:
            return 0
        rows = client.query(
            "SELECT b.blob_hash, any(b.blob_size_bytes), any(b.s3_path), groupUniqArray(splitByChar('/', f.path)[-1]) "
            "FROM blobs AS b INNER JOIN vfs_files AS f FINAL ON f.hash = b.blob_hash "
            "AND f.collection_dataset = b.collection_dataset WHERE b.collection_dataset = {cd:String} "
            "AND b.blob_hash IN {hashes:Array(String)} AND f.is_deleted = 0 GROUP BY b.blob_hash",
            parameters={"cd": params.collection_dataset, "hashes": hashes}).result_rows
    if {row[0] for row in rows} != set(hashes):
        raise RuntimeError("A split archive has no stored source")
    from database.clickhouse import insert_durable
    with get_collection_client(params.collectionname) as client:
        insert_durable(client, "processing_output_receipts",
            [[params.collection_dataset, file_hash, "archive_manifest", pending[file_hash][0],
              contract(), "attempt", params.op_id] for file_hash in hashes],
            column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id"])
    with tempfile.TemporaryDirectory(prefix="hoover4-archive-update-") as folder:
        write_blob_files(params.collectionname, params.collection_dataset, [
            {"item_hash": file_hash, "file_size_bytes": int(size), "s3_url": path,
             "path": os.path.join(folder, file_hash)} for file_hash, size, path, names in rows],
            context=f"{params.collection_dataset} archive manifest update")
        files = [BatchFile(file_hash, os.path.join(folder, file_hash), pending[file_hash][1], file_names=names)
                 for file_hash, size, path, names in rows]
        result = extract_archive_batch(StageBatchParams(params.collectionname, params.collection_dataset,
                                                        "archive-update", files, params.op_id))
        folders = []
        for item in result.results:
            if item.status == "failed" or not isinstance(item.value, dict) or not item.value.get("reconcile_members"):
                raise RuntimeError(f"A split archive could not publish its complete members: "
                                   f"{item.error_type}: {item.error_message or str(item.value)[:500]}")
            value = item.value
            folders.append(ContainerFolder(value["container_hash"], value["out_dir"], "archive_scan",
                member_count=int(value.get("member_count") or 0), reconcile_members=True,
                archive_manifest_identity=value["archive_manifest_identity"]))
        scanned = scan_container_folders(ScanContainerFoldersParams(params.collectionname,
            params.collection_dataset, "archive-update", folders, params.op_id))
        if any(item.status == "failed" for item in scanned.results):
            raise RuntimeError("A split archive member scan did not complete")
    return len(rows)


@activity.defn
@with_heartbeat
def finish_archive_members(params: TablePlansParams) -> int:
    from database.clickhouse import get_collection_client, insert_durable
    from tasks.P_admin.updates.selectors import ScopeContext, select_unfinished
    with get_collection_client(params.collectionname) as client:
        if select_unfinished(client, ScopeContext("dataset", params.collection_dataset, params.collectionname)).count:
            raise RuntimeError("Archive members still have unfinished processing")
        failures = client.query(
            "SELECT count() FROM processing_errors FINAL WHERE collection_dataset = {cd:String} AND op_id = {op:String}",
            parameters={"cd": params.collection_dataset, "op": params.op_id}).result_rows
        if failures and failures[0][0]:
            raise RuntimeError("Archive member processing has recorded errors")
        pending = pending_archives(client, params.collection_dataset)
        reconciled = pending_archives(client, params.collection_dataset, stage="reconcile")
        if reconciled:
            raise RuntimeError("Archive member reconciliation remains incomplete")
        values = [[params.collection_dataset, file_hash, "archive_manifest", identity, contract(), "complete", params.op_id]
                  for file_hash, (identity, size) in pending.items()]
        for start in range(0, len(values), 500):
            insert_durable(client, "processing_output_receipts", values[start:start + 500],
                           column_names=["collection_dataset", "file_hash", "output_kind", "output_identity",
                                         "fingerprint", "stage", "op_id"])
    return len(values)
