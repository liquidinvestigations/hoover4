#!/usr/bin/env bash
# SessionStart: hand the agent the invariants it must not rediscover, and re-hand them
# after a compaction, which is exactly when they fall out of context.
#
# stdin is the hook payload; `source` tells us why the session started
# (startup | resume | clear | compact). The text below is the only thing that is
# unconditionally in context: everything else is a skill the agent loads on demand.
# Keep it short -- every line here is paid for by every session, forever.
set -euo pipefail

payload=$(cat)
source_field=$(printf '%s' "$payload" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("source",""))' 2>/dev/null || echo "")

core=$(cat <<'CORE'
Standing invariants for this repo (the full versions are skills; load them by name):

- Everything runs in containers. Inspect the stack before acting; run tools with
  `docker exec` in the right container, not on the host.
- Never run an unfiltered recursive search. `grep` is ugrep here and does not skip
  build trees; scope with --include/--exclude-dir or name a subdirectory. A search
  that has not returned within seconds is wrong, not slow.
- Edit code with the Edit/Write tools or serena's symbol operations. `sed -i`,
  `cat >` and heredocs are for throwaway analysis outside the repo, not for source.
- Commit messages are one lowercase line under ~50 characters, and nothing else.
  No body, no trailer, no explanation anywhere in git.
- Documentation is present-tense truth: no dates, no history of the work, nothing
  aspirational, and never a reference to the gitignored scratch folder. Keep the
  lesson, drop the anecdote. Fix a comment in the patch that makes it false.
- Verify before claiming. If the check did not run this turn, the claim is not
  available to you. Say whether you fixed a cause or applied a workaround.
- No private infrastructure detail in a tracked file: no hostname, address, port
  identifying a real host, credential, or auth boundary. Those live only in the
  gitignored INFRASTRUCTURE_INVENTORY.md at the repo root.
- A change that adds, removes or re-scopes a capability edits its row in
  docs/technical-specification/ in the same patch.
- Sub-agents run one at a time, waited on, self-timeboxed, with a written work
  package. Never a swarm.
- Skills live in .agents/skills/<name>/SKILL.md (also reachable as .claude/skills/).
  Read the one that matches before improvising; rules in .agents/rules/ cover
  particular kinds of file.
CORE
)

case "$source_field" in
  compact)
    context="Context was just compacted. Re-establishing the invariants:

$core"
    ;;
  *)
    context="$core"
    ;;
esac

python3 - "$context" <<'PY'
import json, sys
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": sys.argv[1],
}}))
PY
