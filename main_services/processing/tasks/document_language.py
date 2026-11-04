"""Detect one language for each complete text source."""

from functools import lru_cache
from pathlib import Path
import logging

log = logging.getLogger(__name__)
MODEL_PATH = Path(__file__).resolve().parents[1] / "models/lid.176.ftz"


@lru_cache(maxsize=1)
def language_model():
    import fasttext
    return fasttext.load_model(str(MODEL_PATH))


#: The language of a Tesseract script model with one language in practice. These scripts
#: need no reading and no language model.
SINGLE_LANGUAGE_SCRIPTS = {
    "Armenian": "hy", "Canadian_Aboriginal": "iu", "Cherokee": "chr", "Georgian": "ka", "Greek": "el",
    "Gujarati": "gu", "Gurmukhi": "pa", "HanS": "zh", "HanT": "zh", "Hangul": "ko", "Japanese": "ja",
    "Kannada": "kn", "Khmer": "km", "Lao": "lo", "Malayalam": "ml", "Myanmar": "my", "Oriya": "or",
    "Sinhala": "si", "Syriac": "syr", "Tamil": "ta", "Telugu": "te", "Thaana": "dv", "Thai": "th",
    "Vietnamese": "vi",
}
#: The letters that a sample of OCR detection needs. It holds a few lines, so the limit is
#: lower than the limit of a complete text source.
DETECTED_SAMPLE_LETTERS = 20


def detect_language(text: str, min_letters: int = 200) -> str:
    sample = text[:4000]
    if sum(character.isalpha() for character in sample) < min_letters:
        return "und"
    try:
        labels, scores = language_model().predict(sample.replace("\n", " ").replace("\r", " "), k=1)
        return labels[0].removeprefix("__label__") if float(scores[0]) >= 0.5 else "und"
    except Exception:
        log.exception("Document language detection failed.")
        return "und"


def detected_language(model: str, text: str) -> str:
    """The language of one OCR detection result from its script model and its sample."""
    return SINGLE_LANGUAGE_SCRIPTS.get(model) or detect_language(text, DETECTED_SAMPLE_LETTERS)


def source_language(pages) -> str:
    parts = []
    remaining = 4000
    for _, text in pages:
        part = str(text or "")[:remaining]
        parts.append(part)
        remaining -= len(part)
        if remaining == 0:
            break
    return detect_language("".join(parts))
