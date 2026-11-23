"""The skill and tool reads before the first call of a tool. See research_agent/prerequisites.py."""

import dataclasses
import json

import pytest

from research_agent import prerequisites, steps
from research_agent.skill_store import SKILLS, SkillContext

from tests.test_steps import RUN, FakeAgent, dict_tool

pytestmark = pytest.mark.prerequisites

LIST_SCHEMA = {"type": "object", "properties": {"query": {"type": "string"}}}


def agent_with(*names):
    seen = []
    tools = [dict_tool(name, LIST_SCHEMA, seen) for name in names]
    agent = FakeAgent(tools, set(names))
    ctx = SkillContext(profile="full_research", tool_names=frozenset(names))
    agent.context = dataclasses.replace(agent.context, skill_context=ctx)
    return agent, seen


def ai(*calls):
    return {"role": "ai", "content": "", "tool_calls": [
        {"id": call_id, "name": name, "args": args} for call_id, name, args in calls]}


def tool(call_id, name, content, status="ok"):
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": content,
            "status": status}


def skill_read(call_id, skill):
    return [ai((call_id, "read_skill", {"name": skill})),
            tool(call_id, "read_skill", f"Skill `{skill}`.\n\nThe method.")]


def tool_read(call_id, name):
    body = {"tool": name, "description": "d", "parameters": {"type": "object"}}
    return [ai((call_id, "read_tool", {"name": name})), tool(call_id, "read_tool", json.dumps(body))]


def request(name, messages, call_id="c9", key="key-9"):
    return steps.ToolCallRequest(
        **RUN, call={"id": call_id, "name": name, "args": {"query": "x"}},
        idempotency_key=key, messages=[{"role": "human", "content": "Find it."}, *messages])


async def test_a_call_without_reads_is_refused_before_it_runs():
    agent, seen = agent_with("web_search")
    result = await steps.run_tool_call(agent, request("web_search", []))
    assert (result["status"], result["error_class"]) == ("error", "missing_prerequisite")
    message = json.loads(result["content"])["message"]
    assert "read_skill with name `web_research`" in message
    assert "read_tool with name `web_search`" in message
    assert seen == []


async def test_a_call_after_both_reads_runs():
    agent, seen = agent_with("web_search")
    messages = skill_read("a", "web_research") + tool_read("b", "web_search")
    result = await steps.run_tool_call(agent, request("web_search", messages))
    assert result["status"] == "ok"
    assert [name for name, *_ in seen] == ["web_search"]


async def test_the_skill_read_alone_leaves_the_definition_missing():
    agent, seen = agent_with("web_search")
    result = await steps.run_tool_call(agent, request("web_search", skill_read("a", "web_research")))
    message = json.loads(result["content"])["message"]
    assert "read_skill" not in message and "read_tool with name `web_search`" in message
    assert seen == []


async def test_a_failed_read_does_not_count():
    agent, seen = agent_with("update_plan")
    messages = [ai(("a", "read_skill", {"name": "todo_upkeep"})),
                tool("a", "read_skill", "Skill `todo_upkeep`.\n\nx", status="error")]
    messages += tool_read("b", "update_plan")
    result = await steps.run_tool_call(agent, request("update_plan", messages))
    assert "read_skill with name `todo_upkeep`" in json.loads(result["content"])["message"]
    assert seen == []


async def test_a_read_that_a_compaction_removed_is_needed_again():
    agent, seen = agent_with("update_plan")
    reads = skill_read("a", "todo_upkeep") + tool_read("b", "update_plan")
    messages = [{**m, "thread_id": "t", "idx": i + 1} for i, m in enumerate(reads)]
    compaction = {"role": "compaction", "thread_id": "t", "idx": 10, "content": json.dumps({
        "version": 3, "status": "ok", "summary": "Earlier work.",
        "source": [["t", i] for i in range(0, 5)]})}
    rows = [{"role": "human", "content": "Plan.", "thread_id": "t", "idx": 0}, *messages]
    call = {"id": "c9", "name": "update_plan", "args": {"query": "x"}}
    before = await steps.run_tool_call(agent, steps.ToolCallRequest(
        **RUN, call=call, idempotency_key="k", messages=rows))
    assert before["status"] == "ok"
    result = await steps.run_tool_call(agent, steps.ToolCallRequest(
        **RUN, call=call, idempotency_key="k2", messages=[*rows, compaction]))
    assert result["error_class"] == "missing_prerequisite"
    message = json.loads(result["content"])["message"]
    assert "todo_upkeep" in message and "update_plan" in message
    assert len(seen) == 1


def test_a_detailed_code_mode_search_gives_the_definition():
    found = {"matches": [{"tool": "read_page", "description": "d", "parameters": {"type": "object"}}]}
    summary = {"matches": [{"name": "web_search", "summary": "s"}]}
    messages = [steps.RunMessage(role="tool", name="search", content=json.dumps(found), status="ok"),
                steps.RunMessage(role="tool", name="search", content=json.dumps(summary), status="ok")]
    _, tools = prerequisites.visible_reads(messages)
    assert tools == {"read_page"}


async def test_discovery_and_policy_calls_need_no_reads():
    agent, seen = agent_with("read_page")
    result = await steps.run_tool_call(agent, request("read_page", [], call_id="ctl-load-0"))
    assert result["status"] == "ok"
    assert prerequisites.missing_reads("read_skill", "c1", [], SKILLS.values()) == ([], False)


async def test_a_skill_that_the_run_does_not_list_is_not_required():
    agent, seen = agent_with("whois_lookup")
    ctx = SkillContext(profile="full_research", tool_names=frozenset({"search_skills"}))
    agent.context = dataclasses.replace(agent.context, skill_context=ctx)
    result = await steps.run_tool_call(agent, request("whois_lookup", tool_read("b", "whois_lookup")))
    assert result["status"] == "ok"


def test_every_required_by_name_is_a_tool_the_skill_relates_to():
    """`required_by` names only tools of a pack, and the main workflows have their skill."""
    required = {tool: prerequisites.required_skills(tool, SKILLS.values())
                for tool in ("update_plan", "web_search", "browser_navigate", "search_collections",
                             "cite_documents", "cite_chats_and_boards", "write_file",
                             "patch_file", "finish_with_report")}
    assert required == {
        "update_plan": ["todo_upkeep"], "web_search": ["web_research"],
        "browser_navigate": ["browser_use"], "search_collections": ["search"],
        "cite_documents": ["citation"], "cite_chats_and_boards": ["earlier_work"],
        "write_file": ["report"], "patch_file": ["report"], "finish_with_report": ["report"],
    }
