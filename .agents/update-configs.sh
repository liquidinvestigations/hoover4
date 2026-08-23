#!/usr/bin/env bash
# Copy the harness settings template over the live Claude Code settings.
#
# `.claude` is a protected path in Claude Code. A write there is never auto-approved, and an
# allow rule does not pre-approve it, because the path check runs before the allow rules. The
# template is an ordinary tracked file, so it is edited normally and installed from here.
#
# Whatever this installs is already in git. The script takes no content and no path, so the
# only thing it can ever write is the reviewed template.
#
# The hooks block takes effect after a session restart. This script cannot make its own change
# live in the session that ran it.
#
#   .agents/update-configs.sh           copy the template over the live file
#   .agents/update-configs.sh --check   exit 1 when the two files differ, and print the diff
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template="$root/.agents/harnesses/claude-settings.json"
live="$root/.claude/settings.json"

[[ -f "$template" ]] || { echo "missing template: $template" >&2; exit 2; }

python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$template" \
    || { echo "the template is not valid JSON, nothing was copied" >&2; exit 2; }

if [[ "${1:-}" == "--check" ]]; then
    if [[ -f "$live" ]] && diff -q "$template" "$live" >/dev/null; then
        echo "settings match"
        exit 0
    fi
    echo "the live settings differ from the template"
    diff -u "$template" "$live" 2>/dev/null || true
    exit 1
fi

if [[ -f "$live" ]]; then
    if diff -q "$template" "$live" >/dev/null; then
        echo "settings already match, nothing to do"
        exit 0
    fi
    echo "changes to install:"
    diff -u "$live" "$template" || true
    cp "$live" "$live.bak"
    echo "previous settings kept at $live.bak"
fi

mkdir -p "$(dirname "$live")"
cp "$template" "$live"
echo "installed $template into $live"
echo "restart the session, because a hooks change is read at session start"
