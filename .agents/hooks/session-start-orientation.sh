#!/usr/bin/env bash
# Restore repository orientation at session start and after compaction.
set -euo pipefail

payload=$(cat)
source_field=$(printf '%s' "$payload" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("source",""))' 2>/dev/null || echo "")

core=$(cat <<'CORE'
Read AGENTS.md for the shared repository instructions.
Preserve the requested outcome and accepted decisions.
Use the simplest complete implementation and record unrelated findings without implementing them.
Use relevant skills for repository-specific procedures.
Run application tooling and checks in the appropriate containers.
Keep private infrastructure details in the local inventory.
Tie claims to evidence for the tested code and environment.
Resume the current task from its recorded state.
CORE
)

case "$source_field" in
  compact) context="Context was just compacted.

$core" ;;
  *) context="$core" ;;
esac

python3 - "$context" <<'PY'
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": sys.argv[1],
}}))
PY
