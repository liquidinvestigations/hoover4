#!/bin/bash
# Arm the tool-call counter for the pass that is about to be launched.
#
# Usage: .agents/arm-tool-budget.sh [budget]
#
#   budget   tool calls the pass is allowed, default 96 for an implementation pass.
#            Use 58 for a read-only pass, which is the 150,000-token cap at the same
#            measured growth rate.
#
# Run this immediately before launching a sub-agent, and run no tool call of your own
# while that pass is live.
#
# The harness gives a sub-agent the same session id, transcript path and environment as
# the session that launched it, so `warn-tool-call-budget.py` cannot tell one from the
# other. Setting the count to zero here is what makes the pass's warning count only the
# pass's own calls. Without it the organizer's calls are added to the pass's, and the
# warning fires early: one pass was stopped at 26 calls of 96 that way.
set -euo pipefail

budget="${1:-96}"
case "$budget" in
    ''|*[!0-9]*) echo "arm-tool-budget: budget must be a whole number, got '$budget'" >&2; exit 2 ;;
esac

session="${CLAUDE_CODE_SESSION_ID:-shared}"
safe=$(printf '%s' "$session" | tr -cd 'A-Za-z0-9_-' | cut -c1-64)
[ -n "$safe" ] || safe=shared

dir="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/hoover4-tool-budget"
mkdir -p "$dir"
# Minus one, because this script runs as a tool call and its own PostToolUse hook fires
# after it, taking the counter to zero. The launch call after it is a tool named `Agent`,
# which the hook does not count. The pass therefore makes its own first call at one.
printf -- '-1' > "$dir/$safe.count"
printf '%s' "$budget" > "$dir/$safe.budget"

echo "armed: $budget tool calls, counter at 0, session $safe"
