"""Delegation: the caps, the depth limit, and the citation handles that come back."""

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from research_agent import prompts, subagents


class FakeTool:
    def __init__(self, name):
        self.name = name


ALL_TOOLS = [
    FakeTool(name)
    for name in (
        "search_collections",
        "read_documents",
        "cite_documents",
        "web_search",
        "read_page",
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_press_key",
        "read_todo",
        "write_todo",
        "edit_todo",
        "mark_todo",
    )
]


def tool_names(tools):
    return {tool.name for tool in tools}


# --------------------------------------------------------------- the depth limit


def test_a_worker_cannot_delegate_because_the_tool_is_not_in_its_list():
    """The whole depth limit, tested where it is enforced.

    The delegation tool is appended to the lead's list after `worker_tools` has run, so
    even a list that already contains one comes back without it.
    """
    pool = subagents.worker_tools(ALL_TOOLS + [FakeTool(subagents.DELEGATION_TOOL)])
    assert subagents.DELEGATION_TOOL not in tool_names(pool)


def test_only_the_full_research_profile_delegates():
    assert subagents.delegates("full_research")
    assert not subagents.delegates("research_subagent")
    assert not subagents.delegates("internal_search")
    assert not subagents.delegates("")


def test_the_worker_profile_exists_and_never_asks_for_a_plan():
    """A worker has no todo writers, so a plan-first instruction would be uncallable."""
    assert "research_subagent" in prompts.PROFILES
    assert prompts.PLAN_FIRST not in prompts.RESEARCH_SUBAGENT
    assert "write_todo" not in prompts.RESEARCH_SUBAGENT


# ------------------------------------------------------------------ the tool surface


def test_a_worker_reads_pages_but_cannot_drive_one():
    pool = tool_names(subagents.worker_tools(ALL_TOOLS))
    assert "read_page" in pool
    for interactive in (
        "browser_navigate",
        "browser_snapshot",
        "browser_click",
        "browser_type",
        "browser_select_option",
        "browser_press_key",
    ):
        assert interactive not in pool


def test_a_worker_reads_the_todo_but_cannot_write_it():
    pool = tool_names(subagents.worker_tools(ALL_TOOLS))
    assert "read_todo" in pool
    assert not {"write_todo", "edit_todo", "mark_todo"} & pool


def test_a_worker_keeps_the_search_and_citation_tools():
    pool = tool_names(subagents.worker_tools(ALL_TOOLS))
    assert {"search_collections", "read_documents", "web_search", "cite_documents"} <= pool


# ------------------------------------------------------------------------ the caps


def _worker_returning(handle="[D1]"):
    """A stand-in worker: one `cite_documents` result, then a report."""
    seen = []

    async def run_worker(text):
        seen.append(text)
        return [
            HumanMessage(content=text),
            AIMessage(
                content="",
                tool_calls=[{"name": "cite_documents", "args": {}, "id": "c1"}],
            ),
            ToolMessage(
                content=(
                    '{"success": true, "citations": [{"handle": "%s", '
                    '"collectionname": "enron", "file_hash": "abc", '
                    '"path": "mail/1.txt"}]}' % handle
                ),
                tool_call_id="c1",
                name="cite_documents",
            ),
            AIMessage(content=f"Report for: {text.splitlines()[0]} %s" % handle),
        ]

    return run_worker, seen


async def test_more_than_five_tasks_is_refused_by_name():
    run_worker, seen = _worker_returning()
    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-refuse")
    result = await tool.coroutine(
        tasks=[{"objective": f"question {i}"} for i in range(1, 8)]
    )
    assert len(result["reports"]) == subagents.MAX_TASKS_PER_CALL
    assert result["refused"] == ["question 6", "question 7"]
    assert "question 6" in result["note"] and "question 7" in result["note"]
    assert len(seen) == subagents.MAX_TASKS_PER_CALL


async def test_the_turn_budget_bounds_every_call_together():
    """A nagged turn delegates again; the ceiling is the turn's, not the wave's."""
    run_worker, seen = _worker_returning()
    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-budget")
    for _ in range(4):
        await tool.coroutine(tasks=[{"objective": "q"} for _ in range(5)])
    assert len(seen) == subagents.MAX_WORKERS_PER_TURN
    # And the run that finds nothing left says so rather than silently doing nothing.
    exhausted = await tool.coroutine(tasks=[{"objective": "one more"}])
    assert exhausted["success"] is False
    assert "one more" in exhausted["note"]


async def test_a_nag_round_continues_the_budget_and_a_new_turn_resets_it():
    run_worker, seen = _worker_returning()
    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-nag")
    await tool.coroutine(tasks=[{"objective": "q"} for _ in range(5)])
    # The nag round: same session, a non-zero extra tool budget.
    subagents.start_turn("session-nag", continuing=True)
    await tool.coroutine(tasks=[{"objective": "q"} for _ in range(5)])
    await tool.coroutine(tasks=[{"objective": "q"}])
    assert len(seen) == subagents.MAX_WORKERS_PER_TURN
    # A fresh user turn on the same session starts over.
    subagents.start_turn("session-nag")
    await tool.coroutine(tasks=[{"objective": "q"}])
    assert len(seen) == subagents.MAX_WORKERS_PER_TURN + 1


async def test_no_more_than_the_concurrency_cap_run_at_once():
    live = 0
    peak = 0

    async def run_worker(text):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.01)
        live -= 1
        return [AIMessage(content="done")]

    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-concurrency")
    await tool.coroutine(tasks=[{"objective": f"q{i}"} for i in range(5)])
    assert peak == subagents.MAX_CONCURRENCY


# ------------------------------------------------------------- what comes back


async def test_a_worker_returns_its_report_and_its_handles():
    run_worker, _ = _worker_returning("[D4]")
    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-handles")
    result = await tool.coroutine(tasks=[{"objective": "who signed it"}])
    report = result["reports"][0]
    assert report["objective"] == "who signed it"
    assert report["report"].startswith("Report for:")
    assert report["handles"] == ["[D4]"]
    assert report["citations"] == ["[D4] enron/abc  mail/1.txt"]


async def test_a_briefing_carries_the_objective_the_context_and_the_deliverable():
    seen = []

    async def run_worker(text):
        seen.append(text)
        return [AIMessage(content="done")]

    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-briefing")
    await tool.coroutine(
        tasks=[
            {
                "objective": "who signed it",
                "known": "the contract is dated 2001",
                "bring_back": "the signatory and a quote",
            }
        ]
    )
    assert "Objective: who signed it" in seen[0]
    assert "the contract is dated 2001" in seen[0]
    assert "the signatory and a quote" in seen[0]


async def test_one_failing_worker_does_not_fail_the_wave():
    async def run_worker(text):
        if "boom" in text:
            raise RuntimeError("worker exploded")
        return [AIMessage(content="fine")]

    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-failure")
    result = await tool.coroutine(
        tasks=[{"objective": "boom"}, {"objective": "steady"}]
    )
    assert result["success"] is True
    failed = [r for r in result["reports"] if r["objective"] == "boom"][0]
    assert failed["error"] == "worker exploded"
    assert [r for r in result["reports"] if r["objective"] == "steady"][0]["report"]
    assert "boom" in result["note"]


async def test_a_json_string_of_tasks_is_accepted():
    """An XML-style tool-call parser hands a list argument across as a JSON string."""
    run_worker, seen = _worker_returning()
    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-string")
    result = await tool.coroutine(tasks='[{"objective": "who signed it"}]')
    assert result["success"] is True
    assert len(seen) == 1


async def test_nonsense_tasks_are_refused_with_the_shape_that_was_wanted():
    async def run_worker(text):  # pragma: no cover - must not be reached
        raise AssertionError("no worker should run")

    tool = subagents.make_delegation_tool(run_worker)
    subagents.start_turn("session-nonsense")
    result = await tool.coroutine(tasks=42)
    assert result["success"] is False
    assert "objective" in result["error"]
