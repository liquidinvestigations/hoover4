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
COPY hoover4_research_agent/pyproject.toml ./
COPY hoover4_research_agent/poetry.lock ./
COPY hoover4_research_agent/README.md ./
COPY hoover4_research_agent/research_agent/ ./research_agent/
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
COPY hoover4_research_agent/pyproject.toml ./
COPY hoover4_research_agent/research_agent/ ./research_agent/
COPY hoover4_research_agent/main.py ./
COPY hoover4_research_agent/README.md ./

# Install requests for health check
RUN pip install requests

# Add health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5).raise_for_status()" || exit 1

# Set the default command to run the application
CMD ["python", "main.py"]

EXPOSE 8000
