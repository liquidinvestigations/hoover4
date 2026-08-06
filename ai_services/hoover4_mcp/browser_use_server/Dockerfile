# Hoover4 browser MCP server.
#
# This image is large (~1 GB) because it carries Chromium and its shared libraries.
# That is expected and is the point of the server — do not try to slim it by dropping
# fonts or libraries, because the failure mode is a browser that starts and then renders
# nothing.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8087 \
    # nodriver looks for a browser on PATH; be explicit so it cannot pick up something else.
    BROWSER_EXECUTABLE=/usr/bin/chromium

WORKDIR /app

# chromium plus the runtime libraries it dlopens. fonts-liberation and the CJK fonts are
# not optional decoration: without them text-heavy pages render as boxes and innerText
# comes back as garbage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        ca-certificates \
        fonts-liberation \
        fonts-noto-core \
        fonts-noto-cjk \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdbus-1-3 \
        libdrm2 \
        libgbm1 \
        libnspr4 \
        libnss3 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxkbcommon0 \
        libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

COPY ./hoover4_mcp/browser_use_server/pyproject.toml ./
COPY ./hoover4_mcp/browser_use_server/browser_use_server/ ./browser_use_server/
COPY ./hoover4_mcp/browser_use_server/tests/ ./tests/

RUN pip install --no-cache-dir . && pip install --no-cache-dir pytest pytest-asyncio

EXPOSE 8087

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8087')}/health\", timeout=5)" || exit 1

CMD ["python", "-m", "browser_use_server.server"]
