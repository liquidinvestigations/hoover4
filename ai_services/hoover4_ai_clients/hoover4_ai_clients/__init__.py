"""Hoover4 AI Clients Package.

This package contains all the client modules for connecting to the Hoover4 AI server.
It provides clients for embeddings, NER and reranking.

The Milvus vector-store client was removed with the rest of the Milvus tier: nothing in
the pipeline ever wrote vectors, so it had no index to talk to. See
`ai_services/README.md` for what a vector stage would have to build first.
"""

from .data_models import (
    EmbeddingResult,
    EntityExtractionResult,
    RerankResult,
)
from .embeddings_client import Hoover4EmbeddingsClient
from .ner_client import Hoover4NERClient
from .reranker_client import Hoover4RerankClient

__version__ = "1.0.0"

__all__ = [
    "Hoover4EmbeddingsClient",
    "Hoover4NERClient",
    "Hoover4RerankClient",
    "EntityExtractionResult",
    "RerankResult",
    "EmbeddingResult",
]
