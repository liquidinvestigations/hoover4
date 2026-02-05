# Hoover4 RAG Chain

A comprehensive RAG (Retrieval-Augmented Generation) system built with Milvus vector store, advanced reranking, and chat history support.

> ** Project Overview**: This is part of the [Alex RAG Demo](../README.md) project - a comprehensive RAG system with document ingestion, vector search, and interactive chat interface. This component provides the main RAG chain implementation and CLI interface.

## Features

- **Advanced Retrieval**: Retrieves 120 documents before reranking, then uses reranker to get top 10 most relevant documents
- **Hybrid Search**: Supports both semantic and hybrid search modes with entity-aware retrieval
- **Chat History**: Maintains conversation context with LLM-based question extraction
- **Streaming Responses**: Real-time streaming of LLM responses for better user experience
- **Metadata Extraction**: Extracts and displays document metadata for better context
- **Multi-LLM Support**: Uses LiteLLM for OpenAI, Anthropic, Ollama, and other providers
- **CLI Interface**: Full command-line interface with interactive chat mode

## Components

### Core RAG Chain (`chains/rag.py`)
- `build_hoover4_rag_chain()`: Main function to build RAG chain with all functionality
- Returns a LangChain Runnable that accepts question strings directly
- Supports both single queries and streaming responses

### Question Extractor Chain (`chains/question_extractor.py`)
- `QuestionExtractorChain`: Dedicated chain for question enhancement and reformulation
- `QuestionExtractorChainFactory`: Factory for creating different extractor configurations
- Multiple extractor types: default, aggressive, conservative, and custom
- Context-aware question enhancement based on chat history

### CLI Interface (`scripts/rag_cli.py`)
- Command-line interface for querying the RAG system
- Interactive chat mode
- Configuration display
- Verbose output with document details
- Question extractor configuration options

## Installation

> ** Quick Start**: For the complete RAG system setup, see the [main project README](../README.md) Quick Start section.

1. Install dependencies:
```bash
poetry install
```

2. Set up environment variables:
```bash
export LLM_API_KEY="your_llm_api_key_here"  # For OpenAI, Anthropic, or Ollama
```

3. Ensure all AI services are running:
   - [Milvus vector database](https://milvus.io/)
   - [Hoover4 AI server](../hoover4_ai_server/README.md) (embeddings, NER, reranker)

## Usage

### CLI Usage

#### Single Query
```bash
python hoover4_rag/scripts/rag_cli.py query "What is machine learning?"
```

#### Interactive Chat (Terminal-based)
```bash
python hoover4_rag/scripts/rag_cli.py query
```

#### Interactive Chat with Streaming
```bash
python hoover4_rag/scripts/rag_cli.py query --stream
```

The interactive chat provides a terminal-based experience:
- User messages are marked with `>>> ` prompt
- Responses are printed on new lines after the question
- Type `exit` or press `Ctrl+C` to end the conversation
- Available commands: `clear`, `history`, `help`
- Use `--stream` flag for real-time streaming responses

#### Show Configuration
```bash
python hoover4_rag/scripts/rag_cli.py config
```

#### Verbose Query with Documents
```bash
python hoover4_rag/scripts/rag_cli.py query "Tell me about AI" --verbose --show-documents
```

#### Streaming Query
```bash
python hoover4_rag/scripts/rag_cli.py query "Tell me about AI" --stream
```

#### Question Extractor Configuration
```bash
# Use aggressive question extraction with more history context
python hoover4_rag/scripts/rag_cli.py query --question-extractor-type aggressive --question-extractor-history 10

# Use conservative extraction with custom temperature
python hoover4_rag/scripts/rag_cli.py query --question-extractor-type conservative --question-extractor-temp 0.5

# Disable question extraction entirely
python hoover4_rag/scripts/rag_cli.py query --disable-question-extraction
```

### Programmatic Usage

```python
from hoover4_rag.chains.rag import build_hoover4_rag_chain

# Initialize the RAG chain
rag_chain = build_hoover4_rag_chain(
    llm_api_key="your_api_key",
    initial_retrieval_k=120,
    final_retrieval_k=10,
    search_mode="hybrid"
)

# Single query - pass question string directly
response = rag_chain.invoke("What is machine learning?")
print(response["response"])

# Interactive session
while True:
    question = input("You: ")
    if question.lower() in ['quit', 'exit']:
        break
    response = rag_chain.invoke(question)
    print(f"Assistant: {response['response']}")
```

## Configuration Options

### RAG Chain Parameters

- `initial_retrieval_k`: Number of documents to retrieve before reranking (default: 120)
- `final_retrieval_k`: Number of documents to keep after reranking (default: 10)
- `search_mode`: Search mode - "semantic" or "hybrid" (default: "hybrid")
- `max_chat_history`: Maximum number of messages to keep in chat history (default: 10)
- `question_extraction_enabled`: Whether to use LLM for question extraction (default: True)

### Service URLs

- `embeddings_base_url`: Embeddings service URL (default: http://localhost:8000/v1)
- `ner_base_url`: NER service URL (default: http://localhost:8000/v1)
- `reranker_base_url`: Reranker service URL (default: http://localhost:8000/v1)

### LLM Configuration (LiteLLM)

- `llm_api_key`: LLM API key (for OpenAI, Anthropic, Ollama, etc.)
- `llm_model`: LLM model to use (default: gpt-3.5-turbo)
- `llm_temperature`: Temperature for generation (default: 0.7)
- `llm_base_url`: Custom base URL for LLM API (optional, for Ollama, etc.)

## Architecture

The RAG chain follows this workflow:

1. **Question Enhancement**: Uses LLM to enhance the question based on chat history
2. **Initial Retrieval**: Retrieves 120 documents using hybrid search (dense + sparse/BM25)
3. **Entity-Aware Search**: Uses NER to extract entities and search specific sparse fields
4. **Reranking**: Uses reranker to score and rank documents by relevance
5. **Final Selection**: Keeps top 10 most relevant documents
6. **Answer Generation**: Uses LLM (via LiteLLM) with context and chat history
7. **History Update**: Adds interaction to chat history

## Chat History Features

- **Context Awareness**: Uses previous conversation context to enhance questions
- **LLM Question Extraction**: Automatically refines questions based on conversation history
- **Configurable Length**: Adjustable maximum history length
- **Clear Function**: Ability to clear history during conversation
- **LangChain Integration**: Uses proper `MessagesPlaceholder` for structured chat history
- **Message Types**: Supports Human, AI, and System message types

### Question Extractor Features

- **Multiple Extractors**: Default, aggressive, conservative, and custom configurations
- **Context-Aware Enhancement**: Analyzes conversation history to improve questions
- **Configurable Behavior**: Adjustable temperature, history length, and extraction style
- **Factory Pattern**: Easy creation of different extractor types
- **Batch Processing**: Support for processing multiple questions at once
- **Statistics**: Detailed stats about extractor configuration and performance

## Error Handling

The system includes robust error handling:
- Graceful fallbacks when services are unavailable
- Detailed error logging
- User-friendly error messages

## Examples

### Basic Query
```bash
python hoover4_rag/scripts/rag_cli.py query "How does neural network training work?"
```

### Interactive Chat with Context
```bash
python hoover4_rag/scripts/rag_cli.py query

================================================================================
HOOVER4 RAG CHAT INTERFACE
================================================================================
Commands: 'clear' (clear history), 'history' (show history), 'help' (show help)
Type 'exit' or press Ctrl+C to end the conversation
================================================================================

>>> What is machine learning?

Machine learning is a subset of artificial intelligence that focuses on algorithms and statistical models that enable computer systems to improve their performance on a specific task through experience, without being explicitly programmed for every scenario.

>>> How is it different from deep learning?

Deep learning is actually a subset of machine learning that uses artificial neural networks with multiple layers (hence "deep") to model and understand complex patterns in data. While traditional machine learning often relies on hand-engineered features, deep learning can automatically learn feature representations from raw data.
```

### Verbose Output
```bash
python hoover4_rag/scripts/rag_cli.py query "Explain transformers" --verbose --show-documents
```

This will show:
- The answer
- Metadata (question enhancement, document count, etc.)
- Retrieved documents with metadata
- Reranking scores

##  Related Components

- **[Main Project](../README.md)**: Complete RAG system setup and usage
- **[Hoover4 AI Server](../hoover4_ai_server/README.md)**: FastAPI server providing embeddings, NER, and reranking services
- **[Hoover4 AI Clients](../hoover4_ai_clients/README.md)**: Client libraries for connecting to AI services
