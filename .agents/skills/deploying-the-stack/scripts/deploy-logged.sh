#!/usr/bin/env bash
# Run ./deploy with its whole output captured, so a failure can be read rather than
# guessed at from a tail. Every argument is passed straight through.
#
#   deploy-logged.sh --build
#   deploy-logged.sh --ai-services --build
#
# Prints the log path, the exit status on its own line, and the error context if there
# is any. Exits with the deploy's own status.
set -uo pipefail

ROOT="$(git rev-parse --show-toplevel)"
LOGDIR="${HOOVER4_DEPLOY_LOG_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/hoover4-deploy-$(date +%s).log"

echo "log: $LOG"
"$ROOT/deploy" "$@" > "$LOG" 2>&1
status=$?
echo "EXIT=$status"

# Show the shape of the run whatever happened: how much output there was, and any line
# that reads as a failure. A clean run prints its own last lines and nothing else.
echo "lines: $(wc -l < "$LOG")"
if [ "$status" -ne 0 ]; then
    echo "--- error context"
    grep -nEi -B3 -A6 '(^|[^a-z])(error|failed|fatal|cannot|refused|no such|denied)' "$LOG" \
        | tail -80
else
    echo "--- last lines"
    tail -15 "$LOG"
fi
echo "--- full output is in $LOG; grep it rather than reading the tail"
exit "$status"
