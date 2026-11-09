"""Select automatic OCR replacements and verify their dependent publication."""

import json
import os
import tempfile
from dataclasses import dataclass, field

from temporalio import activity

from tasks.automatic_ocr import POLICY_VERSION, accepted_capability_digests, capabilities, capability_digest
from tasks.heartbeat import with_heartbeat


@dataclass
class AutomaticOcrScope:
    collectionname: str
    collection_dataset: str
    op_id: str = ""
    after: str = ""
    hashes: list[str] | None = None
    plans: dict[str, str] = field(default_factory=dict)


def hash_sql():
    """Select live OCR sources without a matching applied automatic manifest.

    An applied plan matches when its policy is current and its capability digest is the
    current digest or the digest of a compatible earlier plan version
    (`COMPATIBLE_PLAN_VERSIONS`). A file without an applied plan stays selected, which
    includes historical OCR output and an incomplete reconciliation.
    """
    return ("SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} AND is_deleted = 0 "
        "AND (hash IN (SELECT image_hash FROM image WHERE collection_dataset = {cd:String}) "
        "OR hash IN (SELECT hash FROM pdf_metadata WHERE collection_dataset = {cd:String} AND ifNull(defect, '') = '') "
        "OR hash IN (SELECT hash FROM pdf_previews WHERE collection_dataset = {cd:String})) "
        "AND hash NOT IN (SELECT hash FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
        "GROUP BY hash HAVING argMax(state, revision) = 'applied' AND argMax(policy_version, revision) = {policy:UInt16} "
        "AND argMax(capability_digest, revision) IN {caps:Array(String)})")


def target():
    from tasks.P3_parse_files.ocr_detection import OCR_DETECTION_VERSION
    installed = capabilities()
    return dict(policy=POLICY_VERSION, cap=capability_digest(installed), caps=accepted_capability_digests(installed),
                detector=OCR_DETECTION_VERSION)


@activity.defn
@with_heartbeat
def list_automatic_ocr_files(params: AutomaticOcrScope) -> list[dict]:
    """Read at most 32 source descriptors after the supplied content hash."""
    from database.clickhouse import get_collection_client
    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT blob_hash, any(blob_size_bytes), any(s3_path) FROM blobs "
            "WHERE collection_dataset = {cd:String} AND blob_hash > {after:String} "
            f"AND blob_hash IN ({hash_sql()}) GROUP BY blob_hash ORDER BY blob_hash LIMIT 32",
            parameters={"cd": params.collection_dataset, "after": params.after, **target()}).result_rows
        result = []
        for h, size, path in rows:
            image = client.query("SELECT count() FROM image WHERE collection_dataset = {cd:String} AND image_hash = {h:String}",
                                 parameters={"cd": params.collection_dataset, "h": h}).result_rows[0][0]
            preview = client.query("SELECT count() FROM pdf_previews WHERE collection_dataset = {cd:String} AND hash = {h:String}",
                                   parameters={"cd": params.collection_dataset, "h": h}).result_rows[0][0]
            result.append(dict(item_hash=h, file_size_bytes=int(size), s3_url=path,
                               routes=["image"] if image else [], source_kind="preview" if preview else "original"))
        return result


@activity.defn
@with_heartbeat
def run_automatic_ocr_files(params: AutomaticOcrScope) -> dict[str, str]:
    """Download a bounded source page into one private activity directory."""
    from tasks.P2_execute_plan.activities import write_blob_files
    from tasks.P3_parse_files.automatic_ocr import execute_file
    from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams
    from tasks.P3_parse_files.pdf_parts import prepare_pdf
    files = list_automatic_ocr_files(params) if params.hashes is None else []
    # Hashes pin the descriptor page across activity retries.
    if params.hashes is not None:
        from database.clickhouse import get_collection_client
        with get_collection_client(params.collectionname) as client:
            files = []
            for h in params.hashes:
                row = client.query("SELECT any(blob_size_bytes), any(s3_path) FROM blobs WHERE collection_dataset = {cd:String} AND blob_hash = {h:String}",
                    parameters={"cd": params.collection_dataset, "h": h}).result_rows[0]
                image = client.query("SELECT count() FROM image WHERE collection_dataset = {cd:String} AND image_hash = {h:String}",
                    parameters={"cd": params.collection_dataset, "h": h}).result_rows[0][0]
                preview = client.query("SELECT count() FROM pdf_previews WHERE collection_dataset = {cd:String} AND hash = {h:String}",
                    parameters={"cd": params.collection_dataset, "h": h}).result_rows[0][0]
                files.append(dict(item_hash=h, file_size_bytes=int(row[0]), s3_url=row[1], routes=["image"] if image else [], source_kind="preview" if preview else "original"))
    completed = {}
    with tempfile.TemporaryDirectory(prefix="hoover4-automatic-ocr-") as folder:
        for item in files:
            item["path"] = os.path.join(folder, item["item_hash"])
        write_blob_files(params.collectionname, params.collection_dataset, files, context=params.op_id)
        for item in files:
            file = BatchFile(item_hash=item["item_hash"], file_path=item["path"], file_size_bytes=item["file_size_bytes"],
                             routes=item["routes"], source_kind=item["source_kind"])
            scope = StageBatchParams(params.collectionname, params.collection_dataset, "", [file], params.op_id)
            if file.routes:
                from tasks.P3_parse_files.image_preview import make_image_preview, ImagePreviewParams
                from tasks.P3_parse_files.batch_runner import try_budget_seconds
                make_image_preview(ImagePreviewParams(params.collectionname, params.collection_dataset, file.item_hash,
                    file.file_path, [], ["image"], try_budget_seconds("make_image_preview_batch", file.file_size_bytes)))
            else:
                prepare_pdf(scope, file, compact=True, automatic=True)
            completed[file.item_hash] = execute_file(scope, file)
    return completed


@activity.defn
@with_heartbeat
def verify_automatic_ocr_files(params: AutomaticOcrScope) -> None:
    """Verify durable dependencies and pin the exact completed automatic plan."""
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.automatic_ocr import (write_plan, read_outputs, publication_rows,
        verify_text_publication, verify_artifacts, plan_sources)
    from tasks.P_admin.updates.table_receipts import TableReceiptParams, verify_stages
    from tasks.ocr_targets import _index_states
    from tasks.text_sources import ocr_extracted_by, pdf_ocr_extracted_by
    from tasks.P_admin.updates.table_receipts import verify_vector_index
    with get_collection_client(params.collectionname) as client:
        for h in params.hashes or []:
            rows = client.query("SELECT plan_json, state, has_ocr_output FROM automatic_ocr_plans FINAL "
                "WHERE collection_dataset = {cd:String} AND hash = {h:String} AND plan_digest = {p:String} "
                "ORDER BY revision DESC LIMIT 1",
                parameters={"cd": params.collection_dataset, "h": h, "p": params.plans.get(h, "")}).result_rows
            if not rows or rows[0][1] not in ("published", "applied"):
                raise RuntimeError("Automatic OCR publication changed or has no complete replacement")
            plan = json.loads(rows[0][0])
            if params.plans.get(h) != plan["plan_digest"]:
                raise RuntimeError("Automatic OCR publication changed during dependent processing")
            if len(plan["pages"]) != plan["expected_pages"]:
                raise RuntimeError("Automatic OCR plan has incomplete page coverage")
            from tasks.P3_parse_files.automatic_ocr import require_current_claim
            publication_epoch = require_current_claim(client, plan)
            state = _index_states(client, params.collection_dataset, [h])[h]
            if state.segments and (not state.indexed or any(state.receipts.get(key) != version for key, version in state.segments.items())):
                raise RuntimeError("Automatic OCR has incomplete exact page indexing")
            from tasks.P6_index_data.location_refresh import load_indexed_ids
            shards = client.query("SELECT shard_name FROM index_state FINAL WHERE collection_dataset = {cd:String} "
                "AND file_hash = {h:String}", parameters={"cd": params.collection_dataset, "h": h}).result_rows
            if not shards:
                raise RuntimeError("Automatic OCR has no stored document index publication")
            from database.manticore import shard_table_from_name, table_has_column
            if not table_has_column(shard_table_from_name(shards[0][0]), "has_ocr_output"):
                raise RuntimeError("Automatic OCR requires the current search schema before settlement")
            indexed = load_indexed_ids(params.collectionname, params.collection_dataset, {h: shards[0][0]})
            if any(values.get(h) == frozenset({-1}) for values in indexed):
                raise RuntimeError("Automatic OCR has incomplete indexed page coverage or attributes")
            extractor = ocr_extracted_by if plan["source_kind"] == "image" else pdf_ocr_extracted_by
            sources = plan_sources(plan)
            output = read_outputs(client, plan)
            bodies = {}
            for item in output.values():
                bodies.setdefault(extractor(item["engine"], item["languages"]), []).extend(item["pages"])
            bodies = publication_rows(client, params.collection_dataset, h, plan["source_kind"], bodies)
            verify_text_publication(client, params, h, bodies)
            verify_artifacts(params.collectionname, output.values())
            verify_vector_index(client, TableReceiptParams(params.collectionname, params.collection_dataset, params.op_id, [h]))
            for source in sources:
                verify_stages(client, TableReceiptParams(params.collectionname, params.collection_dataset,
                    params.op_id, [h], ["entities", "regex", "embed", "index_text", "index_vectors"], text_source=source))
            from tasks.P3_parse_files.table_generations import GenerationCommand, send_command
            send_command(GenerationCommand(params.collectionname, h, "apply_ocr_plan", owner_op=params.op_id,
                manifest=json.dumps(dict(dataset=params.collection_dataset, plan_digest=plan["plan_digest"], publication_epoch=publication_epoch)).encode()))


@activity.defn
@with_heartbeat
def verify_ingested_automatic_ocr(params: AutomaticOcrScope) -> None:
    """Apply only the exact automatic publications prepared by this ingestion operation."""
    from database.clickhouse import get_collection_client
    with get_collection_client(params.collectionname) as client:
        rows = client.query("SELECT file_hash, argMax(output_identity, receipt_version) FROM processing_output_receipts "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} AND output_kind = 'automatic_ocr' "
            "AND fingerprint = {op:String} AND stage = 'prepared' GROUP BY file_hash",
            parameters={"cd": params.collection_dataset, "hashes": params.hashes or [], "op": params.op_id}).result_rows
    params.hashes = [h for h, _ in rows]
    params.plans = dict(rows)
    verify_automatic_ocr_files(params)
