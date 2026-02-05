# Integration Tests for Hoover4 AI Clients

This directory contains comprehensive integration tests for the Hoover4 AI clients that test against live services instead of mocks.

## Overview

The integration tests verify that the AI clients work correctly with real:
- **Embeddings Server** - Tests the `Hoover4EmbeddingsClient`
- **NER Server** - Tests the `Hoover4NERClient`
- **Reranker Server** - Tests the `Hoover4RerankClient`
- **Milvus Database** - Tests the `Hoover4MilvusVectorStore`

### Test Behavior

- **Without `--integration` flag**: All tests are skipped with the message "Integration tests require --integration flag"
- **With `--integration` flag**: Tests run but are skipped if required services are not available
- **Service Health Checks**: Tests automatically detect if services are running and skip accordingly

## Prerequisites

### Required Services

Before running integration tests, ensure these services are running:

1. **AI Server** (Embeddings, NER, Reranker)
   - Default: `http://localhost:8000/v1`
   - Start with: `poetry run python hoover4_ai_server/hoover4_ai_server.py`

2. **Milvus Database**
   - Default: `localhost:19530`
   - Start with Docker: `docker run -d --name milvus -p 19530:19530 milvusdb/milvus:latest`

### Dependencies

Install test dependencies:
```bash
cd hoover4_ai_clients
poetry install
```

## Configuration

### Environment Variables

Create a `.env` file in the `hoover4_ai_clients` directory:

```bash
# AI Server Configuration
EMBEDDING_SERVER_URL=http://localhost:8000/v1

# Milvus Database Configuration
MILVUS_HOST=localhost
MILVUS_PORT=19530

# Test Collection Configuration
TEST_COLLECTION_NAME=test_integration_collection
```

### Alternative Configurations

**Docker Compose Setup:**
```bash
EMBEDDING_SERVER_URL=http://localhost:8000/v1
MILVUS_HOST=localhost
MILVUS_PORT=19530
```

**Remote Services:**
```bash
EMBEDDING_SERVER_URL=http://your-server.com:8000/v1
MILVUS_HOST=your-milvus-server.com
MILVUS_PORT=19530
```

**Different Ports:**
```bash
EMBEDDING_SERVER_URL=http://localhost:8080/v1
MILVUS_HOST=localhost
MILVUS_PORT=19531
```

## Running Tests

### Quick Start

```bash
# Run all integration tests
python -m pytest tests/ --integration

# Run with verbose output
python -m pytest tests/ --integration -v

# Run specific test categories
python -m pytest tests/ --integration -m embeddings
python -m pytest tests/ --integration -m ner
python -m pytest tests/ --integration -m reranker
python -m pytest tests/ --integration -m milvus
```

### Using pytest directly

```bash
# Run all integration tests
python -m pytest tests/ --integration

# Run specific test files
python -m pytest tests/test_embeddings_integration.py --integration

# Run with custom server configuration
python -m pytest tests/ --integration --server-url http://localhost:8080/v1

# Run with custom Milvus configuration
python -m pytest tests/ --integration --milvus-host localhost --milvus-port 19531

# Run without integration flag (tests will be skipped)
python -m pytest tests/
```

### Test Categories

Tests are organized by service with pytest markers:

- `@pytest.mark.embeddings` - Embeddings client tests
- `@pytest.mark.ner` - NER client tests
- `@pytest.mark.reranker` - Reranker client tests
- `@pytest.mark.milvus` - Milvus client tests
- `@pytest.mark.integration` - All integration tests
- `@pytest.mark.slow` - Slow-running tests

## Test Files

### `test_embeddings_integration.py`
Tests the `Hoover4EmbeddingsClient` against live embedding server:
- Single and batch document embedding
- Query embedding
- Health checks
- Error handling
- Performance testing
- Multilingual support

### `test_ner_integration.py`
Tests the `Hoover4NERClient` against live NER server:
- Entity extraction from single and multiple texts
- Entity type filtering
- Multilingual text processing
- Special character handling
- Batch processing performance

### `test_reranker_integration.py`
Tests the `Hoover4RerankClient` against live reranker server:
- Document reranking by relevance
- Top-k result filtering
- Relevance score validation
- Consistency testing
- Performance benchmarking

### `test_milvus_integration.py`
Tests the `Hoover4MilvusVectorStore` against live Milvus database:
- Collection creation and management
- Document insertion and retrieval
- Similarity search
- Vector search
- Document deletion
- Batch operations

## Test Utilities

### `conftest.py`
Provides pytest configuration and fixtures:
- Service health checks
- Client initialization
- Test data generation
- Cleanup utilities
- Environment configuration

### Test Configuration
The tests use pytest configuration with:
- Service health checking via fixtures
- Environment variable loading
- Flexible command-line configuration
- Automatic test skipping when services unavailable
- Comprehensive error handling

## Troubleshooting

### Common Issues

**Service Not Available:**
```
 AI server is not available at http://localhost:8000/v1: Connection refused
```
- Ensure the AI server is running
- Check the server URL in your configuration
- Verify the server is accessible

**Milvus Connection Failed:**
```
 Milvus is not available at localhost:19530: Connection refused
```
- Start Milvus with Docker: `docker run -d --name milvus -p 19530:19530 milvusdb/milvus:latest`
- Check Milvus host and port configuration
- Ensure Milvus is accessible

**Test Timeouts:**
- Increase timeout values in test configuration
- Check server performance and resources
- Consider running tests with smaller batch sizes

**Collection Already Exists:**
```
Error: Collection 'test_integration_collection' already exists
```
- Tests automatically clean up collections
- Manually drop collections if needed: `collection.drop()`
- Use different collection names for parallel test runs

### Debug Mode

Run tests with maximum verbosity:
```bash
python -m pytest tests/ --integration -v
```

Run specific tests for debugging:
```bash
python -m pytest tests/test_embeddings_integration.py::TestEmbeddingsIntegration::test_embeddings_client_initialization --integration -v
```

### Performance Issues

For slow systems, run tests with smaller batches:
```bash
# Run only fast tests
python -m pytest tests/ --integration -m "not slow"

# Run with reduced batch sizes (modify test files)
```

## Contributing

When adding new integration tests:

1. **Use appropriate markers** - Mark tests with service-specific markers
2. **Include health checks** - Skip tests if services aren't available
3. **Clean up resources** - Use fixtures for automatic cleanup
4. **Add performance tests** - Include throughput and timing tests
5. **Test error conditions** - Verify proper error handling
6. **Document configuration** - Update this README with new options

## Best Practices

1. **Isolation** - Each test should be independent
2. **Cleanup** - Always clean up test data
3. **Configuration** - Use environment variables for flexibility
4. **Performance** - Include reasonable timeouts and batch sizes
5. **Error Handling** - Test both success and failure scenarios
6. **Documentation** - Keep tests and documentation in sync
