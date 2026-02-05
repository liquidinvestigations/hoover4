"""Data models for Hoover4 AI clients."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class EntityExtractionResult:
    """Result of entity extraction from text."""

    text: str
    entities: dict[str, list[str]]
    confidence_scores: Optional[dict[str, list[float]]] = None


@dataclass
class RerankResult:
    """Result of document reranking."""

    index: int
    relevance_score: float
    document: Optional[str] = None


@dataclass
class EmbeddingResult:
    """Result of text embedding."""

    text: str
    embedding: list[float]
    model: str
    usage: Optional[dict[str, int]] = None
