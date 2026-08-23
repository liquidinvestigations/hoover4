"""PDF parsing activities and workflow for metadata, text, and images."""

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import asyncio
import os
import json
import math
import tempfile
import subprocess
import logging
log = logging.getLogger(__name__)

from tasks.P0_scan_disk.workflows import HandleFoldersParams
from tasks.P3_parse_files.parse_archives import CleanupTempDirParams, RecordArchiveContainerParams
from tasks.P3_parse_files.parse_ocr_pdf import RunOcrPdfParams, run_ocr_pdf_and_store
from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT, HeartbeatClock, heartbeat_pump, with_heartbeat
from tasks.text_sources import OCR_ENGINES


#: Wall-clock ceiling for one qpdf/pdftotext invocation. These had NO timeout,
#: which the heartbeat pump does not fix: the pump proves the pump thread is
#: alive, so a wedged qpdf would heartbeat happily until start_to_close. A
#: subprocess timeout is the only thing that catches a wedged child.
#: Generous, because a 500-page split is legitimately
#: slow, and the value of the cap is that it is finite.
_PDF_SUBPROCESS_TIMEOUT_S = 900


def _run_qpdf(args: List[str]) -> subprocess.CompletedProcess:
    cmd = ["qpdf"] + args
    return subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=_PDF_SUBPROCESS_TIMEOUT_S)


def _qpdf_show_npages(path: str) -> int:
    res = _run_qpdf(["--show-npages", path])
    if res.returncode != 0:
        raise RuntimeError(f"qpdf --show-npages failed: {res.stderr[:200]} {res.stdout[:200]}")
    out = (res.stdout or b"").decode("utf-8", errors="ignore").strip()
    try:
        return int(out)
    except Exception:
        raise RuntimeError(f"Invalid page count from qpdf: '{out}'")


def _qpdf_json(path: str) -> Dict[str, Any]:
    res = _run_qpdf(["--json", path])
    if res.returncode != 0:
        # Some qpdf builds require explicit --json-output
        raise RuntimeError(f"qpdf --json failed: {res.stderr[:200]} {res.stdout[:200]}")
    txt = (res.stdout or b"").decode("utf-8", errors="ignore")
    try:
        return json.loads(txt)
    except Exception:
        # Fallback to empty metadata
        return {}


def _maybe_pdftotext(path: str) -> Optional[str]:
    try:
        res = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", path, "-"],
                             capture_output=True, stdin=subprocess.DEVNULL,
                             timeout=_PDF_SUBPROCESS_TIMEOUT_S)
        if res.returncode == 0:
            return (res.stdout or b"").decode("utf-8", errors="ignore")
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        # Text extraction is best-effort here (the caller falls back to other
        # sources); a wedged pdftotext must not take the whole activity with it.
        log.warning("[P3] pdftotext timed out for %s", path)
    return None


#: pdftotext writes a form feed after every page, including the last one. That single
#: byte is the whole per-page split. One subprocess call still covers every page, and the
#: alternative -- `pdftotext -f N -l N` once per page -- would be one process spawn per
#: page of every PDF in the corpus.
_PAGE_BREAK = "\x0c"


def _pdftotext_pages(path: str) -> List[str]:
    """Return the PDF's text as one string per page, index 0 == page 1.

    An empty list means pdftotext produced nothing usable; an empty *string* at index
    i means page i+1 has no extractable text, which is the normal signal for a scanned
    page and is exactly what makes it an OCR candidate. The two are not the same and
    callers must not collapse them.
    """
    raw = _maybe_pdftotext(path)
    if raw is None:
        return []
    pages = raw.split(_PAGE_BREAK)
    # The trailing form feed produces one empty element past the last real page.
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _insert_pdf_text_pages(collectionname: str, collection_dataset: str, pdf_hash: str,
                           pages: List[str]) -> int:
    """Store extracted PDF text one row per real page.

    `page_id` is the 1-based PDF page number here, not a segment ordinal, which is what
    makes the document viewer's page jump and `search_document_pdf.rs`'s
    `min_page..=max_page` iteration correct rather than coincidental. It is also the
    unit OCR works in, so an OCR variant of the same PDF lines up page for page with
    this one.
    """
    if not pages:
        return 0
    from tasks.P3_parse_files.parse_common import insert_text_pages
    return insert_text_pages(
        collectionname, collection_dataset, pdf_hash, "pdftotext",
        [(i, text) for i, text in enumerate(pages, start=1)],
    )


def _extract_images_with_qpdf(input_pdf: str, out_dir: str) -> List[str]:
    # Newer qpdf supports --extract-images=<prefix>. We'll attempt and collect files.
    # Files are typically written as <prefix>-<obj>-<gen>.<ext>
    prefix = os.path.join(out_dir, "img")
    res = _run_qpdf([f"--extract-images={prefix}", input_pdf])
    if res.returncode != 0:
        # If unsupported or failed, return empty list
        return []
    # Gather files created
    files = []
    for entry in os.scandir(out_dir):
        if entry.is_file() and entry.name.startswith("img-"):
            files.append(entry.path)
    return sorted(files)


def _compute_pages_per_chunk(file_size_bytes: int, page_count: int) -> int:
    # Target ~32MB or 500 pages, whichever smaller
    if page_count <= 0:
        return 500
    chunks_by_size = max(1, math.ceil(file_size_bytes / (32 * 1024 * 1024)))
    chunks_by_pages = max(1, math.ceil(page_count / 500))
    chunks = max(chunks_by_size, chunks_by_pages)
    pages_per_chunk = max(1, math.ceil(page_count / chunks))
    return min(pages_per_chunk, 500)


@dataclass
class PdfMetaParams:
    collectionname: str
    collection_dataset: str
    pdf_hash: str
    file_path: str


@activity.defn
@with_heartbeat
def pdf_get_metadata_and_store(params: PdfMetaParams) -> Dict[str, Any]:
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa
    from datetime import datetime, timezone

    collection_dataset: str = params.collection_dataset
    pdf_hash: str = params.pdf_hash
    file_path: str = params.file_path

    log.info("[P3] Getting PDF metadata for %s", file_path)

    try:
        size_bytes = os.path.getsize(file_path)
    except Exception:
        size_bytes = 0

    # Two blocking qpdf calls with no loop of their own -> pump.
    with heartbeat_pump(f"qpdf meta {pdf_hash[:8]}"):
        page_count = _qpdf_show_npages(file_path)
        meta = {}
        try:
            meta = _qpdf_json(file_path)
        except Exception:
            meta = {}

    # Attempt to derive author and creation date from common keys
    author_fields: List[str] = []
    date_created_dt: Optional[datetime] = None
    try:
        info = meta.get("info") or {}
        for k in ["Author", "Creator", "Producer"]:
            v = info.get(k)
            if isinstance(v, str) and v:
                author_fields.append(f"{k}={v}")
        cd = info.get("CreationDate") or info.get("ModDate")
        if isinstance(cd, str) and cd:
            # Try Tika-like ISO first, otherwise ignore
            try:
                # Strip common PDF date prefix D:
                cd_norm = cd
                if cd_norm.startswith("D:"):
                    cd_norm = cd_norm[2:]
                # Best-effort parse of YYYYMMDDHHmmSSZ or ISO
                from datetime import datetime
                if "-" in cd_norm or ":" in cd_norm:
                    date_created_dt = datetime.fromisoformat(cd_norm.replace("Z", "+00:00")).replace(tzinfo=None)
                else:
                    date_created_dt = datetime.strptime(cd_norm[:14], "%Y%m%d%H%M%S")
            except Exception:
                date_created_dt = None
    except Exception:
        pass

    author_metadata = "; ".join(author_fields)
    if date_created_dt is None:
        # ClickHouse non-nullable DateTime; use epoch
        from datetime import datetime
        date_created_dt = datetime(1970, 1, 1)

    processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_collection_client(params.collectionname) as client:
        # pdfs row
        tbl_pdfs = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "pdf_hash": pa.array([pdf_hash], type=pa.string()),
            "page_count": pa.array([page_count], type=pa.uint32()),
            "word_count": pa.array([0], type=pa.uint32()),
            "author_metadata": pa.array([author_metadata], type=pa.string()),
            "date_created": pa.array([date_created_dt], type=pa.timestamp("s")),
        })
        insert_arrow_idempotent(client, "pdfs", tbl_pdfs)

        # pdf_metadata row
        tbl_meta = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "hash": pa.array([pdf_hash], type=pa.string()),
            "pdf_metadata_json": pa.array([json.dumps(meta)], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        insert_arrow_idempotent(client, "pdf_metadata", tbl_meta)

    return {"page_count": page_count, "size_bytes": size_bytes}


@dataclass
class PdfSmallParams:
    collectionname: str
    collection_dataset: str
    pdf_hash: str
    file_path: str
    page_count: int | None = None


@activity.defn
@with_heartbeat
def pdf_small_extract_text_and_images(params: PdfSmallParams) -> Dict[str, Any]:
    """For small PDFs, attempt text extraction and extract images to temp dir."""
    from database.clickhouse import get_collection_client, insert_arrow_idempotent
    import pyarrow as pa

    log.info("[P3] Extracting text and images for PDF %s", params.file_path)

    collection_dataset: str = params.collection_dataset
    pdf_hash: str = params.pdf_hash
    file_path: str = params.file_path
    page_count: int = int(params.page_count or 0)

    # Create temp dir
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    out_dir = make_temp_dir(collection_dataset, "pdf", pdf_hash)

    # Both extractions block in a child process with no loop to beat from.
    with heartbeat_pump(f"pdf small {pdf_hash[:8]}"):
        # Text, one row per real PDF page.
        text_pages = _pdftotext_pages(file_path)
        _insert_pdf_text_pages(params.collectionname, collection_dataset, pdf_hash, text_pages)

        # Extract images via qpdf (best-effort)
        image_paths = _extract_images_with_qpdf(file_path, out_dir)
    if image_paths:
        # Insert image rows and pdfs_image relationships
        from hashlib import sha3_256

        from tasks.P3_parse_files.image_loader import image_dimensions
        rows_img_cd: List[str] = []
        rows_img_hash: List[str] = []
        rows_img_w: List[int] = []
        rows_img_h: List[int] = []
        rows_img_meta: List[str] = []

        rows_link_cd: List[str] = []
        rows_link_pdf: List[str] = []
        rows_link_page: List[int] = []
        rows_link_img: List[str] = []

        for idx, p in enumerate(image_paths):
            try:
                with open(p, "rb") as f:
                    data = f.read()
                ih = sha3_256(data).hexdigest()
            except Exception:
                continue
            # Real dimensions, from the header. They are what the OCR size gate reads
            # to skip icons and rules, and a stored 0x0 would make every extracted image
            # look ungated. `image_dimensions` returns None for a format Pillow cannot
            # open, and 0 then means "unknown" rather than "tiny".
            size = image_dimensions(data)
            rows_img_cd.append(collection_dataset)
            rows_img_hash.append(ih)
            rows_img_w.append(size[0] if size else 0)
            rows_img_h.append(size[1] if size else 0)
            rows_img_meta.append("")

            rows_link_cd.append(collection_dataset)
            rows_link_pdf.append(pdf_hash)
            # Best-effort page number. qpdf --extract-images names files by object id,
            # not by page, so this is a sequential approximation and not the real page.
            # It is 1-based like every other page number in the schema: a 0 in a page
            # column reads as "page zero exists" to the viewer.
            on_page = idx + 1 if page_count == 0 else min(idx + 1, max(1, page_count))
            rows_link_page.append(on_page)
            rows_link_img.append(ih)

        if rows_img_hash:
            with get_collection_client(params.collectionname) as client:
                tbl_img = pa.table({
                    "collection_dataset": pa.array(rows_img_cd, type=pa.string()),
                    "image_hash": pa.array(rows_img_hash, type=pa.string()),
                    "width_pixels": pa.array(rows_img_w, type=pa.uint32()),
                    "height_pixels": pa.array(rows_img_h, type=pa.uint32()),
                    "image_metadata": pa.array(rows_img_meta, type=pa.string()),
                })
                insert_arrow_idempotent(client, "image", tbl_img)

                tbl_link = pa.table({
                    "collection_dataset": pa.array(rows_link_cd, type=pa.string()),
                    "pdf_hash": pa.array(rows_link_pdf, type=pa.string()),
                    "on_page": pa.array(rows_link_page, type=pa.uint32()),
                    "image_hash": pa.array(rows_link_img, type=pa.string()),
                })
                insert_arrow_idempotent(client, "pdfs_image", tbl_link)

    return {"out_dir": out_dir}


@dataclass
class PdfLargeParams:
    collectionname: str
    collection_dataset: str
    pdf_hash: str
    file_path: str
    page_count: int | None = None
    size_bytes: int | None = None


@activity.defn
@with_heartbeat
def pdf_large_split_to_chunks(params: PdfLargeParams) -> Dict[str, Any]:
    collection_dataset: str = params.collection_dataset
    pdf_hash: str = params.pdf_hash
    file_path: str = params.file_path
    page_count: int = int(params.page_count or 0)
    size_bytes: int = int(params.size_bytes or 0)

    log.info("[P3] Splitting PDF into chunks: %s", file_path)

    # Create temp dir for chunks
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    out_dir = make_temp_dir(collection_dataset, "pdfchunks", pdf_hash)

    # Compute pages per chunk
    if page_count <= 0:
        page_count = _qpdf_show_npages(file_path)
    pages_per_chunk = _compute_pages_per_chunk(size_bytes, page_count)

    # Split into ranges
    ranges: List[Tuple[int, int]] = []
    a = 1
    while a <= page_count:
        b = min(page_count, a + pages_per_chunk - 1)
        ranges.append((a, b))
        a = b + 1

    # Generate chunk files. Class B: this loop is real work per iteration, so an
    # in-loop heartbeat is strictly better than a pump -- it is evidence of
    # forward progress rather than evidence of a live thread, and the details
    # show up in `temporal workflow describe` as an advancing chunk count.
    heartbeat = HeartbeatClock()
    chunk_files: List[str] = []
    try:
        for i, (a, b) in enumerate(ranges):
            heartbeat.beat(f"qpdf split {i}/{len(ranges)} chunks")
            dest = os.path.join(out_dir, f"chunk_{i+1}_{a}-{b}.pdf")
            res = _run_qpdf([
                "--empty", "--no-warn", "--warning-exit-0", "--deterministic-id",
                "--object-streams=generate", "--remove-unreferenced-resources=yes", "--no-original-object-ids",
                "--pages", file_path, f"{a}-{b}", "--", dest,
            ])
            if res.returncode != 0:
                raise RuntimeError(f"qpdf split failed for pages {a}-{b}: {res.stderr[:200]} {res.stdout[:200]}")
            chunk_files.append(dest)
    except BaseException:
        # A retry must not find half a chunk set from the cancelled attempt.
        import shutil
        shutil.rmtree(out_dir, ignore_errors=True)
        raise

    return {"out_dir": out_dir, "chunks": chunk_files}


@dataclass
class PdfProcessingWorkflowParams:
    collectionname: str
    collection_dataset: str
    pdf_hash: str
    file_path: str
    timeout_seconds: int




@workflow.defn
class PdfProcessingAndScan:
    @workflow.run
    async def run(self, params: PdfProcessingWorkflowParams) -> str:
        # 1) Gather metadata and store
        meta = await workflow.execute_activity(
            pdf_get_metadata_and_store,
            PdfMetaParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                pdf_hash=params.pdf_hash,
                file_path=params.file_path,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        page_count = int(meta.get("page_count") or 0)
        size_bytes = int(meta.get("size_bytes") or 0)

        # 1b) Searchable PDFs, one activity per engine, started now and awaited at the
        # end. Which engines run (and whether any do) is decided inside the activity
        # from `pdf_ocr_provider` and `dataset_settings`, not here: a workflow argument
        # would freeze the value at schedule time, and the apply job exists
        # to reach activities that are already in flight.
        #
        # On the OCR queue rather than the common one: the work is one OCR call per page,
        # so it belongs behind the same bounded tier as image OCR. An engine with nothing
        # configured records a skip and succeeds, so this fan-out costs nothing on a box
        # with no OCR tier at all.
        ocr_pdf_futures = [
            workflow.execute_activity(
                run_ocr_pdf_and_store,
                RunOcrPdfParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    pdf_hash=params.pdf_hash,
                    file_path=params.file_path,
                    engine=engine,
                    timeout_seconds=params.timeout_seconds,
                ),
                start_to_close_timeout=timedelta(seconds=max(params.timeout_seconds, 3600)),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                task_queue="processing-ocr-queue",
            )
            for engine in OCR_ENGINES
        ]

        # 2) Branch by size and page count
        SMALL_BYTES = 64 * 1024 * 1024
        SMALL_PAGES = 1000

        # Create child workflow args for scanning
        out_dir = None
        if size_bytes < SMALL_BYTES or page_count < SMALL_PAGES:
            res = await workflow.execute_activity(
                pdf_small_extract_text_and_images,
                PdfSmallParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    pdf_hash=params.pdf_hash,
                    file_path=params.file_path,
                    page_count=page_count,
                ),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            out_dir = res.get("out_dir")
        else:
            res = await workflow.execute_activity(
                pdf_large_split_to_chunks,
                PdfLargeParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    pdf_hash=params.pdf_hash,
                    file_path=params.file_path,
                    page_count=page_count,
                    size_bytes=size_bytes,
                ),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            out_dir = res.get("out_dir")

        # 3) Scan the out_dir via P0 as a container, then cleanup
        if out_dir:
            args = HandleFoldersParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                dataset_path=out_dir,
                folder_paths=["/"],
                container_hash=params.pdf_hash,
                root_path_prefix="",
            )
            with workflow.unsafe.imports_passed_through():
                from tasks.P0_scan_disk.workflows import HandleFolders
                from tasks.P3_parse_files.parse_archives import cleanup_temp_dir
                from tasks.P3_parse_files.parse_archives import record_archive_container
                from tasks.visibility import dataset_search_attributes

            # Record an archive-like container row for discoverability
            await workflow.execute_activity(
                record_archive_container,
                RecordArchiveContainerParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    archive_hash=params.pdf_hash,
                    archive_types=["pdf"],
                ),
                start_to_close_timeout=timedelta(minutes=10),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

            await workflow.execute_child_workflow(
                HandleFolders.run,
                args,
                id=f"scan-pdf-{params.collection_dataset}-{params.pdf_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )

            await workflow.execute_activity(
                cleanup_temp_dir,
                CleanupTempDirParams(out_dir=out_dir),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

        # The searchable PDFs are independent of the text/image path above, so they run
        # alongside it and are collected here. Errors are recorded rather than raised: a
        # failure to derive a searchable PDF must not lose the text extraction that
        # already succeeded for the same document.
        if ocr_pdf_futures:
            results = await asyncio.gather(*ocr_pdf_futures, return_exceptions=True)
            with workflow.unsafe.imports_passed_through():
                from tasks.P3_parse_files.parse_common import record_errors_from_results
            await record_errors_from_results(
                results,
                task_ids=[f"run_ocr_pdf_and_store[{engine}]" for engine in OCR_ENGINES],
                starts=[workflow.now()] * len(OCR_ENGINES),
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=[params.pdf_hash] * len(OCR_ENGINES),
                start_to_close_timeout_seconds=params.timeout_seconds,
            )

        return "ok"
