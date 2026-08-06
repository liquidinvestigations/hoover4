# Hoover4 metasearch MCP server.
#
# Same plain slim+pip pattern as the collection search server: this one only makes HTTP
# requests and parses HTML, so it needs no browser, no CUDA and no build toolchain.
# (The browser_use_server next door is the one that needs Chromium.)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8086

WORKDIR /app

COPY ./hoover4_mcp/metasearch_server/pyproject.toml ./
COPY ./hoover4_mcp/metasearch_server/metasearch_server/ ./metasearch_server/
COPY ./hoover4_mcp/metasearch_server/tests/ ./tests/

RUN pip install --no-cache-dir . && pip install --no-cache-dir pytest pytest-asyncio

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8086')}/health\", timeout=5)" || exit 1

CMD ["python", "-m", "metasearch_server.server"]
