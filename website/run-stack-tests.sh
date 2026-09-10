#!/bin/bash
# Run the backend's live-stack integration tests.
#
# Usage: ./run-stack-tests.sh [--slow] [extra cargo test args...]
#
#   (no flag)  run only the fast tests. Each asserts its own wall time against
#              HOOVER4_STACK_TEST_BUDGET_MS (default 5000) and fails if it goes over.
#   --slow     also run the `slow_*` tests. Those wait out the 30 s shard-state cache
#              and a ClickHouse mutation, so they cost one to two minutes EACH and are
#              excluded by default -- a suite nobody runs is worth nothing.
#
# Preconditions: the stack is up and `main_services/verify-stack.sh` has been run, so the
# canonical fixtures are ingested. The tests assert properties of NAMED fixture folders
# (pdf-doc-txt, eml-2-attachment, zip-in-multiple-locations, many-children), not counts
# of the whole corpus.
#
# Rust is not on $PATH in the website container, hence the explicit export. Running the
# tests inside that container rather than on the host is what makes CLICKHOUSE_URL and
# MANTICORE_URL resolve without a port-forward.
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

WEBSITE_CONTAINER="${WEBSITE_CONTAINER:-hoover4-website}"
SLOW=0
if [ "${1:-}" = "--slow" ]; then
    SLOW=1
    shift
fi

url_host() {
    local url="$1" rest host
    rest="${url#*://}"
    rest="${rest%%/*}"
    if [ "${rest#\[}" != "$rest" ]; then
        host="${rest#\[}"
        host="${host%%]*}"
        printf '%s' "$host"
        return
    fi
    printf '%s' "${rest%%:*}"
}

site_url_is_local() {
    local host="$1"
    case "$host" in
        localhost|127.0.0.1|0.0.0.0|::1) return 0 ;;
        hoover4-*.*) ;;
        hoover4-*) return 0 ;;
    esac
    return 1
}

if [ -n "${HOOVER4_SITE_URL:-}" ]; then
    if ! site_url_is_local "$(url_host "$HOOVER4_SITE_URL")"; then
        echo "error: the stack suite refuses a non-local HOOVER4_SITE_URL." >&2
        echo "       These tests run inside the website container against the local stack." >&2
        exit 2
    fi
fi

# `dx check` is the only thing that finds a hook called conditionally or inside a closure.
# Such a hook shifts every hook index after it on the render that adds it and traps the
# WebAssembly runtime: the page paints, then nothing re-renders and no handler ever fires
# again. `cargo check` is blind to it and the release build reports only
# `RuntimeError: unreachable`, so it runs here, first, and a failure stops the suite.
echo "== dx check (hook order) =="
docker exec "$WEBSITE_CONTAINER" sh -lc '
    export PATH=/usr/local/cargo/bin:$PATH
    cd /app
    dx check --package frontend
'

FILTER_ARGS="--ignored --nocapture --test-threads 4"
if [ "$SLOW" = "0" ]; then
    # `--skip` matches on the test's full path, and every slow test's NAME starts with
    # `slow_`. Marking them with #[ignore] instead would not work: they are all already
    # ignored, because they all need a live stack.
    FILTER_ARGS="$FILTER_ARGS --skip slow_"
    echo "== fast stack tests (add --slow for the shard-cache ones) =="
else
    echo "== all stack tests, including the slow ones =="
fi

exec docker exec "$WEBSITE_CONTAINER" sh -lc "
    export PATH=/usr/local/cargo/bin:\$PATH
    cd /app
    cargo test --offline -p backend --test stack_integration -- $FILTER_ARGS $*
"
