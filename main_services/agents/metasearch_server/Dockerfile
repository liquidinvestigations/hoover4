# Hoover4 metasearch MCP server.
#
# Same plain slim+pip pattern as the collection search server: this one only makes HTTP
# requests and parses HTML, so it needs no browser, no CUDA and no build toolchain.
# (The browser_use_server next door is the one that needs Chromium.)
#
# BUILD CONTEXT IS `main_services/agents`, NOT THIS DIRECTORY. `agent_common/` is vendored
# into the image (the artifact writer, the MinIO helper and the rerank client are shared
# with the browser router), and a Docker build cannot reach outside its context. If you
# move this file, move `context:` in ops/docker/compose/agents.yaml with it.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8086

WORKDIR /app

COPY ./agent_common/ ./agent_common/
RUN pip install --no-cache-dir ./agent_common

COPY ./metasearch_server/pyproject.toml ./
COPY ./metasearch_server/metasearch_server/ ./metasearch_server/
COPY ./metasearch_server/tests/ ./tests/

RUN pip install --no-cache-dir . && pip install --no-cache-dir pytest pytest-asyncio

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8086')}/health\", timeout=5)" || exit 1

CMD ["python", "-m", "metasearch_server.server"]
