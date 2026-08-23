#!/usr/bin/env python3
"""PostToolUse(*): remind a pass of its tool-call budget as it approaches the limit.

A pass is capped by context, and the cap is written into its work package as a tool-call
count because an agent can count its own tool calls and cannot see its own context. Where a
harness supplies a live token warning it fires against the whole window, not against the
budget a plan chose.

An instruction in a work package decays. This puts the number back in front of the pass at
the moment it matters, which is the same reason the other hooks in this directory exist.

The budget comes from `.agents/arm-tool-budget.sh`, which the organizer runs immediately
before it launches a pass, or from HOOVER4_TOOL_BUDGET, and defaults to the
implementation-pass budget. The count is kept per session in a state file, because a hook
process does not survive between calls.

**A sub-agent's tool call is indistinguishable from its parent's here.** The payload carries
the same `session_id`, `transcript_path` and `prompt_id` for both, and the environment carries
the same values as well, including `CLAUDE_CODE_CHILD_SESSION`. `CLAUDE_AGENT_MAX_TURNS` is
not exported at all, so the hook cannot read an agent definition's own `maxTurns`. Arming the
counter from outside is therefore the only way this hook can measure one pass rather than a
whole session, and the organizer running the arm script is part of the mechanism.

Reads the hook payload on stdin. Writes a JSON reason on stdout only when a threshold is
crossed, and stays silent otherwise, so it costs nothing on the other calls. It never
blocks: running out of budget is handled by `maxTurns`, and a hook that stops a pass
mid-edit would leave the tree in a worse state than one that lets it finish and hand over.
"""
import json
import os
import pathlib
import sys

#: 250,000 tokens at the measured p90 growth rate of 2,603 tokens per tool call.
DEFAULT_BUDGET = 96

#: Warn once at each of these fractions of the budget.
THRESHOLDS = (0.80, 0.95)

STATE_DIR = pathlib.Path(
    os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
) / "hoover4-tool-budget"


def budget(session):
    """Return the budget this session was armed with, or the default.

    The armed value wins, because it is the number the organizer wrote into the work package
    it is about to launch. An unarmed session falls back to the environment and then to the
    implementation-pass budget, which is what a session that is not running a pass wants.
    """
    armed = state_path(session, "budget")
    try:
        raw = armed.read_text().strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
    except OSError:
        pass
    raw = os.environ.get("HOOVER4_TOOL_BUDGET")
    if raw and raw.strip().isdigit():
        return int(raw.strip())
    return DEFAULT_BUDGET


def state_path(session, suffix):
    """The state file for one session, named so a path-shaped id cannot escape the directory."""
    safe = "".join(c for c in (session or "shared") if c.isalnum() or c in "-_")[:64] or "shared"
    return STATE_DIR / f"{safe}.{suffix}"


def bump(session):
    """Increment this session's counter and return the new total.

    A session id that is missing falls back to one shared counter. The organizer's own calls
    land in the same counter as the pass it launched, because the harness gives both the same
    session id, so the count is only about one pass when the counter was armed just before
    that pass started.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = state_path(session, "count")
    try:
        count = int(path.read_text().strip()) + 1
    except (OSError, ValueError):
        count = 1
    try:
        path.write_text(str(count))
    except OSError:
        return 0            # cannot count, so say nothing rather than warn wrongly
    return count


def message(count, total):
    remaining = total - count
    if remaining <= 0:
        return (
            f"You have used {count} of your {total} tool calls. Stop taking new work now. "
            "Finish the step you are on and write the handover: what is done, what is not, "
            "and the rule you derived, so the next context does not derive it again."
        )
    return (
        f"You have used {count} of your {total} tool calls, with {remaining} left. "
        "Stop taking new work, finish the step you are on, and write a handover naming what "
        "is done, what is not, and the rule you derived. A handover that carries the rule is "
        "what makes the restart cheap."
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    # Launching a pass is the organizer's work, never the pass's, and it is the one call
    # that always falls between arming the counter and the pass's first call.
    if payload.get("tool_name") == "Agent":
        return 0
    session = payload.get("session_id")
    total = budget(session)
    count = bump(session)
    if not count:
        return 0
    # Warn on the exact call that crosses a threshold, and never again for that threshold.
    for fraction in THRESHOLDS:
        mark = int(total * fraction)
        if count == mark:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": message(count, total),
                }
            }))
            return 0
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print(message(int(sys.argv[2]), int(sys.argv[3])))
        sys.exit(0)
    sys.exit(main())
