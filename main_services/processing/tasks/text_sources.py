"""The `extracted_by` naming convention, in one place.

`extracted_by` is not an internal key: it reaches the user as the label on the document
viewer's source selector, and it is the join key between `text_content`, `entity_hit`,
`nlp_processed`, `text_chunks` and `text_chunk_vectors`. Both runtimes therefore need to
agree on it, and both need to be able to take one apart again for display.

The Rust half lives in `website/common/src/document_sources.rs`. The duplication is
deliberate, like `collectionname` validation: neither runtime may depend on the other
being right, and `tests/unit/test_text_sources.py` plus a cargo test keep the two
conventions from drifting.

    native:       pdftotext | extractous | office_xml | email_parser | raw_text | qpdf
    OCR variants: ocr_<engine>_<languages>   e.g. ocr_tesseract_eng+ron, ocr_easyocr_en

Language codes are joined with `+`, which is Tesseract's own convention, for both
engines. Nothing else in the string may contain `_` before the engine name, which is why
the parser splits from the left exactly twice.

`ner_reads_variant` is the one rule here with no Rust counterpart: which variants the NLP
stage reads is a pipeline decision and nothing in the website depends on it.
"""

from typing import Collection, List, Optional, Tuple

#: The file's own bytes, decoded and segmented, with nothing interpreted. For a mail file
#: that is the MIME envelope: header block, boundaries, base64 attachment payloads.
RAW_TEXT = "raw_text"

#: The `text/plain` parts of a mail file, decoded. Same document, none of the envelope.
EMAIL_PARSER = "email_parser"

#: Engine identifiers. These appear inside `extracted_by`, so changing one invalidates
#: every stored row that used it.
ENGINE_TESSERACT = "tesseract"
ENGINE_EASYOCR = "easyocr"
OCR_ENGINES = (ENGINE_TESSERACT, ENGINE_EASYOCR)

#: Prefix marking an OCR variant. Native extractors have no prefix.
OCR_PREFIX = "ocr_"


def ner_reads_variant(extracted_by: str, variants_present: Collection[str]) -> bool:
    """Is this text variant worth running named-entity recognition over?

    Every variant is stored, indexed and offered in the viewer's source selector; this
    decides only which of them the NLP stage reads.

    A mail file that parsed produces both `raw_text` (the MIME envelope: header names,
    boundaries, base64 payloads) and `email_parser` (the body alone). They are the same
    document, so NER over both doubles the work and the entities of the second copy are
    the envelope -- `Content-Transfer-Encoding`, `Message-ID`, every `X-` header the
    mailer wrote -- which then outnumber every real entity in the facet.

    The predicate is structural rather than a file-type check: a file HAS a parsed body,
    or it does not. Mail whose only body part is HTML produces no `email_parser` rows, and
    that file keeps its `raw_text` entities rather than silently losing all of them --
    which is also why the stop-list exists, since those envelopes still reach the model.
    """
    if extracted_by == RAW_TEXT and EMAIL_PARSER in variants_present:
        return False
    return True


def ocr_extracted_by(engine: str, languages: str) -> str:
    """Build the `extracted_by` label for one OCR pass.

    ``languages`` is the `+`-joined code set the pass actually ran with -- one string
    for Tesseract (which takes `eng+ron` in a single pass and picks per region) and one
    per script group for EasyOCR (which cannot mix scripts in one Reader).
    """
    if engine not in OCR_ENGINES:
        raise ValueError(f"unknown OCR engine {engine!r}, expected one of {OCR_ENGINES}")
    if not languages:
        raise ValueError("OCR languages must not be empty: the label is a key, not a hint")
    return f"{OCR_PREFIX}{engine}_{languages}"


def parse_ocr_extracted_by(extracted_by: str) -> Optional[Tuple[str, str]]:
    """Return ``(engine, languages)``, or ``None`` for a native extractor.

    Splits from the left exactly twice so a `+`-joined language set containing anything
    else stays intact in the third field.
    """
    if not extracted_by.startswith(OCR_PREFIX):
        return None
    parts = extracted_by.split("_", 2)
    if len(parts) != 3 or parts[0] != "ocr":
        return None
    engine, languages = parts[1], parts[2]
    if engine not in OCR_ENGINES or not languages:
        return None
    return engine, languages


def split_languages(languages: str) -> List[str]:
    """`'eng+ron'` -> `['eng', 'ron']`, tolerant of spacing and empty entries."""
    return [part.strip() for part in (languages or "").split("+") if part.strip()]


def join_languages(codes) -> str:
    """Inverse of :func:`split_languages`, with duplicates removed and order kept.

    Order is preserved rather than sorted because Tesseract treats the first language as
    the primary one, so `eng+ron` and `ron+eng` are genuinely different requests -- and
    they are genuinely different `extracted_by` values as a result.
    """
    seen = []
    for code in codes:
        code = (code or "").strip()
        if code and code not in seen:
            seen.append(code)
    return "+".join(seen)


#: EasyOCR builds one model per Reader and cannot mix arbitrary scripts in it. Languages
#: are therefore grouped by script, one pass per group, and each pass is its own variant.
#:
#: English is compatible with every latin-script set and is silently accepted by the
#: other groups too, which is why it is not listed here: it never forces a group of its
#: own. The lists are not exhaustive -- an unknown code falls into its own group, which
#: costs an extra pass but never produces a Reader EasyOCR refuses to build.
_EASYOCR_SCRIPT_GROUPS = {
    "cyrillic": ("ru", "rs_cyrillic", "be", "bg", "uk", "mn"),
    "arabic": ("ar", "fa", "ug", "ur"),
    "devanagari": ("hi", "mr", "ne", "bh", "mai", "ang", "bho", "sa", "new", "gom"),
    "chinese_sim": ("ch_sim",),
    "chinese_tra": ("ch_tra",),
    "japanese": ("ja",),
    "korean": ("ko",),
    "tamil": ("ta",),
    "telugu": ("te",),
    "kannada": ("kn",),
    "bengali": ("bn", "as"),
    "thai": ("th",),
}


def easyocr_language_groups(languages: str) -> List[str]:
    """Split a requested language set into script-compatible EasyOCR passes.

    Returns a list of `+`-joined language strings, one per pass, each of which becomes
    its own `extracted_by` variant and its own set of downstream NER, chunk, embed and
    index rows.

    **This is the main cost lever in the pipeline.** Adding a Tesseract language is
    nearly free -- one extra pass over the dataset. Adding an EasyOCR language in a new
    script adds a full pass *and* a complete set of downstream rows for it. The admin
    form says so for that reason.
    """
    codes = split_languages(languages)
    if not codes:
        return []

    script_of = {}
    for script, members in _EASYOCR_SCRIPT_GROUPS.items():
        for code in members:
            script_of[code] = script

    groups: dict = {}
    order: List[str] = []
    for code in codes:
        # Unknown codes get a group of their own rather than being lumped into latin:
        # a wrong guess produces a Reader EasyOCR refuses to build, which fails the whole
        # pass, while an extra group only costs time.
        script = script_of.get(code, "latin" if code == "en" else f"unknown:{code}")
        if script not in groups:
            groups[script] = []
            order.append(script)
        groups[script].append(code)

    # English rides along with every group it is compatible with rather than forming a
    # pass of its own, because EasyOCR accepts 'en' alongside any single other script and
    # recognition quality improves when it is present.
    if "latin" in groups and len(order) > 1:
        latin = groups.pop("latin")
        order.remove("latin")
        for script in order:
            groups[script] = latin + groups[script]

    return [join_languages(groups[script]) for script in order]
