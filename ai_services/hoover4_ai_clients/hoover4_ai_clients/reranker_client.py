"""Reranking client for document relevance scoring."""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class Hoover4RerankClient:
    """Client for document reranking API."""

    def __init__(self, base_url: str = "http://localhost:8000/v1"):
        """Initialize the reranker client."""
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        logger.info(f"Initialized reranker client for {base_url}")

    def rerank_documents(
        self,
        query: str,
        documents: list[str],
        top_k: Optional[int] = None,
        return_documents: bool = True
    ) -> list[tuple[int, float, Optional[str]]]:
        """
        Rerank documents based on relevance to a query.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_k: Number of top documents to return (all if None)
            return_documents: Whether to include document text in results

        Returns:
            List of tuples: (original_index, relevance_score, document_text)
            Sorted by relevance score in descending order

        Raises:
            requests.exceptions.RequestException: If the API request fails
        """
        try:
            logger.debug(f"Reranking {len(documents)} documents for query: '{query[:50]}...'")

            # Handle empty query by returning documents in original order with neutral scores
            if not query or not query.strip():
                logger.debug("Empty query provided, returning documents in original order")
                results = []
                for i, doc in enumerate(documents):
                    if top_k is not None and i >= top_k:
                        break
                    results.append((
                        i,
                        0.5,  # Neutral relevance score for empty query
                        doc if return_documents else None
                    ))
                return results

            response = self.session.post(
                f"{self.base_url}/rerank",
                json={
                    "query": query,
                    "documents": documents,
                    "top_k": top_k,
                    "return_documents": return_documents
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            response.raise_for_status()

            data = response.json()

            # Convert response to tuples
            results = []
            for item in data["data"]:
                results.append((
                    item["index"],
                    item["relevance_score"],
                    item.get("document") if return_documents else None
                ))

            logger.debug(f"Successfully reranked {len(documents)} documents, returning {len(results)} results")
            return results

        except requests.exceptions.RequestException as e:
            logger.error(f"Error reranking documents: {e}")
            raise
