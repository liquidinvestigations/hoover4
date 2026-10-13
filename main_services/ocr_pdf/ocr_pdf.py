"""Build source-preserving PDF overlays in isolated child processes."""
import base64
import binascii
import hashlib
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
from contextlib import asynccontextmanager
from typing import Any, Dict, Literal, Optional

import anyio.to_thread
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, StrictInt

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ocr_pdf")

#: Derived outputs remain outside source ingestion.
DERIVED_PREFIX = "derived/"

#: Render resolution. 200 dpi is the usual floor for reliable OCR of body text and keeps
#: an A4 page at ~1650x2340 px, which the OCR tier's 64 MB image cap accepts.
DEFAULT_DPI = int(os.getenv("OCR_PDF_DPI", "200"))
MAX_DPI = int(os.getenv("OCR_PDF_MAX_DPI", "400"))

#: Ceilings. A malformed or hostile PDF must not be able to turn one request into hours
#: of CPU or gigabytes of memory, and a bomb-shaped PDF is a real corpus artefact.
MAX_PDF_BYTES = int(os.getenv("OCR_PDF_MAX_INPUT_BYTES", str(512 * 1024 * 1024)))
MAX_PAGES = int(os.getenv("OCR_PDF_MAX_PAGES", "2000"))

#: PDFs at once, one render process each, and the requests that may wait for a slot.
#: deploy.py renders both from `ocr_pdf_concurrency` and `ocr_pdf_queue_depth` in
#: hoover4.ini, and gives the worker queue of searchable-PDF batches as many slots as
#: this service runs, so the worker sends at most that many requests. The pages of one
#: PDF go to the OCR tier one after the other.
OCR_PDF_CONCURRENCY = int(os.getenv("OCR_PDF_CONCURRENCY", "2"))
OCR_PDF_QUEUE_DEPTH = int(os.getenv("OCR_PDF_QUEUE_DEPTH", "4"))

#: Threads for `def` handlers. A request holds one thread from its admission check to its
#: answer, so the limit covers every admitted request and leaves 4 for other handlers.
#: AnyIO's default is 40.
HTTP_THREADS = OCR_PDF_CONCURRENCY + OCR_PDF_QUEUE_DEPTH + 4

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

@asynccontextmanager
async def lifespan(_app):
    """Raise the thread limit of `def` handlers to the admission of this service."""
    anyio.to_thread.current_default_thread_limiter().total_tokens = HTTP_THREADS
    yield


app = FastAPI(title="hoover4 OCR'd PDF", version="1.0", lifespan=lifespan)

_pool = ThreadPoolExecutor(max_workers=OCR_PDF_CONCURRENCY, thread_name_prefix="ocrpdf")
_inflight = threading.Semaphore(OCR_PDF_CONCURRENCY + OCR_PDF_QUEUE_DEPTH)
RENDER_WORKER_COMMAND = [sys.executable, "-m", "render_worker"]
RENDER_TIMEOUT_SECONDS = int(os.getenv("OCR_PDF_RENDER_TIMEOUT_SECONDS", "3600"))


class OcrPdfRequest(BaseModel):
    #: Owned output uses the collection bucket. Empty uses the configured default.
    bucket: str = Field("", description="Bucket holding the destination key")
    source_bucket: str = Field("", description="Source bucket. Empty uses the destination bucket")
    #: Small sources can use inline input when they have no object-store key.
    source_key: str = Field("", description="Object key of the source PDF or image")
    source_b64: str = Field("", description="Inline source PDF or image")
    pdf_b64: str = Field("", description="Legacy inline source PDF")
    mode: Literal["pdf", "image"] = "pdf"
    ocr_pages: Optional[list[StrictInt]] = Field(None, description="Selected local pages, numbered from one. Omitted means all pages")
    words: list[dict[str, Any]] = Field(default_factory=list, description="Stored OCR word boxes for image mode")
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
    pages: list[dict[str, Any]] = Field(default_factory=list)


def _s3():
    from minio import Minio

    return Minio(
        S3_ENDPOINT,
        access_key=S3_ACCESS_KEY,
        secret_key=S3_SECRET_KEY,
        secure=S3_SECURE,
    )


def validate_dest_key(dest_key: str) -> str:
    """Require a derived destination key without parent-directory traversal."""
    key = (dest_key or "").strip()
    if not key.startswith(DERIVED_PREFIX):
        raise ValueError(f"dest_key must start with {DERIVED_PREFIX!r}, got {key!r}")
    if key.endswith("/") or ".." in key.split("/") or key.startswith("/"):
        raise ValueError(f"dest_key is not a plain object key: {key!r}")
    return key


def run_renderer(source: str, destination: str, engine: str, languages: str,
                 dpi: int, mode="pdf", ocr_pages=None, words=None) -> dict:
    """Run PDFium in one child process and return its page results."""
    options_path = destination + ".request.json"
    with open(options_path, "w") as handle:
        json.dump({"mode": mode, "ocr_pages": ocr_pages, "words": words or []}, handle)
    try:
        result = subprocess.run(
            list(RENDER_WORKER_COMMAND) + [source, destination, engine, languages, str(dpi), options_path],
            text=True, capture_output=True, timeout=RENDER_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "the renderer timed out on this PDF")
    finally:
        os.unlink(options_path)
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
    if result.returncode != 0 or not os.path.isfile(destination):
        raise HTTPException(500, "the renderer wrote no PDF")
    return body


def write_inline_source(encoded, destination, field):
    """Decode inline input in bounded blocks and retain the input byte limit."""
    size = 0
    try:
        with open(destination, "wb") as handle:
            for offset in range(0, len(encoded), 65536):
                block = base64.b64decode(encoded[offset:offset + 65536], validate=True)
                # Padding is valid only at the end of the complete input.
                if "=" in encoded[offset:offset + 65536] and offset + 65536 < len(encoded):
                    raise ValueError("base64 padding precedes the end")
                size += len(block)
                if size > MAX_PDF_BYTES:
                    raise HTTPException(413, "the source exceeds the input byte limit")
                handle.write(block)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "%s is not valid base64: %s" % (field, exc))


def fetch_source(client, bucket, key, destination):
    """Stream an object to disk after verifying its reported input size."""
    try:
        size = client.stat_object(bucket, key).size
        if size > MAX_PDF_BYTES:
            raise HTTPException(413, "the source exceeds the input byte limit")
        client.fget_object(bucket, key, destination)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(404, "cannot read %r: %s" % (key, exc))


@app.get("/health")
async def health():
    """What this instance can actually do, engines included.

    An `async` handler, so it answers while every handler thread serves an admitted
    request.

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
        "http_threads": HTTP_THREADS,
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

        with tempfile.TemporaryDirectory(prefix="ocr-pdf-") as folder:
            source = os.path.join(folder, "source")
            destination = os.path.join(folder, "result.pdf")
            if request.source_b64 or request.pdf_b64:
                field = "source_b64" if request.source_b64 else "pdf_b64"
                write_inline_source(request.source_b64 or request.pdf_b64, source, field)
            elif request.source_key:
                fetch_source(client, request.source_bucket.strip() or bucket, request.source_key, source)
            else:
                raise HTTPException(400, "one of source_key, source_b64 or pdf_b64 is required")
            size = os.path.getsize(source)
            if not size:
                raise HTTPException(400, "the source is zero bytes")
            if size > MAX_PDF_BYTES:
                raise HTTPException(413, "the source exceeds the input byte limit")
            try:
                result = _pool.submit(
                    run_renderer, source, destination, request.engine, request.languages,
                    request.dpi, request.mode, request.ocr_pages, request.words,
                ).result()
            except HTTPException:
                raise
            except Exception as exc:
                log.warning("[ocr-pdf] assembly failed for %s", dest_key, exc_info=True)
                raise HTTPException(422, "could not assemble the PDF: %s" % exc)
            digest = hashlib.sha3_256()
            with open(destination, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            size_bytes = os.path.getsize(destination)
            # Upload the object before the caller records its result row.
            client.fput_object(bucket, dest_key, destination, content_type="application/pdf")
            run_time_ms = max(int((time.time() - started) * 1000), 0)
            log.info("[ocr-pdf] %s: %d pages (%d with text), %d bytes in %d ms",
                     dest_key, result["page_count"], result["pages_with_text"], size_bytes, run_time_ms)
            return OcrPdfResponse(
                page_count=result["page_count"], pages_with_text=result["pages_with_text"],
                pages=result["pages"], size_bytes=size_bytes, blob_hash=digest.hexdigest(),
                engine=request.engine, languages=request.languages, dest_key=dest_key,
                run_time_ms=run_time_ms,
            )
    finally:
        _inflight.release()
