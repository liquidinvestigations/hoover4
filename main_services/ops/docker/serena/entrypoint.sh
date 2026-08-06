#!/bin/sh
# Serena MCP server over SSE, bound by compose to 127.0.0.1 only.
#
# --project is the repo root, mounted at the IDENTICAL absolute path as on the host
# (HOOVER4_REPO_ROOT, set by deploy.py): Serena returns absolute paths to the agent,
# and the agent edits files on the host, so any path mismatch sends edits nowhere.
#
# --transport sse serves the MCP endpoint at /sse (see .mcp.json at the repo root).
set -e

if [ -z "${HOOVER4_REPO_ROOT:-}" ]; then
    echo "entrypoint: HOOVER4_REPO_ROOT is not set" >&2
    exit 1
fi

exec uvx --from "git+https://github.com/oraios/serena@${SERENA_GIT_REF}" \
    serena start-mcp-server \
    --project "${HOOVER4_REPO_ROOT}" \
    --transport sse \
    --host 0.0.0.0 \
    --port 21940 \
    --enable-web-dashboard false \
    --open-web-dashboard false \
    --enable-gui-log-window false \
    --log-level INFO
