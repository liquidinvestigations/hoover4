# Research Agent API

A FastAPI-based research agent with MCP (Model Context Protocol) tool integration, providing streaming chat capabilities for research assistance.

## The two agent profiles

One image, two containers, different tool sets — and the difference is deliberate.

| | `hoover4-internal-search-agent` (9099) | `hoover4-full-research-agent` (9090) |
|---|---|---|
| `AGENT_PROFILE` | `internal_search` | `full_research` |
| MCP servers | collections **only** | collections + metasearch + browser + ddg + whois + wikipedia |
| Used by | the website's AI Chat page | the Temporal `ResearchTask` |

**The internal-search agent has no web tools on purpose.** A chat about the user's own
documents must not quietly become a web search — the user cannot tell from the answer
which sentence came from their archive and which came from a search engine.

## The ACL header chain

An agent answering for a user must only reach collections that user could read in the
search UI:

1. The **website backend** resolves the user's permitted collections (group grants union
   public collections). It is the only component that can — it owns the auth tables.
2. It passes that list to the agent as `allowed_collections` on the `/chat` request.
3. `acl_headers()` turns it into `X-Hoover4-Collections: <list>` plus
   `Authorization: Bearer $MCP_SHARED_SECRET`, set as **MCP connection headers**.
4. The agent caches **one graph per ACL** (`_acl_key`), so a connection opened for one
   user is never reused for another.
5. `hoover4-mcp-collections` enforces the header on every tool call.

The model never sees or supplies its own permissions — they are not tool arguments, so it
cannot widen them. An empty list is sent as an empty header rather than omitted: "this user
may read nothing" and "no ACL was supplied" must not look the same to the MCP server, which
denies the second outright.

## System prompts live in `research_agent/prompts.py`

Not in compose. `SYSTEM_PROMPT` overrides; empty means "use the profile's canonical text".

**Keep them short.** Qwen3.5-2B follows a long, numbered, multi-clause prompt by doing all
of it forever: an earlier five-step draft made the model search, search again, then re-run
a query it had already run until the request died with no answer. Detail belongs in tool
descriptions, which the model reads in context at the moment it picks a tool. The Manticore
MATCH syntax deliberately lives in the collection MCP server's `instructions` instead, where
every agent reads it at tool-discovery time and there is only one copy to maintain.

## Stopping the model looping

Small models are bad at deciding they are finished. Given results that fully answer the
question, Qwen3.5-2B will still re-issue a search it has already run. Left alone that ends
in langgraph's `GraphRecursionError`, which surfaces as an **HTTP 500 with no answer at
all** — the least useful possible failure, since the tool results needed to answer were
already in hand.

`_create_graph` therefore routes to a `finalize` node when either guard trips:

* **a repeated tool call** — at temperature 0 the same call returns the same result, so a
  repeat is a stuck loop, not exploration;
* **`AGENT_MAX_TOOL_TURNS`** (default 12) tool-calling turns.

`finalize` removes the unsatisfied tool call (an OpenAI-shaped request carrying `tool_calls`
with no matching results is rejected), appends "answer now from what you already have", and
runs the same model **with no tools bound** — a model that cannot call a tool has to answer.
`AGENT_RECURSION_LIMIT` (default 40) is the hard backstop behind both.

`finalize` is an answer-producing node exactly like `agent`, so the SSE event loop must
watch both. Omitting it is why the forced answer first came back as an empty string with a
cheerful HTTP 200.

## `LLM_STREAMING` and `disable_streaming` — the Q12 finding

**Streaming is back on** (`LLM_STREAMING=true`), and the workaround is retained.

Under **vLLM 0.11**, streamed tool-call deltas arrived with the function name but
`arguments` absent. langchain turned those into `tool_call_chunk`s with `args=None`, which
never accumulated into the final `AIMessage`. `message.tool_calls` came back empty,
`should_continue` routed straight to `END`, and the agent produced a confident answer having
silently made **zero** tool calls. That is Q12, and it presented as "the model is bad".

`disable_streaming` is the switch that actually matters, not `streaming`: the latter only
affects `invoke`, while langgraph drives the model through `astream_events`, which calls
`astream` and streams regardless. With `disable_streaming=True`, `astream` degenerates to a
single `invoke` and the node emits a whole `AIMessage` with its `tool_calls` intact.

**Re-tested on vLLM 0.17.1 + Qwen3.5-2B: fixed.** With `LLM_STREAMING=true` a real agent run
made 4 tool calls and returned a correctly cited answer, so the default is now on and token
streaming is back. The code path and its comment are deliberately left in place — set
`LLM_STREAMING=false` if it ever regresses. **The symptom to watch for is an agent that
answers with no tool calls**, not an error.

Note this is a separate failure from the tool-*parser* problem: `--tool-call-parser hermes`
does not match Qwen3.5's XML blocks and produces the same zero-tool-call symptom for an
unrelated reason. See [`../README.md`](../README.md).

## Features

- 🤖 **AI Research Agent**: Powered by configurable LLM models
- 🔗 **MCP Integration**: Connect to multiple MCP servers for tool access
- 🌊 **Streaming Responses**: Real-time streaming of agent responses with reasoning
- 🚀 **FastAPI Backend**: Modern, fast web API with automatic documentation
- ⚙️ **Environment Configuration**: Fully configurable via environment variables
- 🏥 **Health Checks**: Built-in health monitoring and status endpoints

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd hoover4_research_agent

# Install dependencies
poetry install
```

### 2. Configuration

```bash
# Copy environment template
cp env.example .env

# Edit configuration
nano .env
```

### 3. Run the Server

```bash
# Start the API server
python main.py
```

The server will start on `http://localhost:8000` by default.

## Configuration

The application is configured entirely via environment variables. Copy `env.example` to `.env` and customize:

### Required Variables

- `LLM_API_KEY`: Your LLM API key
- `MCP_SERVERS`: Comma-separated list of MCP server URLs

### Optional Variables

- `LLM_BASE_URL`: Base URL for your LLM service
- `LLM_MODEL`: Model name to use
- `LLM_TEMPERATURE`: Temperature setting (default: 0.0)
- `AGENT_NAME`: Name of the agent
- `SYSTEM_PROMPT`: System prompt for the agent
- `HOST`: Host to bind to (default: 0.0.0.0)
- `PORT`: Port to bind to (default: 8000)
- `RELOAD`: Enable auto-reload for development (default: false)

## API Endpoints

### Health Check
- **GET** `/health` - Check agent status and readiness

### Chat Streaming
- **POST** `/chat/stream` - Stream chat responses from the agent

**Request Body:**
```json
{
  "query": "Your research question",
  "context_id": "unique_context_id",
  "thread_id": "unique_thread_id"
}
```

### API Information
- **GET** `/` - API information and configuration details

## Usage Examples

### Basic Chat Request

```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the latest developments in AI research?",
    "context_id": "research_123",
    "thread_id": "thread_456"
  }'
```

### Health Check

```bash
curl http://localhost:8000/health
```

### Python Client Example

```python
import asyncio
import aiohttp
import json

async def chat_with_agent():
    async with aiohttp.ClientSession() as session:
        payload = {
            "query": "Help me understand quantum computing",
            "context_id": "quantum_research",
            "thread_id": "session_001"
        }

        async with session.post(
            "http://localhost:8000/chat/stream",
            json=payload
        ) as response:
            async for line in response.content:
                if line:
                    line_str = line.decode('utf-8').strip()
                    if line_str.startswith('data: '):
                        data_str = line_str[6:]
                        chunk = json.loads(data_str)
                        print(f"Type: {chunk.get('type')}")
                        print(f"Content: {chunk.get('content')}")

# Run the example
asyncio.run(chat_with_agent())
```

## Response Format

The streaming endpoint returns Server-Sent Events with JSON data:

```json
{
  "is_task_complete": false,
  "type": "start",
  "content": ""
}
```

### Response Types

- `start`: Initial response start
- `start_reasoning`: Beginning of reasoning phase
- `reasoning`: Reasoning content (if supported by model)
- `start_response`: Beginning of final response
- `response`: Final response content
- `start_tool`: Tool execution start
- `end_tool`: Tool execution end
- `error`: Error occurred
- `end`: Final completion signal

## Development

### Running in Development Mode

```bash
# Enable auto-reload
export RELOAD=true
python main.py
```

### Testing

```bash
# Run tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=research_agent
```

### Code Quality

```bash
# Format code
poetry run black .

# Lint code
poetry run ruff check .

# Type checking
poetry run mypy research_agent/
```

## Docker Support

```dockerfile
# Dockerfile is included for containerized deployment
docker build -t research-agent .
docker run -p 8000:8000 --env-file .env research-agent
```

## Architecture

### Components

- **FastAPI Application**: Web API with lifespan management
- **MCP Gateway Agent**: Core agent with MCP tool integration
- **Streaming Handler**: Real-time response streaming
- **Environment Configuration**: Flexible configuration system

### MCP Integration

The agent connects to MCP servers to access various tools and capabilities:

- Database connections
- File system access
- External API integrations
- Custom research tools

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Run the test suite
6. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For questions, issues, or contributions, please open an issue on the GitHub repository.
