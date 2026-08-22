# Hoover4 browser MCP router.
#
# This image is large (~1.5 GB) because it carries Chromium, its shared libraries and
# fonts, Node, and the two ad/consent blockers. That is expected and is the point of the
# server — do not try to slim it by dropping fonts or libraries, because the failure mode
# is a browser that starts and then renders nothing.
#
# BUILD CONTEXT IS `main_services/agents`, NOT THIS DIRECTORY. `agent_common/` is vendored
# into the image (the artifact writer and the MinIO helper are shared with the metasearch
# server), and a Docker build cannot reach outside its context. If you move this file,
# move `context:` in ops/docker/compose/agents.yaml with it.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOST=0.0.0.0 \
    PORT=8087 \
    # nodriver looks for a browser on PATH; be explicit so it cannot pick up something else.
    BROWSER_EXECUTABLE=/usr/bin/chromium \
    BROWSER_EXTENSIONS_DIR=/opt/browser-extensions \
    PLAYWRIGHT_MCP_BIN=/opt/playwright-mcp/node_modules/.bin/playwright-mcp

WORKDIR /app

# chromium plus the runtime libraries it dlopens. fonts-liberation and the CJK fonts are
# not optional decoration: without them text-heavy pages render as boxes and innerText
# comes back as garbage.
#
# nodejs is for the @playwright/mcp sidecar, one process per live chat.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        ca-certificates \
        curl \
        unzip \
        nodejs \
        npm \
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

# The MCP sidecar. PINNED, never @latest: a silently updated sidecar changes the entire
# tool surface the agent sees, mid-conversation, with nothing in the transcript saying so.
#
# PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD: the sidecar attaches to the Chromium above over CDP
# and never launches one of its own, so Playwright's own ~400 MB browser bundle would be
# dead weight.
ARG PLAYWRIGHT_MCP_VERSION=0.0.79
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN mkdir -p /opt/playwright-mcp \
    && cd /opt/playwright-mcp \
    && npm install --no-audit --no-fund --omit=dev "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" \
    && test -x /opt/playwright-mcp/node_modules/.bin/playwright-mcp

# uBlock Origin Lite and "I still don't care about cookies", unpacked at build time from
# PINNED GitHub release URLs with their checksums verified. Both projects publish the
# unpacked Chromium extension as a release asset, which is versioned and immutable — the
# Chrome Web Store's CRX endpoint is neither, and a blocker that updates itself changes
# what the agent sees with nothing recording it.
#
# Ids and versions are recorded in README.md. Keep them in step with the ARGs here.
ARG UBOL_VERSION=2026.804.1652
ARG UBOL_SHA256=062d95b68aea70e6173a4c30d5f48a4d79f23ce889f3335a50b3edf7992c6c38
ARG ISDCAC_VERSION=1.1.9
ARG ISDCAC_SHA256=8f70ab947cb2d274f4022a970f5dd3cecd8ec02b060e05187bef9ee3cb18bbcb
RUN set -eux; \
    mkdir -p /opt/browser-extensions/ubol /opt/browser-extensions/isdcac; \
    curl -fsSL -o /tmp/ubol.zip \
      "https://github.com/uBlockOrigin/uBOL-home/releases/download/${UBOL_VERSION}/uBOLite_${UBOL_VERSION}.chromium.zip"; \
    echo "${UBOL_SHA256}  /tmp/ubol.zip" | sha256sum -c -; \
    unzip -q /tmp/ubol.zip -d /opt/browser-extensions/ubol; \
    curl -fsSL -o /tmp/isdcac.zip \
      "https://github.com/OhMyGuus/I-Still-Dont-Care-About-Cookies/releases/download/v${ISDCAC_VERSION}/ISDCAC-chrome-source.zip"; \
    echo "${ISDCAC_SHA256}  /tmp/isdcac.zip" | sha256sum -c -; \
    unzip -q /tmp/isdcac.zip -d /opt/browser-extensions/isdcac; \
    rm -f /tmp/ubol.zip /tmp/isdcac.zip; \
    test -f /opt/browser-extensions/ubol/manifest.json; \
    test -f /opt/browser-extensions/isdcac/manifest.json

COPY ./agent_common/ ./agent_common/
RUN pip install --no-cache-dir ./agent_common

COPY ./browser_use_server/pyproject.toml ./
COPY ./browser_use_server/browser_use_server/ ./browser_use_server/
COPY ./browser_use_server/tests/ ./tests/
# The shared package's tests, under the one target a runner reaches. Without this they
# ship in the image and run in nothing, so a regression in `agent_common` lands silently
# in all three server images at once.
COPY ./agent_common/tests/ ./tests/shared/

RUN pip install --no-cache-dir . && pip install --no-cache-dir pytest pytest-asyncio

EXPOSE 8087

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT','8087')}/health\", timeout=5)" || exit 1

CMD ["python", "-m", "browser_use_server.server"]
