# OCR, NER and RAG services

This section contains:
- A OCR service based on EasyOCR and TesseractOCR, supporting text and PDF content, running on the GPU.
- A NER service that tags text as `PER` (person), `ORG` (organization), `LOC` (place) or `MISC` type semantic entities, running on the GPU.
- A comprehensive RAG (Retrieval-Augmented Generation) system with document ingestion, vector search, advanced reranking, and interactive chat interface. Built with Milvus vector store, Hoover4 AI services, and LiteLLM integration.


## Requirements

Hardware: minimum of 1 x RTX 3090 with 24gb of video RAM (or better). Minimum of 64gb of system RAM or better. CPU with at least 8 CPU cores.

Software: Running these services requires `nvidia-docker` and `CUDA 12.8` installed.



## Features

- **Advanced Retrieval**: Retrieves 120 documents before reranking, then uses reranker to get top 10 most relevant documents
- **Hybrid Search**: Supports both semantic and hybrid search modes with entity-aware retrieval
- **Chat History**: Maintains conversation context with LLM-based question extraction
- **Streaming Responses**: Real-time streaming of LLM responses for better user experience
- **Metadata Extraction**: Extracts and displays document metadata for better context
- **Multi-LLM Support**: Uses LiteLLM for OpenAI, Anthropic, Ollama, and other providers
- **CLI Interface**: Full command-line interface with interactive chat mode
- **Health Monitoring**: Comprehensive health checks for all system components

## Architecture

The system consists of three main components:

### 1. Hoover4 AI Server (`hoover4_ai_server/`)
- FastAPI-based server providing embeddings, NER, and reranking services
- Uses `intfloat/multilingual-e5-large-instruct` for embeddings
- Runs on `http://localhost:8000`

### 2. Hoover4 AI Clients (`hoover4_ai_clients/`)
- Client libraries for connecting to Hoover4 AI server services
- Includes Milvus vector store integration
- LangChain-compatible components

### 3. Hoover4 RAG (`hoover4_rag/`)
- Main RAG chain implementation with chat history support
- Document ingestion from ClickHouse
- CLI interface for querying and interaction

## Quick Start

### 1. Install Dependencies
```bash
poetry install
```

### 2. Set Up Environment
```bash
cp env.example .env
# Edit .env with your configuration (see Configuration section below)
```

### 3. Start the AI Server
```bash
cd hoover4_ai_server
poetry install
poetry run python hoover4_ai_server.py
```
The server will start on `http://localhost:8000` and provide embeddings, reranking, and NER services.

### 4. Run Document Ingestion
```bash
python hoover4_rag/scripts/ingest.py
```
This processes documents from ClickHouse, generates embeddings, and stores them in Milvus for retrieval.

### 5. Start Chat with the Bot
```bash
python hoover4_rag/scripts/rag_cli.py query --stream
```
This starts an interactive chat interface where you can ask questions and get answers based on your ingested documents.

## Usage Examples

### Single Query
```bash
python hoover4_rag/scripts/rag_cli.py query "What is machine learning?"
```

### Interactive Chat (Terminal-based)
```bash
python hoover4_rag/scripts/rag_cli.py query
```

### Streaming Query
```bash
python hoover4_rag/scripts/rag_cli.py query "Tell me about AI" --stream
```

### Interactive Chat with Streaming
```bash
python hoover4_rag/scripts/rag_cli.py query --stream
```

### Verbose Query with Documents
```bash
python hoover4_rag/scripts/rag_cli.py query "Explain transformers" --verbose --show-documents
```

### Health Check
```bash
python hoover4_rag/scripts/rag_cli.py health
```

### Show Configuration
```bash
python hoover4_rag/scripts/rag_cli.py config
```

### Question Extractor Configuration
```bash
# Use aggressive question extraction with more history context
python hoover4_rag/scripts/rag_cli.py query --question-extractor-type aggressive --question-extractor-history 10

# Use conservative extraction with custom temperature
python hoover4_rag/scripts/rag_cli.py query --question-extractor-type conservative --question-extractor-temp 0.5

# Disable question extraction entirely
python hoover4_rag/scripts/rag_cli.py query --disable-question-extraction
```

## Configuration

Edit `.env` to configure the system. Here are the main configuration options:

### Milvus Vector Database
```bash
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION_NAME=rag_chunks
```

### AI Service URLs
```bash
EMBEDDING_SERVER_URL=http://localhost:8000/v1
NER_SERVER_URL=http://localhost:8000/v1
RERANKER_SERVER_URL=http://localhost:8000/v1
```

### ClickHouse Database (for document ingestion)
```bash
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=8123
CLICKHOUSE_USERNAME=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DATABASE=default
```

### LLM Configuration (LiteLLM)
```bash
# For OpenAI
LLM_API_KEY=your_openai_api_key
LLM_MODEL=gpt-3.5-turbo
LLM_TEMPERATURE=0.7

# For Ollama (local setup)
LLM_API_KEY=ollama
LLM_MODEL=ollama/phi4:latest
LLM_BASE_URL=http://localhost:11434

# For Anthropic
LLM_API_KEY=your_anthropic_api_key
LLM_MODEL=claude-3-sonnet
```

### RAG Configuration
```bash
RAG_INITIAL_K=120          # Documents retrieved before reranking
RAG_FINAL_K=10            # Documents after reranking
RAG_SEARCH_MODE=hybrid    # "semantic" or "hybrid"
RAG_MAX_HISTORY=10        # Maximum chat history length
```

### Question Extractor Configuration
```bash
RAG_QUESTION_EXTRACTOR_TYPE=default      # "default", "aggressive", "conservative"
RAG_QUESTION_EXTRACTOR_TEMP=0.3         # Temperature for question extraction
RAG_QUESTION_EXTRACTOR_HISTORY=5        # Max history messages for extraction
```

## CLI Options

The RAG CLI supports various options:

### Query Command Options
- `--stream, -s`: Stream the response in real-time
- `--verbose, -v`: Show detailed information
- `--show-documents, -d`: Show retrieved documents (requires --verbose)
- `--no-history`: Don't use chat history
- `--question-extractor-type`: Choose extractor type (default/aggressive/conservative)
- `--question-extractor-temp`: Set extraction temperature
- `--question-extractor-history`: Set max history for extraction
- `--disable-question-extraction`: Disable LLM-based question extraction

### Available Commands
- `query`: Query the RAG system (single query or interactive chat)
- `health`: Check system health
- `config`: Show current configuration

## System Requirements

- Python 3.9+
- Poetry for dependency management
- Milvus vector database
- ClickHouse database (for document ingestion)
- GPU recommended for AI server (for embeddings/reranking)

## Project Structure

```
alex-rag-demo/
├── hoover4_ai_server/          # AI services server
├── hoover4_ai_clients/         # Client libraries
├── hoover4_rag/               # Main RAG implementation
│   ├── chains/                # RAG and question extractor chains
│   └── scripts/               # CLI and ingestion scripts
├── tests/                     # Test suite
├── env.example               # Environment configuration template
└── pyproject.toml           # Project dependencies
```

## Development

### Running Tests
```bash
poetry run pytest
```

### Code Formatting
```bash
poetry run black .
poetry run ruff check .
```

## Troubleshooting

### Health Check
Use the health command to diagnose issues:
```bash
python hoover4_rag/scripts/rag_cli.py health
```

This will check:
- Embeddings service connectivity
- Vector store (Milvus) status
- NER service availability
- Reranker service status
- LLM connectivity

### Common Issues
1. **AI Server not running**: Ensure `hoover4_ai_server` is started on port 8000
2. **Milvus connection issues**: Check Milvus is running and accessible
3. **LLM API errors**: Verify API keys and model availability
4. **No documents found**: Run ingestion script to populate the vector store
