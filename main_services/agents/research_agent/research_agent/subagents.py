"""Delegation: the `run_subagent` tool schema and the briefing it carries.

A hard research question is several independent questions wearing one coat. The lead
agent splits it into briefings, and each briefing runs as a sub-agent run of its own with
fresh context. The sub-agents do not talk to each other.

A `/run/stream` run stops at `run_subagent` (`execution.py`). The worker then starts each
accepted briefing as an `AgentRun` of its own, up to depth 2, and applies the budgets
(`tasks/P_agent/run_budgets.py`). This module defines the tool the model sees and the
briefing shape. The tool body never runs, because the execution node stops first.

**Depth is enforced by what is bound, not by what the prompt asks.** A run at depth 2 binds
no `run_subagent`. Which run kinds bind it is decided by the tool packs
(`agent_common.tool_packs`).

**Every cap is a number.** Asking for more tasks than a cap allows does not fail the call:
the surplus is refused *by name* in the result that the continuation receives.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

#: The name the lead agent calls to delegate.
DELEGATION_TOOL = "run_subagent"


def _cap(name: str, default: int) -> int:
    """A cap from the environment, falling back to its default.

    Tolerant of an unset variable AND of one set to the empty string, because compose
    renders every optional setting as `NAME=${NAME:-}` and an empty value there means "use
    the default". Read at import: a cap that changed mid-process would apply to some
    conversations and not others.
    """
    try:
        return max(1, int(os.getenv(name) or default))
    except ValueError:
        return default


#: Tasks one `run_subagent` call may carry. The published upper end of "3-5 per wave";
#: beyond it a model is fanning out instead of decomposing.
MAX_TASKS_PER_CALL = _cap("AGENT_SUBAGENT_MAX_TASKS", 5)


class Briefing(BaseModel):
    """One task, as the lead hands it over.

    Three fields and not a free-text string, because a worker starting from nothing
    repeats the search the lead already ran. `known` is what the lead has established
    already; `bring_back` is what the report has to contain to be usable.
    """

    objective: str = Field(
        description="The one question this worker is to answer, in a sentence."
    )
    known: str = Field(
        default="",
        description=(
            "What is already established, so the worker does not repeat work the lead "
            "has already done. Names, dates, collection names, findings so far."
        ),
    )
    bring_back: str = Field(
        default="",
        description=(
            "What the report must contain to be usable: the facts, the quotes, the "
            "documents to cite."
        ),
    )
    plan_node_id: Optional[str] = Field(
        default=None,
        description=(
            "Organizer only: the node_id of the plan section this briefing works on. "
            "Leave it out in every other run."
        ),
    )
    purpose: Optional[Literal["execute", "review", "correct"]] = Field(
        default=None,
        description=(
            "Organizer only, with plan_node_id: execute the section, review its report, "
            "or correct it after a rejected review."
        ),
    )


def briefing_text(briefing: Briefing) -> str:
    """The briefing as the worker receives it: objective, context, deliverable."""
    parts = [f"Objective: {briefing.objective.strip()}"]
    if briefing.known.strip():
        parts.append(f"Already established, do not re-derive:\n{briefing.known.strip()}")
    if briefing.bring_back.strip():
        parts.append(f"Bring back:\n{briefing.bring_back.strip()}")
    parts.append(
        "Answer this objective only. Write your report as prose, and cite the documents "
        "you relied on with `cite_documents` before you finish."
    )
    return "\n\n".join(parts)


def _as_briefings(value: Any) -> Optional[List[Briefing]]:
    """Coerce whatever the model sent into a list of briefings.

    The same coercion `cite_documents` needs, for the same reason: an XML-style tool-call
    parser hands a list argument across as a JSON string, and rejecting it teaches the
    model nothing at the moment it made the mistake.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return None
    out: List[Briefing] = []
    for item in value:
        if isinstance(item, Briefing):
            out.append(item)
            continue
        if isinstance(item, str):
            out.append(Briefing(objective=item))
            continue
        if not isinstance(item, dict):
            return None
        try:
            out.append(Briefing(**item))
        except Exception:  # noqa: BLE001 - a malformed entry is a caller error
            return None
    return out


def make_delegation_tool() -> StructuredTool:
    """The `run_subagent` tool, for its schema.

    The execution node of a `/run/stream` graph stops at a `run_subagent` call before it
    runs any tool body, so this body refuses. A call that reaches it is a graph that was
    built without the stop.
    """

    async def run_subagent(tasks: Any) -> Dict[str, Any]:
        raise RuntimeError("a run delegates through its run rows, never in process")

    return StructuredTool.from_function(
        coroutine=run_subagent,
        name=DELEGATION_TOOL,
        description=(
            "Delegate independent parts of a hard question to several researchers at "
            "once, each starting fresh and working only on what you give it. Send "
            f"between two and {MAX_TASKS_PER_CALL} tasks in one call; each is a briefing "
            "with an `objective` (the one question it answers), `known` (what you have "
            "already established, so it does not repeat your work) and `bring_back` "
            "(what its report must contain). They run in parallel and cannot see each "
            "other. Each returns a written report plus the citation handles it "
            "allocated, which are yours to write into your answer. "
            "Use it when parts of the question can be pursued independently; do the work "
            "yourself when it is one thread."
        ),
        args_schema=type(
            "RunSubagentArgs",
            (BaseModel,),
            {
                "__annotations__": {"tasks": List[Briefing]},
                "tasks": Field(description="The briefings to run, one per worker."),
            },
        ),
    )
