# DuckDuckGo Search MCP Server Dockerfile
# This builds an MCP server that provides DuckDuckGo search functionality
FROM python:3.12-slim AS builder

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$VENV_PATH/bin:$PATH"

# Install system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Set up Python virtual environment
WORKDIR $PYSETUP_PATH
RUN python -m venv $VENV_PATH

# Copy project files
COPY ./hoover4_mcp/ddg_search_server/pyproject.toml ./hoover4_mcp/ddg_search_server/poetry.lock ./
COPY ./hoover4_mcp/ddg_search_server/ddg_server/ ./ddg_server/

# Install dependencies
RUN $VENV_PATH/bin/pip install --upgrade pip && \
    $VENV_PATH/bin/pip install poetry && \
    $VENV_PATH/bin/poetry config virtualenvs.create false && \
    $VENV_PATH/bin/poetry install --no-root

# Runtime stage
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    VENV_PATH="/opt/pysetup/.venv" \
    HOST=0.0.0.0 \
    PORT=8080

ENV PATH="$VENV_PATH/bin:$PATH"

# Create application directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder $VENV_PATH $VENV_PATH

# Copy application files
COPY ./hoover4_mcp/ddg_search_server/ddg_server/ ./ddg_server/
COPY ./hoover4_mcp/ddg_search_server/pyproject.toml ./

# Expose the port
EXPOSE 8080

# Health check (assuming the MCP server has a health endpoint)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)" || exit 1

# Run the MCP server
CMD ["python", "ddg_server/server.py"]
