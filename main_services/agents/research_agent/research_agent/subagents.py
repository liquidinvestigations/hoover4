"""Delegation: one lead agent, several workers, exactly one level deep.

A hard research question is several independent questions wearing one coat. The lead
agent splits it into briefings, runs them at once with fresh context each, and writes the
answer from what comes back. Workers do not talk to each other and do not plan; they have
one objective and a small budget.

**Depth is enforced by what is bound, not by what the prompt asks.** `run_subagent` is
added to the lead's tool list here and is never in the list `worker_tools` filters, so a
worker cannot delegate however it is prompted. A prompt asking a model not to recurse
eventually meets a model that does; a tool that is absent cannot be called by any of them.
That is why there is no environment variable for the depth, unlike every other cap below.

**Every cap is a number.** The measured cost of an orchestrator-plus-workers run is
roughly an order of magnitude over a plain turn, so "please use few workers" in a prompt
is not a budget. Asking for more tasks than the cap allows does not fail the call: the
surplus is refused *by name* in the response, the way every other batched tool here
reports what it would not do.

**Workers share the lead's chat session, and that is the citation contract.** Handles are
allocated per session by the collection-search server (`citations.HandleTable`), keyed by
the session header the MCP connection carries. A worker citing a document in a session of
its own would hand back `[D1]` meaning something the lead cannot resolve, and an answer
citing a document nobody can open is a correctness bug. Reusing the lead's connections
gives the lead's session id for free, and has a second benefit: `read_page` runs against
the conversation's single browser context rather than opening one per worker, so a
delegating turn costs the browser server exactly what a plain turn costs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, RemoveMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from research_agent import compaction

log = logging.getLogger(__name__)

#: The name the lead agent calls to delegate.
DELEGATION_TOOL = "run_subagent"

#: Profiles whose agent binds the delegation tool. One entry, and it is the whole depth
#: limit: the worker profile is not in it, so a worker's tool list is built without
#: `run_subagent` and no prompt can put it back.
DELEGATING_PROFILES = frozenset({"full_research"})

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

#: Workers running at once. Sized to what the serving configuration can actually keep
#: busy — more in flight buys queueing, not answers.
MAX_CONCURRENCY = _cap("AGENT_SUBAGENT_CONCURRENCY", 3)

#: Tool turns one worker may take before it is made to write its report. The failure mode
#: this bounds is one worker that never stops, which a lead cannot detect from outside.
WORKER_TOOL_TURNS = _cap("AGENT_SUBAGENT_TOOL_TURNS", 6)

#: Workers one user turn may spend in total, across every `run_subagent` call it makes.
#: Per-call is not enough: a nagged turn runs the agent again and the second run can
#: delegate again, so the ceiling that matters is the turn's, not the wave's.
MAX_WORKERS_PER_TURN = _cap("AGENT_SUBAGENT_MAX_PER_TURN", 10)

#: Tools a worker does not get, by name.
#:
#: The interactive browser six, because each needs a persistent context and the server
#: holds eight in total; `read_page` is the overwhelmingly common browser action, needs no
#: persistent context, and is deliberately still there. The three todo *writers*, because
#: the plan belongs to the conversation and a worker with one objective has nothing to
#: plan — `read_todo` stays so a worker can see the plan its briefing came out of.
#:
#: `run_subagent` is here as well as being absent from what a worker is built from. That
#: is redundant on purpose: the primary guarantee is that the delegation tool is appended
#: after `worker_tools` has run, and this second one covers the day an MCP server starts
#: advertising a tool of that name. A depth limit that holds one way holds until someone
#: changes that way.
WORKER_DENIED_TOOLS = frozenset(
    {
        DELEGATION_TOOL,
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_press_key",
        "write_todo",
        "edit_todo",
        "mark_todo",
    }
)


def worker_tools(tools: Sequence[Any]) -> List[Any]:
    """The lead's MCP tools, minus the ones a worker must not have.

    The delegation tool is normally not in the list this is given at all — it is appended
    to the lead's list *after* this has run — so the filter below is the second of two
    independent reasons a worker cannot delegate. See `WORKER_DENIED_TOOLS`.
    """
    return [tool for tool in tools if getattr(tool, "name", "") not in WORKER_DENIED_TOOLS]


def delegates(profile: str) -> bool:
    """Whether an agent running this profile binds the delegation tool."""
    return (profile or "").strip().lower() in DELEGATING_PROFILES


#: Workers already spent by the user turn currently running.
#:
#: A `ContextVar` for the same reason the compaction trail is one: the compiled graph is
#: cached and shared across concurrent conversations, while the budget belongs to exactly
#: one of them. A run that never installs a counter is not delegating under a budget —
#: which is the case for a direct call in a test — and gets the per-call cap only.
_WORKERS_SPENT: ContextVar[Optional[List[int]]] = ContextVar(
    "hoover4_subagent_workers_spent", default=None
)

#: Live turn budgets, by chat session. Bounded, least-recently-used, for the reason every
#: per-session map in this process is: one process serves every conversation on the site.
_TURN_BUDGETS: "OrderedDict[str, List[int]]" = OrderedDict()
MAX_TRACKED_TURNS = _cap("AGENT_SUBAGENT_TRACKED_TURNS", 512)


def start_turn(session_id: Optional[str] = None, continuing: bool = False) -> List[int]:
    """Install this run's worker budget and return its cell.

    Called once per run by the lead's `stream`. The cell is a single-element list so the
    tool mutates the same counter rather than rebinding a name.

    **A nag round continues the turn's budget rather than starting a new one.** A nagged
    turn is the agent run again on the same user message, and it can delegate again, so a
    budget reset per run would multiply the ceiling by the nag count — which is exactly
    the case the cap exists for. The chat workflow's own signal for "this is a nag round"
    is a non-zero extra tool budget, and `continuing` is that signal; a first round with a
    session id clears whatever the previous turn left behind.
    """
    if session_id and continuing:
        spent = _TURN_BUDGETS.get(session_id)
        if spent is not None:
            _TURN_BUDGETS.move_to_end(session_id)
            _WORKERS_SPENT.set(spent)
            return spent
    spent = [0]
    if session_id:
        _TURN_BUDGETS[session_id] = spent
        _TURN_BUDGETS.move_to_end(session_id)
        while len(_TURN_BUDGETS) > MAX_TRACKED_TURNS:
            _TURN_BUDGETS.popitem(last=False)
    _WORKERS_SPENT.set(spent)
    return spent


def _take_worker_slots(wanted: int) -> int:
    """Claim up to `wanted` slots from the turn's budget, returning how many were given."""
    spent = _WORKERS_SPENT.get()
    if spent is None:
        return wanted
    room = max(0, MAX_WORKERS_PER_TURN - spent[0])
    granted = min(wanted, room)
    spent[0] += granted
    return granted


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
            "What the report must contain to be usable — the facts, the quotes, the "
            "documents to cite."
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


def build_worker_graph(
    llm: Any,
    plain_llm: Any,
    system_prompt: str,
    tools: Sequence[Any],
    state_schema: Any,
):
    """A worker's own agent loop: call tools, then answer, under a fixed budget.

    Deliberately smaller than the lead's graph. There is no nag, no plan-first opening and
    no repeat-call guard beyond the budget, because a worker has one objective and
    `WORKER_TOOL_TURNS` turns to meet it: the cheapest correct behaviour when it runs out
    is to write up what it has, which is what the forced-answer node does.
    """
    prompt = ChatPromptTemplate.from_messages(
        [("system", system_prompt), MessagesPlaceholder(variable_name="messages")]
    )
    builder = StateGraph(state_schema)
    builder.add_node("agent", prompt | {"messages": llm})
    builder.add_node("tools", ToolNode(list(tools)))

    def should_continue(state):
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return END
        turns = sum(1 for m in state["messages"] if getattr(m, "tool_calls", None))
        if turns >= WORKER_TOOL_TURNS:
            log.info("subagent hit its %d-turn budget; forcing a report", WORKER_TOOL_TURNS)
            return "report_entry"
        return "tools"

    def report_entry(state):
        # The trailing AIMessage holds tool calls that will never be satisfied, and an
        # OpenAI-shaped request carrying tool_calls with no matching results is rejected
        # outright. `add_messages` merges by id and cannot delete, hence `RemoveMessage`.
        last = state["messages"][-1]
        return {
            "messages": [
                RemoveMessage(id=last.id),
                HumanMessage(
                    content=(
                        "Stop searching and write your report now, from what the tool "
                        "results above already contain. Say plainly what you could not "
                        "establish."
                    )
                ),
            ]
        }

    builder.add_node("report_entry", report_entry)
    builder.add_node("report", prompt | {"messages": plain_llm})
    builder.set_entry_point("agent")
    builder.add_conditional_edges("agent", should_continue)
    builder.add_edge("tools", "agent")
    builder.add_edge("report_entry", "report")
    builder.add_edge("report", END)
    return builder.compile()


def _report_of(messages: Sequence[BaseMessage]) -> str:
    """The worker's last piece of prose."""
    for message in reversed(messages):
        if getattr(message, "tool_calls", None):
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if isinstance(content, str) and content.strip():
            return content.strip()
    return ""


def make_delegation_tool(run_worker: Callable[[str], Any]) -> StructuredTool:
    """The `run_subagent` tool, over a callable that runs one briefing to completion.

    `run_worker` takes the briefing text and returns the worker's finished message list.
    Injecting it keeps the graph construction in `agent.py`, where the model and the MCP
    connections already live.
    """

    async def run_subagent(tasks: Any) -> Dict[str, Any]:
        briefings = _as_briefings(tasks)
        if briefings is None:
            return {
                "success": False,
                "error": "tasks must be a list of {objective, known, bring_back}",
            }
        if not briefings:
            return {"success": False, "error": "no tasks were given"}

        notes: List[str] = []
        refused: List[str] = []
        if len(briefings) > MAX_TASKS_PER_CALL:
            for surplus in briefings[MAX_TASKS_PER_CALL:]:
                refused.append(surplus.objective)
            notes.append(
                f"{len(briefings)} tasks were asked for and this call runs at most "
                f"{MAX_TASKS_PER_CALL}. Refused: "
                + "; ".join(f'"{objective}"' for objective in refused)
                + ". Split the work differently or delegate the rest in a later call."
            )
            briefings = briefings[:MAX_TASKS_PER_CALL]

        granted = _take_worker_slots(len(briefings))
        if granted < len(briefings):
            for surplus in briefings[granted:]:
                refused.append(surplus.objective)
            notes.append(
                f"This turn has spent its budget of {MAX_WORKERS_PER_TURN} sub-agents, "
                f"so {len(briefings) - granted} of these did not run. Refused: "
                + "; ".join(f'"{b.objective}"' for b in briefings[granted:])
                + ". Answer from what you have."
            )
            briefings = briefings[:granted]
        if not briefings:
            return {
                "success": False,
                "reports": [],
                "refused": refused,
                "note": " ".join(notes),
                "error": "no sub-agent was run",
            }

        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

        async def one(index: int, briefing: Briefing) -> Dict[str, Any]:
            async with semaphore:
                try:
                    messages = await run_worker(briefing_text(briefing))
                except Exception as exc:  # noqa: BLE001 - one worker must not fail the wave
                    log.warning("sub-agent %d failed: %s", index + 1, exc)
                    return {
                        "task": index + 1,
                        "objective": briefing.objective,
                        "report": "",
                        "handles": [],
                        "citations": [],
                        "error": str(exc),
                    }
            return {
                "task": index + 1,
                "objective": briefing.objective,
                "report": _report_of(messages),
                # Handles the worker's own `cite_documents` calls allocated. They are the
                # lead's handles: the worker ran on the lead's session, so writing one of
                # these into the answer resolves to the document the worker read.
                "handles": compaction.issued_citations(messages),
                "citations": compaction.citation_index(messages),
                "tool_calls": sum(
                    1 for m in messages if getattr(m, "tool_calls", None)
                ),
            }

        results = await asyncio.gather(
            *(one(i, briefing) for i, briefing in enumerate(briefings))
        )
        thin = [r["objective"] for r in results if not r.get("report")]
        if thin:
            notes.append(
                "These came back with no report and are yours to redo or answer without: "
                + "; ".join(f'"{objective}"' for objective in thin)
                + "."
            )
        return {
            "success": True,
            "reports": list(results),
            "refused": refused,
            "note": " ".join(notes),
        }

    return StructuredTool.from_function(
        coroutine=run_subagent,
        name=DELEGATION_TOOL,
        description=(
            "Delegate independent parts of a hard question to several researchers at "
            "once, each starting fresh and working only on what you give it. Send "
            f"between two and {MAX_TASKS_PER_CALL} tasks in one call; each is a briefing "
            "with an `objective` (the one question it answers), `known` (what you have "
            "already established, so it does not repeat your work) and `bring_back` "
            "(what its report must contain). They run in parallel, cannot see each "
            "other, and cannot delegate further. Each returns a written report plus the "
            "citation handles it allocated, which are yours to write into your answer. "
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
