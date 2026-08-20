"""OCR'd-PDF activity: one engine, every language pass that engine needs for this dataset.

Shaped exactly like `parse_ocr.py`, and for the same reasons — one activity per *engine*,
languages read inside the activity so an apply job reaches work already in flight, and a
watermark checked before anything is spent. What differs is what it produces: not text
rows but a **derived object**, a searchable PDF written under `derived/` by
`hoover4-ocr-pdf`, with `pdf_ocr_results` as the sole index of its existence.

That last part is the whole risk of this stage. A derived PDF the ingest walker can see is
ingested, OCR'd and re-derived forever, and each lap bills a full OCR pass over the
document. Three guards stand between here and that loop:

* the key is built by `ocr_pdf_client.derived_key`, always under `derived/ocr-pdf/`;
* the service refuses any other prefix, so a caller bug cannot get past it;
* `verify-stack.sh` asserts no `blobs` row references `derived/`.

The row is written **after** the object, never before: an object with no row is found by a
prefix scan, a row with no object is a broken link nothing can repair.
"""

import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import List, Optional

from temporalio import activity

from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.text_sources import ENGINE_EASYOCR, ENGINE_TESSERACT

log = logging.getLogger(__name__)

#: Above this, a PDF that is not in MinIO is left alone rather than base64'd through the
#: request body. Blobs this small are in `blob_values` because they are small; a file that
#: is both large and absent from object storage is a state worth failing loudly on.
MAX_INLINE_PDF_BYTES = int(os.getenv("OCR_PDF_MAX_INLINE_BYTES", str(64 * 1024 * 1024)))


@dataclass
class RunOcrPdfParams:
    collectionname: str
    collection_dataset: str
    pdf_hash: str
    file_path: str
    engine: str
    timeout_seconds: int


def _record_skip(params: RunOcrPdfParams, run_time_ms: int, reason: str) -> None:
    """Record a skip in `processing_errors` without failing the activity.

    A skip is a *data* or *deployment* fact — no endpoint, no languages, an unreadable
    file — and must not consume retries. A configured-but-unreachable service is not a
    skip: that raises, so Temporal retries it.
    """
    from tasks.P2_execute_plan.activities import (
        RecordProcessingErrorsParams,
        record_processing_errors,
    )

    record_processing_errors(RecordProcessingErrorsParams(
        collectionname=params.collectionname,
        errors=[{
            "collection_dataset": params.collection_dataset,
            "hash": params.pdf_hash,
            "task_name": "run_ocr_pdf_and_store",
            "run_time_ms": run_time_ms,
            "error_logs": f"{reason}: {params.file_path}",
        }],
    ))


def _already_done(client, params: RunOcrPdfParams, languages: str) -> bool:
    """Whether this exact `(pdf, engine, languages)` variant already exists.

    Checked before the source is even read: assembling a searchable PDF is one OCR call
    per page, so a retry that re-derives what it already produced is the difference
    between a cheap retry and a doubled bill.

    `argMax(is_deleted)` rather than a plain count: the purge in `change_ocr_languages`
    tombstones rows, and a tombstoned variant must be re-derivable.
    """
    try:
        # `count()` alongside the tombstone read, and not only for tidiness: an aggregate
        # with no GROUP BY over an empty match still returns ONE row, with argMax's
        # default -- 0, which reads as "live variant" and would skip every PDF that has
        # never been processed. The count is what distinguishes "no row" from "row, not
        # deleted".
        rows = client.query(
            "SELECT count(), argMax(is_deleted, updated_at) FROM pdf_ocr_results "
            "WHERE collection_dataset = {cd:String} AND pdf_hash = {ph:String} "
            "AND engine = {en:String} AND languages = {la:String}",
            parameters={"cd": params.collection_dataset, "ph": params.pdf_hash,
                        "en": params.engine, "la": languages},
        ).result_rows
        if not rows or not rows[0]:
            return False
        count, is_deleted = int(rows[0][0]), int(rows[0][1])
        return count > 0 and is_deleted == 0
    except Exception:
        # Never let a watermark read fail the work it is supposed to save.
        log.warning("[P3] OCR-PDF watermark read failed for %s/%s",
                    params.pdf_hash, languages, exc_info=True)
        return False


def _passes_for(engine: str, collection_dataset: str) -> List[str]:
    from tasks.dataset_config import easyocr_passes, tesseract_languages

    if engine == ENGINE_TESSERACT:
        languages = tesseract_languages(collection_dataset)
        return [languages] if languages else []
    if engine == ENGINE_EASYOCR:
        return easyocr_passes(collection_dataset)
    raise ValueError(f"unknown OCR engine {engine!r}")


def _source_key(client, collection_dataset: str, pdf_hash: str) -> Optional[str]:
    """The MinIO object key of the source PDF, or None when it is not in object storage.

    Small blobs live in `blob_values` in ClickHouse and have no object at all, which is
    why this returns None rather than raising: the caller falls back to sending the local
    file inline.
    """
    try:
        rows = client.query(
            "SELECT s3_path FROM blobs "
            "WHERE collection_dataset = {cd:String} AND blob_hash = {bh:String} "
            "AND s3_path != '' LIMIT 1",
            parameters={"cd": collection_dataset, "bh": pdf_hash},
        ).result_rows
    except Exception:
        log.warning("[P3] could not read the blobs row for %s", pdf_hash, exc_info=True)
        return None
    if not rows or not rows[0] or not rows[0][0]:
        return None
    # `s3://<bucket>/<key>` -> `<key>`. The bucket is the service's own configuration;
    # re-deriving it here would let two components disagree about which bucket is meant.
    path = str(rows[0][0])
    without_scheme = path.split("://", 1)[-1]
    parts = without_scheme.split("/", 1)
    return parts[1] if len(parts) == 2 else None


@activity.defn
@with_heartbeat
def run_ocr_pdf_and_store(params: RunOcrPdfParams) -> str:
    import pyarrow as pa

    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    from tasks.ocr_pdf_client import build_ocr_pdf, engines_for_provider, service_configured

    started_all = time.time()

    if not service_configured():
        # Not an error: `ocr_pdf_enabled = false` simply means no searchable PDFs.
        log.info("[P3] ocr-pdf service not configured, no OCR'd PDF for %s", params.file_path)
        _record_skip(params, 0, "ocr_pdf_not_configured: no OCR_PDF_URL")
        return "ocr_pdf_skipped_not_configured"

    if params.engine not in engines_for_provider():
        # `pdf_ocr_provider` decides which engines produce a PDF, independently of which
        # engines produce *text*: the PDF is an extra artefact per engine, and the cost is
        # a full pass, so it gets its own switch.
        log.info("[P3] pdf_ocr_provider excludes %s, no OCR'd PDF for %s",
                 params.engine, params.file_path)
        return f"ocr_pdf_skipped_{params.engine}_not_requested"

    passes = _passes_for(params.engine, params.collection_dataset)
    if not passes:
        _record_skip(params, 0,
                     f"ocr_pdf_no_languages: {params.engine} has no languages for this dataset")
        return "ocr_pdf_skipped_no_languages"

    heartbeat = HeartbeatClock()
    inline_b64: Optional[str] = None
    done = 0

    with get_collection_client(params.collectionname) as client:
        source_key = _source_key(client, params.collection_dataset, params.pdf_hash) or ""

        for index, languages in enumerate(passes):
            heartbeat.beat(
                f"ocr-pdf {params.engine} {index + 1}/{len(passes)} ({languages})")

            if _already_done(client, params, languages):
                log.info("[P3] OCR'd PDF already exists for %s %s/%s",
                         params.pdf_hash, params.engine, languages)
                done += 1
                continue

            if not source_key and inline_b64 is None:
                # Read once, reuse across passes, and only when a pass actually needs it:
                # a fully watermarked PDF costs no disk read at all.
                try:
                    with open(params.file_path, "rb") as handle:
                        raw = handle.read()
                except OSError as exc:
                    _record_skip(params, 0, f"ocr_pdf_skipped_unreadable: {exc}")
                    return "ocr_pdf_skipped_unreadable"
                if not raw:
                    _record_skip(params, 0, "ocr_pdf_skipped_empty: file is zero bytes")
                    return "ocr_pdf_skipped_empty"
                if len(raw) > MAX_INLINE_PDF_BYTES:
                    _record_skip(
                        params, 0,
                        f"ocr_pdf_skipped_no_object: {len(raw)} bytes and no s3_path")
                    return "ocr_pdf_skipped_no_object"
                inline_b64 = base64.b64encode(raw).decode("ascii")

            started = time.time()
            outcome = build_ocr_pdf(
                collection_dataset=params.collection_dataset,
                pdf_hash=params.pdf_hash,
                engine=params.engine,
                languages=languages,
                source_key=source_key,
                pdf_b64="" if source_key else (inline_b64 or ""),
            )
            run_time_ms = max(int((time.time() - started) * 1000), 0)

            # Object first, row second — see the module docstring.
            insert_arrow_idempotent(client, "pdf_ocr_results", pa.table({
                "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
                "pdf_hash": pa.array([params.pdf_hash], type=pa.string()),
                "engine": pa.array([outcome.engine], type=pa.string()),
                "languages": pa.array([outcome.languages], type=pa.string()),
                "blob_key": pa.array([outcome.dest_key], type=pa.string()),
                "blob_hash": pa.array([outcome.blob_hash], type=pa.string()),
                "page_count": pa.array([outcome.page_count], type=pa.uint32()),
                "size_bytes": pa.array([outcome.size_bytes], type=pa.uint64()),
                "run_time_ms": pa.array([outcome.run_time_ms or run_time_ms],
                                        type=pa.uint32()),
            }))

            done += 1
            log.info("[P3] OCR'd PDF %s: %d pages (%d with text), %d bytes in %d ms",
                     outcome.dest_key, outcome.page_count, outcome.pages_with_text,
                     outcome.size_bytes, run_time_ms)

    total_ms = max(int((time.time() - started_all) * 1000), 0)
    log.info("[P3] OCR-PDF %s complete for %s: %d/%d variants in %d ms",
             params.engine, params.pdf_hash, done, len(passes), total_ms)
    return f"ocr_pdf_ok_{done}_variants"
