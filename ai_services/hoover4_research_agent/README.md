# Research Agent API

A FastAPI-based research agent with MCP (Model Context Protocol) tool integration, providing streaming chat capabilities for research assistance.

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
