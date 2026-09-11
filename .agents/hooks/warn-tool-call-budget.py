#!/usr/bin/env python3
"""PostToolUse(*): remind a sub-agent of its tool-call budget as it approaches the limit.

A pass is capped by context, and the cap is written into its work package as a tool-call
count because an agent can count its own tool calls and cannot see its own context. Where a
harness supplies a live token warning it fires against the whole window, not against the
budget a plan chose.

An instruction in a work package decays. This puts the number back in front of the pass at
the moment it matters, which is the same reason the other hooks in this directory exist.

**Only a sub-agent is counted.** The payload carries `agent_id` and `agent_type` on a
sub-agent's tool call. It carries neither key on a call from the session that launched the
pass. Every other field is the same for both, including `session_id`, `transcript_path` and
the whole environment. `agent_id` is what tells them apart. The organizer therefore gets no
warning and runs until its context ends it. A count of the organizer's calls does not measure
the work it has left, because it reads diffs and launches passes.

A sub-agent's budget comes from its `agent_type`: the smaller read-only figure for an agent
type that only reads, and the writing figure for every other. An agent type this file does
not know gets the writing budget, which is the safe direction, because a budget that is too
high costs a handover that was not planned and one that is too low stops a pass that had work
left. `HOOVER4_TOOL_BUDGET` overrides both for a whole session.

The count is kept per agent id in a state file, because a hook process does not survive
between calls. **A new sub-agent starts at zero on its own**, because its counter file does
not exist yet. Nothing has to be armed before a launch and nothing has to be put back after
one. A pass resumed under the same agent id continues its own count, which is correct, because
a resume is the same context carrying on.

Reads the hook payload on stdin. Writes a JSON reason on stdout only when a threshold is
crossed, and stays silent otherwise, so it costs nothing on the other calls. It never
blocks: running out of budget is handled by `maxTurns`, and a hook that stops a pass
mid-edit would leave the tree in a worse state than one that lets it finish and hand over.
"""
import json
import os
import pathlib
import sys

#: The 300,000-token cap on a pass that writes, at the measured median growth of 1,489 tokens
#: a tool call. See `.agents/skills/planning-work/reference/estimating.md`, section 2c.
DEFAULT_BUDGET = 202

#: The 150,000-token cap on a pass that only reads, at the same measured rate.
REVIEW_BUDGET = 101

#: The agent types that only read. Everything else writes source and gets the larger budget.
#: An agent type that writes anything takes the writing budget, whatever else it does.
READ_ONLY_AGENTS = {"reviewer", "Explore", "Plan"}

#: Warn once at each of these fractions of the budget.
THRESHOLDS = (0.80, 0.95)

STATE_DIR = pathlib.Path(
    os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
) / "hoover4-tool-budget"


def budget(payload):
    """Return the budget for the sub-agent this call belongs to.

    Decided by its agent type, because nothing arms it beforehand and the type is the only
    thing the payload says about what the pass is for. `HOOVER4_TOOL_BUDGET` overrides both
    figures for a whole session when a run needs another.
    """
    raw = os.environ.get("HOOVER4_TOOL_BUDGET")
    if raw and raw.strip().isdigit() and int(raw.strip()) > 0:
        return int(raw.strip())
    if payload.get("agent_type") in READ_ONLY_AGENTS:
        return REVIEW_BUDGET
    return DEFAULT_BUDGET


def state_path(agent_id):
    """The count file for one sub-agent, named so a path-shaped id cannot escape the directory."""
    safe = "".join(c for c in agent_id if c.isalnum() or c in "-_")[:64] or "unnamed"
    return STATE_DIR / f"{safe}.count"


def bump(agent_id):
    """Increment this sub-agent's counter and return the new total.

    The file is keyed on the agent id, which the harness gives each sub-agent. One pass's
    calls are therefore never added to another pass's, or to the organizer's.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = state_path(agent_id)
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
    # A call with no agent id was made by the session that launched the pass. That session
    # is bounded by its context, not by a number, so it is counted by nothing here.
    agent_id = payload.get("agent_id")
    if not agent_id:
        return 0
    total = budget(payload)
    count = bump(agent_id)
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
