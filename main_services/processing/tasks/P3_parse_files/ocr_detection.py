"""The OCR detection stage: text presence, script and language of images and OCR pages.

The stage stores evidence for automatic routing and search attributes.
An image takes one row. Each eligible PDF page takes one row.
Requests use bounded page batches and retain completed detection rows.
An image under the OCR size gate stores a successful negative row.
A render failure stores no negative result for its page.
The update step selects missing current-version page identities.
An image that the service cannot decode stores a row with `model` `undecodable`.
`NotDetectable` marks a PDF page that does not render, so an update continues with the
other files of its plan and the file stays selected.

"""

import logging
import os
import subprocess
import tempfile
import time
from typing import List, Optional, Sequence

from temporalio import activity

from tasks.document_language import detected_language
from tasks.heartbeat import with_heartbeat
from tasks.ocr_client import detect_text, engine_configured
from tasks.P3_parse_files.batch_runner import BatchFile, BatchResult, StageBatchParams, run_batch
from tasks.P3_parse_files.image_loader import image_dimensions
from tasks.task_timing import SkippedOutcome
from tasks.text_sources import ENGINE_TESSERACT, MIN_OCR_IMAGE_PX

log = logging.getLogger(__name__)

#: The logical version of the stage output. `STAGE_VERSIONS["ocr_detection"]` reads it.
OCR_DETECTION_VERSION = 4
#: The workflow patch that runs the stage in a new group.
OCR_DETECTION_PATCH = "ocr-detection"
#: The retained legacy sample limit. Automatic routing examines every eligible page.
MAX_DETECTED_PAGES = 100
#: The render resolution of a PDF page. It matches the OCR render.
RENDER_DPI = 200
RENDER_TIMEOUT_SECONDS = 120

KIND_IMAGE = "image"
#: The `model` of a row for an image that the service cannot decode. The row has no text, so
#: the update step selects it no more and OCR sends no request. A retry sends the same bytes.
UNDECODABLE = "undecodable"


class NotDetectable(RuntimeError):
    """The page cannot be rendered. Another try uses the same file."""


def spaced_pages(pages: Sequence[int], limit: int = MAX_DETECTED_PAGES) -> List[int]:
    """At most `limit` evenly spaced values of `pages`, with the first value kept."""
    if len(pages) <= limit:
        return list(pages)
    step = len(pages) / limit
    return [pages[int(index * step)] for index in range(limit)]


def _row(collection_dataset: str, file_hash: str, kind: str, page: int, found: Optional[dict]) -> dict:
    if found is None:
        return dict(collection_dataset=collection_dataset, hash=file_hash, source_kind=kind, page_id=page,
                    detector_version=OCR_DETECTION_VERSION, has_text=0, box_count=0, script="",
                    model=UNDECODABLE, language="und", run_time_ms=0)
    from tasks.automatic_ocr import LANGUAGE_SCRIPTS

    script, model = found.get("script") or "", found.get("model") or ""
    language = detected_language(model, found.get("text") or "")
    if not script:
        # The service reads an unresolved page with the Latin model. Only an identified
        # Latin-script language confirms that sample.
        if LANGUAGE_SCRIPTS.get(language) == "Latin":
            script, model = "Latin", "Latin"
        else:
            language = "und"
    return dict(collection_dataset=collection_dataset, hash=file_hash, source_kind=kind, page_id=page,
                detector_version=OCR_DETECTION_VERSION, has_text=1 if found.get("has_text") else 0,
                box_count=int(found.get("box_count") or 0), script=script, model=model, language=language,
                run_time_ms=int(found.get("run_time_ms") or 0))


def store_rows(client, rows: List[dict]) -> None:
    """Write the rows of one file through the parser insert buffer of the current stage."""
    import pyarrow as pa

    from database.clickhouse import insert_parser_arrow

    types = {"page_id": pa.uint32(), "detector_version": pa.uint16(), "has_text": pa.uint8(),
             "box_count": pa.uint32(), "run_time_ms": pa.uint32()}
    insert_parser_arrow(client, "ocr_detection", pa.table(
        {key: pa.array([row[key] for row in rows], type=types.get(key, pa.string())) for key in rows[0]}))
    from tasks.P3_parse_files.insert_batch import current_batch
    batch = current_batch()
    if batch is not None:
        batch.flush()
        if batch.index in batch.errors:
            raise batch.errors[batch.index]


def image_rows(collection_dataset: str, file_hash: str, image_bytes: bytes) -> List[dict]:
    """The row of one image. An image under the OCR size gate sends no request."""
    size = image_dimensions(image_bytes) if image_bytes else None
    if not image_bytes or (size is not None and min(size) < MIN_OCR_IMAGE_PX):
        return [_row(collection_dataset, file_hash, KIND_IMAGE, 1, {"has_text": False})]
    return [_row(collection_dataset, file_hash, KIND_IMAGE, 1, detect_text(image_bytes))]


def render_page(path: str, page: int) -> Optional[bytes]:
    """Render one JPEG page. Raise a retryable error when rendering fails."""
    with tempfile.TemporaryDirectory(prefix="hoover4-ocr-detection-") as folder:
        out = os.path.join(folder, "page")
        try:
            result = subprocess.run(
                ["pdftoppm", "-r", str(RENDER_DPI), "-f", str(page), "-l", str(page), "-jpeg",
                 "-jpegopt", "quality=88", "-singlefile", path, out],
                capture_output=True, timeout=RENDER_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            log.warning("[P3] page %d render timed out for OCR detection: %s", page, path)
            raise RuntimeError(f"OCR detection render timed out for page {page}")
        if result.returncode != 0 or not os.path.exists(out + ".jpg"):
            log.warning("[P3] page %d render failed for OCR detection: %s", page, path)
            raise NotDetectable(f"OCR detection render failed for page {page}")
        with open(out + ".jpg", "rb") as handle:
            return handle.read()


def pdf_rows(collection_dataset: str, file_hash: str, kind: str, path: str, pages: Sequence[int]) -> List[dict]:
    """Return one successful detection row for each requested PDF page."""
    rows = []
    for page in pages:
        rendered = render_page(path, page)
        if not rendered:
            raise NotDetectable(f"OCR detection render returned no image for page {page}")
        rows.append(_row(collection_dataset, file_hash, kind, page, detect_text(rendered)))
    return rows


def stored_pdf_pages(client, collection_dataset: str, file_hash: str, kind: str) -> List[int]:
    rows = client.query(
        "SELECT ocr_pages FROM ocr_page_needs FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String} AND source_kind = {k:String} LIMIT 1",
        parameters={"cd": collection_dataset, "h": file_hash, "k": kind}).result_rows
    return list(rows[0][0]) if rows else []


def already_detected(client, collection_dataset: str, file_hash: str) -> bool:
    rows = client.query(
        "SELECT count() FROM ocr_detection WHERE collection_dataset = {cd:String} AND hash = {h:String} "
        "AND detector_version = {v:UInt16}",
        parameters={"cd": collection_dataset, "h": file_hash, "v": OCR_DETECTION_VERSION}).result_rows
    return bool(rows and rows[0][0])


def read_image(client, collection_dataset: str, file_hash: str, path: str) -> bytes:
    """The preview of an uncommon image format, else the original bytes."""
    from tasks.P3_parse_files.image_preview import read_preview_bytes

    preview = read_preview_bytes(client, collection_dataset, file_hash)
    if preview is not None:
        return preview
    with open(path, "rb") as handle:
        return handle.read()


def _detect_file(params: StageBatchParams, file: BatchFile) -> str | SkippedOutcome:
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.pdf_parts import source_file

    if not engine_configured(ENGINE_TESSERACT):
        return SkippedOutcome("ocr_detection_skipped_not_configured")
    started = time.time()
    cd = params.collection_dataset
    with get_collection_client(params.collectionname) as client:
        current = {int(row[0]) for row in client.query(
            "SELECT page_id FROM ocr_detection FINAL WHERE collection_dataset = {cd:String} "
            "AND hash = {h:String} AND source_kind = {k:String} AND detector_version = {v:UInt16}",
            parameters={"cd": cd, "h": file.item_hash, "k": "image" if "image" in file.routes else file.source_kind,
                        "v": OCR_DETECTION_VERSION}).result_rows}
        rows = []
        if "image" in file.routes:
            if 1 not in current:
                rows = image_rows(cd, file.item_hash, read_image(client, cd, file.item_hash, file.file_path))
                store_rows(client, rows)
        else:
            from tasks.automatic_ocr import PAGE_BATCH
            from tasks.heartbeat import HeartbeatClock
            clock = HeartbeatClock()
            pages = [page for page in stored_pdf_pages(client, cd, file.item_hash, file.source_kind)
                     if page not in current]
            with source_file(client, params, file) as path:
                for start in range(0, len(pages), PAGE_BATCH):
                    clock.beat(f"Detecting OCR pages {start}/{len(pages)}")
                    rows = pdf_rows(cd, file.item_hash, file.source_kind, path, pages[start:start + PAGE_BATCH])
                    store_rows(client, rows)
    log.info("[P3] OCR detection of %s: %d rows in %d ms", file.item_hash, len(rows),
             int((time.time() - started) * 1000))
    return "ocr_detection_ok"


@activity.defn
@with_heartbeat
def detect_ocr_text_batch(params: StageBatchParams) -> BatchResult:
    """Store the detection rows of the images and PDF sources of one group."""
    return run_batch("detect_ocr_text_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=lambda f: _detect_file(params, f),
                     task_name="detect_ocr_text")
