# Hoover4 AI services

GPU-backed embeddings / NER / reranking, a local LLM, a set of MCP tool servers, and
the LangGraph research agents that use them.

> **Deployment note (plan 3).** These services used to run across several hosts behind a
> VPN and addressed each other by `10.69.x.x`. That network is gone. Everything now runs
> on **one machine with one GPU**, joining the `hoover4` podman network created by
> `main_services/ops/docker/docker-compose.yaml`. Bring the main stack up first, then
> this one.

## What runs here

| Service | Port (loopback) | Purpose |
|---|---|---|
| `hoover4-ai-server` | 8821 | Embeddings, reranking, NER. Also serves the pipeline's P4 stage (`NER_URL`). |
| `hoover4-vllm` | 8011 | Local LLM (Qwen3-4B-Instruct), OpenAI-compatible. Replaces the old LiteLLM proxy. |
| `hoover4-mcp-collections` | 8085 | **The RAG path.** ACL-bounded search over the user's collections. |
| `hoover4-mcp-ddg` / `-wikipedia` / `-whois` | 8889 / 8093 / 8092 | Open-web tools. |
| `hoover4-mcp-milvus` | 18081 | Vector search. **Behind the `milvus` profile — nothing populates Milvus yet.** |
| `hoover4-internal-search-agent` | 9099 | Collection-only agent. What the website's AI Chat page calls. |
| `hoover4-full-research-agent` | 9090 | Collections + open web. Target of the Temporal `ResearchTask`. |

## How access control works

An agent answering for a user must only reach collections that user could read in the
search UI. The chain is:

1. The **website backend** resolves the user's permitted collections (group grants union
   public collections). It is the only component that can — it owns the auth tables.
2. It passes that list to the agent as `allowed_collections`.
3. The agent opens its MCP connections with `X-Hoover4-Collections: <list>` and
   `Authorization: Bearer $MCP_SHARED_SECRET`, and caches one graph **per ACL** so a
   connection is never reused across users.
4. `hoover4-mcp-collections` enforces the header on every tool call. A request for a
   collection outside it is an error, not a silently-narrowed filter.

The model never sees or supplies its own permissions. Set `MCP_SHARED_SECRET` in `.env`;
without it the MCP servers accept any caller and log a warning (the ports are bound to
127.0.0.1, which is the only reason that is survivable locally).

## Why search goes through Manticore, not Milvus

The ingestion pipeline writes extracted text to ClickHouse and search documents to
Manticore shards. It **never writes vectors to Milvus** — `text_chunks_milvus` and
`entity_hits_milvus` exist but are unused. So `hoover4-mcp-collections` searches
Manticore and reads text from ClickHouse, which is where the data actually is. The
Milvus MCP server is kept and still builds, behind the `milvus` compose profile, for
whenever a chunk-and-embed stage is added to the pipeline.

## Quick start

```bash
# 1. the main stack must be up first — it creates the `hoover4` network
../main_services/start-docker.sh

# 2. configure once
cp env.example .env
$EDITOR .env          # at minimum, set MCP_SHARED_SECRET

# 3. start
./start-docker.sh                       # add --build to rebuild images
```

The first start downloads model weights (~2 GB for the embedding model, ~8 GB for the
LLM), so `hoover4-ai-server` and `hoover4-vllm` take several minutes to report healthy.
`start-docker.sh` waits for health and prints what is still coming up.

### Use `start-docker.sh`, not bare `docker compose up`

A plain `docker compose up -d` in this directory fails in two ways that are easy to
misread, and the script checks both before starting anything:

1. **`network hoover4 not found`** — the network is declared `external` here and is
   created by the main stack. That has to be up first.
2. **`crun: cannot stat /usr/lib/libnvidia-*.so.<driver>: OCI runtime attempted to
   invoke a command that was not found`** — `/etc/cdi/nvidia.yaml` lists library mounts
   derived from the running driver version, and a partial driver upgrade (on this host:
   `nvidia-utils` at `610.57.04` while `nvidia-settings` is still at `610.43.03`) leaves
   entries pointing at files that were never installed. A CDI mount is a bind, so `crun`
   refuses to start the container at all. Only the two **GPU** services fail while the
   six others come up, which looks like a GPU problem and is not.

   The script prunes mounts whose host path does not exist, keeping a timestamped backup
   of the spec. The entries this hits in practice (`libnvidia-gtk3`,
   `libnvidia-wayland-client`) belong to `nvidia-settings` and are irrelevant to CUDA.
   **The durable fix is to bring every `nvidia-*` package to the same version**; until
   then `nvidia-ctk cdi generate` will reintroduce the bad entries.

The compose project name is pinned to `ai_services` so the model caches
(`ai_services_ai_models_cache` ~6 GB, `ai_services_vllm_huggingface_cache` ~16 GB) stay
attached. Changing it orphans them and re-downloads every weight.

### Podman specifics

* GPUs are requested with `devices: nvidia.com/gpu=all` (CDI). The
  `deploy.resources.reservations.devices` block docker-compose uses is **silently
  ignored** by podman-compose — services appeared to start and then ran on CPU.
* `HEALTHCHECK` in a Dockerfile is dropped for OCI images, so healthchecks are declared
  in the compose file.
* Both GPU services share one 24 GB card. `VLLM_GPU_FRACTION` (default `0.45`) is the
  knob to turn down first if either OOMs.

### Testing

Python here runs **in containers only**. To run the collection-search server's tests:

```bash
podman run --rm hoover4-mcp-collections:local python -m pytest tests/ -q
```

---

# Legacy notes

The sections below describe the original multi-host RAG design. Kept for reference;
the Milvus-based ingestion path they describe is not wired up.

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
