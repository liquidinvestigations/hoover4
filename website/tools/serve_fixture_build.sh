#!/usr/bin/env bash
# Serve a website build with the cargo feature `browser-fixtures` beside the stack website.
# The scenarios in website/browser-tests/fixture-build/ open its harness pages.
#
# Usage: website/tools/serve_fixture_build.sh start|stop
#
# start runs `dx serve` with the feature in hoover4-website on FIXTURE_PORT (default 8090).
# The build has its own cargo target folder, so the stack website and its build stay as they are.
# The first build copies the build caches of the stack website before it compiles.
# When the build answers, the script starts tools/identity_proxy.py in hoover4-mcp-browser
# on PROXY_PORT (default 8091) of the loopback address. The proxy asserts the account admin
# with the group admin, as the development sign-in proxy does. Then run this command.
#
#   website/take-screenshots.sh --fixture-build --target http://localhost:8091 --names view-doc-two-previews
#
# stop ends both processes. A restart of either container also ends them.
set -euo pipefail

FIXTURE_PORT="${FIXTURE_PORT:-8090}"
PROXY_PORT="${PROXY_PORT:-8091}"
TARGET_DIR=/tmp/h4-fixture-target
LOG=/tmp/h4-fixture-serve.log
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

case "${1:-}" in
    start)
        docker exec hoover4-website sh -c "mkdir -p $TARGET_DIR && for d in wasm32-unknown-unknown x86_64-unknown-linux-gnu; do [ -d $TARGET_DIR/\$d ] || cp -a /app/target/\$d $TARGET_DIR/; done"
        docker exec -d hoover4-website sh -lc "export PATH=/usr/local/cargo/bin:\$PATH && cd /app && CARGO_TARGET_DIR=$TARGET_DIR exec dx serve --fullstack --package frontend --renderer web --port $FIXTURE_PORT --addr 0.0.0.0 --open false --hot-reload false --watch false --features browser-fixtures > $LOG 2>&1"
        for _ in $(seq 1 240); do
            code=$(docker exec hoover4-website curl -s -o /dev/null -w '%{http_code}' -H 'X-Forwarded-User: admin' -H 'X-Forwarded-Groups: admin' "http://localhost:$FIXTURE_PORT/" || true)
            [ "$code" = "200" ] && break
            sleep 5
        done
        if [ "$code" != "200" ]; then
            echo "error: the fixture build does not answer. Read $LOG in hoover4-website." >&2
            exit 1
        fi
        docker cp "$repo_root/website/tools/identity_proxy.py" hoover4-mcp-browser:/tmp/identity_proxy.py
        docker exec -d hoover4-mcp-browser python /tmp/identity_proxy.py --listen "$PROXY_PORT" \
            --upstream "http://hoover4-website:$FIXTURE_PORT" --user admin --groups admin
        echo "fixture build answers. Target: http://localhost:$PROXY_PORT"
        ;;
    stop)
        docker exec hoover4-mcp-browser pkill -f /tmp/identity_proxy.py || true
        docker exec hoover4-website pkill -f "features browser-fixtures" || true
        # dx starts the built server as a child process, which outlives dx.
        docker exec hoover4-website pkill -f "$TARGET_DIR/" || true
        echo "stopped"
        ;;
    *)
        echo "usage: $0 start|stop" >&2
        exit 2
        ;;
esac
