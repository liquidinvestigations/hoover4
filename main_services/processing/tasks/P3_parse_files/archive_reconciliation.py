"""Reconcile removed archive descendants after recursive member discovery completes."""

from temporalio import activity
from tasks.heartbeat import with_heartbeat
from tasks.P6_index_data.params import BuildVfsNodesParams


@activity.defn
@with_heartbeat
def reconcile_archive_descendants(params: BuildVfsNodesParams) -> int:
    from database.clickhouse import get_collection_client, insert_durable
    from tasks.P0_scan_disk.activities import deindex_unreachable
    from tasks.P3_parse_files.parse_archives import _reconcile_removed_descendants, _remove_unreachable_output
    from tasks.P_admin.updates.archive_members import contract
    with get_collection_client(params.collectionname) as client:
        from tasks.P_admin.updates.selectors import ScopeContext, select_unfinished
        pending = client.query(
            "SELECT file_hash, output_identity, fingerprint FROM processing_output_receipts "
            "WHERE collection_dataset = {cd:String} AND output_kind = 'archive_removed_root' AND stage = 'pending' "
            "AND (file_hash, output_identity, fingerprint) NOT IN ("
            "SELECT file_hash, output_identity, fingerprint FROM processing_output_receipts "
            "WHERE collection_dataset = {cd:String} AND output_kind = 'archive_removed_root' AND stage = 'complete')",
            parameters={"cd": params.collection_dataset}).result_rows
        candidates = {row[0] for row in pending}
        if candidates and select_unfinished(client, ScopeContext("dataset", params.collection_dataset, params.collectionname)).count:
            raise RuntimeError("Archive discovery still has unfinished processing")
        if candidates:
            failures = client.query(
                "SELECT count() FROM processing_errors FINAL WHERE collection_dataset = {cd:String} "
                "AND task_name IN ('archive_scan', 'email_scan', 'pdf_process', 'make_pdf_preview', 'video_process', 'extract_archive_to_temp') "
                "AND hash IN (SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0)",
                parameters={"cd": params.collection_dataset}).result_rows
            if failures and failures[0][0]:
                raise RuntimeError("Archive discovery has unresolved container failures")
        if candidates:
            _reconcile_removed_descendants(client, params.collection_dataset, set(candidates), candidates)
    if candidates:
        deindex_unreachable(params.collectionname, params.collection_dataset)
    with get_collection_client(params.collectionname) as client:
        if candidates:
            _remove_unreachable_output(client, params.collection_dataset, candidates)
            completed = [[params.collection_dataset, file_hash, "archive_removed_root", identity,
                          fingerprint, "complete", ""] for file_hash, identity, fingerprint in pending]
            for start in range(0, len(completed), 500):
                insert_durable(client, "processing_output_receipts", completed[start:start + 500],
                    column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id"])
        manifests = client.query(
            "SELECT file_hash, output_identity, op_id FROM processing_output_receipts "
            "WHERE collection_dataset = {cd:String} AND output_kind = 'archive_manifest' "
            "AND fingerprint = {contract:String} AND stage = 'members_published' "
            "AND (file_hash, output_identity) NOT IN (SELECT file_hash, output_identity FROM processing_output_receipts "
            "WHERE collection_dataset = {cd:String} AND output_kind = 'archive_manifest' "
            "AND fingerprint = {contract:String} AND stage = 'reconcile')",
            parameters={"cd": params.collection_dataset, "contract": contract()}).result_rows
        rows = [[params.collection_dataset, file_hash, "archive_manifest", identity, contract(), "reconcile", op_id]
                for file_hash, identity, op_id in manifests]
        for start in range(0, len(rows), 500):
            insert_durable(client, "processing_output_receipts", rows[start:start + 500],
                column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id"])
    return len(pending)
