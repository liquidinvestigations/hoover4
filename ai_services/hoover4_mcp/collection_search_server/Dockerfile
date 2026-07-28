# Hoover4 collection search MCP server.
#
# Deliberately a plain slim image with pip: this server talks to ClickHouse and
# Manticore over HTTP and needs no database drivers, no CUDA and no build toolchain, so
# it builds in seconds and can be rebuilt freely while iterating on the tools.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8085

WORKDIR /app

COPY ./hoover4_mcp/collection_search_server/pyproject.toml ./
COPY ./hoover4_mcp/collection_search_server/collection_search_server/ ./collection_search_server/
COPY ./hoover4_mcp/collection_search_server/tests/ ./tests/

RUN pip install --no-cache-dir . && pip install --no-cache-dir pytest

EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8085')}/health\", timeout=5)" || exit 1

CMD ["python", "-m", "collection_search_server.server"]
