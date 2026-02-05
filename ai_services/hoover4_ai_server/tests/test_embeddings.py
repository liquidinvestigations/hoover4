#!/usr/bin/env python3
"""
Basic embedding API tests for the embedding server
"""

import requests
import pytest
from test_utils import (
    cosine_similarity, euclidean_distance, check_server_health,
    print_test_header, validate_server_connection,
    SIMILARITY_TEST_TEXTS, DEFAULT_MODEL, DEFAULT_TASK_DESCRIPTION
)


def test_basic_embedding_generation():
    """Test basic embedding generation with direct API calls"""
    print_test_header("BASIC EMBEDDING GENERATION TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    print("\nTest texts:")
    for i, text in enumerate(SIMILARITY_TEST_TEXTS):
        print(f"{i+1}. {text}")

    # Get embeddings using direct API call
    print("\nGetting embeddings using direct API...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/embeddings",
            json={
                "input": SIMILARITY_TEST_TEXTS,
                "model": DEFAULT_MODEL,
                "task_description": DEFAULT_TASK_DESCRIPTION
            }
        )

        assert response.status_code == 200, f"API returned status code {response.status_code}: {response.text}"

        result = response.json()
        embeddings = [item["embedding"] for item in result["data"]]

        print(f" Successfully got {len(embeddings)} embeddings")
        print(f"Embedding dimension: {len(embeddings[0])}")

        # Verify embeddings structure
        assert len(embeddings) == len(SIMILARITY_TEST_TEXTS), "Number of embeddings should match input texts"
        assert all(len(emb) == len(embeddings[0]) for emb in embeddings), "All embeddings should have same dimension"
        assert len(embeddings[0]) > 0, "Embeddings should not be empty"

        # return embeddings  # Removed return to fix pytest warning

    except Exception as e:
        pytest.fail(f"Error getting embeddings: {e}")


def test_similarity_computation():
    """Test similarity computation with embedding results"""
    print_test_header("EMBEDDING SIMILARITY COMPUTATION TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Get embeddings first
    try:
        response = requests.post(
            "http://localhost:8000/v1/embeddings",
            json={
                "input": SIMILARITY_TEST_TEXTS,
                "model": DEFAULT_MODEL
            }
        )

        assert response.status_code == 200, f"API returned status code {response.status_code}: {response.text}"

        result = response.json()
        embeddings = [item["embedding"] for item in result["data"]]
        print(f" Successfully got {len(embeddings)} embeddings")
        print(f"Embedding dimension: {len(embeddings[0])}")

    except Exception as e:
        pytest.fail(f"Error getting embeddings: {e}")

    # Compute similarities and distances
    print("\n" + "=" * 60)
    print("SIMILARITY ANALYSIS")
    print("=" * 60)

    # All pairwise comparisons
    comparisons = [
        (0, 1, "Similar text 1 vs Similar text 2"),
        (0, 2, "Similar text 1 vs Different text"),
        (1, 2, "Similar text 2 vs Different text")
    ]

    results = []

    for i, j, description in comparisons:
        cosine_sim = cosine_similarity(embeddings[i], embeddings[j])
        euclidean_dist = euclidean_distance(embeddings[i], embeddings[j])

        results.append({
            'description': description,
            'cosine_similarity': cosine_sim,
            'euclidean_distance': euclidean_dist
        })

        print(f"\n{description}:")
        print(f"  Cosine similarity: {cosine_sim:.4f}")
        print(f"  Euclidean distance: {euclidean_dist:.4f}")

    # Analysis
    print("\n" + "=" * 60)
    print("ANALYSIS")
    print("=" * 60)

    similar_cosine = results[0]['cosine_similarity']  # Similar texts
    different_cosine_1 = results[1]['cosine_similarity']  # Similar vs different
    different_cosine_2 = results[2]['cosine_similarity']  # Similar vs different

    print(f"\nExpected behavior:")
    print(f"- Similar texts should have HIGH cosine similarity (close to 1.0)")
    print(f"- Different texts should have LOWER cosine similarity")
    print(f"- Similar texts should have LOW Euclidean distance")
    print(f"- Different texts should have HIGHER Euclidean distance")

    print(f"\nActual results:")
    print(f"- Similar texts cosine similarity: {similar_cosine:.4f}")
    print(f"- Different texts cosine similarity: {different_cosine_1:.4f}, {different_cosine_2:.4f}")

    # Verify expectations
    assert similar_cosine > different_cosine_1, "Similar texts should be more similar than different texts"
    assert similar_cosine > different_cosine_2, "Similar texts should be more similar than different texts"
    print(" SUCCESS: Similar texts are more similar than different texts!")

    assert similar_cosine > 0.7, f"Similar texts similarity ({similar_cosine:.4f}) should be > 0.7"
    print(" SUCCESS: Similar texts have high similarity score")

    # Summary table
    print("\n" + "=" * 60)
    print("SUMMARY TABLE")
    print("=" * 60)
    print(f"{'Comparison':<40} {'Cosine Sim':<12} {'Euclidean Dist':<15}")
    print("-" * 67)
    for result in results:
        print(f"{result['description']:<40} {result['cosine_similarity']:<12.4f} {result['euclidean_distance']:<15.4f}")


def test_custom_task_description():
    """Test embedding generation with custom task description"""
    print_test_header("CUSTOM TASK DESCRIPTION TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    print("Testing with different task description...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/embeddings",
            json={
                "input": SIMILARITY_TEST_TEXTS,
                "model": DEFAULT_MODEL,
                "task_description": "Given a question, retrieve documents that contain the answer"
            }
        )

        assert response.status_code == 200, f"Custom task test failed: {response.status_code}"

        result = response.json()
        embeddings = [item["embedding"] for item in result["data"]]
        print(f" Successfully got embeddings with custom task description")
        print(f"Custom task embeddings dimension: {len(embeddings[0])}")

        assert len(embeddings) == len(SIMILARITY_TEST_TEXTS), "Should return same number of embeddings"
        assert len(embeddings[0]) > 0, "Embeddings should not be empty"

    except Exception as e:
        pytest.fail(f"Error testing custom task: {e}")


def test_single_text_embedding():
    """Test embedding generation for single text input"""
    print_test_header("SINGLE TEXT EMBEDDING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    single_text = "This is a single test sentence for embedding."
    print(f"Test text: '{single_text}'")

    try:
        response = requests.post(
            "http://localhost:8000/v1/embeddings",
            json={
                "input": single_text,
                "model": DEFAULT_MODEL,
                "task_description": DEFAULT_TASK_DESCRIPTION
            }
        )

        assert response.status_code == 200, f"Single text test failed: {response.status_code}: {response.text}"

        result = response.json()
        embeddings = [item["embedding"] for item in result["data"]]

        print(f" Successfully got embedding for single text")
        print(f"Embedding dimension: {len(embeddings[0])}")

        assert len(embeddings) == 1, "Should return exactly one embedding"
        assert len(embeddings[0]) > 0, "Embedding should not be empty"

    except Exception as e:
        pytest.fail(f"Error getting single text embedding: {e}")


def test_error_handling():
    """Test API error handling"""
    print_test_header("EMBEDDING API ERROR HANDLING TEST")

    # Validate server connection
    if not validate_server_connection():
        pytest.skip("Server not available")

    # Test empty input
    print("Testing empty input...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/embeddings",
            json={
                "input": [],
                "model": DEFAULT_MODEL
            }
        )

        assert response.status_code == 400, f"Expected 400 for empty input, got {response.status_code}"
        print(" Empty input correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error testing empty input: {e}")

    # Test missing input
    print("Testing missing input field...")
    try:
        response = requests.post(
            "http://localhost:8000/v1/embeddings",
            json={
                "model": DEFAULT_MODEL
            }
        )

        assert response.status_code == 422, f"Expected 422 for missing input field validation, got {response.status_code}"
        print(" Missing input correctly rejected")

    except requests.exceptions.RequestException as e:
        pytest.fail(f"Error testing missing input: {e}")


if __name__ == "__main__":
    print("Running embedding API tests...\n")

    try:
        test_basic_embedding_generation()
        print("\n" + "=" * 80)

        test_similarity_computation()
        print("\n" + "=" * 80)

        test_custom_task_description()
        print("\n" + "=" * 80)

        test_single_text_embedding()
        print("\n" + "=" * 80)

        test_error_handling()
        print("\n" + "=" * 80)

        print("EMBEDDING TESTS RESULTS")
        print("=" * 80)
        print(" All embedding tests passed!")

    except Exception as e:
        print(f" Embedding tests failed: {e}")
        exit(1)
