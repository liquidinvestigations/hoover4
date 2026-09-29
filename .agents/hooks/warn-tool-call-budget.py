#!/usr/bin/env python3
"""Report progress against an explicitly configured subagent tool-call budget.

HOOVER4_TOOL_BUDGET enables counting when it contains a positive integer.
Without that setting, the hook stays silent and creates no counter files.
Warnings are advisory. The hook never blocks a tool or assigns work.
"""
import json
import os
import pathlib
import sys

THRESHOLDS = (0.80, 0.95)
STATE_DIR = pathlib.Path(
    os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
) / "hoover4-tool-budget"


def budget(payload):
    """Return the explicit budget, or None when counting is disabled."""
    raw = os.environ.get("HOOVER4_TOOL_BUDGET", "").strip()
    if raw.isascii() and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


def state_path(agent_id):
    """Return the counter path for a sanitized agent identifier."""
    safe = "".join(c for c in agent_id if c.isalnum() or c in "-_")[:64] or "unnamed"
    return STATE_DIR / f"{safe}.count"


def bump(agent_id):
    """Increment the agent counter, returning zero when storage fails."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = state_path(agent_id)
        try:
            count = int(path.read_text().strip()) + 1
        except (OSError, ValueError):
            count = 1
        path.write_text(str(count))
        return count
    except OSError:
        return 0


def message(count, total):
    remaining = max(0, total - count)
    return (
        f"You have used {count} of your explicit {total} tool-call budget, "
        f"with {remaining} left. Follow the agreed budget and preserve enough "
        "state to continue any unfinished required work."
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0
    agent_id = payload.get("agent_id")
    total = budget(payload)
    if not isinstance(agent_id, str) or not agent_id or total is None:
        return 0
    count = bump(agent_id)
    marks = {max(1, int(total * fraction)) for fraction in THRESHOLDS}
    if count in marks:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": message(count, total),
            }
        }))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print(message(int(sys.argv[2]), int(sys.argv[3])))
        sys.exit(0)
    sys.exit(main())
