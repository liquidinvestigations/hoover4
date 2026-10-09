"""The `rerun_ocr` operation, which the dataset page names "Run OCR".

One run brings every OCR target of the dataset under its current settings to done, and a
second run on a finished dataset sends no OCR request. `tasks/ocr_targets.py` defines the
targets and the rule that says when one is done. The run has two phases.

1. **Unfinished plans.** When the dataset has an unfinished plan or a blob without a plan,
   `ExecutePlans` runs them with every stage, as ingestion does. That completes a cancelled
   or failed ingestion and creates the member files of containers that were never
   extracted. Progress counts plans in this phase.
2. **Open targets.** `record_ocr_run_targets` writes one `ocr_run_targets` row for each
   target that is not done. `OcrRunPlan` then runs only the preview and OCR stages for the
   open image and PDF targets of one plan, and P4, P5 and P6 only for the files whose OCR
   text is not indexed. New OCR text adds an index target, so the total of the progress
   can increase. `settle_ocr_run_targets` is the only writer of `done = 1`. A plan whose
   final settlement leaves a target open fails, and `verify_ocr_run_completion` fails the
   operation while any target of it is open.

The second phase reads and writes no `processing_plan_finished` row. Plans only group the
files and say where their bytes are. A cancel at any point leaves the stored results, skips
and errors in place, and the next run computes the open targets from them again.

An existing result is never produced again: the OCR stages skip every pass that has a
result. A target with an OCR error counts as done, and the error retry repeats it.

`RerunOcr` executions that started before the target-based run replay the whole-plan path:
`reopen_plans_for_ocr_rerun`, then `ExecutePlans`.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from temporalio import activity

from tasks.heartbeat import HeartbeatClock, with_heartbeat

log = logging.getLogger(__name__)

OPERATION_KIND = "rerun_ocr"
#: Plans of one page of the target phase. A full page continues as new.
OCR_RUN_PAGE = 1000
#: Open targets named in the error of an incomplete run or plan.
OCR_RUN_SAMPLES = 5
#: The error type of a plan or an operation that ends with an open target.
OCR_RUN_INCOMPLETE = "OcrRunIncomplete"


@dataclass
class RerunOcrParams:
    collectionname: str
    collection_dataset: str
    op_id: str
    #: True after the first phase ran and the open targets were recorded.
    listed: bool = False
    #: The last plan of the previous page, for continue-as-new.
    after: str = ""
    #: Plans that the target phase took, over every page so far.
    plans: int = 0
    failed_plans: int = 0
    failed_dataset_steps: int = 0
    #: Plans that `ExecutePlans` ran in the first phase.
    phase_one_plans: int = 0


@dataclass
class ListOcrRunPlansParams:
    collectionname: str
    collection_dataset: str
    op_id: str
    after: str = ""


@dataclass
class OcrRunPlanParams:
    collectionname: str
    collection_dataset: str
    op_id: str
    plan_hash: str


@dataclass
class OcrRunFile:
    """One file of a plan with an open image or searchable-PDF target."""

    item_hash: str
    file_size_bytes: int = 0
    s3_url: str = ""
    mime_types: List[str] = field(default_factory=list)
    #: Engines with an open image target for this file.
    image_engines: List[str] = field(default_factory=list)
    #: Engines with an open searchable-PDF target for this file.
    pdf_engines: List[str] = field(default_factory=list)


@dataclass
class OcrRunPlanWork:
    files: List[OcrRunFile] = field(default_factory=list)
    #: Files with an open index target, or with text that the load wrote from a stored result.
    index_hashes: List[str] = field(default_factory=list)


@dataclass
class SettleOcrRunTargetsParams:
    collectionname: str
    collection_dataset: str
    op_id: str
    plan_hash: str
    #: The files to settle. Empty means every open target of the plan.
    hashes: List[str] = field(default_factory=list)


@dataclass
class SettleOcrRunTargetsResult:
    settled: int = 0
    #: Open targets among the selected ones after the settlement.
    remaining: int = 0


@dataclass
class OcrTextPendingParams:
    collectionname: str
    collection_dataset: str
    op_id: str
    plan_hash: str
    hashes: List[str] = field(default_factory=list)


@dataclass
class VerifyOcrRunParams:
    collectionname: str
    collection_dataset: str
    op_id: str


@activity.defn
@with_heartbeat
def reopen_plans_for_ocr_rerun(params: RerunOcrParams) -> int:
    """Delete the finished markers of every plan holding an image or a PDF.

    The whole-plan path of `RerunOcr` executions that started before the target-based
    run. The candidates come from the detector rows in `file_types`, so an image with no
    OCR result is selected as well as one with a result.
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


# ---- target rows ---------------------------------------------------------------------------

_PLAN_ITEMS_SQL = (
    "SELECT plan_hash, groupArray(item_hash) FROM processing_plan_hits FINAL "
    "WHERE collection_dataset = {cd:String} {plan} AND item_hash IN ("
    " SELECT DISTINCT hash FROM file_types WHERE collection_dataset = {cd:String} "
    " AND hasAny(file_type, ['image', 'pdf'])) "
    "GROUP BY plan_hash ORDER BY plan_hash"
)


def _plan_items(client, collection_dataset: str, plan_hash: str = "") -> List[Tuple[str, List[str]]]:
    """Each plan with its items that a detector typed as an image or a PDF."""
    parameters = {"cd": collection_dataset}
    plan = ""
    if plan_hash:
        plan = "AND plan_hash = {ph:String}"
        parameters["ph"] = plan_hash
    rows = client.query(_PLAN_ITEMS_SQL.replace("{plan}", plan), parameters=parameters).result_rows
    return [(plan_hash, sorted(set(items))) for plan_hash, items in rows]


def _image_items(routes, items: Sequence[str]) -> List[str]:
    return [h for h in items if h in routes and "image" in routes[h].routes]


def _plan_targets(client, collectionname: str, collection_dataset: str,
                  items: Sequence[str], pairs) -> Tuple[Dict, List[str]]:
    """The targets of one plan's items, after the text of stored results is written.

    Returns the targets with their setting versions, and the files whose text was written.
    """
    from tasks.ocr_targets import (
        STAGE_IMAGE, STAGE_INDEX, STAGE_PDF, SettingVersion, Target, chunked,
        recover_ocr_text, stored_routes,
    )
    from tasks.text_sources import OCR_PREFIX

    routes = stored_routes(client, collection_dataset, items)
    images = _image_items(routes, items)
    recovered = recover_ocr_text(client, collectionname, collection_dataset, images,
                                 [(engine, languages) for engine, languages, _ in pairs.image])
    pdf_rows: set = set()
    with_text: set = set()
    for chunk in chunked(items):
        parameters = {"cd": collection_dataset, "h": chunk, "p": OCR_PREFIX}
        pdf_rows.update(row[0] for row in client.query(
            "SELECT DISTINCT pdf_hash FROM pdfs WHERE collection_dataset = {cd:String} "
            "AND pdf_hash IN {h:Array(String)}", parameters=parameters).result_rows)
        with_text.update(row[0] for row in client.query(
            "SELECT DISTINCT file_hash FROM text_content WHERE collection_dataset = {cd:String} "
            "AND file_hash IN {h:Array(String)} AND startsWith(extracted_by, {p:String})",
            parameters=parameters).result_rows)
    targets: Dict = {}
    for file_hash in images:
        for engine, languages, version in pairs.image:
            targets[Target(file_hash, STAGE_IMAGE, engine, languages)] = version
    for file_hash in items:
        if file_hash in pdf_rows and file_hash in routes and "pdf" in routes[file_hash].routes:
            for engine, languages, version in pairs.pdf:
                targets[Target(file_hash, STAGE_PDF, engine, languages)] = version
    for file_hash in sorted(with_text):
        targets[Target(file_hash, STAGE_INDEX)] = SettingVersion()
    return targets, recovered


def _insert_targets(client, op_id: str, collection_dataset: str, plan_hash: str,
                    rows: Sequence[Tuple], done: int) -> None:
    """Write `(target, setting version)` rows of one plan with the given `done` value."""
    import pyarrow as pa

    from database.clickhouse import insert_arrow_durable

    if not rows:
        return
    count = len(rows)
    insert_arrow_durable(client, "ocr_run_targets", pa.table({
        "op_id": pa.array([op_id] * count, type=pa.string()),
        "collection_dataset": pa.array([collection_dataset] * count, type=pa.string()),
        "plan_hash": pa.array([plan_hash] * count, type=pa.string()),
        "file_hash": pa.array([t.file_hash for t, _ in rows], type=pa.string()),
        "stage": pa.array([t.stage for t, _ in rows], type=pa.string()),
        "engine": pa.array([t.engine for t, _ in rows], type=pa.string()),
        "languages": pa.array([t.languages for t, _ in rows], type=pa.string()),
        "since": pa.array([v.version_us for _, v in rows], type=pa.timestamp("us")),
        "since_is_precise": pa.array([1 if v.is_precise else 0 for _, v in rows],
                                     type=pa.uint8()),
        "done": pa.array([done] * count, type=pa.uint8()),
    }))


def _open_targets(client, op_id: str, collection_dataset: str, plan_hash: str,
                  hashes: Sequence[str] = ()) -> Dict:
    """The open targets of one plan, or of `hashes` in it, with their setting versions."""
    from tasks.ocr_targets import SettingVersion, Target

    parameters = {"op": op_id, "cd": collection_dataset, "ph": plan_hash}
    files = ""
    if hashes:
        files = "AND file_hash IN {h:Array(String)} "
        parameters["h"] = list(hashes)
    rows = client.query(
        "SELECT file_hash, stage, engine, languages, toUnixTimestamp64Micro(since), "
        "since_is_precise FROM ocr_run_targets FINAL "
        "WHERE op_id = {op:String} AND collection_dataset = {cd:String} "
        "AND plan_hash = {ph:String} " + files + "AND done = 0",
        parameters=parameters,
    ).result_rows
    return {Target(file_hash, stage, engine, languages): SettingVersion(int(since), bool(precise))
            for file_hash, stage, engine, languages, since, precise in rows}


def _settle(client, params: SettleOcrRunTargetsParams) -> SettleOcrRunTargetsResult:
    from tasks.ocr_targets import settled

    open_targets = _open_targets(client, params.op_id, params.collection_dataset,
                                 params.plan_hash, params.hashes)
    done = settled(client, params.collection_dataset, open_targets)
    _insert_targets(client, params.op_id, params.collection_dataset, params.plan_hash,
                    [(target, open_targets[target]) for target in sorted(
                        done, key=lambda t: (t.file_hash, t.stage, t.engine, t.languages))], 1)
    remaining = _open_targets(client, params.op_id, params.collection_dataset,
                              params.plan_hash, params.hashes)
    return SettleOcrRunTargetsResult(settled=len(done), remaining=len(remaining))


# ---- activities ------------------------------------------------------------------------------


@activity.defn
@with_heartbeat
def record_ocr_run_targets(params: RerunOcrParams) -> int:
    """Record the open OCR targets of every plan of the dataset. Returns how many.

    Walks the plans that hold an item that a detector typed as an image or a PDF, in plan
    order. For each plan it writes the text of stored OCR results that `text_content`
    lacks, computes the targets, and records those that are not done. A retry computes
    the same rows, and a row of the same key replaces the earlier one.
    """
    from database.clickhouse import get_collection_client
    from tasks.ocr_targets import current_pairs, language_settings, settled

    pairs = current_pairs(language_settings(params.collection_dataset))
    heartbeat = HeartbeatClock()
    recorded = 0
    with get_collection_client(params.collectionname) as client:
        plans = _plan_items(client, params.collection_dataset)
        for index, (plan_hash, items) in enumerate(plans):
            targets, _ = _plan_targets(client, params.collectionname,
                                       params.collection_dataset, items, pairs)
            done = settled(client, params.collection_dataset, targets)
            open_rows = [(target, targets[target]) for target in sorted(
                set(targets) - done, key=lambda t: (t.file_hash, t.stage, t.engine, t.languages))]
            _insert_targets(client, params.op_id, params.collection_dataset, plan_hash,
                            open_rows, 0)
            recorded += len(open_rows)
            heartbeat.beat(f"recorded plan {index + 1}/{len(plans)}")
    log.info("[P_admin] %s: %d open OCR target(s) in %d plan(s)",
             params.collection_dataset, recorded, len(plans))
    return recorded


@activity.defn
@with_heartbeat
def list_ocr_run_plans(params: ListOcrRunPlansParams) -> List[str]:
    """At most `OCR_RUN_PAGE` plans after `after`, in order, that have an open target."""
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        rows = client.query(
            "SELECT plan_hash FROM ocr_run_targets FINAL "
            "WHERE op_id = {op:String} AND collection_dataset = {cd:String} "
            "AND plan_hash > {after:String} AND done = 0 "
            "GROUP BY plan_hash ORDER BY plan_hash LIMIT {limit:UInt32}",
            parameters={"op": params.op_id, "cd": params.collection_dataset,
                        "after": params.after, "limit": OCR_RUN_PAGE},
        ).result_rows
    return [row[0] for row in rows]


@activity.defn
@with_heartbeat
def load_ocr_run_plan(params: OcrRunPlanParams) -> OcrRunPlanWork:
    """The open work of one plan, after its completed targets are settled.

    Writes the text of stored OCR results that `text_content` lacks first, so a file with
    a result and no text is indexed without a second OCR request.
    """
    from database.clickhouse import get_collection_client
    from tasks.ocr_targets import (
        STAGE_IMAGE, STAGE_INDEX, current_pairs, language_settings, recover_ocr_text,
        stored_routes,
    )
    from tasks.P2_execute_plan.activities import GetPlanItemsMetadataParams, get_plan_items_metadata

    pairs = current_pairs(language_settings(params.collection_dataset))
    with get_collection_client(params.collectionname) as client:
        recovered: List[str] = []
        for _, items in _plan_items(client, params.collection_dataset, params.plan_hash):
            routes = stored_routes(client, params.collection_dataset, items)
            recovered.extend(recover_ocr_text(
                client, params.collectionname, params.collection_dataset,
                _image_items(routes, items),
                [(engine, languages) for engine, languages, _ in pairs.image]))
        _settle(client, SettleOcrRunTargetsParams(
            params.collectionname, params.collection_dataset, params.op_id, params.plan_hash))
        open_targets = _open_targets(client, params.op_id, params.collection_dataset,
                                     params.plan_hash)
        engines: Dict[str, Tuple[set, set]] = {}
        index_hashes = set(recovered)
        for target in open_targets:
            if target.stage == STAGE_INDEX:
                index_hashes.add(target.file_hash)
                continue
            image, pdf = engines.setdefault(target.file_hash, (set(), set()))
            (image if target.stage == STAGE_IMAGE else pdf).add(target.engine)
        routes = stored_routes(client, params.collection_dataset, sorted(engines))

    files = []
    if engines:
        metadata = {item["item_hash"]: item for item in get_plan_items_metadata(
            GetPlanItemsMetadataParams(params.collectionname, params.collection_dataset,
                                       params.plan_hash))}
        for file_hash in sorted(engines):
            item = metadata.get(file_hash)
            if item is None:
                continue
            image, pdf = engines[file_hash]
            route = routes.get(file_hash)
            files.append(OcrRunFile(
                item_hash=file_hash,
                file_size_bytes=int(item.get("file_size_bytes") or 0),
                s3_url=item.get("s3_url") or "",
                mime_types=list(route.mime_types) if route else [],
                image_engines=sorted(image),
                pdf_engines=sorted(pdf),
            ))
    return OcrRunPlanWork(files=files, index_hashes=sorted(index_hashes))


@activity.defn
@with_heartbeat
def settle_ocr_run_targets(params: SettleOcrRunTargetsParams) -> SettleOcrRunTargetsResult:
    """Mark the open targets that are done, and count those still open.

    The only writer of `done = 1`. Each target is judged under the setting version it was
    recorded with.
    """
    from database.clickhouse import get_collection_client

    with get_collection_client(params.collectionname) as client:
        return _settle(client, params)


@activity.defn
@with_heartbeat
def ocr_text_pending_index(params: OcrTextPendingParams) -> List[str]:
    """The files among `hashes` whose OCR text is not indexed, each with an open index target.

    A file that needs indexing and has no open index target gets one, so new OCR text adds
    to the total of the progress before its OCR targets settle. A file whose current text
    is indexed gets no row, so a retry opens nothing again.
    """
    from database.clickhouse import get_collection_client
    from tasks.ocr_targets import STAGE_INDEX, SettingVersion, Target, text_pending_index

    if not params.hashes:
        return []
    with get_collection_client(params.collectionname) as client:
        pending = text_pending_index(client, params.collection_dataset, params.hashes)
        if pending:
            already = _open_targets(client, params.op_id, params.collection_dataset,
                                    params.plan_hash, pending)
            new = [(Target(file_hash, STAGE_INDEX), SettingVersion()) for file_hash in pending
                   if Target(file_hash, STAGE_INDEX) not in already]
            _insert_targets(client, params.op_id, params.collection_dataset,
                            params.plan_hash, new, 0)
    return pending


@activity.defn
@with_heartbeat
def verify_ocr_run_completion(params: VerifyOcrRunParams) -> int:
    """Fail when a target of the operation is open. Returns how many targets it recorded."""
    from temporalio.exceptions import ApplicationError

    from database.clickhouse import get_collection_client

    parameters = {"op": params.op_id, "cd": params.collection_dataset}
    with get_collection_client(params.collectionname) as client:
        total, open_count = client.query(
            "SELECT count(), countIf(done = 0) FROM ocr_run_targets FINAL "
            "WHERE op_id = {op:String} AND collection_dataset = {cd:String}",
            parameters=parameters,
        ).result_rows[0]
        if not open_count:
            return int(total)
        samples = client.query(
            "SELECT plan_hash, file_hash, stage, engine, languages FROM ocr_run_targets FINAL "
            "WHERE op_id = {op:String} AND collection_dataset = {cd:String} AND done = 0 "
            "ORDER BY plan_hash, file_hash LIMIT {limit:UInt32}",
            parameters={**parameters, "limit": OCR_RUN_SAMPLES},
        ).result_rows
    raise ApplicationError(
        f"{open_count} of {total} OCR targets are not done: "
        + "; ".join("plan %s file %s %s %s %s" % tuple(row) for row in samples),
        type=OCR_RUN_INCOMPLETE,
        non_retryable=True,
    )
