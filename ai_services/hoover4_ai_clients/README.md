# Hoover4 AI Clients

A comprehensive Python package providing client libraries for connecting to Hoover4 AI server services. This package offers LangChain-compatible interfaces for embeddings, named entity recognition, document reranking, and vector storage operations.

> ** Project Overview**: This is part of the [Alex RAG Demo](../README.md) project - a comprehensive RAG system with document ingestion, vector search, and interactive chat interface. See the main project README for complete setup instructions and architecture overview.

##  Features

- ** Embeddings**: `Hoover4EmbeddingsClient` - LangChain-compatible embeddings client with async support
- ** Named Entity Recognition**: `Hoover4NERClient` - Extract entities (persons, organizations, locations) from text
- ** Reranking**: `Hoover4RerankClient` - Rerank documents by relevance to improve search quality
- ** Vector Storage**: `Hoover4MilvusVectorStore` - LangChain-compatible Milvus vector store with advanced features

##  Installation

> ** Quick Start**: For the complete RAG system setup, see the [main project README](../README.md) Quick Start section.

### Using Poetry (Recommended)

```bash
# Install from local path (development)
poetry install

# Or install as a dependency in another project
poetry add ./hoover4_ai_clients
```

### Using pip

```bash
# Install from local path
pip install -e .

# Or install as a dependency
pip install ./hoover4_ai_clients
```

### Prerequisites

Before using these clients, ensure you have:
- [Hoover4 AI Server](../hoover4_ai_server/README.md) running on your specified URL
- [Milvus vector database](https://milvus.io/) running (for vector storage operations)

##  Quick Start

### Basic Usage

```python
from hoover4_ai_clients import (
    Hoover4EmbeddingsClient,
    Hoover4NERClient,
    Hoover4RerankClient,
    Hoover4MilvusVectorStore,
)

# Initialize clients
embeddings_client = Hoover4EmbeddingsClient(base_url="http://localhost:8000/v1")
ner_client = Hoover4NERClient(base_url="http://localhost:8000/v1")
rerank_client = Hoover4RerankClient(base_url="http://localhost:8000/v1")
vector_store = Hoover4MilvusVectorStore(collection_name="my_collection")

# Use the clients
embeddings = embeddings_client.embed_query("Hello world")
entities = ner_client.extract_entities(["John Doe works at Apple Inc."])
```

### Working with Documents

```python
from langchain_core.documents import Document

# Create documents with metadata
documents = [
    Document(
        page_content="Machine learning is a subset of AI.",
        metadata={"source": "textbook", "entities_persons": "", "entities_organizations": "AI"}
    ),
    Document(
        page_content="Python is great for data science.",
        metadata={"source": "tutorial", "entities_persons": "", "entities_organizations": "Python"}
    )
]

# Add documents to vector store
vector_store.add_documents(documents)

# Search and rerank
results = vector_store.similarity_search("What is machine learning?", k=5)
reranked = rerank_client.rerank_documents("What is machine learning?", [doc.page_content for doc in results])
```

##  Configuration

### Environment Variables

You can configure the clients using environment variables:

```bash
export HOOVER4_BASE_URL="http://localhost:8000/v1"
export MILVUS_HOST="localhost"
export MILVUS_PORT="19530"
```

### Logging

Configure logging for better debugging:

```python
import logging

# Set up logging
logging.basicConfig(level=logging.DEBUG)
```

##  Requirements

- Python 3.9+
- Hoover4 AI server running on your specified URL
- Milvus vector database (for vector storage operations)

##  Dependencies

- `requests` - HTTP client library
- `pymilvus` - Milvus vector database client
- `langchain-core` - LangChain core interfaces
- `python-dotenv` - Environment variable management

##  Development

### Setup Development Environment

```bash
# Clone the repository
git clone <repository-url>
cd hoover4_ai_clients

# Install dependencies
poetry install

# Run tests
poetry run pytest

# Format code
poetry run black .
poetry run ruff check .
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_embeddings_integration.py

# Run with coverage
poetry run pytest --cov=hoover4_ai_clients
```

##  API Reference

### Hoover4EmbeddingsClient

LangChain-compatible embeddings client with support for:
- Single query embedding
- Batch document embedding
- Async operations
- Health checks
- Retry logic with exponential backoff

### Hoover4NERClient

Named Entity Recognition client that extracts:
- Persons (PER)
- Organizations (ORG)
- Locations (LOC)
- Miscellaneous entities (MISC)

### Hoover4RerankClient

Document reranking client for improving search relevance:
- Rerank documents by query relevance
- Configurable top-k results
- Optional document text return

### Hoover4MilvusVectorStore

Advanced Milvus vector store with LangChain compatibility:
- Full CRUD operations
- Similarity search with scores
- Batch operations
- Metadata filtering
- Entity-aware storage

##  Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

##  License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

##  Support

If you encounter any issues or have questions:

1. Review the test files in `tests/` for usage examples
2. Check the integration tests for proper setup
3. See the [main project README](../README.md) for troubleshooting guidance
4. Check the [Hoover4 AI Server README](../hoover4_ai_server/README.md) for server setup issues
5. Open an issue on GitHub

##  Related Components

- **[Main Project](../README.md)**: Complete RAG system setup and usage
- **[Hoover4 AI Server](../hoover4_ai_server/README.md)**: FastAPI server providing embeddings, NER, and reranking services
- **[Hoover4 RAG](../hoover4_rag/README.md)**: Main RAG chain implementation with CLI interface

##  Version History

- **1.0.0** - Initial release with core functionality
  - Embeddings client with LangChain compatibility
  - NER client for entity extraction
  - Reranker client for document relevance
  - Milvus vector store with advanced features
