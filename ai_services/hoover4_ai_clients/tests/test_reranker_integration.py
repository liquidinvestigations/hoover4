"""Integration tests for Hoover4RerankClient against live server."""

import pytest


@pytest.mark.integration
@pytest.mark.reranker
class TestRerankerIntegration:
    """Integration tests for reranker client with live server."""

    def test_reranker_client_initialization(self, reranker_client):
        """Test reranker client initialization."""
        assert reranker_client.base_url is not None
        assert reranker_client.session is not None

    def test_rerank_documents_basic(self, reranker_client, server_health_check):
        """Test basic document reranking."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "What are the benefits of exercise?"
        documents = [
            "Exercise helps improve cardiovascular health and reduces stress.",
            "Cooking is a great way to save money and eat healthier.",
            "Regular physical activity boosts mental health and energy levels.",
            "Reading books can expand your knowledge and vocabulary."
        ]

        results = reranker_client.rerank_documents(query, documents)

        assert isinstance(results, list)
        assert len(results) == len(documents)

        # Check result format: (original_index, relevance_score, document_text)
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 3

            original_index, relevance_score, document_text = result
            assert isinstance(original_index, int)
            assert 0 <= original_index < len(documents)
            assert isinstance(relevance_score, float)
            assert isinstance(document_text, str)
            assert document_text == documents[original_index]

        # Results should be sorted by relevance score (descending)
        scores = [result[1] for result in results]
        assert scores == sorted(scores, reverse=True)

        # Exercise-related documents should have higher scores
        exercise_docs = [i for i, doc in enumerate(documents) if "exercise" in doc.lower() or "physical activity" in doc.lower()]
        non_exercise_docs = [i for i, doc in enumerate(documents) if i not in exercise_docs]

        if exercise_docs and non_exercise_docs:
            # Find the highest score for exercise docs and non-exercise docs
            exercise_scores = [result[1] for result in results if result[0] in exercise_docs]
            non_exercise_scores = [result[1] for result in results if result[0] in non_exercise_docs]

            assert max(exercise_scores) > max(non_exercise_scores)

    def test_rerank_documents_with_top_k(self, reranker_client, server_health_check):
        """Test document reranking with top_k parameter."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "machine learning algorithms"
        documents = [
            "Machine learning is a subset of artificial intelligence.",
            "Deep learning uses neural networks with multiple layers.",
            "Supervised learning uses labeled training data.",
            "Cooking pasta requires boiling water and adding salt.",
            "Unsupervised learning finds patterns in unlabeled data."
        ]

        top_k = 3
        results = reranker_client.rerank_documents(query, documents, top_k=top_k)

        assert len(results) == top_k

        # All results should be sorted by relevance score
        scores = [result[1] for result in results]
        assert scores == sorted(scores, reverse=True)

        # Should return the most relevant documents
        ml_docs = [i for i, doc in enumerate(documents) if any(term in doc.lower() for term in ["machine learning", "deep learning", "neural", "supervised", "unsupervised"])]
        cooking_docs = [i for i, doc in enumerate(documents) if "cooking" in doc.lower()]

        if ml_docs and cooking_docs:
            # ML-related documents should be in top results
            top_indices = [result[0] for result in results]
            assert any(idx in ml_docs for idx in top_indices)

    def test_rerank_documents_without_return_documents(self, reranker_client, server_health_check):
        """Test document reranking without returning document text."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "climate change effects"
        documents = [
            "Climate change is causing rising sea levels and extreme weather.",
            "Global warming affects ecosystems and biodiversity.",
            "Renewable energy sources can help reduce carbon emissions.",
            "Pizza is a popular Italian dish with various toppings."
        ]

        results = reranker_client.rerank_documents(query, documents, return_documents=False)

        assert len(results) == len(documents)

        # Check result format: (original_index, relevance_score, None)
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 3

            original_index, relevance_score, document_text = result
            assert isinstance(original_index, int)
            assert 0 <= original_index < len(documents)
            assert isinstance(relevance_score, float)
            assert document_text is None

    def test_rerank_documents_empty_query(self, reranker_client, server_health_check):
        """Test reranking with empty query."""
        if not server_health_check:
            pytest.skip("Server not available")

        documents = ["Document 1", "Document 2", "Document 3"]

        # Empty query should still work but may not provide meaningful ranking
        results = reranker_client.rerank_documents("", documents)

        assert len(results) == len(documents)
        assert all(isinstance(result, tuple) and len(result) == 3 for result in results)

    def test_rerank_documents_single_document(self, reranker_client, server_health_check):
        """Test reranking with single document."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "artificial intelligence"
        documents = ["AI is transforming various industries and applications."]

        results = reranker_client.rerank_documents(query, documents)

        assert len(results) == 1
        result = results[0]

        assert isinstance(result, tuple)
        assert len(result) == 3
        assert result[0] == 0  # original_index should be 0
        assert isinstance(result[1], float)  # relevance_score
        assert result[2] == documents[0]  # document_text

    def test_rerank_documents_large_batch(self, reranker_client, server_health_check):
        """Test reranking with large batch of documents."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "technology innovation"

        # Create a large batch of documents
        documents = [
            f"Technology innovation in field {i} is advancing rapidly."
            for i in range(50)
        ]

        results = reranker_client.rerank_documents(query, documents)

        assert len(results) == len(documents)

        # All results should be properly formatted
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 3
            assert 0 <= result[0] < len(documents)

    def test_rerank_documents_consistency(self, reranker_client, server_health_check):
        """Test that same input produces consistent reranking results."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "sustainable energy solutions"
        documents = [
            "Solar panels convert sunlight into electricity.",
            "Wind turbines generate clean energy from wind.",
            "Hydroelectric dams produce renewable power.",
            "Fossil fuels are non-renewable energy sources."
        ]

        # Rerank twice
        results1 = reranker_client.rerank_documents(query, documents)
        results2 = reranker_client.rerank_documents(query, documents)

        # Results should be identical
        assert results1 == results2

    def test_rerank_documents_relevance_ordering(self, reranker_client, server_health_check):
        """Test that reranking produces meaningful relevance ordering."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "python programming language"
        documents = [
            "Python is a high-level programming language.",  # Highly relevant
            "Java is another popular programming language.",  # Somewhat relevant
            "Cooking requires following recipes carefully.",  # Not relevant
            "Python has a simple syntax and is easy to learn.",  # Highly relevant
            "Gardening involves planting and caring for plants."  # Not relevant
        ]

        results = reranker_client.rerank_documents(query, documents)

        # Find the indices of Python-related documents
        python_docs = [i for i, doc in enumerate(documents) if "python" in doc.lower()]
        non_python_docs = [i for i, doc in enumerate(documents) if "python" not in doc.lower()]

        if python_docs and non_python_docs:
            # Python-related documents should have higher scores
            python_scores = [result[1] for result in results if result[0] in python_docs]
            non_python_scores = [result[1] for result in results if result[0] in non_python_docs]

            assert max(python_scores) > max(non_python_scores)

    def test_rerank_documents_special_characters(self, reranker_client, server_health_check):
        """Test reranking with documents containing special characters."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "data analysis & visualization"
        documents = [
            "Data analysis involves processing and interpreting data.",
            "Visualization tools help present data in charts & graphs.",
            "Statistical methods are used for data analysis.",
            "Machine learning algorithms can analyze large datasets."
        ]

        results = reranker_client.rerank_documents(query, documents)

        assert len(results) == len(documents)

        # All results should be properly formatted
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 3
            assert 0 <= result[0] < len(documents)
            assert result[2] == documents[result[0]]

    def test_rerank_documents_multilingual(self, reranker_client, server_health_check):
        """Test reranking with multilingual documents."""
        if not server_health_check:
            pytest.skip("Server not available")

        query = "artificial intelligence"
        documents = [
            "Artificial intelligence is transforming industries.",  # English
            "L'intelligence artificielle transforme les industries.",  # French
            "La inteligencia artificial está transformando industrias.",  # Spanish
            "Künstliche Intelligenz transformiert Industrien.",  # German
        ]

        results = reranker_client.rerank_documents(query, documents)

        assert len(results) == len(documents)

        # All results should be properly formatted
        for result in results:
            assert isinstance(result, tuple)
            assert len(result) == 3
            assert 0 <= result[0] < len(documents)

    def test_rerank_documents_performance(self, reranker_client, server_health_check):
        """Test reranking performance with medium batch size."""
        if not server_health_check:
            pytest.skip("Server not available")

        import time

        query = "machine learning applications"

        # Create a batch of documents
        batch_size = 20
        documents = [
            f"Machine learning application {i} in various domains."
            for i in range(batch_size)
        ]

        start_time = time.time()
        results = reranker_client.rerank_documents(query, documents)
        end_time = time.time()

        processing_time = end_time - start_time

        assert len(results) == batch_size
        assert processing_time < 15.0  # Should complete within 15 seconds

        # Calculate throughput
        throughput = batch_size / processing_time
        print(f"Reranker batch processing throughput: {throughput:.2f} docs/sec")

        # Should be reasonably fast
        assert throughput > 1.0  # At least 1 document per second
