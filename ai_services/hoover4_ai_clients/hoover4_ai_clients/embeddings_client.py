#!/usr/bin/env python3
"""
Custom embeddings client that implements the LangChain Embeddings interface.
This client connects to the local embedding server instead of using OpenAI.
"""

import logging

import requests
from langchain_core.embeddings import Embeddings
from langchain_core.runnables.config import run_in_executor

logger = logging.getLogger(__name__)


class Hoover4EmbeddingsClient(Embeddings):
    """
    Hoover4 RAG embeddings client that implements the LangChain Embeddings interface.
    Connects to a local embedding server instead of using OpenAI.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        model: str = "intfloat/multilingual-e5-large-instruct",
        task_description: str = "Given a web search query, retrieve relevant passages that answer the query",
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Initialize the Hoover4 RAG embeddings client.

        Args:
            base_url: Base URL of the embedding server
            model: Model name to use for embeddings
            task_description: Task description for the embedding model
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
        """
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.task_description = task_description
        self.timeout = timeout
        self.max_retries = max_retries

        # Ensure the base URL is properly formatted
        if not self.base_url.startswith('http'):
            self.base_url = f"http://{self.base_url}"

    def _make_request(self, payload: dict) -> dict:
        """
        Make a request to the embedding server with retry logic.

        Args:
            payload: Request payload

        Returns:
            Response data from the server

        Raises:
            requests.RequestException: If the request fails after all retries
        """
        url = f"{self.base_url}/embeddings"

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    timeout=self.timeout,
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                logger.warning(f"Request attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    logger.error(f"All {self.max_retries} attempts failed for embedding request")
                    raise
                # Wait before retrying (exponential backoff)
                import time
                time.sleep(2 ** attempt)


    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of documents.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (each embedding is a list of floats)
        """
        if not texts:
            return []

        # Prepare the request payload
        payload = {
            "input": texts,
            "model": self.model,
            "encoding_format": "float",
            "task_description": self.task_description
        }

        try:
            response = self._make_request(payload)

            # Extract embeddings from response
            embeddings = []
            for item in response.get("data", []):
                if "embedding" in item:
                    embeddings.append(item["embedding"])
                else:
                    logger.error(f"Missing embedding in response item: {item}")
                    raise ValueError("Invalid response format from embedding server")

            if len(embeddings) != len(texts):
                raise ValueError(f"Expected {len(texts)} embeddings, got {len(embeddings)}")

            return embeddings

        except Exception as e:
            logger.error(f"Error embedding documents: {e}")
            raise

    def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query text.

        Args:
            text: Text to embed

        Returns:
            Embedding as a list of floats
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        # Prepare the request payload
        payload = {
            "input": text,
            "model": self.model,
            "encoding_format": "float",
            "task_description": self.task_description
        }

        try:
            response = self._make_request(payload)

            # Extract embedding from response
            data = response.get("data", [])
            if not data:
                raise ValueError("No embedding data in response")

            embedding = data[0].get("embedding")
            if not embedding:
                raise ValueError("Missing embedding in response")

            return embedding

        except Exception as e:
            logger.error(f"Error embedding query: {e}")
            raise

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Asynchronous version of embed_documents.

        Args:
            texts: List of texts to embed

        Returns:
            List of embeddings (each embedding is a list of floats)
        """
        return await run_in_executor(None, self.embed_documents, texts)

    async def aembed_query(self, text: str) -> list[float]:
        """
        Asynchronous version of embed_query.

        Args:
            text: Text to embed

        Returns:
            Embedding as a list of floats
        """
        return await run_in_executor(None, self.embed_query, text)

    def health_check(self) -> bool:
        """
        Check if the embedding server is healthy.

        Returns:
            True if the server is healthy, False otherwise
        """
        try:
            # Try to embed a simple test query
            test_embedding = self.embed_query("health check")
            return len(test_embedding) > 0
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False
