"""Named Entity Recognition client."""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class Hoover4NERClient:
    """Client for the NER (Named Entity Recognition) API."""

    def __init__(self, base_url: str = "http://localhost:8000/v1"):
        """Initialize the NER client."""
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        logger.info(f"Initialized NER client for {base_url}")

    def extract_entities(
        self,
        texts: list[str],
        entity_types: Optional[list[str]] = None
    ) -> list[dict[str, list[str]]]:
        """
        Extract named entities from texts.

        Args:
            texts: List of texts to extract entities from
            entity_types: Optional list of entity types to filter for

        Returns:
            List of dictionaries with entity types as keys and lists of entity texts as values.
            For example: [{"PER": ["John Doe"], "ORG": ["Apple Inc."], "LOC": ["California"], "MISC": []}]

        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        try:
            logger.debug(f"Extracting entities from {len(texts)} texts")

            # Handle empty texts by returning empty results with proper structure
            if not texts or all(not text.strip() for text in texts):
                logger.debug("No non-empty texts provided, returning empty results")
                return [{"PER": [], "ORG": [], "LOC": [], "MISC": []} for _ in texts] if texts else []

            response = self.session.post(
                f"{self.base_url}/extract-entities",
                json={
                    "input": texts,
                    "include_confidence": False,
                    "entity_types": entity_types
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()

            data = response.json()
            entities_by_text = self._group_entities_by_text(data["data"], len(texts))

            logger.debug(f"Successfully extracted entities from {len(texts)} texts")
            return entities_by_text

        except requests.exceptions.RequestException as e:
            logger.error(f"Error extracting entities: {e}")
            raise

    def _group_entities_by_text(self, entities: list[dict], num_texts: int) -> list[dict[str, list[str]]]:
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
