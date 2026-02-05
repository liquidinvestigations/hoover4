#!/usr/bin/env python3
"""
Reranking functionality tests for the embedding server
"""

import requests
import time
import pytest
from test_utils import (
    validate_server_connection, print_test_header, print_test_subheader, check_server_health
)


def test_basic_reranking():
    """Test basic reranking functionality"""
    print_test_header("BASIC RERANKING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if reranker model is loaded
    health_data = check_server_health()
    if not health_data.get('reranker_model_loaded', False):
        pytest.skip("Reranker model not loaded")

    # Test documents - mix of relevant and irrelevant to cats
    query = "Tell me about cats as pets"
    documents = [
        "Dogs are loyal companions that require daily walks and training.",  # Irrelevant
        "Cats are independent pets that love to play with toys and sleep in sunny spots.",  # Very relevant
        "Fish tanks require regular cleaning and proper water temperature control.",  # Irrelevant
        "Felines make wonderful indoor pets and are known for their cleanliness and affection.",  # Very relevant
        "Cars need regular maintenance including oil changes and tire rotations.",  # Irrelevant
        "Pet cats enjoy interactive play and benefit from scratching posts and climbing trees.",  # Very relevant
        "Computers require software updates and virus protection for optimal performance."  # Irrelevant
    ]

    print(f"\nTest query: '{query}'")
    print(f"\nTest documents ({len(documents)} total):")
    for i, doc in enumerate(documents):
        print(f"{i+1}. {doc}")

    try:
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "query": query,
                "documents": documents
            }
        )

        assert response.status_code == 200, f"API returned status code {response.status_code}: {response.text}"

        result = response.json()

        print(f" Successfully reranked {len(documents)} documents")
        print(f"Model used: {result.get('model', 'unknown')}")
        print(f"Usage: {result.get('usage', {})}")

        print(f"\nReranked results (by relevance):")
        for i, item in enumerate(result["data"]):
            original_idx = item["index"]
            score = item["relevance_score"]
            doc_text = item["document"][:80] + "..." if len(item["document"]) > 80 else item["document"]
            print(f"{i+1}. [Original #{original_idx+1}] Score: {score:.4f}")
            print(f"   {doc_text}")

        # Verify that cat-related documents are ranked higher
        top_3_docs = [item["document"] for item in result["data"][:3]]
        cat_terms = ["cat", "feline", "pet"]

        relevant_in_top_3 = sum(1 for doc in top_3_docs
                               if any(term.lower() in doc.lower() for term in cat_terms))

        assert relevant_in_top_3 >= 2, f"Expected at least 2 cat-related documents in top 3, got {relevant_in_top_3}"
        print(" SUCCESS: Cat-related documents are properly ranked in top 3")

        # Verify response structure
        assert "data" in result, "Response should contain 'data' field"
        assert len(result["data"]) == len(documents), "Should return same number of results as input documents"

        for item in result["data"]:
            assert "index" in item, "Each result should have 'index' field"
            assert "relevance_score" in item, "Each result should have 'relevance_score' field"
            assert "document" in item, "Each result should have 'document' field"
            assert isinstance(item["relevance_score"], (int, float)), "Relevance score should be numeric"

    except Exception as e:
        pytest.fail(f"Error in basic reranking test: {e}")


def test_top_k_filtering():
    """Test top-k filtering functionality"""
    print_test_header("TOP-K FILTERING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if reranker model is loaded
    health_data = check_server_health()
    if not health_data.get('reranker_model_loaded', False):
        pytest.skip("Reranker model not loaded")

    query = "Tell me about machine learning"
    documents = [
        "Machine learning algorithms can analyze large datasets efficiently.",
        "Cooking recipes require precise measurements and timing.",
        "Artificial intelligence is transforming many industries.",
        "Weather patterns are influenced by global climate changes.",
        "Deep learning neural networks mimic brain structures.",
        "Sports teams need good coordination and practice.",
        "Data science combines statistics and programming skills."
    ]

    print(f"\nTest query: '{query}'")
    print(f"Testing with top_k=3 from {len(documents)} documents")

    try:
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "query": query,
                "documents": documents,
                "top_k": 3
            }
        )

        assert response.status_code == 200, f"Top-k test failed: Status code {response.status_code}: {response.text}"

        result = response.json()
        returned_count = len(result["data"])

        assert returned_count == 3, f"Expected 3 documents, got {returned_count}"
        print(f" SUCCESS: Top-k filtering works correctly (returned {returned_count} documents)")

        # Verify results are sorted by relevance score
        scores = [item["relevance_score"] for item in result["data"]]
        assert scores == sorted(scores, reverse=True), "Results should be sorted by relevance score (descending)"

        print("Top 3 results:")
        for i, item in enumerate(result["data"]):
            print(f"{i+1}. Score: {item['relevance_score']:.4f} - {item['document'][:60]}...")

    except Exception as e:
        pytest.fail(f"Error in top-k test: {e}")


def test_return_documents_false():
    """Test excluding document content from response"""
    print_test_header("RETURN DOCUMENTS FALSE TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if reranker model is loaded
    health_data = check_server_health()
    if not health_data.get('reranker_model_loaded', False):
        pytest.skip("Reranker model not loaded")

    query = "artificial intelligence applications"
    documents = [
        "AI is used in healthcare for medical diagnosis.",
        "Traditional farming methods require manual labor.",
        "Machine learning improves recommendation systems.",
        "Art galleries display various cultural artifacts."
    ]

    print(f"\nTest query: '{query}'")
    print("Testing with return_documents=False")

    try:
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "query": query,
                "documents": documents,
                "return_documents": False,
                "top_k": 3
            }
        )

        assert response.status_code == 200, f"Return documents test failed: Status code {response.status_code}: {response.text}"

        result = response.json()
        has_documents = any(item.get("document") is not None for item in result["data"])

        assert not has_documents, "Documents should not be included when return_documents=False"
        print(" SUCCESS: Documents correctly excluded from response")

        print("Results (index and score only):")
        for i, item in enumerate(result["data"]):
            assert "index" in item, "Should still include index"
            assert "relevance_score" in item, "Should still include relevance score"
            print(f"{i+1}. Original index: {item['index']}, Score: {item['relevance_score']:.4f}")

    except Exception as e:
        pytest.fail(f"Error in return_documents test: {e}")


def test_reranking_error_handling():
    """Test error handling for invalid inputs"""
    print_test_header("RERANKING ERROR HANDLING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if reranker model is loaded
    health_data = check_server_health()
    if not health_data.get('reranker_model_loaded', False):
        pytest.skip("Reranker model not loaded")

    documents = ["Valid document for testing"]

    # Test empty query
    print("Testing empty query...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "query": "",
                "documents": documents
            }
        )

        assert response.status_code == 400, f"Expected 400 for empty query, got {response.status_code}"
        print(" SUCCESS: Empty query correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error in empty query test: {e}")

    # Test empty documents
    print("Testing empty documents list...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "query": "valid query",
                "documents": []
            }
        )

        assert response.status_code == 400, f"Expected 400 for empty documents, got {response.status_code}"
        print(" SUCCESS: Empty documents list correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error in empty documents test: {e}")

    # Test missing fields
    print("Testing missing query field...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "documents": documents
            }
        )

        assert response.status_code == 422, f"Expected 422 for missing query field validation, got {response.status_code}"
        print(" SUCCESS: Missing query field correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error in missing query test: {e}")


def test_reranking_performance():
    """Test reranking performance with larger document set"""
    print_test_header("RERANKING PERFORMANCE TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Check if reranker model is loaded
    health_data = check_server_health()
    if not health_data.get('reranker_model_loaded', False):
        pytest.skip("Reranker model not loaded")

    query = "machine learning and artificial intelligence"

    # Create a larger set of documents
    base_docs = [
        "Machine learning algorithms process data to find patterns.",
        "Cooking requires creativity and following recipes carefully.",
        "Artificial intelligence systems can make autonomous decisions.",
        "Weather forecasting uses mathematical models and data analysis.",
        "Deep learning networks learn complex representations automatically.",
        "Sports teams practice regularly to improve performance.",
        "Data scientists analyze information to extract insights."
    ]

    # Duplicate to create larger test set
    large_docs = base_docs * 10  # 70 documents

    print(f"\nTest query: '{query}'")
    print(f"Testing performance with {len(large_docs)} documents")

    try:
        start_time = time.time()
        response = requests.post(
            "http://localhost:8000/v1/rerank",
            json={
                "query": query,
                "documents": large_docs,
                "top_k": 5
            }
        )
        end_time = time.time()

        assert response.status_code == 200, f"Performance test failed: Status code {response.status_code}: {response.text}"

        processing_time = end_time - start_time
        result = response.json()

        print(f" SUCCESS: Processed {len(large_docs)} documents in {processing_time:.2f}s")
        print(f"Average time per document: {processing_time/len(large_docs)*1000:.1f}ms")
        print(f"Returned top {len(result['data'])} results")

        # Performance expectations
        assert processing_time < 30.0, f"Processing took too long: {processing_time:.2f}s"

        if processing_time < 10.0:
            print(" Excellent performance for batch reranking")
        elif processing_time < 20.0:
            print(" Good performance for batch reranking")
        else:
            print("⚠️  Performance could be improved")

        # Verify results structure
        assert len(result['data']) == 5, "Should return exactly top 5 results"

        # Verify scores are sorted
        scores = [item["relevance_score"] for item in result["data"]]
        assert scores == sorted(scores, reverse=True), "Results should be sorted by relevance score"

    except Exception as e:
        pytest.fail(f"Error in performance test: {e}")


if __name__ == "__main__":
    print("Running reranking tests...\n")

    try:
        test_basic_reranking()
        print("\n" + "=" * 80)

        test_top_k_filtering()
        print("\n" + "=" * 80)

        test_return_documents_false()
        print("\n" + "=" * 80)

        test_reranking_error_handling()
        print("\n" + "=" * 80)

        test_reranking_performance()
        print("\n" + "=" * 80)

        print("RERANKING TESTS RESULTS")
        print("=" * 80)
        print(" All reranking tests passed!")
        print("\nKey features tested:")
        print("  • Basic document reranking by relevance")
        print("  • Top-k result filtering")
        print("  • Optional document content in response")
        print("  • Error handling for invalid inputs")
        print("  • Performance with larger document sets")

    except Exception as e:
        print(f" Reranking tests failed: {e}")
        exit(1)
