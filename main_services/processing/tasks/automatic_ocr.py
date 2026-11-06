"""Pin automatic OCR decisions to detected pages and installed engine coverage."""

import hashlib
import json
from functools import lru_cache
import time

POLICY_VERSION = 1
AUTOMATIC_OCR_PATCH = "automatic-ocr-v1"
PAGE_BATCH = 32
ARTIFACT_SEGMENTATION_VERSION = 1
_KNOWN_CAPABILITIES = {}


def digest(value) -> str:
    """Return a stable identity for a JSON contract."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


# ISO language codes differ from installed Tesseract model names.
TESSERACT_LANGUAGES = dict(zip(
    "en ro fr de es it pt nl ru uk bg sr hr pl cs sk sl hu el tr ar fa he hi bn ta te kn ml gu pa th vi ko ja zh hy ka km lo my si sv da no fi et lv lt id ms sw af sq az be ca cy eu gl is mk mt ne ur uz kk ky mn ps sd so tg ti yi".split(),
    "eng ron fra deu spa ita por nld rus ukr bul srp hrv pol ces slk slv hun ell tur ara fas heb hin ben tam tel kan mal guj pan tha vie kor jpn chi_sim hye kat khm lao mya sin swe dan nor fin est lav lit ind msa swa afr sqi aze bel cat cym eus glg isl mkd mlt nep urd uzb kaz kir mon pus snd som tgk tir yid".split()))
LANGUAGE_SCRIPTS = {language: "Latin" for language in
    "en ro fr de es it pt nl hr pl cs sk sl hu tr vi sv da no fi et lv lt id ms sw af sq az ca cy eu gl is mt uz so".split()}
LANGUAGE_SCRIPTS.update({language: script for script, languages in {
    "Cyrillic": "ru uk bg sr be kk ky mn tg mk", "Arabic": "ar fa ur ps sd ug",
    "Devanagari": "hi mr ne", "Greek": "el", "Armenian": "hy", "Georgian": "ka",
    "Bengali": "bn as", "Tamil": "ta", "Telugu": "te", "Kannada": "kn", "Malayalam": "ml",
    "Gujarati": "gu", "Gurmukhi": "pa", "Thai": "th", "Hangul": "ko", "Japanese": "ja",
    "Han": "zh", "Khmer": "km", "Lao": "lo", "Myanmar": "my", "Sinhala": "si", "Hebrew": "he yi",
    "Ethiopic": "ti", "Syriac": "syr", "Thaana": "dv", "Canadian_Aboriginal": "iu", "Cherokee": "chr",
}.items() for language in languages.split()})

SCRIPT_MODELS = {"Han": ("HanS", "HanT"), "Latin": ("Latin",), "Cyrillic": ("Cyrillic",)}
# Script groups follow https://github.com/JaidedAI/EasyOCR/blob/master/easyocr/config.py.
# Installed package support limits each group.
EASY_SCRIPT_GROUPS = {
    "Latin": ("en", "af", "az", "bs", "cs", "cy", "da", "de", "es", "et", "fr", "ga", "hr", "hu", "id", "is", "it", "ku", "la", "lt", "lv", "mi", "ms", "mt", "nl", "no", "oc", "pi", "pl", "pt", "ro", "rs_latin", "sk", "sl", "sq", "sv", "sw", "tl", "tr", "uz", "vi"),
    "Cyrillic": ("ru", "rs_cyrillic", "be", "bg", "uk", "mn", "abq", "ady", "kbd", "ava", "dar", "inh", "che", "lbe", "lez", "tab", "tjk"),
    "Arabic": ("ar", "fa", "ug", "ur"), "Devanagari": ("hi", "mr", "ne", "bh", "mai", "ang", "bho", "mah", "sck", "new", "gom", "sa", "bgc"),
    "Bengali": ("bn", "as", "mni"), "Han": ("ch_sim",), "Japanese": ("ja",),
    "Hangul": ("ko",), "Tamil": ("ta",), "Telugu": ("te",), "Kannada": ("kn",),
    "Thai": ("th",),
}


@lru_cache(maxsize=1)
def _capabilities(_window: int) -> dict:
    """Read installed models and retain optional engine availability failures."""
    import requests
    from tasks.ocr_client import _endpoints_for
    result = {}
    for engine in ("tesseract", "easyocr"):
        endpoints = [url for _, url in _endpoints_for(engine) if url]
        if not endpoints:
            result[engine] = []
            continue
        try:
            response = requests.get(endpoints[0].removesuffix("/ocr") + "/health", timeout=(10, 30))
            response.raise_for_status()
            health = response.json()
            if health.get("status") != "healthy":
                raise RuntimeError(f"OCR capability service is unavailable: {engine}")
            field = "languages_supported" if engine == "easyocr" else "languages_available"
            supported = sorted(set(health.get(field) or []))
            if not supported:
                raise RuntimeError(f"OCR capability service returned no supported models: {engine}")
            _KNOWN_CAPABILITIES[engine] = supported
            result[engine] = supported
        except (requests.RequestException, ValueError, RuntimeError):
            result[engine] = _KNOWN_CAPABILITIES.get(engine, [])
            result[engine + "_unavailable"] = True
    return result


def capabilities() -> dict:
    """Refresh supported model identities once per minute."""
    return _capabilities(int(time.monotonic() // 60))


def capability_digest(installed: dict) -> str:
    from tasks.P3_parse_files.ocr_detection import OCR_DETECTION_VERSION
    from tasks.text_sources import PDF_SEGMENTATION_VERSION, PDF_TEXT_LAYER_VERSION
    from tasks.stage_versions import STAGE_VERSIONS
    from tasks.ocr_pdf_client import service_configured
    versions = {stage: STAGE_VERSIONS[stage] for stage in
                ("ocr_image", "ocr_pdf", "image_pdf", "image_preview", "pdf_preview", "pdf", "ocr_plan", "index_text")}
    return digest(dict(searchable_pdf=service_configured(), artifact_segmentation=ARTIFACT_SEGMENTATION_VERSION, artifact_page_batch=PAGE_BATCH, stages=versions, engines={engine: installed.get(engine, []) for engine in ("tesseract", "easyocr")}, detector=OCR_DETECTION_VERSION,
                       segmentation=PDF_SEGMENTATION_VERSION, pdf_text_layer=PDF_TEXT_LAYER_VERSION))


def choose_pass(found: dict, installed: dict) -> dict:
    """Choose one engine from successful detection without reading manual settings."""
    if not found.get("has_text"):
        return dict(status="no_text", reason="detected_no_text", passes=[])
    script, language = found.get("script") or "", found.get("language") or "und"
    if not script or script in ("Unknown", "Common", "NULL"):
        return dict(status="incomplete", reason="unknown_script", passes=[])
    if installed.get("tesseract_unavailable"):
        return dict(status="failed", reason="tesseract_capabilities_unavailable", passes=[])
    tesseract = set(installed.get("tesseract", []))
    model_hint = found.get("model") or ""
    exact = "chi_tra" if language == "zh" and model_hint == "HanT" else TESSERACT_LANGUAGES.get(language)
    if language == "sr" and script == "Latin":
        exact = "srp_latn"
    matching_script = LANGUAGE_SCRIPTS.get(language) == script or (language == "sr" and script == "Latin")
    if exact and exact in tesseract and matching_script:
        return dict(status="ready", reason="detected_language", passes=[dict(engine="tesseract", languages=exact)])
    scripts = ((model_hint,) if model_hint in ("HanS", "HanT") else
               tuple(dict.fromkeys(((model_hint,) if model_hint else ()) + SCRIPT_MODELS.get(script, (script,)))))
    model = next((model for model in scripts if model in tesseract), None)
    if model:
        reason = ("unknown_language_script_coverage" if language == "und" else
                  "language_script_mismatch_script_coverage" if exact in tesseract and not matching_script else
                  "language_model_unavailable_script_coverage")
        return dict(status="ready", reason=reason, passes=[dict(engine="tesseract", languages=model)])
    if installed.get("easyocr_unavailable"):
        return dict(status="failed", reason="easyocr_capabilities_unavailable", passes=[])
    supported = set(installed.get("easyocr", []))
    exact = {"zh": "ch_tra" if model_hint == "HanT" else "ch_sim", "sr": "rs_cyrillic"}.get(language, language)
    group = ("ch_tra",) if model_hint == "HanT" else EASY_SCRIPT_GROUPS.get(script, ())
    if exact in supported and exact in group:
        languages = exact
    else:
        languages = "+".join(sorted(supported.intersection(group)))
    if languages:
        return dict(status="ready", reason="tesseract_script_unavailable", passes=[dict(engine="easyocr", languages=languages)])
    return dict(status="unsupported", reason="script_coverage_unavailable", passes=[])


def make_plan(dataset: str, file_hash: str, source_revision: str, kind: str,
              rows: list[dict], installed: dict, segmentation: int) -> dict:
    """Build deterministic page decisions and a document publication identity."""
    pages = []
    for found in sorted(rows, key=lambda row: row["page_id"]):
        page = dict(page_id=found["page_id"], detector_version=found.get("detector_version", 0), detector_digest=digest(found),
                    model=found.get("model", ""), script=found.get("script", ""), language=found.get("language", "und"), **choose_pass(found, installed))
        for item in page["passes"]:
            item["pass_id"] = digest(dict(page_id=page["page_id"], **item))
        page["page_digest"] = digest(page)
        pages.append(page)
    plan = dict(dataset=dataset, file_hash=file_hash, source_revision=source_revision,
                source_kind=kind, segmentation=segmentation, artifact_segmentation=ARTIFACT_SEGMENTATION_VERSION,
                artifact_page_batch=PAGE_BATCH, policy_version=POLICY_VERSION,
                capability_digest=capability_digest(installed), capabilities=installed, pages=pages, expected_pages=len(pages),
                page_digest=digest([page["page_digest"] for page in pages]))
    plan["plan_digest"] = digest(plan)
    return plan
