"""Integration tests for Hoover4EmbeddingsClient against live server."""

import time

import pytest
import requests


@pytest.mark.integration
@pytest.mark.embeddings
class TestEmbeddingsIntegration:
    """Integration tests for embeddings client with live server."""

    def test_embeddings_client_initialization(self, embeddings_client):
        """Test embeddings client initialization."""
        assert embeddings_client.base_url is not None
        assert embeddings_client.model is not None
        assert embeddings_client.timeout > 0
        assert embeddings_client.max_retries > 0

    def test_health_check(self, embeddings_client, server_health_check):
        """Test embeddings client health check."""
        if not server_health_check:
            pytest.skip("Server not available")

        is_healthy = embeddings_client.health_check()
        assert is_healthy is True

    def test_embed_single_query(self, embeddings_client, server_health_check):
        """Test embedding a single query."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "This is a test query for embedding"
        embedding = embeddings_client.embed_query(query)

        assert isinstance(embedding, list)
        assert len(embedding) > 0
        assert all(isinstance(x, float) for x in embedding)
        assert len(embedding) == 1024  # Expected dimension for multilingual-e5-large-instruct

    def test_embed_multiple_documents(self, embeddings_client, server_health_check):
        """Test embedding multiple documents."""
        if not server_health_check:
            pytest.skip("Server not available")

        documents = [
            "Apple Inc. was founded by Steve Jobs in Cupertino, California.",
            "Microsoft Corporation is headquartered in Redmond, Washington.",
            "Google LLC is based in Mountain View, California."
        ]

        embeddings = embeddings_client.embed_documents(documents)

        assert isinstance(embeddings, list)
        assert len(embeddings) == len(documents)

        for embedding in embeddings:
            assert isinstance(embedding, list)
            assert len(embedding) == 1024
            assert all(isinstance(x, float) for x in embedding)

    def test_embed_empty_query_raises_error(self, embeddings_client, server_health_check):
        """Test that embedding empty query raises error."""
        if not server_health_check:
            pytest.skip("Server not available")

        with pytest.raises(ValueError, match="Text cannot be empty"):
            embeddings_client.embed_query("")

        with pytest.raises(ValueError, match="Text cannot be empty"):
            embeddings_client.embed_query("   ")

    def test_embed_empty_documents_list(self, embeddings_client, server_health_check):
        """Test that embedding empty documents list returns empty list."""
        if not server_health_check:
            pytest.skip("Server not available")

        embeddings = embeddings_client.embed_documents([])
        assert embeddings == []

    def test_embed_large_document(self, embeddings_client, server_health_check):
        """Test embedding a large document."""
        if not server_health_check:
            pytest.skip("Server not available")

        # Create a large document (should be within model limits)
        large_document = "This is a test document. " * 100  # ~2500 characters

        embedding = embeddings_client.embed_query(large_document)

        assert isinstance(embedding, list)
        assert len(embedding) == 1024
        assert all(isinstance(x, float) for x in embedding)

    def test_embed_multilingual_text(self, embeddings_client, server_health_check):
        """Test embedding multilingual text."""
        if not server_health_check:
            pytest.skip("Server not available")

        multilingual_texts = [
            "Hello, how are you?",  # English
            "Hola, ¿cómo estás?",  # Spanish
            "Bonjour, comment allez-vous?",  # French
            "Hallo, wie geht es dir?",  # German
            "こんにちは、元気ですか？",  # Japanese
        ]

        embeddings = embeddings_client.embed_documents(multilingual_texts)

        assert len(embeddings) == len(multilingual_texts)
        for embedding in embeddings:
            assert len(embedding) == 1024
            assert all(isinstance(x, float) for x in embedding)

    def test_embed_with_different_task_descriptions(self, embeddings_client, server_health_check):
        """Test embedding with different task descriptions."""
        if not server_health_check:
            pytest.skip("Server not available")

        # Test with search task description
        search_client = embeddings_client
        search_client.task_description = "Given a web search query, retrieve relevant passages that answer the query"

        search_query = "What is machine learning?"
        search_embedding = search_client.embed_query(search_query)

        # Test with classification task description
        classification_client = embeddings_client
        classification_client.task_description = "Classify the following text into categories"

        classification_text = "This is a positive review of the product"
        classification_embedding = classification_client.embed_query(classification_text)

        # Both should work and produce embeddings
        assert len(search_embedding) == 1024
        assert len(classification_embedding) == 1024

        # Embeddings should be different due to different task descriptions
        assert search_embedding != classification_embedding

    def test_embedding_consistency(self, embeddings_client, server_health_check):
        """Test that same input produces consistent embeddings."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "Consistency test query"

        # Get embedding twice
        embedding1 = embeddings_client.embed_query(query)
        time.sleep(0.1)  # Small delay
        embedding2 = embeddings_client.embed_query(query)

        # Should be identical (deterministic model)
        assert embedding1 == embedding2

    def test_embedding_similarity(self, embeddings_client, server_health_check):
        """Test that similar texts produce similar embeddings."""
        if not server_health_check:
            pytest.skip("Server not available")

        similar_texts = [
            "The cat is sleeping on the couch",
            "A cat is resting on the sofa",
            "The feline is napping on the furniture"
        ]

        different_text = "The weather is sunny today"

        embeddings = embeddings_client.embed_documents(similar_texts + [different_text])

        # Calculate cosine similarity between embeddings
        def cosine_similarity(a, b):
            import math
            dot_product = sum(x * y for x, y in zip(a, b))
            magnitude_a = math.sqrt(sum(x * x for x in a))
            magnitude_b = math.sqrt(sum(x * x for x in b))
            return dot_product / (magnitude_a * magnitude_b)

        # Similar texts should have high similarity
        sim_01 = cosine_similarity(embeddings[0], embeddings[1])
        sim_02 = cosine_similarity(embeddings[0], embeddings[2])
        sim_12 = cosine_similarity(embeddings[1], embeddings[2])

        # Different text should have lower similarity
        sim_03 = cosine_similarity(embeddings[0], embeddings[3])
        sim_13 = cosine_similarity(embeddings[1], embeddings[3])
        sim_23 = cosine_similarity(embeddings[2], embeddings[3])

        # Similar texts should have higher similarity than different text
        assert sim_01 > sim_03
        assert sim_02 > sim_03
        assert sim_12 > sim_13
        assert sim_12 > sim_23

        # Similarity should be reasonably high for similar texts
        assert sim_01 > 0.7
        assert sim_02 > 0.7
        assert sim_12 > 0.7

    def test_retry_mechanism(self, embeddings_client, server_health_check):
        """Test retry mechanism with short timeout."""
        if not server_health_check:
            pytest.skip("Server not available")

        # Create client with very short timeout to trigger retries
        client = embeddings_client
        client.timeout = 0.001  # Very short timeout
        client.max_retries = 2

        # This should fail after retries due to unrealistic timeout
        query = "Test retry mechanism"
        with pytest.raises(requests.exceptions.ReadTimeout):
            embedding = client.embed_query(query)

    def test_batch_processing_performance(self, embeddings_client, server_health_check):
        """Test batch processing performance."""
        if not server_health_check:
            pytest.skip("Server not available")

        # Create a batch of documents
        batch_size = 10
        documents = [f"Document {i} for batch processing test" for i in range(batch_size)]

        start_time = time.time()
        embeddings = embeddings_client.embed_documents(documents)
        end_time = time.time()

        processing_time = end_time - start_time

        assert len(embeddings) == batch_size
        assert processing_time < 10.0  # Should complete within 10 seconds

        # Calculate throughput
        throughput = batch_size / processing_time
        print(f"Batch processing throughput: {throughput:.2f} docs/sec")

        # Should be reasonably fast
        assert throughput > 1.0  # At least 1 document per second
