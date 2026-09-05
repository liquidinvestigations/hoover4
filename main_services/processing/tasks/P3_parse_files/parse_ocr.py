"""OCR activity: one engine, every language pass that engine needs for this dataset.

Replaces the in-process EasyOCR activity. That version was GPU-or-nothing and, on a box
without CUDA, recorded a skip for every image, which is why a full ingest of `testdata`
produced 65 `ocr_skipped_no_gpu` rows and not one character of OCR text.

Shape of the work
-----------------
One activity per *engine*, not per pass, because the two engines are asymmetric:

* **Tesseract** takes `eng+ron` in a single invocation and picks per region. One pass,
  one variant, `extracted_by = 'ocr_tesseract_eng+ron'`.
* **EasyOCR** builds one model per Reader and cannot mix scripts, so a dataset asking
  for several scripts runs several passes, each its own variant with its own confidence.

Reading the language settings inside the activity rather than passing them down from the
workflow is deliberate: an apply job that changes them must reach activities that are
already running (`tasks/dataset_config.py`), and a workflow argument would freeze the
value at schedule time.

Retries are cheap by construction: every pass checks the `raw_ocr_results` watermark for
its own `(image, engine, languages)` before spending anything.
"""

import logging
import time
from dataclasses import dataclass
from typing import List

from temporalio import activity

from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.P3_parse_files.image_loader import image_dimensions
from tasks.task_timing import SkippedOutcome
from tasks.text_sources import (
    ENGINE_EASYOCR, ENGINE_TESSERACT, MIN_OCR_IMAGE_PX, ocr_extracted_by,
)

log = logging.getLogger(__name__)


@dataclass
class RunOcrParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    engine: str
    timeout_seconds: int


def _record_skip(params: RunOcrParams, run_time_ms: int, reason: str) -> None:
    """Record a skip in `processing_errors` without failing the activity.

    A skip is a *data* fact (an undecodable image, a disabled engine), and must not
    consume retries or hold up the plan. An unreachable but configured service is not a
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
            "hash": params.file_hash,
            "task_name": "run_ocr_and_store",
            "run_time_ms": run_time_ms,
            "error_logs": f"{reason}: {params.file_path}",
        }],
    ))


def _already_done(client, params: RunOcrParams, languages: str) -> bool:
    """Whether this exact `(image, engine, languages)` pass already has a payload.

    The watermark is checked before the image is even read: OCR is the most expensive
    thing in the pipeline per byte, and a retry that re-OCRs what it already produced is
    the difference between a cheap retry and a doubled bill.
    """
    try:
        rows = client.query(
            "SELECT count() FROM raw_ocr_results "
            "WHERE collection_dataset = {cd:String} AND image_hash = {ih:String} "
            "AND engine = {en:String} AND languages = {la:String}",
            parameters={"cd": params.collection_dataset, "ih": params.file_hash,
                        "en": params.engine, "la": languages},
        ).result_rows
        return bool(rows and rows[0] and int(rows[0][0]) > 0)
    except Exception:
        # Never let a watermark read fail the work it is supposed to save.
        log.warning("[P3] OCR watermark read failed for %s/%s", params.file_hash, languages,
                    exc_info=True)
        return False


def _passes_for(engine: str, collection_dataset: str) -> List[str]:
    from tasks.dataset_config import easyocr_passes, tesseract_languages

    if engine == ENGINE_TESSERACT:
        languages = tesseract_languages(collection_dataset)
        return [languages] if languages else []
    if engine == ENGINE_EASYOCR:
        return easyocr_passes(collection_dataset)
    raise ValueError(f"unknown OCR engine {engine!r}")


@activity.defn
@with_heartbeat
def run_ocr_and_store(params: RunOcrParams) -> str | SkippedOutcome:
    import pyarrow as pa

    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    from tasks.ocr_client import engine_configured, run_ocr
    from tasks.P3_parse_files.parse_common import insert_text_chunks

    started_all = time.time()

    if not engine_configured(params.engine):
        # Not an error: a box with no GPU tier produces no EasyOCR variants.
        log.info("[P3] OCR engine %s not configured, no variant for %s",
                 params.engine, params.file_path)
        _record_skip(params, 0,
                     f"ocr_engine_not_configured: {params.engine} has no endpoint")
        return f"ocr_skipped_{params.engine}_not_configured"

    passes = _passes_for(params.engine, params.collection_dataset)
    if not passes:
        _record_skip(params, 0,
                     f"ocr_no_languages: {params.engine} has no languages for this dataset")
        return "ocr_skipped_no_languages"

    heartbeat = HeartbeatClock()
    image_bytes = None
    done = 0

    with get_collection_client(params.collectionname) as client:
        for index, languages in enumerate(passes):
            heartbeat.beat(f"ocr {params.engine} {index + 1}/{len(passes)} ({languages})")

            if _already_done(client, params, languages):
                log.info("[P3] OCR already done for %s %s/%s",
                         params.file_hash, params.engine, languages)
                done += 1
                continue

            if image_bytes is None:
                # Read once, reuse across passes. Deferred until a pass actually needs
                # it so a fully watermarked file costs no disk read at all.
                try:
                    with open(params.file_path, "rb") as handle:
                        image_bytes = handle.read()
                except OSError as exc:
                    _record_skip(params, 0, f"ocr_skipped_unreadable: {exc}")
                    return "ocr_skipped_unreadable"
                if not image_bytes:
                    _record_skip(params, 0, "ocr_skipped_empty: file is zero bytes")
                    return "ocr_skipped_empty"

                # The size gate. An image whose shorter edge is under
                # MIN_OCR_IMAGE_PX is an icon, a bullet, a rule or a signature scrap --
                # it carries no text content, and a corpus of PDFs is mostly those.
                # Read from the header, so this costs a few hundred bytes rather than a
                # decode. An image whose header will not parse is NOT skipped here: the
                # engines handle formats Pillow does not, and `ocr_skipped_unreadable`
                # is what this reports for a file neither can read.
                size = image_dimensions(image_bytes)
                if size is not None and min(size) < MIN_OCR_IMAGE_PX:
                    # A decision, not a failure: an image this small has no text to
                    # read. Recorded as `outcome = 'skipped'` on `processing_task_runs`,
                    # never in `processing_errors`, so it costs no retry and does not
                    # count as a failure anywhere that counts that table.
                    log.info(
                        "[P3] OCR skip for %s: %dx%d is under %dpx",
                        params.file_hash, size[0], size[1], MIN_OCR_IMAGE_PX,
                    )
                    return SkippedOutcome("ocr_skipped_too_small")

            started = time.time()
            outcome = run_ocr(params.engine, languages, image_bytes)
            run_time_ms = max(int((time.time() - started) * 1000), 0)

            extracted_by = ocr_extracted_by(outcome.engine, outcome.languages)

            insert_arrow_idempotent(client, "raw_ocr_results", pa.table({
                "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
                "image_hash": pa.array([params.file_hash], type=pa.string()),
                "engine": pa.array([outcome.engine], type=pa.string()),
                "languages": pa.array([outcome.languages], type=pa.string()),
                "confidence": pa.array([outcome.confidence], type=pa.float32()),
                "run_time_ms": pa.array([outcome.run_time_ms or run_time_ms], type=pa.uint32()),
                "result_hash": pa.array([""], type=pa.string()),
                "raw_json": pa.array([outcome.raw_json], type=pa.string()),
            }))

            if outcome.text.strip():
                # An image is one page. insert_text_chunks numbers from 1 and segments
                # only if the text is enormous, which OCR output never is.
                insert_text_chunks(params.collectionname, params.collection_dataset,
                                   params.file_hash, extracted_by, outcome.text)
            done += 1
            log.info("[P3] OCR %s in %d ms, %d chars, confidence %.1f (%s)",
                     extracted_by, run_time_ms, len(outcome.text), outcome.confidence,
                     outcome.provider)

    total_ms = max(int((time.time() - started_all) * 1000), 0)
    log.info("[P3] OCR %s complete for %s: %d/%d passes in %d ms",
             params.engine, params.file_hash, done, len(passes), total_ms)
    return f"ocr_ok_{done}_passes"
