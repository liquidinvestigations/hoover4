"""Tesseract OCR over HTTP — the CPU twin of the GPU EasyOCR service.

Why this is a service and not a subprocess in the worker
-------------------------------------------------------
OCR moved out of the worker image on purpose (plans/1-part-2.md §3.1). Two reasons,
both learned the hard way:

* **`tesseract-ocr-eng` inside the worker made native Tika OCR scanned PDFs
  implicitly**, producing text attributed to `extractous` that nobody asked for and
  nobody could turn off per dataset. Removing the binary makes that parser inert, and
  the same text comes back through here as its own attributed variant instead.
* **EasyOCR in-process deadlocked the worker.** Two concurrent `readtext` calls in one
  process parked all 91 threads in `futex_wait` with heartbeats still flowing — a live
  thread making no progress, which is the one failure the heartbeat pump cannot see.
  A bounded pool behind an HTTP boundary is what stops that from being possible.

Contract
--------
``POST /ocr``   ``{"image_b64": ..., "languages": "eng+ron"}``
                -> ``{"text", "confidence", "engine", "languages", "run_time_ms",
                      "words": [...]}``
``GET /health`` -> ``{"status", "engine", "languages_available", ...}``

The request is JSON with base64 rather than multipart because the client
(`tasks/remote.py`) speaks JSON and carries the timeout, fallback and circuit-breaker
contract with it. That costs 33% on the wire for a payload that is bounded at
``OCR_MAX_IMAGE_BYTES`` anyway; PDFs never come through here, they go to the
OCR'd-PDF service.

Backpressure is explicit: a bounded worker pool, a capped queue, and `503` +
`Retry-After` when the queue is full. The client maps that to a *retryable* Temporal
error rather than a failure, so a busy OCR tier slows the pipeline down instead of
filling `processing_errors` with noise.
"""

import base64
import binascii
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("ocr_tesseract")

#: Hard ceiling on one decoded image. Bigger than any page render we produce, small
#: enough that a malformed request cannot exhaust memory.
OCR_MAX_IMAGE_BYTES = int(os.getenv("OCR_MAX_IMAGE_BYTES", str(64 * 1024 * 1024)))

#: Tesseract is CPU-bound and already uses several threads per page. More concurrency
#: than this trades throughput for latency on every request at once.
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "2"))

#: How many requests may wait for a slot before the service starts shedding load.
OCR_QUEUE_DEPTH = int(os.getenv("OCR_QUEUE_DEPTH", "8"))

#: Wall-clock ceiling for one tesseract invocation. A wedged child is the one failure
#: an HTTP boundary does not fix by itself.
OCR_SUBPROCESS_TIMEOUT_S = float(os.getenv("OCR_SUBPROCESS_TIMEOUT_S", "300"))

CONFIG_FINGERPRINT = os.getenv("HOOVER4_CONFIG_FINGERPRINT", "")

app = FastAPI(title="hoover4 tesseract OCR", version="1.0")

_pool = ThreadPoolExecutor(max_workers=OCR_CONCURRENCY, thread_name_prefix="ocr")
_inflight = threading.Semaphore(OCR_CONCURRENCY + OCR_QUEUE_DEPTH)


class OcrRequest(BaseModel):
    image_b64: str = Field(..., description="Base64 of the image bytes, any format Leptonica reads")
    languages: str = Field("eng", description="+-joined Tesseract language codes, e.g. eng+ron")
    #: Page segmentation mode. 3 (fully automatic, no OSD) is Tesseract's own default and
    #: the right choice for document scans; exposed so the caller can override per file.
    psm: int = Field(3, ge=0, le=13)


class OcrWord(BaseModel):
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int


class OcrResponse(BaseModel):
    text: str
    confidence: float
    engine: str
    languages: str
    run_time_ms: int
    words: List[OcrWord]


def _available_languages() -> List[str]:
    try:
        res = subprocess.run(["tesseract", "--list-langs"], capture_output=True,
                             stdin=subprocess.DEVNULL, timeout=30)
        lines = (res.stdout or b"").decode("utf-8", "ignore").splitlines()
        # First line is a header ("List of available languages...").
        return sorted(line.strip() for line in lines[1:] if line.strip())
    except Exception:
        log.warning("could not list tesseract languages", exc_info=True)
        return []


_LANGUAGES = _available_languages()


def _run_tesseract(image_bytes: bytes, languages: str, psm: int) -> tuple:
    """Return ``(text, mean_confidence, words)`` for one image.

    Uses the TSV output rather than plain text because the per-word confidence is what
    lets several language variants of the same image be scored against each other and a
    winner marked — storing every variant is only useful if they can be compared.
    """
    with tempfile.TemporaryDirectory(prefix="ocr_") as work:
        src = os.path.join(work, "input")
        with open(src, "wb") as handle:
            handle.write(image_bytes)

        cmd = ["tesseract", src, "stdout", "-l", languages, "--psm", str(psm), "tsv"]
        res = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL,
                             timeout=OCR_SUBPROCESS_TIMEOUT_S)
        if res.returncode != 0:
            stderr = (res.stderr or b"").decode("utf-8", "ignore")[:500]
            raise RuntimeError(f"tesseract failed ({res.returncode}): {stderr}")

        tsv = (res.stdout or b"").decode("utf-8", "ignore")

    words: List[OcrWord] = []
    lines: List[List[str]] = []
    for row in tsv.splitlines()[1:]:
        parts = row.split("\t")
        if len(parts) < 12:
            continue
        text = parts[11].strip()
        if not text:
            continue
        try:
            confidence = float(parts[10])
        except ValueError:
            continue
        # -1 marks a layout row (block/paragraph/line), not a recognised word.
        if confidence < 0:
            continue
        words.append(OcrWord(
            text=text, confidence=confidence,
            left=int(parts[6]), top=int(parts[7]),
            width=int(parts[8]), height=int(parts[9]),
        ))
        # Group by (block, paragraph, line) so the reconstructed text keeps its layout
        # instead of becoming one word per line.
        key = (parts[2], parts[3], parts[4])
        if lines and lines[-1][0] == key:
            lines[-1][1].append(text)
        else:
            lines.append([key, [text]])

    text = "\n".join(" ".join(words_of_line) for _, words_of_line in lines)
    confidence = sum(w.confidence for w in words) / len(words) if words else 0.0
    return text, confidence, words


@app.get("/health")
def health():
    """Reports what this instance can actually do, not what it was asked to do.

    `languages_available` is read from tesseract itself: a dataset configured for a
    language whose traineddata is not installed fails per file, and this is the only
    place that mismatch is visible before it does.
    """
    return {
        "status": "healthy" if shutil.which("tesseract") and _LANGUAGES else "unhealthy",
        "engine": "tesseract",
        "languages_available": _LANGUAGES,
        "concurrency": OCR_CONCURRENCY,
        "queue_depth": OCR_QUEUE_DEPTH,
        "max_image_bytes": OCR_MAX_IMAGE_BYTES,
        "config_fingerprint": CONFIG_FINGERPRINT,
    }


@app.post("/ocr", response_model=OcrResponse)
def ocr(request: OcrRequest, response: Response):
    if not _inflight.acquire(blocking=False):
        # Shed load rather than queue without bound. The client turns this into a
        # retryable Temporal error, so the work is not lost -- it is rescheduled.
        raise HTTPException(
            status_code=503,
            detail="OCR queue is full",
            headers={"Retry-After": "5"},
        )
    try:
        try:
            image_bytes = base64.b64decode(request.image_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"image_b64 is not valid base64: {exc}")

        if not image_bytes:
            raise HTTPException(status_code=400, detail="image_b64 decoded to zero bytes")
        if len(image_bytes) > OCR_MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"image is {len(image_bytes)} bytes, limit is {OCR_MAX_IMAGE_BYTES}",
            )

        missing = [code for code in request.languages.split("+")
                   if code and _LANGUAGES and code not in _LANGUAGES]
        if missing:
            # A clear 400 beats a tesseract error buried in stderr: the fix is an image
            # rebuild or a settings change, not a retry.
            raise HTTPException(
                status_code=400,
                detail=f"language(s) {missing} not installed; available: {_LANGUAGES}",
            )

        started = time.time()
        try:
            text, confidence, words = _pool.submit(
                _run_tesseract, image_bytes, request.languages, request.psm
            ).result()
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="tesseract timed out")
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

        return OcrResponse(
            text=text,
            confidence=confidence,
            engine="tesseract",
            languages=request.languages,
            run_time_ms=int((time.time() - started) * 1000),
            words=words,
        )
    finally:
        _inflight.release()
