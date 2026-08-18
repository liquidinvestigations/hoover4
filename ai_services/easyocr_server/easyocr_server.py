"""EasyOCR over HTTP — the GPU half of the OCR tier.

Contract
--------
``POST /ocr``   ``{"image_b64": ..., "languages": "en+ro"}``
                -> ``{"text", "confidence", "engine", "languages", "run_time_ms",
                      "words": [...]}``
``GET /health`` -> ``{"status", "engine", "languages_available", ...}``

Byte-for-byte the same contract as ``main_services/ocr_tesseract``, because
``tasks/ocr_client.py`` builds one request shape and posts it to whichever engine a
dataset asked for. It parses `psm` off the request and ignores it: page segmentation is
a Tesseract concept with no EasyOCR equivalent, and rejecting a field the shared client
always sends would make the two engines un-substitutable at the call site for no gain.

Why the concurrency is one, and why it is enforced here
------------------------------------------------------
Two concurrent ``readtext`` calls in a single process park every thread in
``futex_wait`` while heartbeats keep flowing — a live process making no progress, which
is the one failure a heartbeat pump cannot see. That is why OCR is a service and not a
subprocess in the worker, and it is equally true inside this service: the bounded pool
below is the thing that makes the deadlock unreachable, not an optimisation. Raising
``OCR_CONCURRENCY`` above 1 reintroduces it.

Backpressure is explicit: a bounded pool, a capped queue, and `503` + `Retry-After` when
the queue is full. The client maps that to a *retryable* Temporal error, so a busy OCR
tier slows the pipeline down instead of filling `processing_errors` with noise.

Readers are cached per language set
-----------------------------------
Building an EasyOCR ``Reader`` loads a detection and a recognition network onto the GPU
and costs seconds. A dataset OCRs thousands of pages against the same language set, so
the readers are cached; the cache is bounded because each entry holds GPU memory, and
`languages` is caller-supplied — an unbounded map keyed on it is a memory leak with a
remote trigger.
"""

import base64
import binascii
import logging
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import List

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from PIL import Image
from pydantic import BaseModel, Field

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("easyocr_server")

#: Hard ceiling on one decoded image. Bigger than any page render we produce, small
#: enough that a malformed request cannot exhaust memory.
OCR_MAX_IMAGE_BYTES = int(os.getenv("OCR_MAX_IMAGE_BYTES", str(64 * 1024 * 1024)))

#: See the module docstring: 1 is a correctness bound, not a throughput setting.
OCR_CONCURRENCY = int(os.getenv("OCR_CONCURRENCY", "1"))

#: How many requests may wait for a slot before the service starts shedding load.
OCR_QUEUE_DEPTH = int(os.getenv("OCR_QUEUE_DEPTH", "8"))

#: How many distinct language sets keep a warm Reader. Each one holds GPU memory.
OCR_READER_CACHE_SIZE = int(os.getenv("OCR_READER_CACHE_SIZE", "3"))

#: Language sets baked into the image, and the ones /health advertises. The models for
#: anything else are fetched on first use, which is why this is also what the deploy
#: configures: an unlisted language works, but pays a download on the first page.
EASYOCR_LANGUAGES = os.getenv("EASYOCR_LANGUAGES", "en")

#: Where the model weights live. The compose overlay mounts the shared model-cache
#: volume here, so a reset that preserves caches also preserves these.
EASYOCR_MODEL_DIR = os.getenv("EASYOCR_MODEL_DIR", "/root/.EasyOCR")

CONFIG_FINGERPRINT = os.getenv("HOOVER4_CONFIG_FINGERPRINT", "")

app = FastAPI(title="hoover4 easyocr", version="1.0")

_pool = ThreadPoolExecutor(max_workers=OCR_CONCURRENCY, thread_name_prefix="ocr")
_inflight = threading.Semaphore(OCR_CONCURRENCY + OCR_QUEUE_DEPTH)

_readers: "OrderedDict[tuple, object]" = OrderedDict()
_readers_lock = threading.Lock()


def _use_gpu() -> bool:
    import torch

    return torch.cuda.is_available()


def _split_languages(languages: str) -> List[str]:
    return [code.strip() for code in (languages or "").split("+") if code.strip()]


def _get_reader(codes: List[str]):
    """Return a cached ``Reader`` for one language set, building it if needed.

    Held under a lock for the whole build: two requests for a cold language set would
    otherwise construct two Readers and load two copies of the weights onto the card.
    """
    import easyocr

    key = tuple(codes)
    with _readers_lock:
        if key in _readers:
            _readers.move_to_end(key)
            return _readers[key]
        log.info("building EasyOCR reader for %s (gpu=%s)", key, _use_gpu())
        reader = easyocr.Reader(
            list(codes),
            gpu=_use_gpu(),
            model_storage_directory=EASYOCR_MODEL_DIR,
            user_network_directory=EASYOCR_MODEL_DIR,
            download_enabled=True,
            verbose=False,
        )
        _readers[key] = reader
        while len(_readers) > OCR_READER_CACHE_SIZE:
            evicted, _ = _readers.popitem(last=False)
            log.info("evicted EasyOCR reader for %s", evicted)
        return reader


class OcrRequest(BaseModel):
    image_b64: str = Field(..., description="Base64 of the image bytes, any format Pillow reads")
    languages: str = Field("en", description="+-joined EasyOCR language codes, e.g. en+ro")
    #: Accepted and ignored — Tesseract's page segmentation mode has no EasyOCR
    #: equivalent. Present so both engines take the one request shape ocr_client sends.
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


def _run_easyocr(image_bytes: bytes, codes: List[str]) -> tuple:
    """Return ``(text, mean_confidence, words)`` for one image.

    EasyOCR reports one box per recognised *line*, not per word, and gives it a free
    quadrilateral rather than a rectangle. Both are normalised here — the box is reduced
    to its bounding rectangle and the line is emitted as a single ``words`` entry — so
    that a consumer can score an EasyOCR variant against a Tesseract one without knowing
    which engine produced it.
    """
    import io

    with Image.open(io.BytesIO(image_bytes)) as handle:
        # EasyOCR takes RGB; a palette or CMYK scan otherwise reaches it as the wrong
        # channel count and fails inside the detector rather than here.
        image = np.array(handle.convert("RGB"))

    reader = _get_reader(codes)
    detections = reader.readtext(image, detail=1, paragraph=False)

    words: List[OcrWord] = []
    lines: List[str] = []
    for box, text, confidence in detections:
        text = (text or "").strip()
        if not text:
            continue
        xs = [int(point[0]) for point in box]
        ys = [int(point[1]) for point in box]
        left, top = min(xs), min(ys)
        words.append(OcrWord(
            text=text,
            # EasyOCR scores 0..1; Tesseract's TSV scores 0..100. The stored variants are
            # compared against each other, so they have to be on one scale.
            confidence=float(confidence) * 100.0,
            left=left, top=top,
            width=max(xs) - left, height=max(ys) - top,
        ))
        lines.append(text)

    text = "\n".join(lines)
    confidence = sum(w.confidence for w in words) / len(words) if words else 0.0
    return text, confidence, words


@app.get("/health")
def health():
    """Reports what this instance can actually do, not what it was asked to do.

    `gpu` is read from torch rather than from the env: a container that lost its device
    injection still starts and still OCRs, only ~20x slower, and this is the one place
    that shows it before a dataset takes a day.
    """
    try:
        import easyocr  # noqa: F401
        gpu = _use_gpu()
        status = "healthy"
    except Exception:
        log.warning("easyocr is not importable", exc_info=True)
        gpu = False
        status = "unhealthy"
    return {
        "status": status,
        "engine": "easyocr",
        "languages_available": _split_languages(EASYOCR_LANGUAGES),
        "gpu": gpu,
        "readers_warm": [list(key) for key in _readers],
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

        codes = _split_languages(request.languages)
        if not codes:
            raise HTTPException(status_code=400, detail="languages is empty")

        started = time.time()
        try:
            text, confidence, words = _pool.submit(_run_easyocr, image_bytes, codes).result()
        except ValueError as exc:
            # EasyOCR raises this for a language set it cannot build a Reader for (codes
            # from incompatible scripts, or a code it does not know). The fix is a
            # settings change, not a retry, so it must not look retryable.
            raise HTTPException(status_code=400, detail=f"unusable language set {codes}: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"easyocr failed: {exc}")

        return OcrResponse(
            text=text,
            confidence=confidence,
            engine="easyocr",
            languages=request.languages,
            run_time_ms=int((time.time() - started) * 1000),
            words=words,
        )
    finally:
        _inflight.release()
