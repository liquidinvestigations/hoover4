#!/bin/bash
# Capture a screenshot + snapshot of every page listed in `browser-tests/`, at 720p and
# 1080p by default.
#
# Usage: ./take-screenshots.sh [--target URL] [--out DIR] [--only SUBSTRING] [--names CSV]
#                               [--login-env FILE] [--resolutions LIST]
# Credentials come from HOOVER4_TEST_USERNAME/HOOVER4_TEST_PASSWORD or --login-env.
# Credential values are not accepted as wrapper arguments and are not placed in
# Docker or Python argument lists.
#
# Output: <out>/run-<UTC-timestamp>-<pid>/ (default: website/test_reports/screenshots/,
#   gitignored). Never deleted by this script; each run adds a new directory and rewrites
#   <out>/index.md and <out>/latest, a symlink to the newest run.
#   <resolution>/NN-name.png           what a person would see, at an exact pixel size
#   <resolution>/NN-name.snapshot.txt  the rendered DOM as a text outline, plus observations
#   <resolution>/NN-name.FAILED.png    the state at the moment an action failed
#   report.md, report.html             the index: severities per page and why
#   manifest.json, diagnostics/        machine-readable, ignored by the generated .gitignore
#
# This is a GATE. Exit 1 when an application error occurred (a missing page, a non-200
# response, an undeclared error marker or bar). Exit 2 when execution was incomplete (a
# failed login, a stopped browser, a missing fixture, or a capture that could not be
# written) and no application error also occurred. See the header of
# tools/capture_screenshots.py for the full table.
# tools/console_whitelist.txt holds the run-wide console exceptions and is copied in too.
#
# Preconditions: the stack is up and `main_services/verify-stack.sh` has been run, so the
# fixtures the scenarios name exist. Nothing here ingests anything. Two scenarios in
# `browser-tests/`, `admin-dataset-rescan-dispatch` and `admin-operations-rerun`, name a
# control that dispatches server work; both capture the control's state without engaging
# it, so no scenario in the current list dispatches server work. A page whose dataset is
# absent is incomplete_execution; other pages still run.
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
# container, which is fine -- the container-side scratch at $REMOTE_DIR is rebuilt every
# run and never holds anything this script needs to keep.
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

BROWSER_CONTAINER="${BROWSER_CONTAINER:-hoover4-mcp-browser}"
# The PID makes this path unique per run. Two runs with different --out values take
# different host-side locks and so both proceed; without a unique scratch path they would
# share this container-side directory and each run's cleanup would delete the other's
# working files.
REMOTE_DIR="/tmp/h4shots-$$"

# ---------------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------------

TARGET_ARG=""
OUT_ARG=""
ONLY=""
NAMES=""
LOGIN_ENV_ARG=""
RESOLUTIONS_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET_ARG="${2:?--target needs a value}"; shift 2 ;;
        --out) OUT_ARG="${2:?--out needs a value}"; shift 2 ;;
        --only) ONLY="${2:?--only needs a value}"; shift 2 ;;
        --names) NAMES="${2:?--names needs a value}"; shift 2 ;;
        --username|--password)
            echo "error: $1 is not accepted. Set HOOVER4_TEST_USERNAME and HOOVER4_TEST_PASSWORD, or pass --login-env FILE." >&2
            exit 2 ;;
        --login-env) LOGIN_ENV_ARG="${2:?--login-env needs a value}"; shift 2 ;;
        --resolutions) RESOLUTIONS_ARG="${2:?--resolutions needs a value}"; shift 2 ;;
        *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

# --login-env defaults to TEST_LOGIN.env beside this script, but ONLY when that file
# exists; an unset, absent default is not an error, it is "no file source".
LOGIN_ENV_FILE="${LOGIN_ENV_ARG:-$SCRIPT_DIR/TEST_LOGIN.env}"
if [ -z "$LOGIN_ENV_ARG" ] && [ ! -f "$LOGIN_ENV_FILE" ]; then
    LOGIN_ENV_FILE=""
fi

# ---------------------------------------------------------------------------------
# Target precedence: --target, then HOOVER4_SITE_URL in the environment or the
# login-env file. There is no built-in default. A missing target exits 2 and names
# the sources that were checked.
# ---------------------------------------------------------------------------------

# shellcheck source=tools/capture_credentials.sh
source "$SCRIPT_DIR/tools/capture_credentials.sh"
require_capture_target
echo "== target: $SITE_URL (source: $TARGET_SOURCE) =="

# ---------------------------------------------------------------------------------
# Credential precedence: HOOVER4_TEST_USERNAME and HOOVER4_TEST_PASSWORD together,
# then the login-env file's pair. Sources are not mixed. No credential value is
# printed, including the username.
# ---------------------------------------------------------------------------------
if [ -n "$CRED_USERNAME" ]; then
    echo "== identity: authenticating (credential source: $CRED_SOURCE) =="
else
    echo "== identity: no credentials supplied, proceeding unauthenticated =="
fi
CAPTURE_REVISION="$(git -C "$SCRIPT_DIR/.." rev-parse HEAD 2>/dev/null || true)"
if [ -n "$CAPTURE_REVISION" ]; then
    export HOOVER4_CAPTURE_REVISION="$CAPTURE_REVISION"
fi

# ---------------------------------------------------------------------------------
# Output and the lock. The lock is taken FIRST, before anything is deleted or created --
# the previous wrapper wiped its output directory before checking a run marker, so a
# refused second run had already destroyed the first run's local output.
# ---------------------------------------------------------------------------------

OUT_DIR="${OUT_ARG:-$SCRIPT_DIR/test_reports/screenshots}"
mkdir -p "$OUT_DIR"

LOCK_DIR="$OUT_DIR/.lock"
LOCK_OWNER_FILE="$LOCK_DIR/owner"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    OWNER_PID=""
    OWNER_RUN="(unknown)"
    if [ -f "$LOCK_OWNER_FILE" ]; then
        OWNER_PID="$(sed -n '1p' "$LOCK_OWNER_FILE" 2>/dev/null || true)"
        OWNER_RUN="$(sed -n '2p' "$LOCK_OWNER_FILE" 2>/dev/null || true)"
    fi
    if [ -n "$OWNER_PID" ] && kill -0 "$OWNER_PID" 2>/dev/null; then
        echo "error: another capture run is in progress (pid $OWNER_PID, ${OWNER_RUN:-unknown run})." >&2
        exit 2
    fi
    echo "error: a stale lock is at $LOCK_DIR (owning pid ${OWNER_PID:-unknown} is gone)." >&2
    echo "       Every earlier run directory in $OUT_DIR is untouched." >&2
    echo "       If you are sure no run is active: rm -rf $LOCK_DIR" >&2
    exit 2
fi

RUN_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_NAME="run-${RUN_STAMP}-$$"
printf '%s\n%s\n' "$$" "$RUN_NAME" > "$LOCK_OWNER_FILE"

cleanup() {
    local status=$?
    docker exec "$BROWSER_CONTAINER" python "$REMOTE_DIR/browser_lifecycle.py" --stop-run "$REMOTE_DIR" >/dev/null 2>&1 || true
    if [ "$status" -ne 0 ]; then
        docker cp "$BROWSER_CONTAINER:$REMOTE_DIR/out/." "$OUT_DIR/" >/dev/null 2>&1 || true
    fi
    # Release only a lock this run took: a run that clears another run's lock is the
    # failure the lock exists to prevent.
    if [ -f "$LOCK_OWNER_FILE" ] && [ "$(sed -n '1p' "$LOCK_OWNER_FILE" 2>/dev/null || true)" = "$$" ]; then
        rm -rf "$LOCK_DIR"
    fi
    docker exec "$BROWSER_CONTAINER" rm -rf "$REMOTE_DIR" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! docker inspect -f '{{.State.Running}}' "$BROWSER_CONTAINER" 2>/dev/null | grep -q true; then
    echo "error: $BROWSER_CONTAINER is not running. Start the stack with ./deploy" >&2
    exit 2
fi

echo "== copying the capture script into $BROWSER_CONTAINER =="
docker exec "$BROWSER_CONTAINER" rm -rf "$REMOTE_DIR"
docker exec "$BROWSER_CONTAINER" mkdir -p "$REMOTE_DIR"
docker cp tools/capture_screenshots.py "$BROWSER_CONTAINER:$REMOTE_DIR/capture_screenshots.py"
docker cp tools/capture_credentials.py "$BROWSER_CONTAINER:$REMOTE_DIR/capture_credentials.py"
docker cp tools/browser_lifecycle.py "$BROWSER_CONTAINER:$REMOTE_DIR/browser_lifecycle.py"
docker cp tools/manual_qa.py "$BROWSER_CONTAINER:$REMOTE_DIR/manual_qa.py"
docker cp tools/manual_qa_runtime.py "$BROWSER_CONTAINER:$REMOTE_DIR/manual_qa_runtime.py"
docker cp tools/manual_qa_fixtures.json "$BROWSER_CONTAINER:$REMOTE_DIR/manual_qa_fixtures.json"
if [ -f test_reports/manual_qa_fixtures.json ]; then
    docker cp test_reports/manual_qa_fixtures.json "$BROWSER_CONTAINER:$REMOTE_DIR/manual_qa_profile.json"
fi
if [ -f test_reports/manual_qa_original_cases.json ]; then
    docker cp test_reports/manual_qa_original_cases.json "$BROWSER_CONTAINER:$REMOTE_DIR/manual_qa_original_cases.json"
fi
docker cp browser-tests "$BROWSER_CONTAINER:$REMOTE_DIR/browser-tests"
docker cp tools/console_whitelist.txt "$BROWSER_CONTAINER:$REMOTE_DIR/console_whitelist.txt"

echo "== capturing from $SITE_URL =="
set +e
# Forwarded only when set: this is the override a page's `requires_dataset` is checked
# against instead of the site's own storage tree, which is how a run simulates an absent
# corpus without deleting or un-ingesting anything.
PASS_THROUGH_ENV=()
[ -n "${HOOVER4_SCREENSHOT_PRESENT_DATASETS+x}" ] &&
    PASS_THROUGH_ENV+=(-e "HOOVER4_SCREENSHOT_PRESENT_DATASETS=$HOOVER4_SCREENSHOT_PRESENT_DATASETS")
# Names only: docker reads values from this process environment. A `-e NAME=value`
# form would place the secret in the host argument list.
[ -n "$CRED_USERNAME" ] && PASS_THROUGH_ENV+=(-e HOOVER4_TEST_USERNAME -e HOOVER4_TEST_PASSWORD)
[ -n "${HOOVER4_CAPTURE_REVISION:-}" ] && PASS_THROUGH_ENV+=(-e HOOVER4_CAPTURE_REVISION)
docker exec "${PASS_THROUGH_ENV[@]}" "$BROWSER_CONTAINER" python "$REMOTE_DIR/capture_screenshots.py" \
    --ini "$REMOTE_DIR/browser-tests" \
    --out-root "$REMOTE_DIR/out" \
    --run-name "$RUN_NAME" \
    --base-url "$SITE_URL" \
    --console-whitelist "$REMOTE_DIR/console_whitelist.txt" \
    --only "$ONLY" \
    --names "$NAMES" \
    --resolutions "${RESOLUTIONS_ARG:-720p,1080p}"
CAPTURE_STATUS=$?
set -e

echo "== copying the results out =="
# `.` on the source keeps the directory's CONTENTS rather than nesting another `out/`.
# This MERGES onto $OUT_DIR: docker cp overwrites matching names (the freshly rewritten
# index.md) and adds the new run-*/ directory, without touching any sibling it does not
# name, which is what keeps every earlier run directory intact.
docker cp "$BROWSER_CONTAINER:$REMOTE_DIR/out/." "$OUT_DIR/" 2>/dev/null || {
    echo "error: nothing was produced inside the container" >&2
    exit 2
}
# The "latest" symlink is written here, host-side, rather than inside the container and
# copied out: `docker cp` onto an existing symlink can follow it instead of replacing it,
# which risks writing into a previous run's directory instead of updating the pointer.
ln -sfn "$RUN_NAME" "$OUT_DIR/latest"

echo
echo "$(ls -1 "$OUT_DIR/$RUN_NAME"/*/*.png 2>/dev/null | wc -l) screenshots in $OUT_DIR/$RUN_NAME"
[ -f "$OUT_DIR/$RUN_NAME/report.md" ] && grep -E "application_error|incomplete_execution" "$OUT_DIR/$RUN_NAME/report.md" || true
exit $CAPTURE_STATUS
