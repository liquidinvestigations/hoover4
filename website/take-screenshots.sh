#!/bin/bash
# Capture a screenshot + snapshot of every page listed in `screenshots.ini`.
#
# Usage: ./take-screenshots.sh [--only SUBSTRING]
#
# Output: website/test_reports/screenshots/ (gitignored), wiped at the start of every run.
#   NN-name.png           what a person would see
#   NN-name.snapshot.txt  the rendered DOM as a text outline, plus the page's verdict
#   NN-name.FAILED.png    the state at the moment an action failed
#   report.md             the index: a line per page with pass/fail and the reason
#
# This is a GATE. It exits non-zero when a page shows an error marker, gets a non-200
# response, or logs a console error that no whitelist covers -- see the header of
# tools/capture_screenshots.py for what each means and how a page opts out.
# tools/console_whitelist.txt holds the run-wide console exceptions and is copied in too.
#
# Preconditions: the stack is up and `main_services/verify-stack.sh` has been run, so the
# fixtures the ini names exist. Nothing here ingests anything.
#
# How it works, and why it looks like this
# ----------------------------------------
# The website is only reachable from inside the podman network, and the one container
# with a browser in it -- hoover4-mcp-browser -- deliberately refuses internal hosts
# through its MCP endpoint (an explicit deny-list plus a PAC script handed to Chromium).
# So this does not use that endpoint: it copies a standalone nodriver script in and runs
# it, which launches a plain Chromium with no proxy filtering. Nothing about the MCP
# server's own filtering is touched or relaxed.
#
# The container has NO bind mounts, so the script goes in with `docker cp` and the images
# come back out the same way. `docker cp` copies are lost when a build recreates the
# container, which is fine -- this copies every run.
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

BROWSER_CONTAINER="${BROWSER_CONTAINER:-hoover4-mcp-browser}"
SITE_URL="${HOOVER4_SITE_URL:-http://hoover4-proxy:8080}"
OUT_DIR="$SCRIPT_DIR/test_reports/screenshots"
REMOTE_DIR="/tmp/h4shots"

ONLY=""
if [ "${1:-}" = "--only" ]; then
    ONLY="$2"
    shift 2
fi

if ! docker inspect -f '{{.State.Running}}' "$BROWSER_CONTAINER" 2>/dev/null | grep -q true; then
    echo "error: $BROWSER_CONTAINER is not running. Start the stack with ./deploy" >&2
    exit 1
fi

echo "== clearing $OUT_DIR =="
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# One run at a time. Two overlapping runs share $REMOTE_DIR inside the container, and the
# second one's `rm -rf` deletes the first one's output from under it, which presents as
# every page after the halfway point failing with ENOENT on its own PNG.
if docker exec "$BROWSER_CONTAINER" test -e "$REMOTE_DIR/.running" 2>/dev/null; then
    echo "error: another capture run is in progress (${REMOTE_DIR}/.running exists)." >&2
    echo "       If you are sure it is dead: docker exec $BROWSER_CONTAINER rm -rf $REMOTE_DIR" >&2
    exit 1
fi

echo "== copying the capture script into $BROWSER_CONTAINER =="
docker exec "$BROWSER_CONTAINER" rm -rf "$REMOTE_DIR"
docker exec "$BROWSER_CONTAINER" mkdir -p "$REMOTE_DIR"
docker cp tools/capture_screenshots.py "$BROWSER_CONTAINER:$REMOTE_DIR/capture_screenshots.py"
docker cp screenshots.ini "$BROWSER_CONTAINER:$REMOTE_DIR/screenshots.ini"
docker cp tools/console_whitelist.txt "$BROWSER_CONTAINER:$REMOTE_DIR/console_whitelist.txt"
docker exec "$BROWSER_CONTAINER" touch "$REMOTE_DIR/.running"

echo "== capturing from $SITE_URL =="
set +e
# Forwarded only when set: this is the override a page's `requires_dataset` is checked
# against instead of the site's own storage tree, which is how a run simulates an absent
# corpus without deleting or un-ingesting anything.
PRESENT_DATASETS_ENV=()
[ -n "${HOOVER4_SCREENSHOT_PRESENT_DATASETS+x}" ] &&
    PRESENT_DATASETS_ENV=(-e "HOOVER4_SCREENSHOT_PRESENT_DATASETS=$HOOVER4_SCREENSHOT_PRESENT_DATASETS")
docker exec "${PRESENT_DATASETS_ENV[@]}" "$BROWSER_CONTAINER" python "$REMOTE_DIR/capture_screenshots.py" \
    --ini "$REMOTE_DIR/screenshots.ini" \
    --out "$REMOTE_DIR/out" \
    --base-url "$SITE_URL" \
    --console-whitelist "$REMOTE_DIR/console_whitelist.txt" \
    --only "$ONLY"
CAPTURE_STATUS=$?
set -e

echo "== copying the results out =="
# `.` on the source keeps the directory's CONTENTS rather than nesting another `out/`.
docker cp "$BROWSER_CONTAINER:$REMOTE_DIR/out/." "$OUT_DIR/" 2>/dev/null || {
    echo "error: nothing was produced inside the container" >&2
    exit 1
}
docker exec "$BROWSER_CONTAINER" rm -rf "$REMOTE_DIR"

echo
echo "$(ls -1 "$OUT_DIR"/*.png 2>/dev/null | wc -l) screenshots in $OUT_DIR"
[ -f "$OUT_DIR/report.md" ] && grep -E "FAILED|warn:" "$OUT_DIR/report.md" || true
exit $CAPTURE_STATUS
