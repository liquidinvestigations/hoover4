"""Delegation: the briefing shape and the `run_subagent` schema.

`/model_step` classifies a readable `run_subagent` call as a delegation, and `/tool_call`
refuses the others before any tool body runs (`test_steps.py` covers both). The worker
applies the budgets. What is tested here is the shape the
model sees and the coercion of what it sends.
"""

import asyncio

import pytest

from research_agent import subagents


def test_a_briefing_text_carries_the_objective_the_context_and_the_deliverable():
    text = subagents.briefing_text(subagents.Briefing(
        objective="Find the contract.", known="It is from 2019.", bring_back="The date."))
    assert text.startswith("Objective: Find the contract.")
    assert "It is from 2019." in text and "The date." in text


def test_a_json_string_of_tasks_is_accepted():
    briefings = subagents._as_briefings('[{"objective": "a"}, {"objective": "b"}]')
    assert [b.objective for b in briefings] == ["a", "b"]


def test_nonsense_tasks_are_refused():
    assert subagents._as_briefings(42) is None
    assert subagents._as_briefings([{"known": "no objective"}]) is None


def test_a_plan_briefing_keeps_its_section_and_purpose():
    [briefing] = subagents._as_briefings(
        [{"objective": "a", "plan_node_id": "n1", "purpose": "review"}])
    assert (briefing.plan_node_id, briefing.purpose) == ("n1", "review")
    assert subagents._as_briefings([{"objective": "a", "purpose": "other"}]) is None


def test_the_tool_schema_takes_a_list_of_briefings_and_its_body_never_runs():
    tool = subagents.make_delegation_tool()
    assert tool.name == subagents.DELEGATION_TOOL
    schema = tool.args_schema.model_json_schema()
    assert "tasks" in schema["properties"]
    with pytest.raises(RuntimeError, match="never in process"):
        asyncio.run(tool.coroutine(tasks=[{"objective": "a"}]))
