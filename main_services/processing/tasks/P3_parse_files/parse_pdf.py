"""PDF parsing activities and workflow for metadata, text, and images."""

from temporalio import workflow, activity
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import os
import json
import math
import tempfile
import subprocess
import logging
log = logging.getLogger(__name__)

from tasks.P0_scan_disk.workflows import HandleFoldersParams
from tasks.P3_parse_files.parse_archives import CleanupTempDirParams, RecordArchiveContainerParams


def _run_qpdf(args: List[str]) -> subprocess.CompletedProcess:
    cmd = ["qpdf"] + args
    return subprocess.run(cmd, capture_output=True)


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
        res = subprocess.run(["pdftotext", "-enc", "UTF-8", "-layout", path, "-"], capture_output=True)
        if res.returncode == 0:
            return (res.stdout or b"").decode("utf-8", errors="ignore")
    except FileNotFoundError:
        pass
    return None


def _insert_text_via_helper(collection_dataset: str, pdf_hash: str, text_content: Optional[str]) -> int:
    if not text_content:
        return 0
    from tasks.P3_parse_files.parse_common import insert_text_chunks
    return insert_text_chunks(collection_dataset, pdf_hash, "qpdf", text_content)


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
    collection_dataset: str
    pdf_hash: str
    file_path: str


@activity.defn
def pdf_get_metadata_and_store(params: PdfMetaParams) -> Dict[str, Any]:
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa
    from datetime import datetime

    collection_dataset: str = params.collection_dataset
    pdf_hash: str = params.pdf_hash
    file_path: str = params.file_path

    log.info("[P3] Getting PDF metadata for %s", file_path)

    try:
        size_bytes = os.path.getsize(file_path)
    except Exception:
        size_bytes = 0

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
        date_created_dt = datetime.utcfromtimestamp(0)

    processed_at = datetime.utcnow()
    with get_clickhouse_client() as client:
        # pdfs row
        tbl_pdfs = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "pdf_hash": pa.array([pdf_hash], type=pa.string()),
            "page_count": pa.array([page_count], type=pa.uint32()),
            "word_count": pa.array([0], type=pa.uint32()),
            "author_metadata": pa.array([author_metadata], type=pa.string()),
            "date_created": pa.array([date_created_dt], type=pa.timestamp("s")),
        })
        client.insert_arrow("pdfs", tbl_pdfs)

        # pdf_metadata row
        tbl_meta = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "hash": pa.array([pdf_hash], type=pa.string()),
            "pdf_metadata_json": pa.array([json.dumps(meta)], type=pa.string()),
            "processed_at": pa.array([processed_at], type=pa.timestamp("s")),
        })
        client.insert_arrow("pdf_metadata", tbl_meta)

    return {"page_count": page_count, "size_bytes": size_bytes}


@dataclass
class PdfSmallParams:
    collection_dataset: str
    pdf_hash: str
    file_path: str
    page_count: int | None = None


@activity.defn
def pdf_small_extract_text_and_images(params: PdfSmallParams) -> Dict[str, Any]:
    """For small PDFs, attempt text extraction and extract images to temp dir."""
    from database.clickhouse import get_clickhouse_client
    import pyarrow as pa

    log.info("[P3] Extracting text and images for PDF %s", params.file_path)

    collection_dataset: str = params.collection_dataset
    pdf_hash: str = params.pdf_hash
    file_path: str = params.file_path
    page_count: int = int(params.page_count or 0)

    # Create temp dir
    from tasks.P3_parse_files.temp_dirs import make_temp_dir
    out_dir = make_temp_dir(collection_dataset, "pdf", pdf_hash)

    # Try to extract text (fallback to pdftotext if present)
    text_content = (_maybe_pdftotext(file_path) or "").strip()
    if text_content and len(text_content) > 1:
        _insert_text_via_helper(collection_dataset, pdf_hash, text_content)

    # Extract images via qpdf (best-effort)
    image_paths = _extract_images_with_qpdf(file_path, out_dir)
    if image_paths:
        # Insert image rows and pdfs_image relationships
        from hashlib import sha3_256
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
            rows_img_cd.append(collection_dataset)
            rows_img_hash.append(ih)
            rows_img_w.append(0)
            rows_img_h.append(0)
            rows_img_meta.append("")

            rows_link_cd.append(collection_dataset)
            rows_link_pdf.append(pdf_hash)
            # Best-effort page number: try to infer from filename like img-<obj>-<gen>-p<page>.*; else sequential
            on_page = idx if page_count == 0 else min(idx, max(0, page_count - 1))
            rows_link_page.append(on_page)
            rows_link_img.append(ih)

        if rows_img_hash:
            with get_clickhouse_client() as client:
                tbl_img = pa.table({
                    "collection_dataset": pa.array(rows_img_cd, type=pa.string()),
                    "image_hash": pa.array(rows_img_hash, type=pa.string()),
                    "width_pixels": pa.array(rows_img_w, type=pa.uint32()),
                    "height_pixels": pa.array(rows_img_h, type=pa.uint32()),
                    "image_metadata": pa.array(rows_img_meta, type=pa.string()),
                })
                client.insert_arrow("image", tbl_img)

                tbl_link = pa.table({
                    "collection_dataset": pa.array(rows_link_cd, type=pa.string()),
                    "pdf_hash": pa.array(rows_link_pdf, type=pa.string()),
                    "on_page": pa.array(rows_link_page, type=pa.uint32()),
                    "image_hash": pa.array(rows_link_img, type=pa.string()),
                })
                client.insert_arrow("pdfs_image", tbl_link)

    return {"out_dir": out_dir}


@dataclass
class PdfLargeParams:
    collection_dataset: str
    pdf_hash: str
    file_path: str
    page_count: int | None = None
    size_bytes: int | None = None


@activity.defn
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

    # Generate chunk files
    chunk_files: List[str] = []
    for i, (a, b) in enumerate(ranges):
        dest = os.path.join(out_dir, f"chunk_{i+1}_{a}-{b}.pdf")
        res = _run_qpdf([
            "--empty", "--no-warn", "--warning-exit-0", "--deterministic-id",
            "--object-streams=generate", "--remove-unreferenced-resources=yes", "--no-original-object-ids",
            "--pages", file_path, f"{a}-{b}", "--", dest,
        ])
        if res.returncode != 0:
            raise RuntimeError(f"qpdf split failed for pages {a}-{b}: {res.stderr[:200]} {res.stdout[:200]}")
        chunk_files.append(dest)

    return {"out_dir": out_dir, "chunks": chunk_files}


@dataclass
class PdfProcessingWorkflowParams:
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
                collection_dataset=params.collection_dataset,
                pdf_hash=params.pdf_hash,
                file_path=params.file_path,
            ),
            start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        page_count = int(meta.get("page_count") or 0)
        size_bytes = int(meta.get("size_bytes") or 0)

        # 2) Branch by size and page count
        SMALL_BYTES = 64 * 1024 * 1024
        SMALL_PAGES = 1000

        # Create child workflow args for scanning
        out_dir = None
        if size_bytes < SMALL_BYTES or page_count < SMALL_PAGES:
            res = await workflow.execute_activity(
                pdf_small_extract_text_and_images,
                PdfSmallParams(
                    collection_dataset=params.collection_dataset,
                    pdf_hash=params.pdf_hash,
                    file_path=params.file_path,
                    page_count=page_count,
                ),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            out_dir = res.get("out_dir")
        else:
            res = await workflow.execute_activity(
                pdf_large_split_to_chunks,
                PdfLargeParams(
                    collection_dataset=params.collection_dataset,
                    pdf_hash=params.pdf_hash,
                    file_path=params.file_path,
                    page_count=page_count,
                    size_bytes=size_bytes,
                ),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            out_dir = res.get("out_dir")

        # 3) Scan the out_dir via P0 as a container, then cleanup
        if out_dir:
            args = HandleFoldersParams(
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

            # Record an archive-like container row for discoverability
            await workflow.execute_activity(
                record_archive_container,
                RecordArchiveContainerParams(
                    collection_dataset=params.collection_dataset,
                    archive_hash=params.pdf_hash,
                    archive_types=["pdf"],
                ),
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

            await workflow.execute_child_workflow(
                HandleFolders.run,
                args,
                id=f"scan-pdf-{params.collection_dataset}-{params.pdf_hash}",
                task_queue="processing-common-queue",
            )

            await workflow.execute_activity(
                cleanup_temp_dir,
                CleanupTempDirParams(out_dir=out_dir),
                start_to_close_timeout=timedelta(seconds=params.timeout_seconds),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        return "ok"
