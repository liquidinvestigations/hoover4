"""The skill tools and the tool descriptions available to a run."""

import json

import pytest

from agent_common.tool_packs import allowed_tools
from research_agent import skill_tools, steps
from research_agent.skill_store import SkillContext, always_read, listed_skills
from research_agent.tool_catalogue import build_snapshot


LOCAL_TOOLS = {"search_agent_tools", "search_skills", "read_skill", "read_tool", "ask_user"}


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"Do the work of {name.replace('_', ' ')}.\nMore text."
        self.args_schema = {
            "type": "object", "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }


def snapshot(kind="chat", packs="all", profile=None):
    allowed = allowed_tools(kind, packs)
    if kind == "subagent":
        allowed -= {"ask_user"}
    tools = [FakeTool(n) for n in sorted(allowed) if n not in LOCAL_TOOLS]
    ctx = SkillContext(profile=profile, tool_names=frozenset()) if profile else None
    return build_snapshot(tools, allowed, kind, ctx)


async def call(snap, tool_name, **args):
    result = await snap.tools_by_name[tool_name].ainvoke(
        {"type": "tool_call", "id": "c", "name": tool_name, "args": args})
    return result.status, result.content


async def test_read_tool_describes_a_callable_tool():
    snap = snapshot()
    status, content = await call(snap, "read_tool", name="doc_email")
    data = json.loads(content)
    assert status == "success"
    assert data["tool"] == "doc_email"
    assert "ready" not in data
    assert data["description"].startswith("Do the work of doc email.")
    assert data["parameters"] == {
        "properties": {"query": {"type": "string"}}, "required": ["query"]}
    assert "doc_email" in snap.callable_names()


async def test_search_skills_with_no_query_lists_every_listed_skill():
    snap = snapshot(profile="full_research")
    _, content = await call(snap, "search_skills")
    names = [match["name"] for match in json.loads(content)["matches"]]
    assert names == [skill.name for skill in listed_skills(snap.skill_context)]


async def test_search_skills_ranks_by_description():
    snap = snapshot(profile="full_research")
    _, content = await call(snap, "search_skills", query="cite")
    assert json.loads(content)["matches"][0]["name"] == "citation"


async def test_read_skill_renders_for_the_run():
    snap = snapshot(profile="research_subagent", kind="subagent")
    status, content = await call(snap, "read_skill", name="citation")
    assert status == "success"
    assert content.startswith("Skill `citation`.\n\n")


async def test_read_skill_of_another_profile_is_refused():
    snap = snapshot(profile="full_research")
    status, content = await call(snap, "read_skill", name="method_organizer")
    data = json.loads(content)
    assert status == "error"
    assert data["error"] == "unknown_skill"


async def test_read_tool_of_an_unknown_name_is_refused():
    snap = snapshot()
    status, content = await call(snap, "read_tool", name="nope")
    data = json.loads(content)
    assert status == "error"
    assert data["error"] == "tool_unavailable"
    assert data["message"] == (
        "No tool of this run is named 'nope'. Find tools with search_agent_tools.")


@pytest.mark.parametrize("kind,profile", [
    ("chat", "full_research"), ("chat", "internal_search"),
    ("subagent", "research_subagent"), ("planner", "planner"),
    ("organizer", "organizer"),
])
def test_each_run_kind_lists_its_tools_and_reads_its_skills(kind, profile):
    snap = snapshot(kind, profile=profile)
    assert "read_skill" in snap.callable_names()
    assert "read_tool" in snap.callable_names()
    assert always_read(snap.skill_context)
    assert ("ask_user" in snap.callable_names()) == (kind != "subagent")


async def test_ask_user_returns_the_question_and_options():
    snap = snapshot()
    status, content = await call(snap, "ask_user", question="Bigger or smaller than 50?",
                                 options=["bigger", "smaller"])
    assert status == "success"
    assert json.loads(content) == {"success": True, "asked": True,
                                   "question": "Bigger or smaller than 50?",
                                   "options": ["bigger", "smaller"]}


async def test_ask_user_validates_question_and_options():
    snap = snapshot()
    with pytest.raises(Exception):
        await call(snap, "ask_user", options=[])
    with pytest.raises(Exception):
        await call(snap, "ask_user", question="Which?", options=["x"] * 7)


async def test_tool_call_route_needs_no_bound_names():
    snap = snapshot()

    class Agent:
        async def context_for(self, *args, **kwargs):
            return type("Context", (), {"snapshot": snap})()

    request = steps.ToolCallRequest(
        run_id="r", kind="chat", depth=0, username="u", session_id="s",
        call={"id": "c", "name": "read_tool", "args": {"name": "doc_email"}},
        idempotency_key="k",
    )
    result = await steps.run_tool_call(Agent(), request)
    assert result["status"] == "ok"
    assert json.loads(result["content"])["tool"] == "doc_email"
