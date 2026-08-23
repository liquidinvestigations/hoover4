#!/usr/bin/env python3
"""PostToolUse(*): remind a pass of its tool-call budget as it approaches the limit.

A pass is capped by context, and the cap is written into its work package as a tool-call
count because an agent can count its own tool calls and cannot see its own context. Where a
harness supplies a live token warning it fires against the whole window, not against the
budget a plan chose.

An instruction in a work package decays. This puts the number back in front of the pass at
the moment it matters, which is the same reason the other hooks in this directory exist.

The budget comes from HOOVER4_TOOL_BUDGET, or from the `maxTurns` of the agent definition
when the harness exports it, and defaults to the implementation-pass budget. The count is
kept per session in a state file, because a hook process does not survive between calls.

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


def budget():
    for name in ("HOOVER4_TOOL_BUDGET", "CLAUDE_AGENT_MAX_TURNS"):
        raw = os.environ.get(name)
        if raw and raw.strip().isdigit():
            return int(raw.strip())
    return DEFAULT_BUDGET


def bump(session):
    """Increment this session's counter and return the new total.

    A session id that is missing or path-shaped falls back to one shared counter. That
    over-counts across concurrent sessions, which warns early rather than late, and this
    repository runs one pass at a time anyway.
    """
    safe = "".join(c for c in (session or "shared") if c.isalnum() or c in "-_")[:64] or "shared"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{safe}.count"
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
    total = budget()
    count = bump(payload.get("session_id"))
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
