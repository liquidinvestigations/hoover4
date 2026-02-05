# Hoover4 AI Server Dockerfile
# This builds a FastAPI-based embedding server using multilingual-e5-large-instruct model
# with support for embeddings, reranking, and NER functionality on GPU/CPU
FROM nvidia/cuda:12.6.0-devel-ubuntu22.04 AS builder

# Set environment variables for NVIDIA GPU support
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    DEBIAN_FRONTEND=noninteractive

# Set environment variables for Python and dependency management
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

ENV PATH="$VENV_PATH/bin:$PATH"

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install --no-install-recommends -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
    python3.13 \
    python3.13-venv \
    python3.13-dev \
    build-essential \
    gcc \
    libpq-dev \
    libc6-dev \
    wget \
    curl \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13 \
    && ln -s /usr/bin/python3.13 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Set up Python virtual environment
WORKDIR $PYSETUP_PATH
RUN python -m venv $VENV_PATH

# Copy Python project files
COPY ./hoover4_ai_server/pyproject.toml ./
COPY ./hoover4_ai_server/hoover4_ai_server.py ./
COPY ./hoover4_ai_server/requirements.txt ./

# Install dependencies in virtual environment
RUN $VENV_PATH/bin/pip install --upgrade pip && \
    $VENV_PATH/bin/pip install -r requirements.txt

# Runtime stage - CUDA-enabled runtime image
FROM nvidia/cuda:12.6.0-runtime-ubuntu22.04 AS runtime

# Set environment variables for NVIDIA GPU support
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    DEBIAN_FRONTEND=noninteractive

ENV PYTHONUNBUFFERED=1 \
    VENV_PATH="/opt/pysetup/.venv" \
    HOST=0.0.0.0 \
    PORT=8000

ENV PATH="$VENV_PATH/bin:$PATH"

# Install runtime system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
    python3.13 \
    curl \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13 \
    && ln -s /usr/bin/python3.13 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder $VENV_PATH $VENV_PATH

# Copy application files
COPY ./hoover4_ai_server/hoover4_ai_server.py ./
COPY ./hoover4_ai_server/pyproject.toml ./

# Expose the port the app runs on
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=30s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# Run the FastAPI server
CMD ["python", "hoover4_ai_server.py"]
