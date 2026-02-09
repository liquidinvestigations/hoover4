"""NER client helper for extracting entities from text via HTTP."""

import os
import logging
logger = logging.getLogger(__name__)

SERVERS = [
    os.getenv('NER_URL')
]

def extract_ner_from_texts(texts: list[str]) -> list[dict[str, list[str]]]:
    import random
    server_url = random.choice(SERVERS) + '/extract-entities'
    import requests
    response = requests.post(server_url, json={
            "input": texts,
            "include_confidence": False,
            "entity_types": None,
        },
        headers={"Content-Type": "application/json"},
        timeout=3000,
    )

    response.raise_for_status()
    data = response.json()
    entities_by_text = _group_entities_by_text(data["data"], len(texts))
    logger.debug(f"Successfully extracted entities from {len(texts)} texts")
    return entities_by_text


def _group_entities_by_text(entities: list[dict], num_texts: int) -> list[dict[str, list[str]]]:
    """Group entities by text index and entity type."""
    # Initialize result for each text
    result = []
    for _ in range(num_texts):
        result.append({"PER": [], "ORG": [], "LOC": [], "MISC": []})

    # Group entities
    for entity in entities:
        text_index = entity.get("text_index", 0) if num_texts > 1 else 0
        if text_index < len(result):
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