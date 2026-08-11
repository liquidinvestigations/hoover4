# WHOIS Search MCP Server Dockerfile
# This builds an MCP server that provides WHOIS domain lookup functionality
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
COPY ./pyproject.toml ./poetry.lock ./
COPY ./whois_server/ ./whois_server/

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
    PORT=8083

ENV PATH="$VENV_PATH/bin:$PATH"

# Create application directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder $VENV_PATH $VENV_PATH

# Copy application files
COPY ./whois_server/ ./whois_server/
COPY ./pyproject.toml ./

# Expose the port
EXPOSE 8083

# Health check. It probes $PORT rather than the literal above, because compose sets a
# different one: a probe pinned to the image's default reports a working server as
# `unhealthy` forever, which is worse than no healthcheck — it trains the operator to
# ignore the one column that says whether the stack came up.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, requests; requests.get('http://localhost:%s/health' % os.environ.get('PORT', '8083'), timeout=5)" || exit 1

# Run the MCP server
CMD ["python", "whois_server/server.py"]
