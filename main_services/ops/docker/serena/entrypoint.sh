#!/bin/sh
# Serena MCP server over streamable HTTP, bound by compose to 127.0.0.1 only.
#
# --project is the repo root, mounted at the IDENTICAL absolute path as on the host
# (HOOVER4_REPO_ROOT, set by deploy.py): Serena returns absolute paths to the agent,
# and the agent edits files on the host, so any path mismatch sends edits nowhere.
#
# --transport streamable-http serves the MCP endpoint at /mcp (see .mcp.json at the
# repo root). The older SSE transport carries the client's session in a held GET: when
# that stream dies -- a container restart, a redeploy, a dropped connection -- the client
# reconnects the stream but does not repeat the `initialize` handshake, so every later
# call is refused for the life of that session. The signature is `Invalid request
# parameters` in the harness while this container logs `Received request before
# initialization was complete`. Streamable HTTP carries the session in an `Mcp-Session-Id`
# header and tells a client presenting an unknown one 404, which makes it re-handshake, so
# a restart costs one failed call rather than the session. It is also the only remote
# transport some harnesses speak.
set -e

if [ -z "${HOOVER4_REPO_ROOT:-}" ]; then
    echo "entrypoint: HOOVER4_REPO_ROOT is not set" >&2
    exit 1
fi

exec uvx --from "git+https://github.com/oraios/serena@${SERENA_GIT_REF}" \
    serena start-mcp-server \
    --project "${HOOVER4_REPO_ROOT}" \
    --transport streamable-http \
    --host 0.0.0.0 \
    --port 21940 \
    --enable-web-dashboard false \
    --open-web-dashboard false \
    --enable-gui-log-window false \
    --log-level INFO
