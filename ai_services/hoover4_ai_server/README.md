# Multilingual E5 Embedding, Reranking & NER Server

A high-performance FastAPI-based server that provides OpenAI-compatible APIs for deep learning-powered text processing:
- **Embeddings** using `intfloat/multilingual-e5-large-instruct`
- **Document Reranking** using `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Named Entity Recognition (NER)** using `FacebookAI/xlm-roberta-large-finetuned-conll03-english`

 **Performance Optimized**: Batch processing, GPU acceleration, and hardware-adaptive configurations for maximum throughput.

> ** Project Overview**: This is part of the [Alex RAG Demo](../README.md) project - a comprehensive RAG system with document ingestion, vector search, and interactive chat interface. This server provides the AI services (embeddings, NER, reranking) used by the RAG system.

## Quick Start

> ** Complete Setup**: For the full RAG system setup, see the [main project README](../README.md) Quick Start section.

### Using Poetry (Local Development)

1. Install dependencies:
```bash
poetry install
```

2. Run the server:
```bash
poetry run python hoover4_ai_server.py
```

The server will start on `http://localhost:8000` and provide embeddings, reranking, and NER services for the RAG system.

## API Endpoints

### Health Check
- `GET /` - Basic server info with all available endpoints
- `GET /health` - Detailed health check with model status and GPU memory
- `GET /performance-stats` - Performance metrics and optimization recommendations

### Embeddings
- `POST /v1/embeddings` - Generate embeddings (OpenAI compatible)

### Document Reranking
- `POST /v1/rerank` - Rerank documents by relevance to a query

### Named Entity Recognition
- `POST /v1/extract-entities` - Extract named entities from text

### Models
- `GET /v1/models` - List available models

## Example Usage

### Generate Embeddings
```bash
curl -X POST "http://localhost:8000/v1/embeddings" \
     -H "Content-Type: application/json" \
     -d '{
       "input": "Hello world",
       "model": "intfloat/multilingual-e5-large-instruct"
     }'
```

### Rerank Documents
```bash
curl -X POST "http://localhost:8000/v1/rerank" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "What are the benefits of exercise?",
       "documents": [
         "Exercise helps improve cardiovascular health and reduces stress.",
         "Cooking is a great way to save money and eat healthier.",
         "Regular physical activity boosts mental health and energy levels."
       ],
       "top_k": 2
     }'
```

### Extract Named Entities
```bash
curl -X POST "http://localhost:8000/v1/extract-entities" \
     -H "Content-Type: application/json" \
     -d '{
       "input": "Apple Inc. was founded by Steve Jobs in Cupertino, California.",
       "include_confidence": true
     }'
```

## Environment Variables

You can configure the server using these environment variables:

### Basic Configuration
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `HUGGING_FACE_HUB_TOKEN`: Optional token for private models
- `CUDA_VISIBLE_DEVICES`: GPU device selection

### Performance Optimization
- `OPTIMAL_BATCH_SIZE`: Batch size for processing (default: 32)
- `ENABLE_HALF_PRECISION`: Enable FP16 for 2x speed boost (default: true)
- `ENABLE_TORCH_COMPILE`: Enable PyTorch compilation (default: true)
- `MAX_SEQUENCE_LENGTH`: Maximum token length (default: 512)

## Requirements

### Dependencies
- Python 3.11+
- Poetry for dependency management
- PyTorch with CUDA support (for GPU acceleration)
- Required Python packages (automatically installed with Poetry):
  - `sentence-transformers` - for embeddings and reranking
  - `transformers` - for NER (disabled in current pyproject.toml due to Python 3.13 compatibility)
  - `fastapi` and `uvicorn` - web framework and server
  - `tiktoken` - for token decoding (LangChain compatibility)

### Hardware Requirements
- **Recommended**: NVIDIA GPU with CUDA support for optimal performance
- **Minimum**: CPU-only execution (slower but functional)
- **Memory**: At least 8GB RAM (16GB+ recommended for GPU)

## Models Used

### Embedding Model
- **Model**: `intfloat/multilingual-e5-large-instruct`
- **Purpose**: Generate high-quality multilingual text embeddings
- **Features**: Instruction-following, multilingual support, 1024-dimensional vectors

### Reranking Model
- **Model**: `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Purpose**: Rerank documents by relevance to search queries
- **Features**: Fast cross-encoder architecture, optimized for search relevance

### Named Entity Recognition Model
- **Model**: `FacebookAI/xlm-roberta-large-finetuned-conll03-english`
- **Purpose**: Extract named entities (persons, organizations, locations, etc.)
- **Features**: Multilingual RoBERTa-based, trained on CoNLL-03 dataset

## Performance

### Optimizations
- **Batch Processing**: Intelligent batching for 2-4x throughput improvement
- **GPU Acceleration**: Half-precision (FP16) and PyTorch compilation for maximum speed
- **Memory Efficiency**: Optimized GPU memory usage and automatic device management
- **Hardware Adaptive**: Automatic configuration based on available hardware

### Benchmark Results (RTX 2080 Ti)

Latest performance test results:

| Batch Size | Throughput (emb/sec) | Avg Time (sec) | Efficiency | Consistency | Status |
|------------|---------------------|----------------|------------|-------------|--------|
| 1          | 21.6                | 0.05           | 21.63      | 0.92        |  Pass |
| 5          | 112.7               | 0.04           | 22.53      | 0.82        |  Pass |
| 10         | 201.3               | 0.05           | 20.13      | 0.79        |  Pass |
| 20         | 223.0               | 0.08           | 11.15      | 0.94        |  Pass |
| 50         | 286.0               | 0.16           | 5.72       | 0.95        |  Pass |
| 100        | 342.1               | 0.26           | 3.42       | 0.97        |  Pass |
| 200        | 356.8               | 0.51           | 1.78       | 0.98        |  Pass |
| **500**    | **381.8**           | **1.17**       | **0.76**   | **1.00**    |  Pass |

** Recommended Configuration**: Batch size 500 for optimal performance
- **Peak Throughput**: 381.8 embeddings/second
- **Processing Time**: 1.17 seconds per batch
- **Estimated 1M embeddings**: 0.7 hours
- **Hardware**: NVIDIA GeForce RTX 2080 Ti (11GB VRAM)

### Expected Performance by Hardware
| Hardware | CUDA Cores | Theoretical Max* | Realistic Est. | Recommended Batch | Notes |
|----------|------------|------------------|----------------|-------------------|-------|
| **RTX 2080 Ti** | **4,352** | **381.8** | **381.8** | **500** | **Measured performance** |
| RTX 4090 | 16,384 | ~1,438 | 800-1000 | 500-1000 | 3.76x cores, memory limited |
| RTX 4080 | 9,728 | ~854 | 600-750 | 400-800 | 2.24x cores |
| RTX 3080 Ti | 10,240 | ~899 | 650-800 | 400-800 | 2.35x cores |
| RTX 3080 | 8,704 | ~764 | 550-700 | 300-600 | 2.0x cores |
| RTX 3070 | 5,888 | ~517 | 400-500 | 200-400 | 1.35x cores |
| RTX 2070 | 2,304 | ~202 | 180-220 | 100-200 | 0.53x cores |
| CPU (16 cores) | N/A | N/A | 10-20 | 4-8 | CPU fallback |

**\*Theoretical Max**: Linear scaling based on CUDA core ratio
**Realistic Est.**: Accounting for memory bandwidth, thermal limits, and architectural efficiency

### Configuration
```bash
# High-performance GPU setup (RTX 2080 Ti optimal)
export OPTIMAL_BATCH_SIZE=500
export ENABLE_HALF_PRECISION=true
export ENABLE_TORCH_COMPILE=true

# High-performance GPU setup (other cards)
export OPTIMAL_BATCH_SIZE=64
export ENABLE_HALF_PRECISION=true
export ENABLE_TORCH_COMPILE=true

# CPU-only setup
export OPTIMAL_BATCH_SIZE=4
export ENABLE_HALF_PRECISION=false
```

### Monitoring
Check real-time performance and get optimization recommendations:
```bash
curl http://localhost:8000/performance-stats
```

## Testing

The server includes comprehensive tests for all functionality:

```bash
# Run all tests
poetry run pytest tests/

# Run specific test categories
poetry run python tests/test_embeddings.py      # Embedding tests
poetry run python tests/test_reranking.py       # Reranking tests
poetry run python tests/test_ner.py            # NER tests
poetry run python tests/test_health.py         # Health check tests

# Performance benchmarks
poetry run python tests/test_throughput.py      # Throughput analysis
poetry run python tests/test_batch_optimization.py  # Batch size optimization
```

##  Related Components

- **[Main Project](../README.md)**: Complete RAG system setup and usage
- **[Hoover4 AI Clients](../hoover4_ai_clients/README.md)**: Client libraries for connecting to this server
- **[Hoover4 RAG](../hoover4_rag/README.md)**: Main RAG chain implementation that uses this server's services
