"""Hoover4 AI Clients Package.

This package contains all the client modules for connecting to the Hoover4 AI server.
It provides clients for embeddings, NER, reranking, and vector storage operations.
"""

from .data_models import (
    EmbeddingResult,
    EntityExtractionResult,
    RerankResult,
)
from .embeddings_client import Hoover4EmbeddingsClient
from .milvus_client import Hoover4MilvusVectorStore, Hoover4MilvusRetriever
from .ner_client import Hoover4NERClient
from .reranker_client import Hoover4RerankClient

__version__ = "1.0.0"

__all__ = [
    "Hoover4EmbeddingsClient",
    "Hoover4NERClient",
    "Hoover4RerankClient",
    "Hoover4MilvusVectorStore",
    "Hoover4MilvusRetriever",
    "EntityExtractionResult",
    "RerankResult",
    "EmbeddingResult",
]
