"""Client for the searchable-PDF service, over `tasks.remote`.

The engine asymmetry from `tasks/ocr_client.py` applies unchanged — a variant is
`tesseract+eng` or `easyocr+en`, so there is no cross-engine fallback and an engine with
no endpoint simply produces no variant. What is different here is *which* endpoint is
missing: `hoover4-ocr-pdf` is one service that speaks to both engines, so the switch that
turns OCR'd PDFs off entirely is `ocr_pdf_enabled` (rendered as `OCR_PDF_URL`), while the
per-engine switch stays where it already is, in the OCR tier's own endpoints.

`pdf_ocr_provider` — `tesseract | easyocr | both | none` — is read here, and this is the
only place that reads it. A switch rendered into the worker's environment and consumed
nowhere is a lie; keep this the consumer.
"""

import logging
import os
from dataclasses import dataclass
from typing import List

from tasks.remote import RemoteUnavailable, post_json
from tasks.text_sources import ENGINE_EASYOCR, ENGINE_TESSERACT

log = logging.getLogger(__name__)

#: Assembling a 300-page scan is 300 OCR calls behind one request. The service's own
#: queue and per-page timeout are the real guards; this bounds the wait for a healthy one.
OCR_PDF_READ_TIMEOUT = float(os.getenv("OCR_PDF_READ_TIMEOUT_SECONDS", "3600"))

#: The one prefix a derived object may live under. Mirrors `DERIVED_PREFIX` in
#: `main_services/ocr_pdf/ocr_pdf.py`, which refuses anything else — the duplication is
#: deliberate, like `collectionname` validation: the caller must not be able to ask for a
#: key the ingest walker could see, and the service must not trust that it did not.
DERIVED_PREFIX = "derived/ocr-pdf"


@dataclass
class OcrPdfOutcome:
    dest_key: str
    blob_hash: str
    page_count: int
    pages_with_text: int
    size_bytes: int
    engine: str
    languages: str
    run_time_ms: int
    provider: str


def _endpoints() -> List[tuple]:
    return [("ocr-pdf", (os.getenv("OCR_PDF_URL") or "").strip())]


def service_configured() -> bool:
    """Whether the assembler has an endpoint at all.

    Disabled is not an error and must not consume retries: `ocr_pdf_enabled = false`
    simply means the corpus gets no searchable PDFs.
    """
    return any(url for _, url in _endpoints())


def engines_for_provider() -> List[str]:
    """Which engines `pdf_ocr_provider` asks for, in a stable order.

    An unknown value is treated as `none` and logged rather than guessed at: producing
    variants nobody asked for costs OCR time and creates rows a purge then has to find.
    """
    provider = (os.getenv("PDF_OCR_PROVIDER") or "tesseract").strip().lower()
    if provider == "none":
        return []
    if provider == "both":
        return [ENGINE_TESSERACT, ENGINE_EASYOCR]
    if provider in (ENGINE_TESSERACT, ENGINE_EASYOCR):
        return [provider]
    log.warning("[ocr-pdf] unknown pdf_ocr_provider %r, producing no OCR'd PDFs", provider)
    return []


def derived_key(collection_dataset: str, pdf_hash: str, engine: str, languages: str) -> str:
    """The Garage key for one variant.

    Keyed exactly like the `pdf_ocr_results` row — `(collection_dataset, pdf_hash, engine,
    languages)` — so the row and the object can always be matched from either side. That
    is what makes the purge in `change_ocr_languages` able to delete both.
    """
    return f"{DERIVED_PREFIX}/{collection_dataset}/{pdf_hash}/{engine}+{languages}.pdf"


def build_ocr_pdf(
    *,
    collectionname: str,
    collection_dataset: str,
    pdf_hash: str,
    engine: str,
    languages: str,
    source_key: str = "",
    pdf_b64: str = "",
) -> OcrPdfOutcome:
    """Assemble one searchable PDF and return where it landed.

    Raises :class:`tasks.remote.RemoteUnavailable` when the service is configured but did
    not answer — retryable, and deliberately distinct from "not configured", which callers
    check with :func:`service_configured` first.
    """
    from database.s3 import collection_bucket

    dest_key = derived_key(collection_dataset, pdf_hash, engine, languages)
    payload = {
        # The collection's own bucket, named by the caller. The service has a fallback
        # for a probe, and using it for real work would read one collection's source and
        # write another collection's derived object.
        "bucket": collection_bucket(collectionname),
        "dest_key": dest_key,
        "engine": engine,
        "languages": languages,
    }
    if source_key:
        payload["source_key"] = source_key
    else:
        payload["pdf_b64"] = pdf_b64

    result = post_json(_endpoints(), payload, read_timeout=OCR_PDF_READ_TIMEOUT,
                       service="ocr_pdf")
    data = result.data if isinstance(result.data, dict) else {}

    return OcrPdfOutcome(
        dest_key=data.get("dest_key") or dest_key,
        blob_hash=data.get("blob_hash") or "",
        page_count=int(data.get("page_count") or 0),
        pages_with_text=int(data.get("pages_with_text") or 0),
        size_bytes=int(data.get("size_bytes") or 0),
        # What the service says it ran, not what was asked for. They agree today; if they
        # ever stop, the stored label must follow what actually ran.
        engine=data.get("engine") or engine,
        languages=data.get("languages") or languages,
        run_time_ms=int(data.get("run_time_ms") or 0),
        provider=result.provider,
    )


__all__ = [
    "DERIVED_PREFIX",
    "OcrPdfOutcome",
    "OCR_PDF_READ_TIMEOUT",
    "RemoteUnavailable",
    "build_ocr_pdf",
    "derived_key",
    "engines_for_provider",
    "service_configured",
]
