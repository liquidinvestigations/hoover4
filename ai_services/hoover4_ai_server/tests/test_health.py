#!/usr/bin/env python3
"""
Health check tests for the embedding server
"""

import pytest
from test_utils import check_server_health, print_test_header, print_server_status


def test_server_health():
    """Test basic server health check"""
    print_test_header("SERVER HEALTH CHECK TEST")

    health_data = check_server_health()
    print_server_status(health_data)

    if health_data.get("status") == "unreachable":
        print("\nError: Cannot connect to embedding server at http://localhost:8000")
        print("Make sure the server is running with: python hoover4_ai_server.py")
        print("Or with Docker: docker-compose up")
        assert False, "Server is unreachable"
    elif health_data.get("status") == "unhealthy":
        print(f"\nWarning: Health check failed: {health_data.get('error', 'Unknown error')}")
        assert False, f"Server is unhealthy: {health_data.get('error', 'Unknown error')}"
    else:
        print(" Server health check passed!")
        assert health_data.get("status") == "healthy"


def test_model_loading_status():
    """Test that required models are loaded"""
    print_test_header("MODEL LOADING STATUS TEST")

    health_data = check_server_health()

    if health_data.get("status") != "healthy":
        pytest.skip("Server not healthy, skipping model tests")

    # Check embedding model
    embedding_loaded = health_data.get('embedding_model_loaded', False) or health_data.get('model_loaded', False)
    print(f"Embedding model loaded: {embedding_loaded}")
    assert embedding_loaded, "Embedding model should be loaded"

    # Check optional models (not required for basic functionality)
    reranker_loaded = health_data.get('reranker_model_loaded', False)
    ner_loaded = health_data.get('ner_model_loaded', False)

    print(f"Reranker model loaded: {reranker_loaded}")
    print(f"NER model loaded: {ner_loaded}")

    if not reranker_loaded:
        print("⚠️  Reranker model not loaded - reranking tests will be limited")

    if not ner_loaded:
        print("⚠️  NER model not loaded - NER tests will be limited")

    print(" Model loading status check completed!")


def test_hardware_capabilities():
    """Test hardware capabilities detection"""
    print_test_header("HARDWARE CAPABILITIES TEST")

    health_data = check_server_health()

    if health_data.get("status") != "healthy":
        pytest.skip("Server not healthy, skipping hardware tests")

    cuda_available = health_data.get('cuda_available', False)
    gpu_count = health_data.get('gpu_count', 0)

    print(f"CUDA available: {cuda_available}")
    print(f"GPU count: {gpu_count}")

    if cuda_available:
        print(" GPU acceleration available")
        assert gpu_count > 0, "GPU count should be greater than 0 when CUDA is available"
    else:
        print("ℹ️  Running on CPU")

    print(" Hardware capabilities check completed!")


if __name__ == "__main__":
    print("Running health check tests...\n")

    try:
        test_server_health()
        print("\n" + "=" * 60)

        test_model_loading_status()
        print("\n" + "=" * 60)

        test_hardware_capabilities()
        print("\n" + "=" * 60)

        print("HEALTH CHECK RESULTS")
        print("=" * 60)
        print(" All health checks passed!")

    except Exception as e:
        print(f" Health check failed: {e}")
        exit(1)
