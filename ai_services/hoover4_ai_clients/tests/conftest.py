"""Pytest configuration for integration tests."""

import os
import time

import pytest
import requests
from dotenv import load_dotenv

from pymilvus import MilvusClient

from hoover4_ai_clients.embeddings_client import Hoover4EmbeddingsClient
from hoover4_ai_clients.milvus_client import Hoover4MilvusVectorStore
from hoover4_ai_clients.ner_client import Hoover4NERClient
from hoover4_ai_clients.reranker_client import Hoover4RerankClient

# Load environment variables from .env file
load_dotenv()

# Test configuration with environment variables and sensible defaults
EMBEDDING_SERVER_URL = os.getenv("EMBEDDING_SERVER_URL", "http://localhost:8821/v1")
MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.getenv("MILVUS_PORT", "19530"))
TEST_COLLECTION_NAME = os.getenv("TEST_COLLECTION_NAME", "test_integration_collection")


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test requiring live services"
    )
    config.addinivalue_line(
        "markers", "throughput: mark test as throughput test for performance measurement"
    )
    config.addinivalue_line(
        "markers", "embeddings: mark test as requiring embeddings server"
    )
    config.addinivalue_line(
        "markers", "ner: mark test as requiring NER server"
    )
    config.addinivalue_line(
        "markers", "reranker: mark test as requiring reranker server"
    )
    config.addinivalue_line(
        "markers", "milvus: mark test as requiring Milvus database"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to skip integration and throughput tests if not requested."""
    if not config.getoption("--integration"):
        skip_integration = pytest.mark.skip(reason="Integration tests require --integration flag")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    if not config.getoption("--throughput"):
        skip_throughput = pytest.mark.skip(reason="Throughput tests require --throughput flag")
        for item in items:
            if "throughput" in item.keywords:
                item.add_marker(skip_throughput)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--integration", "-I",
        action="store_true",
        default=False,
        help="Run integration tests that require live services"
    )
    parser.addoption(
        "--throughput", "-T",
        action="store_true",
        default=False,
        help="Run throughput tests for performance measurement"
    )
    parser.addoption(
        "--server-url",
        action="store",
        default=None,
        help=f"Base URL for the AI server (default: {EMBEDDING_SERVER_URL})"
    )
    parser.addoption(
        "--milvus-host",
        action="store",
        default=None,
        help=f"Milvus host (default: {MILVUS_HOST})"
    )
    parser.addoption(
        "--milvus-port",
        action="store",
        default=None,
        help=f"Milvus port (default: {MILVUS_PORT})"
    )


class MockEmbeddings:
    """Mock embedding class for testing."""

    def embed_documents(self, texts):
        """Mock embed_documents method."""
        return [[0.1] * 1024 for _ in texts]

    def embed_query(self, text):
        """Mock embed_query method."""
        return [0.1] * 1024


@pytest.fixture(scope="session")
def server_health_check(request) -> bool:
    """Check if the AI server is available and healthy."""
    # Use command line option if provided, otherwise use environment variable
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    health_url = base_url.replace("/v1", "/health")

    try:
        response = requests.get(health_url, timeout=5)
        if response.status_code == 200:
            print(f" AI server is healthy at {base_url}")
            return True
        else:
            print(f" AI server returned status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f" AI server is not available at {base_url}: {e}")
        return False


@pytest.fixture(scope="session")
def milvus_health_check(request) -> bool:
    """Check if Milvus is available."""
    # Use command line options if provided, otherwise use environment variables
    host = request.config.getoption("--milvus-host") or MILVUS_HOST
    port = int(request.config.getoption("--milvus-port") or MILVUS_PORT)

    try:
        # Use the project's Milvus client instead of pymilvus directly
        client = Hoover4MilvusVectorStore(
            collection_name="health_check",
            host=host,
            port=port,
            connection_alias="health_check"
        )
        success = client.connect()
        if success:
            # Disconnect after successful connection
            client.disconnect()
            print(f" Milvus is available at {host}:{port}")
            return True
        else:
            print(f" Milvus connection failed at {host}:{port}")
            return False
    except Exception as e:
        print(f" Milvus is not available at {host}:{port}: {e}")
        return False


@pytest.fixture
def embeddings_client(request) -> Hoover4EmbeddingsClient:
    """Create embeddings client for testing."""
    # Use command line option if provided, otherwise use environment variable
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    return Hoover4EmbeddingsClient(base_url=base_url)


@pytest.fixture
def ner_client(request) -> Hoover4NERClient:
    """Create NER client for testing."""
    # Use command line option if provided, otherwise use environment variable
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    return Hoover4NERClient(base_url=base_url)


@pytest.fixture
def reranker_client(request) -> Hoover4RerankClient:
    """Create reranker client for testing."""
    # Use command line option if provided, otherwise use environment variable
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    return Hoover4RerankClient(base_url=base_url)


@pytest.fixture
def milvus_client(request) -> Hoover4MilvusVectorStore:
    """Create Milvus client for testing."""
    # Use command line options if provided, otherwise use environment variables
    host = request.config.getoption("--milvus-host") or MILVUS_HOST
    port = int(request.config.getoption("--milvus-port") or MILVUS_PORT)

    # Use real embeddings client for Milvus tests
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    embeddings_client = Hoover4EmbeddingsClient(base_url=base_url)

    # Create NER client for Milvus tests
    ner_client = Hoover4NERClient(base_url=base_url)

    return Hoover4MilvusVectorStore(
        collection_name=TEST_COLLECTION_NAME,
        host=host,
        port=port,
        embedding_dim=1024,
        embedding=embeddings_client,
        ner_client=ner_client,
        use_ner_for_entities=True
    )


@pytest.fixture
def test_documents():
    """Sample documents for testing."""
    return [
        "Apple Inc. was founded by Steve Jobs in Cupertino, California in 1976.",
        "Microsoft Corporation is headquartered in Redmond, Washington.",
        "Google LLC is based in Mountain View, California.",
        "Tesla Inc. was founded by Elon Musk and is located in Austin, Texas.",
        "Amazon.com Inc. is headquartered in Seattle, Washington."
    ]


@pytest.fixture
def test_queries():
    """Sample queries for testing."""
    return [
        "technology companies in California",
        "companies founded by Steve Jobs",
        "tech companies in Washington state",
        "electric vehicle companies",
        "e-commerce companies"
    ]


@pytest.fixture(autouse=True)
def cleanup_test_collection(milvus_client):
    """Clean up test collection after each test."""
    yield
    try:
        # Try to delete the test collection
        milvus_client.drop_collection()
        print(f"🧹 Cleaned up test collection: {TEST_COLLECTION_NAME}")
    except Exception as e:
        print(f"⚠️  Could not clean up test collection: {e}")


@pytest.fixture(scope="class")
def throughput_test_collection_name():
    """Generate unique test collection name for throughput tests."""
    import time
    return f"throughput_test_{int(time.time())}"


@pytest.fixture(scope="class")
def throughput_embeddings_client(request) -> Hoover4EmbeddingsClient:
    """Create embeddings client for throughput testing with extended timeouts."""
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    return Hoover4EmbeddingsClient(
        base_url=base_url,
        timeout=60,
        max_retries=5
    )


@pytest.fixture(scope="class")
def throughput_ner_client(request) -> Hoover4NERClient:
    """Create NER client for throughput testing."""
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL
    return Hoover4NERClient(base_url=base_url)


@pytest.fixture(scope="class")
def throughput_milvus_client(request, throughput_test_collection_name) -> Hoover4MilvusVectorStore:
    """Create Milvus client for throughput testing."""
    host = request.config.getoption("--milvus-host") or MILVUS_HOST
    port = int(request.config.getoption("--milvus-port") or MILVUS_PORT)
    base_url = request.config.getoption("--server-url") or EMBEDDING_SERVER_URL

    embeddings_client = Hoover4EmbeddingsClient(
        base_url=base_url,
        timeout=60,
        max_retries=5
    )
    ner_client = Hoover4NERClient(base_url=base_url)

    return Hoover4MilvusVectorStore(
        collection_name=throughput_test_collection_name,
        host=host,
        port=port,
        embedding_dim=1024,
        embedding=embeddings_client,
        ner_client=ner_client,
        use_ner_for_entities=True,
        search_mode="hybrid"
    )


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """
    Mock time.sleep to make tests run faster.
    This fixture automatically applies to all tests and replaces time.sleep with a no-op.
    """
    monkeypatch.setattr(time, 'sleep', lambda x: None)


def wait_for_server(base_url: str, max_retries: int = 30, delay: float = 1.0) -> bool:
    """Wait for server to become available."""
    health_url = base_url.replace("/v1", "/health")

    for attempt in range(max_retries):
        try:
            response = requests.get(health_url, timeout=2)
            if response.status_code == 200:
                return True
        except requests.exceptions.RequestException:
            pass

        if attempt < max_retries - 1:
            time.sleep(delay)

    return False
