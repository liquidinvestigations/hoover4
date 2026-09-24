# BUILD CONTEXT IS `main_services/agents`, NOT THIS DIRECTORY. The agent imports the tool
# pack table from `agent_common`, and a Docker build cannot reach outside its context. If
# you move this file, move `context:` in ops/docker/compose/research-agents.yaml with it.
#
# Only the `agent_common` package folder is copied, onto the path beside the agent's own
# package. The agent reads `agent_common.tool_packs` alone, which imports nothing outside
# the standard library, so the shared package's own dependencies are not installed here.
FROM python:3.13.3-slim AS builder
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv" \
    BLIS_ARCH="generic"
ENV PATH="$VENV_PATH/bin:$PATH"
RUN apt-get update && apt-get install --no-install-recommends -y \
    build-essential \
    gcc \
    libpq-dev libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR $PYSETUP_PATH
RUN python -m venv $VENV_PATH
COPY research_agent/pyproject.toml ./
COPY research_agent/poetry.lock ./
COPY research_agent/README.md ./
COPY research_agent/research_agent/ ./research_agent/
# Install the package and its dependencies
RUN $VENV_PATH/bin/pip install --upgrade pip && \
    $VENV_PATH/bin/pip install poetry && \
    $VENV_PATH/bin/poetry config virtualenvs.create false && \
    $VENV_PATH/bin/poetry install --without dev

FROM python:3.13.3-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    VENV_PATH="/opt/pysetup/.venv"
ENV PATH="$VENV_PATH/bin:$PATH"

WORKDIR /app
COPY --from=builder $VENV_PATH $VENV_PATH
COPY research_agent/pyproject.toml ./
COPY research_agent/research_agent/ ./research_agent/
COPY agent_common/agent_common/ ./agent_common/
COPY research_agent/main.py ./
COPY research_agent/README.md ./

# Install requests for health check
RUN pip install requests

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5).raise_for_status()" || exit 1

# Set the default command to run the application
CMD ["python", "main.py"]

EXPOSE 8000
