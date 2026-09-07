#!/bin/bash
# Drive a real chat conversation to completion in a real browser and observe it, the same
# way take-screenshots.sh drives a page: no application code changed, no server dispatched
# beyond the identity check and the chat turn itself.
#
# Usage: ./observe-chat.sh [--target URL] [--out DIR] [--username NAME] [--password VALUE]
#                           [--login-env FILE] [--resolutions LIST] [--prompts LIST]
#                           [--conversations N] [--no-followup]
#
# --prompts takes a comma-separated list of prompt names from chat_observer.py's PROMPTS,
#   or 'all'. Defaults to 'collection-exploration'. --conversations caps how many of the
#   selected prompts run concurrently (0, the default, runs every selected prompt).
#   --no-followup skips the second-turn check on the collection-exploration conversation.
#
# Output: <out>/run-<UTC-timestamp>-<pid>/chat/<prompt-name>/ (default:
#   website/test_reports/chat_observer/, gitignored). Never deleted by this script; each
#   run adds a new directory and rewrites <out>/latest, a symlink to the newest run.
#   See the header of tools/chat_observer.py for the full output shape and the result
#   classification (same six severities and the same exit-status rule as
#   take-screenshots.sh: 1 for an application error, 2 for incomplete execution, else 0).
#
# A local generation runs on the CPU model twins. One turn can take several minutes; a
# Deep Research turn can take tens of minutes. This script waits for the observer's own
# deadline, which is the workflow's configured turn timeout plus a margin. It never
# retries a submitted prompt and never cancels a live generation.
#
# Preconditions: the stack is up. This reaches /ai_chat, which needs an authenticated
# identity, so a credential source (below) is required; running with none produces an
# immediate validation failure rather than an anonymous, doomed attempt.
#
# How it works, and why it looks like this
# ----------------------------------------
# Same mechanism as take-screenshots.sh, described in full in that script's own header:
# hoover4-mcp-browser's MCP endpoint refuses internal hosts by design, so this copies a
# standalone nodriver script in with `docker cp` and runs it directly, then copies the
# images back out the same way. This file does not source or restructure
# take-screenshots.sh; it repeats that script's target/credential-precedence and
# lock/copy-in/output-merge shape for chat_observer.py, a different Python entry point
# with its own arguments.
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

BROWSER_CONTAINER="${BROWSER_CONTAINER:-hoover4-mcp-browser}"
# The PID makes this path unique per run, for the same reason take-screenshots.sh uses one:
# without it, two runs with different --out values would share this container-side
# directory, and the cleanup pkill below could stop a different run's observer process.
REMOTE_DIR="/tmp/h4chat-$$"

# ---------------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------------

TARGET_ARG=""
OUT_ARG=""
USERNAME_ARG=""
PASSWORD_ARG=""
LOGIN_ENV_ARG=""
RESOLUTIONS_ARG=""
PROMPTS_ARG=""
CONVERSATIONS_ARG=""
NO_FOLLOWUP_ARG=""

while [ $# -gt 0 ]; do
    case "$1" in
        --target) TARGET_ARG="${2:?--target needs a value}"; shift 2 ;;
        --out) OUT_ARG="${2:?--out needs a value}"; shift 2 ;;
        --username) USERNAME_ARG="${2:?--username needs a value}"; shift 2 ;;
        --password) PASSWORD_ARG="${2:?--password needs a value}"; shift 2 ;;
        --login-env) LOGIN_ENV_ARG="${2:?--login-env needs a value}"; shift 2 ;;
        --resolutions) RESOLUTIONS_ARG="${2:?--resolutions needs a value}"; shift 2 ;;
        --prompts) PROMPTS_ARG="${2:?--prompts needs a value}"; shift 2 ;;
        --conversations) CONVERSATIONS_ARG="${2:?--conversations needs a value}"; shift 2 ;;
        --no-followup) NO_FOLLOWUP_ARG="1"; shift 1 ;;
        *) echo "error: unknown argument '$1'" >&2; exit 2 ;;
    esac
done

# --login-env defaults to TEST_LOGIN.env beside this script, but ONLY when that file
# exists; an unset, absent default is not an error, it is "no file source".
LOGIN_ENV_FILE="${LOGIN_ENV_ARG:-$SCRIPT_DIR/TEST_LOGIN.env}"
if [ -z "$LOGIN_ENV_ARG" ] && [ ! -f "$LOGIN_ENV_FILE" ]; then
    LOGIN_ENV_FILE=""
fi

read_login_env_value() {
    # $1: file (may be empty or missing), $2: key. Last matching line wins, matching
    # ordinary shell-var-file semantics. Strips one layer of surrounding single or double
    # quotes, since TEST_LOGIN.env.example writes its values that way.
    local file="$1" key="$2" raw
    [ -n "$file" ] && [ -f "$file" ] || return 0
    raw="$(sed -n "s/^${key}=//p" "$file" | tail -n1)"
    raw="${raw%$'\r'}"
    if [[ "$raw" == \'*\' || "$raw" == \"*\" ]]; then
        raw="${raw:1:-1}"
    fi
    printf '%s' "$raw"
}

# ---------------------------------------------------------------------------------
# Target precedence: --target, then HOOVER4_SITE_URL in the environment, then the
# built-in backdoor default. The login-env file supplies credentials only, and never the
# target: this script reaches an authenticated area (/ai_chat) on every invocation, so a
# run with no arguments must still reach the local stack, where the supplied identity
# cannot dispatch anything against a remote deployment. Reaching a remote target stays one
# explicit --target or HOOVER4_SITE_URL away. Dials the backdoor by name, so the default
# needs hoover4.ini.development (development_auth_backdoor_enabled = true); release mode
# has no identity source this script can use.
# ---------------------------------------------------------------------------------

if [ -n "$TARGET_ARG" ]; then
    SITE_URL="$TARGET_ARG"
    TARGET_SOURCE="--target"
elif [ -n "${HOOVER4_SITE_URL:-}" ]; then
    SITE_URL="$HOOVER4_SITE_URL"
    TARGET_SOURCE="the HOOVER4_SITE_URL environment variable"
else
    SITE_URL="http://hoover4-development-auth-backdoor:8080"
    TARGET_SOURCE="the built-in default"
fi
echo "== target: $SITE_URL (source: $TARGET_SOURCE) =="

# ---------------------------------------------------------------------------------
# Credential precedence: --username and --password together, then
# HOOVER4_TEST_USERNAME and HOOVER4_TEST_PASSWORD together, then the login-env file's
# pair. Sources are not mixed: the highest-priority source that supplies EITHER value
# supplies both, and an incomplete pair from that source is a validation failure. No
# credential value is ever printed, including the username, since the precedence list
# names them as one channel. A chat conversation needs an identity, so an empty pair from
# every source is also a validation failure here, unlike take-screenshots.sh's page runner.
# ---------------------------------------------------------------------------------

CRED_USERNAME=""
CRED_PASSWORD=""
CRED_SOURCE=""
if [ -n "$USERNAME_ARG" ] || [ -n "$PASSWORD_ARG" ]; then
    CRED_USERNAME="$USERNAME_ARG"
    CRED_PASSWORD="$PASSWORD_ARG"
    CRED_SOURCE="--username/--password"
elif [ -n "${HOOVER4_TEST_USERNAME:-}" ] || [ -n "${HOOVER4_TEST_PASSWORD:-}" ]; then
    CRED_USERNAME="${HOOVER4_TEST_USERNAME:-}"
    CRED_PASSWORD="${HOOVER4_TEST_PASSWORD:-}"
    CRED_SOURCE="the HOOVER4_TEST_USERNAME/HOOVER4_TEST_PASSWORD environment variables"
else
    FILE_USER="$(read_login_env_value "$LOGIN_ENV_FILE" HOOVER4_TEST_USERNAME)"
    FILE_PASS="$(read_login_env_value "$LOGIN_ENV_FILE" HOOVER4_TEST_PASSWORD)"
    if [ -n "$FILE_USER" ] || [ -n "$FILE_PASS" ]; then
        CRED_USERNAME="$FILE_USER"
        CRED_PASSWORD="$FILE_PASS"
        CRED_SOURCE="$LOGIN_ENV_FILE"
    fi
fi

if [ -n "$CRED_USERNAME" ] && [ -z "$CRED_PASSWORD" ]; then
    echo "error: a username with no password is a validation failure (source: $CRED_SOURCE)" >&2
    exit 2
fi
if [ -z "$CRED_USERNAME" ] && [ -n "$CRED_PASSWORD" ]; then
    echo "error: a password with no username is a validation failure (source: $CRED_SOURCE)" >&2
    exit 2
fi
if [ -z "$CRED_USERNAME" ]; then
    echo "error: a chat conversation needs an identity; no credential source supplied one" >&2
    echo "       (checked --username/--password, HOOVER4_TEST_USERNAME/PASSWORD, $LOGIN_ENV_FILE)" >&2
    exit 2
fi
echo "== identity: authenticating (credential source: $CRED_SOURCE) =="

# ---------------------------------------------------------------------------------
# Output and the lock. The lock is taken FIRST, before anything is deleted or created --
# see take-screenshots.sh for why a refused second run must never destroy the first run's
# local output.
# ---------------------------------------------------------------------------------

OUT_DIR="${OUT_ARG:-$SCRIPT_DIR/test_reports/chat_observer}"
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
        echo "error: another observer run is in progress (pid $OWNER_PID, ${OWNER_RUN:-unknown run})." >&2
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

RESULTS_COPIED=0

cleanup() {
    local status=$?
    # Release only a lock this run took: a run that clears another run's lock is the
    # failure the lock exists to prevent.
    if [ -f "$LOCK_OWNER_FILE" ] && [ "$(sed -n '1p' "$LOCK_OWNER_FILE" 2>/dev/null || true)" = "$$" ]; then
        rm -rf "$LOCK_DIR"
    fi
    if [ "$RESULTS_COPIED" != "1" ]; then
        # An interrupted run reaches here with the container-side observer possibly still
        # writing into $REMOTE_DIR. Stop that process first -- this does not cancel the
        # live generation: chat_observer.py's own docstring records that closing or
        # navigating a browser tab never stops the server-side workflow, so ending the
        # observer script only stops observation, not the chat turn -- then copy out
        # whatever exists before the scratch directory is removed, so an interrupted run
        # keeps its partial evidence instead of losing it.
        docker exec "$BROWSER_CONTAINER" pkill -f "$REMOTE_DIR/chat_observer.py" >/dev/null 2>&1 || true
        mkdir -p "$OUT_DIR"
        docker cp "$BROWSER_CONTAINER:$REMOTE_DIR/out/." "$OUT_DIR/" >/dev/null 2>&1 || true
    fi
    docker exec "$BROWSER_CONTAINER" rm -rf "$REMOTE_DIR" >/dev/null 2>&1 || true
    exit "$status"
}
trap cleanup EXIT

if ! docker inspect -f '{{.State.Running}}' "$BROWSER_CONTAINER" 2>/dev/null | grep -q true; then
    echo "error: $BROWSER_CONTAINER is not running. Start the stack with ./deploy" >&2
    exit 2
fi

echo "== copying the observer script into $BROWSER_CONTAINER =="
docker exec "$BROWSER_CONTAINER" rm -rf "$REMOTE_DIR"
docker exec "$BROWSER_CONTAINER" mkdir -p "$REMOTE_DIR"
# chat_observer.py imports its browser helpers from capture_screenshots.py rather than
# copying them, so both files travel together.
docker cp tools/chat_observer.py "$BROWSER_CONTAINER:$REMOTE_DIR/chat_observer.py"
docker cp tools/capture_screenshots.py "$BROWSER_CONTAINER:$REMOTE_DIR/capture_screenshots.py"
docker cp tools/console_whitelist.txt "$BROWSER_CONTAINER:$REMOTE_DIR/console_whitelist.txt"

echo "== observing a conversation against $SITE_URL =="
set +e
CHAT_ARGS=(
    --out-root "$REMOTE_DIR/out"
    --run-name "$RUN_NAME"
    --base-url "$SITE_URL"
    --console-whitelist "$REMOTE_DIR/console_whitelist.txt"
    --username "$CRED_USERNAME"
    --resolutions "${RESOLUTIONS_ARG:-720p,1080p}"
    --prompts "${PROMPTS_ARG:-collection-exploration}"
)
[ -n "$CONVERSATIONS_ARG" ] && CHAT_ARGS+=(--conversations "$CONVERSATIONS_ARG")
[ -n "$NO_FOLLOWUP_ARG" ] && CHAT_ARGS+=(--no-followup)
# The password travels by environment, set on this one `docker exec` only, and never as a
# process argument: argv is visible to every other process on the host through /proc, an
# env var scoped to one exec is not.
docker exec -e "HOOVER4_CAPTURE_PASSWORD=$CRED_PASSWORD" "$BROWSER_CONTAINER" \
    python "$REMOTE_DIR/chat_observer.py" "${CHAT_ARGS[@]}"
OBSERVE_STATUS=$?
set -e

echo "== copying the results out =="
# `.` on the source keeps the directory's CONTENTS rather than nesting another `out/`.
# This MERGES onto $OUT_DIR: docker cp overwrites matching names (the freshly rewritten
# `latest` target) and adds the new run-*/ directory, without touching any sibling it does
# not name, which is what keeps every earlier run directory intact.
docker cp "$BROWSER_CONTAINER:$REMOTE_DIR/out/." "$OUT_DIR/" 2>/dev/null || {
    echo "error: nothing was produced inside the container" >&2
    exit 2
}
RESULTS_COPIED=1
# The "latest" symlink is written here, host-side, rather than inside the container and
# copied out: `docker cp` onto an existing symlink can follow it instead of replacing it,
# which risks writing into a previous run's directory instead of updating the pointer.
ln -sfn "$RUN_NAME" "$OUT_DIR/latest"

echo
echo "$(find "$OUT_DIR/$RUN_NAME/chat" -name '*.png' 2>/dev/null | wc -l) screenshots in $OUT_DIR/$RUN_NAME/chat"
[ -f "$OUT_DIR/$RUN_NAME/chat/chat_index.md" ] && cat "$OUT_DIR/$RUN_NAME/chat/chat_index.md" || true
exit $OBSERVE_STATUS
