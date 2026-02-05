# Milvus Search MCP Server Dockerfile
# This builds an MCP server that provides Hoover4 Milvus search functionality
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

# Copy project files (need to copy hoover4_ai_clients dependency too)
COPY ./hoover4_mcp/milvus_search_server/pyproject.toml ./hoover4_mcp/milvus_search_server/poetry.lock ./
COPY ./hoover4_mcp/milvus_search_server/milvus_server/ ./milvus_server/
COPY ./hoover4_ai_clients/ ./hoover4_ai_clients/
# Create the expected directory structure for the relative path in pyproject.toml
RUN mkdir -p ../../hoover4_ai_clients && cp -r ./hoover4_ai_clients/* ../../hoover4_ai_clients/

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
    PORT=8081

ENV PATH="$VENV_PATH/bin:$PATH"

# Create application directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder $VENV_PATH $VENV_PATH

# Copy application files
COPY ./hoover4_mcp/milvus_search_server/milvus_server/ ./milvus_server/
COPY ./hoover4_mcp/milvus_search_server/pyproject.toml ./
COPY --from=builder /opt/pysetup/hoover4_ai_clients/hoover4_ai_clients/ ./hoover4_ai_clients/

# Expose the port
EXPOSE 8082

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8082/health', timeout=5)" || exit 1

# Run the MCP server
CMD ["python", "milvus_server/server.py"]
