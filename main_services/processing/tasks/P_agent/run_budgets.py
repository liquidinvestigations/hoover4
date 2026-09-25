"""The sub-agent budgets of a run that delegates.

`run_agent` applies these rules to the briefings of one delegation, in call order, and
refuses the surplus briefings with a reason. The refused briefings go into the delegating
run's `refused_json`, and the continuation gives them to the model beside the reports.

| rule | caller | count | limit |
|---|---|---|---|
| depth | depth 2 | none | depth 2 binds no `run_subagent`, so a call never reaches here |
| briefings a call | every caller | the briefings of one call | `MAX_BRIEFINGS_PER_CALL` |
| turn budget | depth 0 with no plan run | sub-agent rows of the turn | `AGENT_SUBAGENT_MAX_PER_TURN` |
| plan budget | depth 0 with a plan run | sub-agent rows of the plan run | `AGENT_PLAN_RUN_BUDGET` |
| share | depth 1 | none | its own `subagent_share` |

A sub-agent row is a row with `depth >= 1` and no `continues_run_id`, because a
continuation takes the place of a run and is not a new sub-agent. The counts exclude the rows
of the caller's own batch, so a retry of the same delegation counts what it counted first.

**The share rule.** The allowance `a` is the limit minus the count for a depth 0 caller, and
its `subagent_share` for a depth 1 caller. The caller accepts `k = min(briefings, a)`
briefings in call order. The remainder `r = a - k` is divided among the children of a depth 0
caller: child `i` gets `r // k`, plus one when `i < r % k`. The children of a depth 1 caller
are at depth 2 and get 0, and the caller's own share becomes `a - k`. A depth 0 thread and a
depth 1 thread each run one run at a time, so no other run inserts a row between the count
and the insert, and `k` plus the shares never passes `a`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

#: The most briefings one `run_subagent` call runs. The agent's tool schema says the same.
MAX_BRIEFINGS_PER_CALL = 5
#: The deepest run. A run at this depth binds no `run_subagent`.
MAX_DEPTH = 2

DEFAULT_TURN_LIMIT = 6
DEFAULT_PLAN_LIMIT = 300

#: The refusal reasons, as the model reads them in the continuation's tool result.
TOO_MANY_BRIEFINGS = "too_many_briefings"
BUDGET_SPENT = "subagent_budget_spent"
DEPTH_LIMIT = "depth_limit"


def _positive(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} is {value}, and it must be 0 or more")
    return value


def turn_limit() -> int:
    """`AGENT_SUBAGENT_MAX_PER_TURN`: the sub-agent runs of one chat turn with no plan."""
    return _positive("AGENT_SUBAGENT_MAX_PER_TURN", DEFAULT_TURN_LIMIT)


def plan_limit() -> int:
    """`AGENT_PLAN_RUN_BUDGET`: the sub-agent runs of one plan run."""
    return _positive("AGENT_PLAN_RUN_BUDGET", DEFAULT_PLAN_LIMIT)


@dataclass
class Accepted:
    """One accepted briefing: the call it came from, the briefing, and the child's share."""

    tool_call_id: str
    briefing: dict[str, Any]
    share: int


@dataclass
class Decision:
    accepted: list[Accepted] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)
    #: The caller's `subagent_share` after this delegation.
    caller_share: int = 0


def _refusal(call_id: str, briefing: dict[str, Any], reason: str) -> dict[str, Any]:
    return {"tool_call_id": call_id, "objective": str(briefing.get("objective") or ""),
            "reason": reason}


def decide(calls: list[tuple[str, list[dict[str, Any]]]], *, depth: int, used: int,
           limit: int, own_share: int) -> Decision:
    """Apply the rules to the briefings of one delegation.

    `calls` holds `(tool_call_id, briefings)` for each `run_subagent` call, in call order.
    `used` is the count of the turn or plan budget, and `limit` its limit. Both are ignored
    for a depth 1 caller, which reads `own_share`.
    """
    decision = Decision(caller_share=own_share)
    wanted: list[tuple[str, dict[str, Any]]] = []
    for call_id, briefings in calls:
        for position, briefing in enumerate(briefings):
            if depth >= MAX_DEPTH:
                decision.refused.append(_refusal(call_id, briefing, DEPTH_LIMIT))
            elif position >= MAX_BRIEFINGS_PER_CALL:
                decision.refused.append(_refusal(call_id, briefing, TOO_MANY_BRIEFINGS))
            else:
                wanted.append((call_id, briefing))
    allowance = max(0, own_share if depth >= 1 else limit - used)
    k = min(len(wanted), allowance)
    for call_id, briefing in wanted[k:]:
        decision.refused.append(_refusal(call_id, briefing, BUDGET_SPENT))
    remainder = allowance - k
    for i, (call_id, briefing) in enumerate(wanted[:k]):
        share = 0 if depth >= 1 else remainder // k + (1 if i < remainder % k else 0)
        decision.accepted.append(Accepted(call_id, briefing, share))
    if depth >= 1:
        decision.caller_share = remainder
    return decision


def count_used(username: str, session_id: str, *, turn_seq: int, plan_run_id: str | None,
               own_batch_id: str) -> int:
    """The sub-agent rows that count against a depth 0 caller's budget.

    The plan budget counts the rows of the plan run, and the turn budget the rows of the
    turn. Both exclude continuations and the rows of the caller's own batch.
    """
    from database.agent_runs import _client

    scope = ("plan_run_id = {p:UUID}" if plan_run_id else "turn_seq = {t:UInt32}")
    with _client() as client:
        rows = client.query(
            "SELECT count() FROM agent_runs FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND " + scope +
            " AND depth >= 1 AND continues_run_id IS NULL "
            "AND (batch_id IS NULL OR batch_id != {b:UUID})",
            parameters={"u": username, "s": session_id, "t": int(turn_seq),
                        "p": plan_run_id or "00000000-0000-0000-0000-000000000000",
                        "b": own_batch_id},
        ).result_rows
    return int(rows[0][0]) if rows else 0


def limit_for(plan_run_id: str | None) -> int:
    return plan_limit() if plan_run_id else turn_limit()


__all__ = [
    "Accepted", "BUDGET_SPENT", "DEPTH_LIMIT", "Decision", "MAX_BRIEFINGS_PER_CALL",
    "MAX_DEPTH", "TOO_MANY_BRIEFINGS", "count_used", "decide", "limit_for", "plan_limit",
    "turn_limit",
]
