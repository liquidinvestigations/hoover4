"""The endpoints that the worker's policy hooks use, and the pinned assets of a turn.

`/control_snapshot` returns the assets that a turn pins, `/policy_calls` classifies the calls
of a policy action, and a step request with `control` uses the pinned system prompt and
skill texts. A request without `control` uses the current defaults of the service.
"""

import json
from typing import Any, List

from langchain_core.messages import AIMessage

from research_agent import skill_store, steps
from research_agent.agent import AgentContext
from research_agent.skill_store import SkillContext
from research_agent.tool_catalogue import build_snapshot

from test_steps import (  # noqa: F401  (the fixture is used by name)
    EMPTY_SCHEMA, LIST_SCHEMA, FakeAgent, dict_tool, frames_of, model, step_request,
    tool_request,
)


class SkillAgent:
    """A step context with the skills of one profile, as `MCPGatewayAgent` builds it."""

    def __init__(self, names, profile="full_research"):
        self.name = "test"
        self.profile = profile
        self.system_prompt_override = ""
        self.langfuse_handler = None
        self.revisions: List[str] = []
        tools = [dict_tool(n, LIST_SCHEMA, []) for n in names]
        allowed = set(names) | {"read_skill", "search_skills"}
        snapshot = build_snapshot(tools, allowed, "chat",
                                  SkillContext(profile=profile, tool_names=frozenset()))
        self.context = AgentContext(
            snapshot=snapshot, tools=tools, llm_kwargs={}, model_id="stub-model",
            system_text_for=lambda _names: "the current prompt",
            skill_context=snapshot.skill_context)

    async def context_for(self, *args, revision="", **kwargs):
        self.revisions.append(revision)
        return self.context


def skill_row(idx, name, call_id):
    return [
        {"role": "ai", "content": "", "thread_id": "t", "idx": idx,
         "tool_calls": [{"id": call_id, "name": "read_skill", "args": {"name": name}}]},
        {"role": "tool", "content": f"Skill `{name}`.\n\nThe method.", "thread_id": "t",
         "idx": idx + 1, "tool_call_id": call_id, "name": "read_skill"},
    ]


async def test_the_snapshot_holds_the_prompt_the_skills_and_a_stable_revision():
    agent = SkillAgent(["search_collections", "search_passages", "table_overview"])
    request = steps.ControlSnapshotRequest(**step_request().model_dump(
        include={"run_id", "kind", "depth", "username", "session_id", "allowed_collections"}))
    first = await steps.control_snapshot(agent, request)
    second = await steps.control_snapshot(agent, request)
    listed = [s.name for s in skill_store.listed_skills(agent.context.skill_context)]
    assert sorted(first["skills"]) == sorted(listed)
    assert first["system_prompt"] == "the current prompt"
    assert first["revision"] == second["revision"]
    skill = first["skills"]["spreadsheets"]
    assert skill["text"].startswith("Skill `spreadsheets`.")
    assert skill["digest"] == steps.skill_digest(skill["text"])
    assert skill["terms"] and skill["not_for"]
    assert "visible_skills" not in first
    assert "headers" not in json.dumps(first).lower()


async def test_the_visible_skills_follow_every_stored_compaction():
    agent = SkillAgent(["search_collections"])
    thread = ([{"role": "human", "content": "q", "thread_id": "t", "idx": 0}]
              + skill_row(1, "passages", "s1") + skill_row(3, "entities", "s2"))
    request = steps.ControlSnapshotRequest(
        run_id="r1", username="alice", session_id="s1", visibility_only=True, messages=thread)
    assert await steps.control_snapshot(agent, request) == {
        "visible_skills": ["passages", "entities"]}
    # A compaction that evicts the first result leaves only the second skill visible.
    evict = {"role": "compaction", "content": json.dumps({"version": 1, "evicted": [["t", 2]]}),
             "thread_id": "t", "idx": 5}
    request = request.model_copy(update={"messages": [
        steps.RunMessage(**m) for m in thread + [evict]]})
    assert await steps.control_snapshot(agent, request) == {"visible_skills": ["entities"]}


async def test_a_failed_skill_read_is_not_visible():
    rows = [steps.RunMessage(**m) for m in skill_row(1, "passages", "s1")]
    rows[1] = rows[1].model_copy(update={"status": "error"})
    assert steps.visible_skills(rows) == []


async def test_a_pinned_system_prompt_replaces_the_current_one(model):
    model.replies.append(AIMessage(content="done"))
    agent = SkillAgent(["search_collections"])
    control = {"revision": "rev-1", "system_prompt": "the pinned prompt", "skills": {}}
    await frames_of(agent, step_request(control=control))
    assert model.inputs[-1][0].content == "the pinned prompt"
    assert agent.revisions == ["rev-1"]


async def test_a_request_without_control_uses_the_current_prompt(model):
    model.replies.append(AIMessage(content="done"))
    agent = SkillAgent(["search_collections"])
    await frames_of(agent, step_request())
    assert model.inputs[-1][0].content == "the current prompt"
    assert agent.revisions == [""]


async def test_read_skill_returns_the_pinned_text():
    agent = SkillAgent(["search_collections"])
    control = {"revision": "rev-1", "skills": {"passages": "Skill `passages`.\n\nPinned."}}
    result = await steps.run_tool_call(agent, tool_request(
        "read_skill", {"name": "passages"}, control=control))
    assert (result["status"], result["content"]) == ("ok", "Skill `passages`.\n\nPinned.")
    unknown = await steps.run_tool_call(agent, tool_request(
        "read_skill", {"name": "nothing"}, control=control))
    assert unknown["status"] == "error"
    assert json.loads(unknown["content"])["error"] == "unknown_skill"


async def test_read_skill_without_control_renders_the_current_text():
    agent = SkillAgent(["search_collections", "search_passages"])
    result = await steps.run_tool_call(agent, tool_request("read_skill", {"name": "passages"}))
    assert result["status"] == "ok", result["content"]
    assert result["content"].startswith("Skill `passages`.")
    assert "Pinned." not in result["content"]


async def test_policy_calls_are_classified_like_reply_calls_and_unknown_names_refused():
    seen: List[Any] = []
    agent = FakeAgent([dict_tool("read_page", EMPTY_SCHEMA, seen),
                       dict_tool("search_collections", LIST_SCHEMA, seen)],
                      {"read_page", "search_collections"})
    request = steps.PolicyCallsRequest(run_id="r1", username="alice", session_id="s1", calls=[
        {"id": "ctl-a-0", "name": "read_page", "args": {}},
        {"id": "ctl-a-1", "name": "write_todo", "args": {}},
    ])
    out = await steps.policy_calls(agent, request)
    assert [e["id"] for e in out["entries"]] == ["ctl-a-0"]
    assert out["entries"][0]["kind"] and out["entries"][0]["page_share"] > 0
    assert out["refused"] == ["write_todo"]
    assert seen == []
