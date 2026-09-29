"""Searchable-PDF assembly over HTTP, renders, OCRs, and writes a text-layered PDF.

What it does
------------
Given a PDF in the object store (or inline, for the small blobs that live in ClickHouse), it renders
every page to a raster, sends each raster to the **existing** OCR tier
(`hoover4-tesseract-cpu`), and assembles a new PDF: the page image with the recognised
words drawn over it in invisible text. The result reads like a scan and selects, copies
and searches like text.

Why a separate service and not a worker activity
------------------------------------------------
The same two reasons OCR itself is a service (`main_services/ocr_tesseract`), plus one of
its own:

* **Rasterising is a native-library job.** pypdfium2 and Pillow in the worker image would
  put a PDF renderer inside the process that also runs Temporal activities, archives,
  email parsing and ClickHouse writes. The worker deliberately shells out to `qpdf` and
  `pdftotext` instead of linking a PDF library, and this keeps that property.
* **The page loop is unbounded work over one input.** A 500-page scan is 500 OCR calls.
  Bounded concurrency and load-shedding belong on the thing doing them, not spread across
  every caller.

The derived-PDF trap
--------------------
The output is a new PDF. If the ingest walker could see it, it would be ingested, OCR'd,
and produce another PDF, forever, which is the most expensive defect this service can
have. Three
guards, of which this file owns the first two:

1. `dest_key` **must** start with ``derived/``. A request that asks for anything else is
   refused with 400, before a byte is written.
2. Nothing here writes a `blobs` or `vfs_files` row. The only index of the object's
   existence is `pdf_ocr_results`, written by the caller after this returns.
3. `verify-stack.sh` asserts no `blobs` row references the derived prefix.

Contract
--------
``POST /ocr-pdf``  ``{"source_key"|"pdf_b64", "dest_key", "engine", "languages", "dpi"}``
                   -> ``{"page_count", "pages_with_text", "size_bytes", "blob_hash",
                         "engine", "languages", "dest_key", "run_time_ms"}``
``GET  /health``   -> ``{"status", "engines", "renderer", "bucket", ...}``
"""

import base64
import binascii
import hashlib
import io
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

import requests
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ocr_pdf")

#: The one prefix a derived object may be written under. See "The derived-PDF trap".
DERIVED_PREFIX = "derived/"

#: Render resolution. 200 dpi is the usual floor for reliable OCR of body text and keeps
#: an A4 page at ~1650x2340 px, which the OCR tier's 64 MB image cap accepts.
DEFAULT_DPI = int(os.getenv("OCR_PDF_DPI", "200"))
MAX_DPI = int(os.getenv("OCR_PDF_MAX_DPI", "400"))

#: Ceilings. A malformed or hostile PDF must not be able to turn one request into hours
#: of CPU or gigabytes of memory, and a bomb-shaped PDF is a real corpus artefact.
MAX_PDF_BYTES = int(os.getenv("OCR_PDF_MAX_INPUT_BYTES", str(512 * 1024 * 1024)))
MAX_PAGES = int(os.getenv("OCR_PDF_MAX_PAGES", "2000"))

#: JPEG quality for the page images. The output is a scan of a scan either way, so the
#: setting that changes the result is file size: quality 75 is roughly a third of the bytes of 95 and
#: does not change what Tesseract already read off the pre-compression raster.
JPEG_QUALITY = int(os.getenv("OCR_PDF_JPEG_QUALITY", "75"))

#: One PDF at a time per slot, and a short queue. Each in-flight request holds a whole
#: rendered page in memory and keeps an OCR slot busy, so this is deliberately smaller
#: than the OCR tier's own concurrency.
OCR_PDF_CONCURRENCY = int(os.getenv("OCR_PDF_CONCURRENCY", "2"))
OCR_PDF_QUEUE_DEPTH = int(os.getenv("OCR_PDF_QUEUE_DEPTH", "4"))

#: Per-page OCR wait. The OCR service's own subprocess timeout is the real guard against
#: a wedged child; this bounds the wait for a healthy but busy one.
OCR_READ_TIMEOUT = float(os.getenv("OCR_READ_TIMEOUT_SECONDS", "600"))

S3_ENDPOINT = (os.getenv("S3_ENDPOINT", "garage:3900")
               .replace("https://", "").replace("http://", "").rstrip("/"))
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "hoover4-blobs-rw")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "hoover4-garage-blob-secret-key-0")
#: Fallback bucket, for a caller that names none. There is a bucket per collection, so a
#: request carries the one it means: a service with a single configured bucket would read
#: one collection's source and write another collection's derived object.
S3_BUCKET = os.getenv("S3_BUCKET", "hoover4-system")
S3_SECURE = os.getenv("S3_ENDPOINT", "").startswith("https://")

CONFIG_FINGERPRINT = os.getenv("HOOVER4_CONFIG_FINGERPRINT", "")

#: One endpoint per engine, exactly as `tasks/ocr_client.py` names them. An engine with no
#: endpoint is *not configured*, which is a different answer from *unavailable*: the first
#: is a deployment fact the caller must not retry, the second is transient.
OCR_ENDPOINTS: Dict[str, str] = {
    "tesseract": (os.getenv("OCR_TESSERACT_URL") or "").strip(),
    "easyocr": (os.getenv("OCR_EASYOCR_URL") or "").strip(),
}

app = FastAPI(title="hoover4 OCR'd PDF", version="1.0")

_pool = ThreadPoolExecutor(max_workers=OCR_PDF_CONCURRENCY, thread_name_prefix="ocrpdf")
_inflight = threading.Semaphore(OCR_PDF_CONCURRENCY + OCR_PDF_QUEUE_DEPTH)
RENDER_WORKER_COMMAND = [sys.executable, "-m", "render_worker"]
RENDER_TIMEOUT_SECONDS = int(os.getenv("OCR_PDF_RENDER_TIMEOUT_SECONDS", "3600"))


class OcrPdfRequest(BaseModel):
    #: The bucket both keys live in, which is the collection's own. Empty falls back to this
    #: service's configured default, which exists only so that a probe can be made
    #: without one.
    bucket: str = Field("", description="Bucket holding the source and destination keys")
    #: Object key of the source PDF, inside `bucket`. Either this or `pdf_b64`, blobs
    #: under the small-file threshold live in ClickHouse and have no object at all, so
    #: the caller sends those inline.
    source_key: str = Field("", description="Object key of the source PDF")
    pdf_b64: str = Field("", description="Inline source PDF, for blobs not stored in the object store")
    dest_key: str = Field(..., description="Object key to write, must start with derived/")
    engine: str = Field("tesseract", description="OCR engine: tesseract | easyocr")
    languages: str = Field("eng", description="+-joined language codes for one pass")
    dpi: int = Field(DEFAULT_DPI, ge=72, le=MAX_DPI)


class OcrPdfResponse(BaseModel):
    page_count: int
    pages_with_text: int
    size_bytes: int
    blob_hash: str
    engine: str
    languages: str
    dest_key: str
    run_time_ms: int


def _s3():
    from minio import Minio

    return Minio(
        S3_ENDPOINT,
        access_key=S3_ACCESS_KEY,
        secret_key=S3_SECRET_KEY,
        secure=S3_SECURE,
    )


def validate_dest_key(dest_key: str) -> str:
    """Refuse anything that is not under the derived prefix, and any traversal.

    This is guard 1 of the derived-PDF trap and it runs before any work: a caller that
    gets this wrong writes an object the ingest walker *can* see, and the loop it starts
    is the most expensive bug in the system.
    """
    key = (dest_key or "").strip()
    if not key.startswith(DERIVED_PREFIX):
        raise ValueError(f"dest_key must start with {DERIVED_PREFIX!r}, got {key!r}")
    if key.endswith("/") or ".." in key.split("/") or key.startswith("/"):
        raise ValueError(f"dest_key is not a plain object key: {key!r}")
    return key


def run_renderer(pdf_bytes: bytes, engine: str, languages: str, dpi: int) -> tuple:
    """Run PDFium in one child process and return its output."""
    with tempfile.TemporaryDirectory(prefix="ocr-pdf-") as folder:
        source = os.path.join(folder, "source.pdf")
        destination = os.path.join(folder, "result.pdf")
        with open(source, "wb") as handle:
            handle.write(pdf_bytes)
        try:
            result = subprocess.run(
                list(RENDER_WORKER_COMMAND) + [source, destination, engine, languages, str(dpi)],
                text=True, capture_output=True, timeout=RENDER_TIMEOUT_SECONDS, check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "the renderer timed out on this PDF")
        if result.returncode < 0:
            name = signal.Signals(-result.returncode).name
            raise HTTPException(422, "the renderer stopped with signal %s on this PDF" % name)
        try:
            body = json.loads(result.stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError):
            raise HTTPException(500, "the renderer returned no result")
        if not body.get("ok"):
            raise HTTPException(body.get("status", 500), body.get("detail", "renderer failed"),
                                headers=body.get("headers") or None)
        try:
            output = open(destination, "rb").read()
        except OSError as exc:
            raise HTTPException(500, "the renderer wrote no PDF: %s" % exc)
        return output, int(body["page_count"]), int(body["pages_with_text"])


@app.get("/health")
def health():
    """What this instance can actually do, engines included.

    `engines` reports *configured*, not *reachable*: an unreachable OCR tier is a
    transient fact that changes between two health checks, and reporting it here would
    make this service's health flap with someone else's. What cannot change without a
    redeploy is which engines have an endpoint at all, and that is the mismatch worth
    seeing before a dataset is configured for an engine that has nowhere to go.
    """
    try:
        import importlib.metadata

        import pypdfium2  # noqa: F401  - imported to prove the binary loads

        # `importlib.metadata`, not an attribute on the module: pypdfium2 moved its
        # version constants between majors (`V_PYPDFIUM2` is gone in 5.x), and a /health
        # that reports "unavailable" because it guessed the wrong attribute name is a
        # health check reporting on itself rather than on the renderer.
        renderer = f"pypdfium2 {importlib.metadata.version('pypdfium2')}"
        ok = True
    except Exception:  # pragma: no cover - a broken image, not a runtime state
        renderer = "unavailable"
        ok = False

    return {
        "status": "healthy" if ok else "unhealthy",
        "engines": {name: bool(url) for name, url in OCR_ENDPOINTS.items()},
        "renderer": renderer,
        "default_bucket": S3_BUCKET,
        "derived_prefix": DERIVED_PREFIX,
        "dpi_default": DEFAULT_DPI,
        "max_pages": MAX_PAGES,
        "concurrency": OCR_PDF_CONCURRENCY,
        "queue_depth": OCR_PDF_QUEUE_DEPTH,
        "config_fingerprint": CONFIG_FINGERPRINT,
    }


@app.post("/ocr-pdf", response_model=OcrPdfResponse)
def ocr_pdf(request: OcrPdfRequest, response: Response):
    if not _inflight.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="OCR-PDF queue is full",
                            headers={"Retry-After": "10"})
    try:
        try:
            dest_key = validate_dest_key(request.dest_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if not request.languages.strip():
            raise HTTPException(status_code=400,
                                detail="languages must not be empty: it is part of the storage key")
        if request.engine not in OCR_ENDPOINTS:
            raise HTTPException(status_code=400, detail=f"unknown OCR engine {request.engine!r}")

        bucket = (request.bucket or "").strip() or S3_BUCKET
        started = time.time()
        client = _s3()

        if request.pdf_b64:
            try:
                pdf_bytes = base64.b64decode(request.pdf_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"pdf_b64 is not valid base64: {exc}")
        elif request.source_key:
            try:
                obj = client.get_object(bucket, request.source_key)
                try:
                    pdf_bytes = obj.read()
                finally:
                    obj.close()
                    obj.release_conn()
            except Exception as exc:
                raise HTTPException(status_code=404,
                                    detail=f"cannot read {request.source_key!r}: {exc}")
        else:
            raise HTTPException(status_code=400, detail="one of source_key or pdf_b64 is required")

        if not pdf_bytes:
            raise HTTPException(status_code=400, detail="the source PDF is zero bytes")
        if len(pdf_bytes) > MAX_PDF_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"the source PDF is {len(pdf_bytes)} bytes, limit is {MAX_PDF_BYTES}",
            )

        try:
            out_bytes, page_count, pages_with_text = _pool.submit(
                run_renderer, pdf_bytes, request.engine, request.languages, request.dpi
            ).result()
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("[ocr-pdf] assembly failed for %s", dest_key, exc_info=True)
            raise HTTPException(status_code=422, detail=f"could not assemble the PDF: {exc}")

        blob_hash = hashlib.sha3_256(out_bytes).hexdigest()
        # Bytes before the row, always: an object with no row is found by a prefix scan,
        # a row with no object is a broken link nothing can repair. The
        # `pdf_ocr_results` row is the caller's to write, after this returns.
        client.put_object(
            bucket,
            dest_key,
            io.BytesIO(out_bytes),
            length=len(out_bytes),
            content_type="application/pdf",
        )

        run_time_ms = max(int((time.time() - started) * 1000), 0)
        log.info("[ocr-pdf] %s: %d pages (%d with text), %d bytes in %d ms",
                 dest_key, page_count, pages_with_text, len(out_bytes), run_time_ms)
        return OcrPdfResponse(
            page_count=page_count,
            pages_with_text=pages_with_text,
            size_bytes=len(out_bytes),
            blob_hash=blob_hash,
            engine=request.engine,
            languages=request.languages,
            dest_key=dest_key,
            run_time_ms=run_time_ms,
        )
    finally:
        _inflight.release()
