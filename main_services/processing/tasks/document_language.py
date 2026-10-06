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


def detect_language(text: str) -> str:
    sample = text[:4000]
    if sum(character.isalpha() for character in sample) < 200:
        return "und"
    try:
        labels, scores = language_model().predict(sample.replace("\n", " ").replace("\r", " "), k=1)
        return labels[0].removeprefix("__label__") if float(scores[0]) >= 0.5 else "und"
    except Exception:
        log.exception("Document language detection failed.")
        return "und"


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
