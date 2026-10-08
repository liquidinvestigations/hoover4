"""The `rerun_ocr` operation: run OCR again for a dataset with unchanged settings.

The operation reopens every plan that holds an image or a PDF and runs `ExecutePlans`
for the dataset. The OCR stages then produce each `(file, engine, languages)` result
that the current settings ask for and that does not exist yet. That covers an image
that never received OCR and a searchable PDF variant of a newly enabled PDF provider.

With `replace_existing`, the OCR stages of this operation do not skip existing results.
They run each pass again and write the new result. A failed pass leaves the previous
result in place, because a result row is replaced only when its successor is written.

Plans are the unit of work, as in `change_ocr_languages`, so the other stages of a
reopened plan run again too. Every stage is idempotent, so that costs time only.
"""

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from temporalio import activity

from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

OPERATION_KIND = "rerun_ocr"


@dataclass
class RerunOcrParams:
    collectionname: str
    collection_dataset: str
    op_id: str


@lru_cache(maxsize=256)
def replaces_existing(op_id: str) -> bool:
    """Whether the OCR stages running under `op_id` must not skip existing results.

    Cached for the process lifetime: the kind and the inputs of an operation do not
    change after it is created.
    """
    if not op_id:
        return False
    from database.operations import get_operation

    try:
        row = get_operation(op_id)
    except Exception:  # noqa: BLE001 - a failed read keeps the normal skip
        log.warning("[P_admin] could not read operation %s", op_id, exc_info=True)
        return False
    if not row or row.get("kind") != OPERATION_KIND:
        return False
    detail = row.get("detail") or "{}"
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except ValueError:
            return False
    return bool(isinstance(detail, dict) and detail.get("replace_existing"))


@activity.defn
@with_heartbeat
def reopen_plans_for_ocr_rerun(params: RerunOcrParams) -> int:
    """Delete the finished markers of every plan holding an image or a PDF.

    The candidates come from the detector rows in `file_types`, so an image with no OCR
    result is selected as well as one with a result.
    """
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        plan_hashes = [row[0] for row in client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits FINAL "
            "WHERE collection_dataset = {cd:String} AND item_hash IN ("
            " SELECT DISTINCT hash FROM file_types "
            " WHERE collection_dataset = {cd:String} AND hasAny(file_type, ['image', 'pdf']))",
            parameters={"cd": params.collection_dataset},
        ).result_rows if row and row[0]]
        if not plan_hashes:
            log.info("[P_admin] %s has no image or PDF, nothing to reopen",
                     params.collection_dataset)
            return 0
        client.command(
            "ALTER TABLE processing_plan_finished DELETE "
            "WHERE collection_dataset = {cd:String} AND plan_hash IN {ph:Array(String)}",
            parameters={"cd": params.collection_dataset, "ph": plan_hashes},
        )
    log.info("[P_admin] %s: reopened %d plan(s) for an OCR rerun",
             params.collection_dataset, len(plan_hashes))
    return len(plan_hashes)
