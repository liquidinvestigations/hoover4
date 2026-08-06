"""Client for the OCR tier: one function per engine, over `tasks.remote`.

Endpoint layout, and why there is no cross-engine fallback
----------------------------------------------------------
Every other capability in this tier degrades from GPU to a CPU twin and records which
one served (`RemoteResult.provider`). OCR deliberately does not, because the provider is
part of the storage key: a variant is `ocr_easyocr_en` or `ocr_tesseract_eng`, and
serving an EasyOCR request from Tesseract would file Tesseract's output under EasyOCR's
name. Worse, Tesseract has already run as its own variant, so the result would be the
same text stored twice under two labels — the fan-out D4 pays for exists to let variants
be *compared*, and this would quietly make two of them identical.

So: an engine that is not configured produces no variant at all, and an engine that is
configured but unreachable raises, is retried by Temporal, and eventually lands in
`processing_errors` where it is visible and re-runnable. Both are honest; substituting is
not.

Within one engine, `tasks.remote` still applies in full — connect timeout, circuit
breaker, and a second endpoint for that same engine if one is ever configured.
"""

import base64
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from tasks.remote import READ_TIMEOUT, RemoteUnavailable, post_json
from tasks.text_sources import ENGINE_EASYOCR, ENGINE_TESSERACT

log = logging.getLogger(__name__)

#: OCR is slower than a NER batch and legitimately so: a dense scanned page at 300 dpi is
#: tens of seconds on CPU. Still finite -- the subprocess timeout inside the service is
#: the real guard against a wedged child, this bounds the wait for a healthy one.
OCR_READ_TIMEOUT = float(os.getenv("OCR_READ_TIMEOUT_SECONDS", "600"))


@dataclass
class OcrOutcome:
    text: str
    confidence: float
    engine: str
    languages: str
    run_time_ms: int
    raw_json: str
    provider: str


def _endpoints_for(engine: str) -> List[Tuple[str, str]]:
    """Ordered `(provider, url)` for one engine. Empty entries are skipped downstream."""
    if engine == ENGINE_TESSERACT:
        return [("tesseract-cpu", (os.getenv("OCR_TESSERACT_URL") or "").strip())]
    if engine == ENGINE_EASYOCR:
        return [("easyocr-gpu", (os.getenv("OCR_EASYOCR_URL") or "").strip())]
    raise ValueError(f"unknown OCR engine {engine!r}")


def engine_configured(engine: str) -> bool:
    """Whether any endpoint exists for this engine.

    A disabled engine is not an error and must not consume retries: it simply produces
    no variant. `easyocr_enabled = false` in hoover4.ini is the normal state on a box
    with no GPU tier.
    """
    return any(url for _, url in _endpoints_for(engine))


def run_ocr(engine: str, languages: str, image_bytes: bytes,
            *, psm: Optional[int] = None) -> OcrOutcome:
    """OCR one image with one engine and one language set.

    Raises :class:`tasks.remote.RemoteUnavailable` when the engine is configured but no
    endpoint answered — a retryable condition, deliberately distinct from
    "engine not configured", which callers check with :func:`engine_configured` first.
    """
    import json

    payload = {
        "image_b64": base64.b64encode(image_bytes).decode("ascii"),
        "languages": languages,
    }
    if psm is not None:
        payload["psm"] = psm

    result = post_json(_endpoints_for(engine), payload, read_timeout=OCR_READ_TIMEOUT)
    data = result.data if isinstance(result.data, dict) else {}

    return OcrOutcome(
        text=data.get("text") or "",
        confidence=float(data.get("confidence") or 0.0),
        # The engine the *service* reports, not the one requested. They agree today;
        # if they ever stop agreeing, the stored label must follow what actually ran.
        engine=data.get("engine") or engine,
        languages=data.get("languages") or languages,
        run_time_ms=int(data.get("run_time_ms") or 0),
        raw_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        provider=result.provider,
    )


__all__ = [
    "OcrOutcome",
    "OCR_READ_TIMEOUT",
    "RemoteUnavailable",
    "READ_TIMEOUT",
    "engine_configured",
    "run_ocr",
]
