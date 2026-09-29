"""The sub-agent budgets of a run that delegates.

`delegate_step` applies these rules to the briefings of one delegation, in call order, and
refuses the surplus briefings with a reason. The refused briefings go into the delegating
run's `refused_json`, and the continuation gives them to the model beside the reports.

| rule | caller | count | limit |
|---|---|---|---|
| plan budget | depth 0 with a plan run | sub-agent rows of the plan run | `AGENT_PLAN_RUN_BUDGET`, at most `MAX_PLAN_SUBAGENTS` |
| plan section | every caller | none | a briefing with `plan_node_id` is valid only in an `organizer` run, for a section of the approved tree, with a `purpose` of `PURPOSES` |
| review | organizer | none | the purpose `review` is refused `review_not_allowed` |
| one run a section | organizer | `execute` sub-agent rows of the section | 1, then `section_already_run` |
| corrections | organizer | `correct` sub-agent rows of the plan run | `MAX_PLAN_CORRECTIONS`, then `correction_limit` |

The plan rules run before the budget rules, so a refused briefing takes no share of the
budget. A briefing with no `plan_node_id` outside a plan loses its `purpose` and `sections`.
A refusal by the plan section rule names the sections of the approved tree in its `message`.
A `correct` briefing names every section it corrects in `sections`, and `plan_node_id` is one
of them. One correction covers every section it names.

A sub-agent row is a row with `depth >= 1` and no `continues_run_id`, because a
continuation takes the place of a run and is not a new sub-agent. The counts exclude the rows
of the caller's own batch, so a retry of the same delegation counts what it counted first.

The organizer accepts briefings in call order until the plan budget is spent. Its children
receive no delegation share.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

#: The most sub-agent runs of one plan. Section, correction and off-tree work share it.
#: `AGENT_PLAN_RUN_BUDGET` can lower it and never raise it.
MAX_PLAN_SUBAGENTS = 5
DEFAULT_PLAN_LIMIT = MAX_PLAN_SUBAGENTS
#: The most sections of a plan. Mirrors `MAX_SECTIONS` in `database/agent_plans.py`. The
#: skill `method_planner` of the research agent states the same number.
MAX_PLAN_SECTIONS = 4

#: The refusal reasons, as the model reads them in the continuation's tool result.
BUDGET_SPENT = "subagent_budget_spent"
PLAN_NODE_NOT_ALLOWED = "plan_node_not_allowed"
CORRECTION_LIMIT = "correction_limit"
REVIEW_NOT_ALLOWED = "review_not_allowed"
SECTION_ALREADY_RUN = "section_already_run"

#: The last sentence of a refusal by the plan section rule.
SECTION_NOT_TASK = ("A briefing names a section in plan_node_id, and never one of its tasks. "
                    "Put the task in the objective.")

#: The most `correct` sub-agent runs of one plan. A second correction is refused.
MAX_PLAN_CORRECTIONS = 1
#: The purposes an organizer's briefing may name.
PURPOSES = ("execute", "correct")


def _positive(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    value = int(raw)
    if value < 0:
        raise ValueError(f"{name} is {value}, and it must be 0 or more")
    return value


def plan_limit() -> int:
    """`AGENT_PLAN_RUN_BUDGET`: the sub-agent runs of one plan run, at most
    `MAX_PLAN_SUBAGENTS`."""
    return min(_positive("AGENT_PLAN_RUN_BUDGET", DEFAULT_PLAN_LIMIT), MAX_PLAN_SUBAGENTS)


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


#: The most sections that the refusal of a briefing names.
MAX_NAMED_SECTIONS = 20


def _refusal(call_id: str, briefing: dict[str, Any], reason: str,
             message: str = "") -> dict[str, Any]:
    refusal = {"tool_call_id": call_id, "objective": str(briefing.get("objective") or ""),
               "reason": reason}
    if message:
        refusal["message"] = message
    return refusal


def _sections_text(sections: Mapping[str, str] | set[str] | None) -> str:
    """The valid section ids, with their titles when `sections` maps ids to titles.

    Empty when there is no section. At most `MAX_NAMED_SECTIONS` are named. The text ends
    with `SECTION_NOT_TASK`, because the usual refused node is a task of a named section.
    """
    if not sections:
        return ""
    titles = sections if isinstance(sections, Mapping) else {}
    named = [f"{node} ({titles[node]})" if titles.get(node) else str(node)
             for node in list(sections)[:MAX_NAMED_SECTIONS]]
    return ("The sections are: " + ", ".join(named) + ". " + SECTION_NOT_TASK)


def _plan_refusal(briefing: dict[str, Any], kind: str,
                  sections: Mapping[str, str] | set[str] | None,
                  runs: dict[str, int], in_plan: bool) -> str:
    """The plan rules for one briefing, in order. Empty when it passes.

    `runs` holds `{"execute:<node>": n, "correct": n}`. An accepted briefing is counted into
    it, so a second briefing of one section in the same call counts the first.
    """
    node = str(briefing.get("plan_node_id") or "").strip()
    purpose = str(briefing.get("purpose") or "").strip()
    if not node:
        briefing.pop("purpose", None)
        briefing.pop("plan_node_id", None)
        briefing.pop("sections", None)
        return ""
    if purpose == "review":
        return REVIEW_NOT_ALLOWED
    if kind != "organizer" or not sections or node not in sections or purpose not in PURPOSES:
        return PLAN_NODE_NOT_ALLOWED
    briefing["plan_node_id"], briefing["purpose"] = node, purpose
    if purpose == "execute":
        if runs.get(f"execute:{node}", 0) >= 1:
            return SECTION_ALREADY_RUN
        runs[f"execute:{node}"] = 1
        briefing.pop("sections", None)
        return ""
    raw = briefing.get("sections")
    named = [str(s).strip() for s in raw] if isinstance(raw, list) and raw else [node]
    if node not in named or any(s not in sections for s in named):
        return PLAN_NODE_NOT_ALLOWED
    if runs.get("correct", 0) >= MAX_PLAN_CORRECTIONS:
        return CORRECTION_LIMIT
    runs["correct"] = runs.get("correct", 0) + 1
    briefing["sections"] = sorted(set(named), key=named.index)
    return ""


def decide(calls: list[tuple[str, list[dict[str, Any]]]], *, depth: int, used: int,
           limit: int, own_share: int, kind: str = "chat",
           sections: Mapping[str, str] | set[str] | None = None,
           section_runs: dict[str, int] | None = None,
           in_plan: bool = False) -> Decision:
    """Apply the rules to the briefings of one delegation.

    `calls` holds `(tool_call_id, briefings)` for each `run_subagent` call, in call order.
    `used` is the count of the plan budget, and `limit` its limit. `kind` is the caller's run kind,
    `sections` the sections of the approved tree for an organizer, as `{node_id: title}` or
    as a set of node ids, and `section_runs` the counts of `count_section_runs`. `in_plan` is
    true for a run of a plan. A refusal for a node that is not a section names the sections
    in its `message`.
    """
    decision = Decision(caller_share=own_share)
    runs = dict(section_runs or {})
    wanted: list[tuple[str, dict[str, Any]]] = []
    for call_id, briefings in calls:
        for briefing in briefings:
            if reason := _plan_refusal(briefing, kind, sections, runs, in_plan):
                message = _sections_text(sections) if reason == PLAN_NODE_NOT_ALLOWED else ""
                decision.refused.append(_refusal(call_id, briefing, reason, message))
            else:
                wanted.append((call_id, briefing))
    allowance = max(0, limit - used)
    k = min(len(wanted), allowance)
    for call_id, briefing in wanted[k:]:
        decision.refused.append(_refusal(call_id, briefing, BUDGET_SPENT))
    for call_id, briefing in wanted[:k]:
        decision.accepted.append(Accepted(call_id, briefing, 0))
    return decision


def count_used(username: str, session_id: str, *, turn_seq: int, plan_run_id: str | None,
               own_batch_id: str) -> int:
    """The sub-agent rows that count against a depth 0 caller's budget.

    The plan budget counts the rows of the plan run. It excludes continuations and the
    rows of the caller's own batch.
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


def count_section_runs(username: str, session_id: str, *, plan_run_id: str,
                       own_batch_id: str) -> dict[str, int]:
    """`{"execute:<node>": n, "correct": n}` over the sub-agent rows of a plan run, outside
    the caller's own batch, so a retry of the same delegation counts what it counted first."""
    from database.agent_runs import _client

    with _client() as client:
        rows = client.query(
            "SELECT purpose, toString(plan_node_id), count() FROM agent_runs FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} "
            "AND plan_run_id = {p:UUID} AND purpose IN ('execute', 'correct') "
            "AND continues_run_id IS NULL AND plan_node_id IS NOT NULL "
            "AND (batch_id IS NULL OR batch_id != {b:UUID}) GROUP BY purpose, plan_node_id",
            parameters={"u": username, "s": session_id, "p": plan_run_id,
                        "b": own_batch_id},
        ).result_rows
    runs: dict[str, int] = {}
    for purpose, node, n in rows:
        key = f"execute:{node}" if purpose == "execute" else "correct"
        runs[key] = runs.get(key, 0) + int(n)
    return runs


def limit_for(plan_run_id: str | None) -> int:
    return plan_limit()


__all__ = [
    "Accepted", "BUDGET_SPENT", "CORRECTION_LIMIT", "Decision",
    "MAX_PLAN_CORRECTIONS", "MAX_PLAN_SECTIONS",
    "MAX_PLAN_SUBAGENTS", "PLAN_NODE_NOT_ALLOWED", "PURPOSES",
    "REVIEW_NOT_ALLOWED", "SECTION_ALREADY_RUN", "count_section_runs",
    "count_used", "decide", "limit_for", "plan_limit",
]
