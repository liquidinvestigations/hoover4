"""NER client: extract entities from text over HTTP, with a CPU fallback.

The endpoint list is ordered -- GPU first, CPU twin second -- and
``tasks.remote`` decides which one actually serves the request. The caller gets
the model identifier of whichever one did, because that is what has to be
written to ``nlp_processed.nlp_model``: under fallback the configured provider
and the serving provider differ, and that difference is the only evidence an
outage happened at all.
"""

import logging
import os

from tasks.remote import post_json

logger = logging.getLogger(__name__)

# Model identifier per provider. This is written to nlp_processed.nlp_model and
# read back by the left-anti join that makes the stage re-runnable, so changing
# a value here reprocesses every segment under the new name.
NLP_MODEL_BY_PROVIDER = {
    "gpu": "ner-gpu-xlmr",
    "spacy": "ner-spacy-xx",
}


def _endpoints() -> list[tuple[str, str]]:
    """Ordered ``(provider, url)`` candidates, primary first.

    ``NER_URL_FALLBACK`` is empty until Part 2 builds the spacy twin. That is
    deliberate: with no twin, ``post_json`` raises RemoteUnavailable naming the
    unreachable GPU url within the connect timeout instead of stalling.
    """
    primary = (os.getenv("NER_URL") or "").strip().rstrip("/")
    fallback = (os.getenv("NER_URL_FALLBACK") or "").strip().rstrip("/")
    primary_provider = (os.getenv("NER_PROVIDER") or "gpu").strip() or "gpu"
    if primary_provider == "both":
        primary_provider = "gpu"
    candidates = [(primary_provider, f"{primary}/extract-entities" if primary else "")]
    if fallback:
        candidates.append(("spacy", f"{fallback}/extract-entities"))
    return candidates


def extract_ner_from_texts(texts: list[str]) -> tuple[list[dict[str, list[str]]], str]:
    """Return per-text entities and the ``nlp_model`` of the provider that served."""
    result = post_json(_endpoints(), {
        "input": texts,
        "include_confidence": False,
        "entity_types": None,
    }, service="ner")
    entities_by_text = _group_entities_by_text(result.data["data"], len(texts))
    nlp_model = NLP_MODEL_BY_PROVIDER.get(result.provider, f"ner-{result.provider}")
    logger.debug("extracted entities from %d texts via %s", len(texts), nlp_model)
    return entities_by_text, nlp_model


def _group_entities_by_text(entities: list[dict], num_texts: int) -> list[dict[str, list[str]]]:
    """Group entities by text index and entity type."""
    # Initialize result for each text
    result = []
    for _ in range(num_texts):
        result.append({"PER": [], "ORG": [], "LOC": [], "MISC": []})

    # Group entities
    for entity in entities:
        text_index = entity.get("text_index", 0) if num_texts > 1 else 0
        # Bounds-check both directions: a negative index would otherwise pass
        # `text_index < len(result)` and silently write into the wrong text.
        if isinstance(text_index, int) and 0 <= text_index < len(result):
            entity_type = entity["label"]
            entity_text = entity["text"]

            # Map entity types (CoNLL-03 uses different labels)
            if entity_type == "PER":
                result[text_index]["PER"].append(entity_text)
            elif entity_type == "ORG":
                result[text_index]["ORG"].append(entity_text)
            elif entity_type in ["LOC", "GPE"]:  # GPE = Geopolitical entity
                result[text_index]["LOC"].append(entity_text)
            elif entity_type == "MISC":
                result[text_index]["MISC"].append(entity_text)

    return result