# Hoover4 agent todo MCP server.
#
# BUILD CONTEXT IS `main_services`, NOT THIS DIRECTORY AND NOT `main_services/agents`.
# This is the one MCP server whose context is wider than the agents directory, and the
# reason is the store: the four tools are a wrapper over
# `processing/database/chat_todos.py`, which the chat workflow reads directly. Copying
# that module in is what keeps the two readers of the plan agreeing about it; vendoring
# a second copy would mean the cancellation rule could be relaxed in one of them
# without the other noticing. A Docker build cannot reach outside its context, so the
# context is the parent of both. `main_services/.dockerignore` narrows it back down --
# without it the context is the whole tree, virtualenv and test corpus included.
#
# If you move this file, move `context:` in ops/docker/compose/agents.yaml with it.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8088

WORKDIR /app

COPY ./agents/agent_common/ ./agent_common/
RUN pip install --no-cache-dir ./agent_common

# The store, importable as `database.chat_todos` exactly as it is in the worker. Only
# the modules: the migration directories are applied by the pipeline, never from here.
COPY ./processing/database/*.py ./database/

COPY ./agents/agent_todo_server/pyproject.toml ./
COPY ./agents/agent_todo_server/agent_todo_server/ ./agent_todo_server/
COPY ./agents/agent_todo_server/tests/ ./tests/
# The shared package's tests, under the one target a runner reaches. Without this they
# ship in the image and run in nothing, so a regression in `agent_common` lands silently.
COPY ./agents/agent_common/tests/ ./tests/shared/

RUN pip install --no-cache-dir . && pip install --no-cache-dir pytest

EXPOSE 8088

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8088')}/health\", timeout=5)" || exit 1

CMD ["python", "-m", "agent_todo_server.server"]
