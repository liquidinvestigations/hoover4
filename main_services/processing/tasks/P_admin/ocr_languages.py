"""The `change_ocr_languages` apply job: settings, re-run, purge, in that order.

What an admin changes on the dataset page is one string per engine. What that means to
the pipeline is a **set of variants**: `extracted_by = ocr_tesseract_eng+ron` is a
different variant from `ocr_tesseract_eng`, with its own `text_content`, `entity_hit`,
`nlp_processed`, `text_chunks`, `text_chunk_vectors`, `pdf_ocr_results`, Manticore rows
and derived PDF. Adding a language creates a variant; removing one leaves an orphan.

The order below is not interchangeable:

1. **Write `dataset_settings` first.** `tasks/dataset_config.py` re-reads per activity
   with a 10 s cache, which is exactly what makes activities *already in flight* pick the
   change up. Writing later would race the re-run against its own configuration.
2. **Reopen plans, then re-run.** `ExecutePlans` skips plans in
   `processing_plan_finished`, so deleting the finished marker is what puts the work back
   in front of the pipeline. The plan is the unit of work and every stage is idempotent —
   re-running one costs time, not correctness.
3. **Purge dropped variants after the re-run, never before.** A purge that runs first
   deletes rows the re-run has not replaced yet, and a crash in between leaves the
   dataset with neither the old variant nor the new one.
4. **ClickHouse, then Manticore, then Garage.** Manticore is disposable and rebuilt from
   ClickHouse, so it is deleted from rather than reconciled. Garage is last because it is
   the only store with no index of its own: `pdf_ocr_results` is the sole record that a
   derived PDF exists, so the row must survive until the object is gone. Deleting the row
   first orphans the object permanently.

**One job per dataset**, refused at the API (`api/admin/processing.rs`) when a
non-terminal `dataset_jobs` row exists. The disabled button is UI courtesy; two admins in
two browsers are stopped by the row.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List

from temporalio import activity

from tasks.dataset_config import (
    KEY_EASYOCR_LANGUAGES,
    KEY_TESSERACT_LANGUAGES,
    invalidate,
)
from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.text_sources import (
    ENGINE_EASYOCR,
    ENGINE_TESSERACT,
    easyocr_language_groups,
    join_languages,
    ocr_extracted_by,
    split_languages,
)

log = logging.getLogger(__name__)

JOB_KIND = "change_ocr_languages"

#: Collection tables whose rows are keyed by `extracted_by` and therefore have to be
#: purged variant by variant. Named explicitly rather than discovered by column, because
#: this list is the contract: a table added later that carries `extracted_by` and is not
#: added here leaks rows on every language removal, silently.
EXTRACTED_BY_TABLES = (
    "text_content",
    "entity_hit",
    "nlp_processed",
    "text_chunks",
    "text_chunk_vectors",
)

#: Manticore shard tables carry `extracted_by` on the pages and vectors tables. `meta` is
#: per document and has no variant, so it is deliberately absent.
MANTICORE_VARIANT_SUFFIXES = ("_pages", "_vectors")


@dataclass
class ApplyOcrLanguagesParams:
    collectionname: str
    collection_dataset: str
    job_id: str
    tesseract_languages: str
    easyocr_languages: str


@dataclass
class OcrLanguageDiff:
    """What the change means in variants, computed once and carried through the job."""

    changed_engines: List[str] = field(default_factory=list)
    added_variants: List[str] = field(default_factory=list)
    removed_variants: List[str] = field(default_factory=list)
    #: `(engine, languages)` pairs of the removed variants, for `pdf_ocr_results` and the
    #: derived objects, which are keyed by the pair rather than by the joined label.
    removed_pairs: List[List[str]] = field(default_factory=list)


@dataclass
class ReopenParams:
    collectionname: str
    collection_dataset: str
    engines: List[str]


@dataclass
class PurgeVariantsParams:
    collectionname: str
    collection_dataset: str
    variants: List[str]
    removed_pairs: List[List[str]]


@dataclass
class JobProgressParams:
    #: Carried even though `dataset_jobs` is a GLOBAL table and this write needs no
    #: collection client. `collectionname` travels with `collection_dataset` through every
    #: params dataclass in this codebase, resolved once at the workflow entry point and
    #: never re-derived inside an activity -- `tests/unit/test_params_carry_collection.py`
    #: enforces it, because a half-done conversion is exactly the kind of thing that only
    #: shows up in the one activity that was missed.
    collectionname: str
    collection_dataset: str
    job_id: str
    state: str
    detail: str = ""
    error: str = ""


def _variants_for(engine: str, languages: str) -> List[str]:
    """Every `extracted_by` one engine produces for one language string.

    Tesseract takes `eng+ron` in a single pass and produces one variant. EasyOCR cannot
    mix scripts, so it produces one variant per script group — which is why adding an
    EasyOCR language in a new script is a full extra pass plus a complete set of
    downstream rows, and adding a Tesseract one is nearly free. The admin form says so.
    """
    if engine == ENGINE_TESSERACT:
        joined = join_languages(split_languages(languages))
        return [ocr_extracted_by(engine, joined)] if joined else []
    if engine == ENGINE_EASYOCR:
        return [ocr_extracted_by(engine, group) for group in easyocr_language_groups(languages)]
    raise ValueError(f"unknown OCR engine {engine!r}")


def compute_diff(current: Dict[str, str], requested: Dict[str, str]) -> OcrLanguageDiff:
    """The variant-level difference between two language settings.

    Pure, and tested as such: this is where "add `ron`" becomes "one new variant, no
    removals" and where "swap `en` for `ru`" becomes "one added, one removed" — and the
    removal is what the purge acts on, so getting it wrong either leaks rows forever or
    deletes a variant that is still in use.
    """
    diff = OcrLanguageDiff()
    for engine in (ENGINE_TESSERACT, ENGINE_EASYOCR):
        before = _variants_for(engine, current.get(engine, ""))
        after = _variants_for(engine, requested.get(engine, ""))
        if before == after:
            continue
        diff.changed_engines.append(engine)
        for variant in after:
            if variant not in before:
                diff.added_variants.append(variant)
        for variant in before:
            if variant not in after:
                diff.removed_variants.append(variant)
                # `ocr_<engine>_<languages>` -> `(engine, languages)`; the storage keys
                # for pdf_ocr_results and the derived objects are the pair.
                _, _, languages = variant.split("_", 2)
                diff.removed_pairs.append([engine, languages])
    return diff


def _write_job(params: JobProgressParams) -> None:
    """Upsert the `dataset_jobs` row. Best-effort by design at the failure path.

    `updated_at` is both the ReplacingMergeTree version and the staleness clock the UI
    reads: a `running` row that has stopped advancing is what the job strip shows as
    stuck, so every stage writes one even when nothing else changed.
    """
    import pyarrow as pa

    from database.clickhouse import get_global_client

    now = int(time.time())
    finished = pa.array(
        [now if params.state in ("done", "failed") else 0],
        type=pa.int64(),
    ).cast(pa.timestamp("s"))

    with get_global_client() as client:
        # Every stage rewrites the row, and `started_at` must survive that: the readers
        # take argMax over updated_at, so writing now() each time would walk the start
        # time forward and the strip would report a long job as having just begun.
        started = now
        try:
            rows = client.query(
                "SELECT toUnixTimestamp(min(started_at)) FROM dataset_jobs "
                "WHERE collection_dataset = {cd:String} AND kind = {k:String} "
                "AND job_id = {j:String}",
                parameters={"cd": params.collection_dataset, "k": JOB_KIND,
                            "j": params.job_id},
            ).result_rows
            if rows and rows[0] and int(rows[0][0]) > 0:
                started = int(rows[0][0])
        except Exception:
            log.warning("[P_admin] could not read the job's start time", exc_info=True)

        client.insert_arrow("dataset_jobs", pa.table({
            "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
            "job_id": pa.array([params.job_id], type=pa.string()),
            "kind": pa.array([JOB_KIND], type=pa.string()),
            "state": pa.array([params.state], type=pa.string()),
            "detail": pa.array([params.detail], type=pa.string()),
            "error": pa.array([params.error], type=pa.string()),
            "started_at": pa.array([started], type=pa.int64()).cast(pa.timestamp("s")),
            "finished_at": finished,
        }))


@activity.defn
@with_heartbeat
def begin_ocr_language_job(params: ApplyOcrLanguagesParams) -> OcrLanguageDiff:
    """Write the settings and the `running` row, and return what changed.

    Settings first — see the module docstring. The diff is computed against what was
    stored *before* the write, so a job dispatched twice with the same values reports no
    changed engines and the workflow finishes without touching the corpus.
    """
    from tasks.dataset_config import get_dataset_settings, set_dataset_setting

    before = get_dataset_settings(params.collection_dataset)
    current = {
        ENGINE_TESSERACT: before.get(KEY_TESSERACT_LANGUAGES, ""),
        ENGINE_EASYOCR: before.get(KEY_EASYOCR_LANGUAGES, ""),
    }
    requested = {
        ENGINE_TESSERACT: join_languages(split_languages(params.tesseract_languages)),
        ENGINE_EASYOCR: join_languages(split_languages(params.easyocr_languages)),
    }
    diff = compute_diff(current, requested)

    set_dataset_setting(params.collection_dataset, KEY_TESSERACT_LANGUAGES,
                        requested[ENGINE_TESSERACT])
    set_dataset_setting(params.collection_dataset, KEY_EASYOCR_LANGUAGES,
                        requested[ENGINE_EASYOCR])
    invalidate(params.collection_dataset)

    _write_job(JobProgressParams(
        collectionname=params.collectionname,
        collection_dataset=params.collection_dataset,
        job_id=params.job_id,
        state="running",
        detail=json.dumps({
            "stage": "settings written",
            "tesseract": requested[ENGINE_TESSERACT],
            "easyocr": requested[ENGINE_EASYOCR],
            "added": diff.added_variants,
            "removed": diff.removed_variants,
        }),
    ))
    log.info("[P_admin] %s: changed %s, +%s -%s", params.collection_dataset,
             diff.changed_engines, diff.added_variants, diff.removed_variants)
    return diff


@activity.defn
@with_heartbeat
def report_ocr_language_progress(params: JobProgressParams) -> str:
    _write_job(params)
    return "ok"


@activity.defn
@with_heartbeat
def reopen_plans_for_ocr_change(params: ReopenParams) -> int:
    """Delete the finished markers of every plan holding an OCR candidate.

    An OCR candidate is a document that already has an OCR result of any engine, or a
    PDF. That is deliberately the *union* rather than a per-engine set: an engine that
    has never run on this dataset has no rows to select on, and it is precisely the
    newly-enabled engine whose documents must be reopened.

    Coarse, like every retry in this system: the plan is a batch and re-running one costs
    time rather than correctness. `engines` is carried for the log line and for the early
    exit when nothing changed.
    """
    from database.clickhouse import get_collection_client

    if not params.engines:
        return 0

    with get_collection_client(params.collectionname) as client:
        hashes = [row[0] for row in client.query(
            "SELECT DISTINCT image_hash FROM raw_ocr_results "
            "WHERE collection_dataset = {cd:String} "
            "UNION DISTINCT "
            "SELECT DISTINCT pdf_hash FROM pdfs "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": params.collection_dataset},
        ).result_rows if row and row[0]]

        if not hashes:
            log.info("[P_admin] %s has no OCR candidates, nothing to reopen",
                     params.collection_dataset)
            return 0

        plan_hashes = [row[0] for row in client.query(
            "SELECT DISTINCT plan_hash FROM processing_plan_hits FINAL "
            "WHERE collection_dataset = {cd:String} AND item_hash IN {hs:Array(String)}",
            parameters={"cd": params.collection_dataset, "hs": hashes},
        ).result_rows if row and row[0]]

        if not plan_hashes:
            return 0

        client.command(
            "ALTER TABLE processing_plan_finished DELETE "
            "WHERE collection_dataset = {cd:String} AND plan_hash IN {ph:Array(String)}",
            parameters={"cd": params.collection_dataset, "ph": plan_hashes},
        )

    log.info("[P_admin] %s: reopened %d plan(s) for %s",
             params.collection_dataset, len(plan_hashes), params.engines)
    return len(plan_hashes)


@activity.defn
@with_heartbeat
def purge_dropped_ocr_variants(params: PurgeVariantsParams) -> Dict[str, int]:
    """Delete every trace of the removed variants: ClickHouse, then Manticore.

    `pdf_ocr_results` is *tombstoned* rather than deleted, because the object it points at
    is still there — `delete_orphaned_derived_pdfs` reads the tombstones to find the
    objects and only then removes the rows. That is the whole reason the two steps are
    separate activities.
    """
    from database.clickhouse import get_collection_client
    from database.manticore import get_manticore_client, list_shard_tables

    if not params.variants:
        return {"clickhouse_tables": 0, "manticore_tables": 0, "pdf_rows": 0}

    heartbeat = HeartbeatClock()
    purged_tables = 0

    with get_collection_client(params.collectionname) as client:
        existing = {row[0] for row in client.query("SHOW TABLES").result_rows}
        for table in EXTRACTED_BY_TABLES:
            if table not in existing:
                continue
            heartbeat.beat(f"purge {table}")
            client.command(
                f"DELETE FROM `{table}` WHERE collection_dataset = {{cd:String}} "
                "AND extracted_by IN {vs:Array(String)}",
                parameters={"cd": params.collection_dataset, "vs": params.variants},
            )
            purged_tables += 1

        pdf_rows = 0
        if params.removed_pairs and "pdf_ocr_results" in existing:
            heartbeat.beat("tombstone pdf_ocr_results")
            for engine, languages in params.removed_pairs:
                # Tombstone by re-inserting the row with is_deleted = 1: the table is a
                # ReplacingMergeTree(updated_at, is_deleted) and the readers take
                # argMax(is_deleted). A hard DELETE here would lose blob_key, which is
                # the only record of the object to remove.
                client.command(
                    "INSERT INTO pdf_ocr_results "
                    "(collection_dataset, pdf_hash, engine, languages, blob_key, blob_hash, "
                    " page_count, size_bytes, run_time_ms, is_deleted) "
                    "SELECT collection_dataset, pdf_hash, engine, languages, "
                    "       argMax(blob_key, updated_at), argMax(blob_hash, updated_at), "
                    "       argMax(page_count, updated_at), argMax(size_bytes, updated_at), "
                    "       argMax(run_time_ms, updated_at), 1 "
                    "FROM pdf_ocr_results "
                    "WHERE collection_dataset = {cd:String} AND engine = {en:String} "
                    "AND languages = {la:String} "
                    "GROUP BY collection_dataset, pdf_hash, engine, languages "
                    "HAVING argMax(is_deleted, updated_at) = 0",
                    parameters={"cd": params.collection_dataset, "en": engine, "la": languages},
                )
                pdf_rows += 1

    manticore_tables = 0
    tables = [t for t in list_shard_tables(params.collectionname)
              if t.endswith(MANTICORE_VARIANT_SUFFIXES)]
    if tables:
        # Manticore rows are keyed per (dataset, file, extracted_by, page), and the P6
        # writers only REPLACE. A reindex therefore never removes a dropped variant's
        # rows — deleting them here is the only thing that does.
        placeholders = ", ".join(["%s"] * len(params.variants))
        with get_manticore_client() as cnx:
            cursor = cnx.cursor()
            for table in tables:
                heartbeat.beat(f"purge {table}")
                cursor.execute(
                    f"DELETE FROM {table} WHERE collection_dataset = %s "
                    f"AND extracted_by IN ({placeholders})",
                    (params.collection_dataset, *params.variants),
                )
                manticore_tables += 1
            cnx.commit()

    log.info("[P_admin] %s: purged %s from %d ClickHouse and %d Manticore tables",
             params.collection_dataset, params.variants, purged_tables, manticore_tables)
    return {
        "clickhouse_tables": purged_tables,
        "manticore_tables": manticore_tables,
        "pdf_rows": pdf_rows,
    }


@activity.defn
@with_heartbeat
def delete_orphaned_derived_pdfs(params: PurgeVariantsParams) -> int:
    """Remove the derived objects of tombstoned `pdf_ocr_results` rows, then the rows.

    Objects before rows, the reverse of the write path and for the same reason: the row
    is the sole index of the object, so a row deleted first leaves bytes nothing knows
    about. A row whose object is already gone is deleted anyway — that is the crash-in-
    between case, and it converges.
    """
    from database.clickhouse import get_collection_client
    from database.s3 import collection_bucket, get_s3_client

    if not params.removed_pairs:
        return 0

    heartbeat = HeartbeatClock()
    removed = 0

    with get_collection_client(params.collectionname) as client:
        for engine, languages in params.removed_pairs:
            rows = client.query(
                "SELECT pdf_hash, argMax(blob_key, updated_at) FROM pdf_ocr_results "
                "WHERE collection_dataset = {cd:String} AND engine = {en:String} "
                "AND languages = {la:String} "
                "GROUP BY pdf_hash HAVING argMax(is_deleted, updated_at) = 1",
                parameters={"cd": params.collection_dataset, "en": engine, "la": languages},
            ).result_rows

            s3 = get_s3_client()
            bucket = collection_bucket(params.collectionname)
            for pdf_hash, blob_key in rows:
                heartbeat.beat(f"delete {engine}+{languages}")
                if blob_key:
                    try:
                        s3.remove_object(bucket, blob_key)
                    except Exception:
                        # An object that is already gone is the crash-in-between case and
                        # must not stop the pass; anything else is logged and retried by
                        # the next run of this job.
                        log.warning("[P_admin] could not remove %s", blob_key, exc_info=True)
                removed += 1

            client.command(
                "ALTER TABLE pdf_ocr_results DELETE WHERE collection_dataset = {cd:String} "
                "AND engine = {en:String} AND languages = {la:String}",
                parameters={"cd": params.collection_dataset, "en": engine, "la": languages},
            )

    log.info("[P_admin] %s: removed %d derived PDF(s)", params.collection_dataset, removed)
    return removed
