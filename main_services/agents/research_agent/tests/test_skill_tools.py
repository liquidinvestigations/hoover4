"""The skill tools, `read_tool` binding, and the bound set of each run kind."""

from __future__ import annotations

import json

import pytest

from agent_common.tool_packs import PACKS, allowed_tools, packs_for
from research_agent import skill_tools
from research_agent.run_messages import RunMessage
from research_agent.skill_store import SkillContext, always_read, listed_skills
from research_agent.tool_catalogue import (
    ALWAYS_BOUND,
    CATALOGUE_MATCH_COUNT,
    bind_names,
    bound_names_from_thread,
    build_snapshot,
)

LOCAL_TOOLS = {"search_agent_tools", "search_skills", "read_skill", "read_tool"}
PLAN_TOOLS = ("read_plan", "append_node", "append_child", "move_node", "edit_node",
              "remove_node")


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.description = f"Do the work of {name.replace('_', ' ')}.\nMore text."
        self.args_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }


def snapshot(kind="chat", packs="all", profile=None):
    allowed = allowed_tools(kind, packs)
    tools = [FakeTool(n) for n in sorted(allowed) if n not in LOCAL_TOOLS]
    ctx = SkillContext(profile=profile, tool_names=frozenset()) if profile else None
    return build_snapshot(tools, allowed, kind, ctx)


async def call(snap, tool_name, **args):
    """Run one local tool as `/tool_call` does, and return (status, content)."""
    result = await snap.tools_by_name[tool_name].ainvoke(
        {"type": "tool_call", "id": "c", "name": tool_name, "args": args})
    return result.status, result.content


def thread_of(*batches):
    """A thread of one `ai` message per batch, each followed by its `read_tool` results."""
    rows = [{"role": "human", "content": "q"}]
    for b, names in enumerate(batches):
        ids = [f"c{b}-{i}" for i in range(len(names))]
        rows.append({"role": "ai", "content": "", "tool_calls": [
            {"id": i, "name": "read_tool", "args": {"name": n}} for i, n in zip(ids, names)]})
        rows += [{"role": "tool", "content": json.dumps({"tool": n}), "tool_call_id": i,
                  "name": "read_tool", "status": "ok"} for i, n in zip(ids, names)]
    return [RunMessage(**row) for row in rows]


# -------------------------------------------------------------------------- normal


async def test_read_tool_of_a_deferred_tool_is_ready_for_the_next_call():
    snap = snapshot()
    status, content = await call(snap, "read_tool", name="doc_email")
    data = json.loads(content)
    assert status == "success"
    assert data["tool"] == "doc_email" and data["ready"] == "next call"
    assert data["description"].startswith("Do the work of doc email.")
    assert data["parameters"] == {"properties": {"query": {"type": "string"}},
                                  "required": ["query"]}
    assert bound_names_from_thread(snap, thread_of(["doc_email"])) == ("doc_email",)


async def test_search_skills_with_no_query_lists_every_listed_skill():
    snap = snapshot(profile="full_research")
    _, content = await call(snap, "search_skills")
    names = [m["name"] for m in json.loads(content)["matches"]]
    assert names == [s.name for s in listed_skills(snap.skill_context)]
    assert names[0] == "method_chat_full"


async def test_search_skills_ranks_by_the_description():
    snap = snapshot(profile="full_research")
    _, content = await call(snap, "search_skills", query="cite")
    assert json.loads(content)["matches"][0]["name"] == "citation"
    _, content = await call(snap, "search_skills", query="zzqx")
    assert json.loads(content) == {"matches": [], "text": skill_tools.NO_SKILL_TEXT}


async def test_read_skill_renders_for_the_run():
    snap = snapshot(profile="research_subagent", kind="subagent")
    status, content = await call(snap, "read_skill", name="citation")
    assert status == "success"
    assert content.startswith("Skill `citation`.\n\n")
    assert "The lead researcher resolves them" in content.replace("\n", " ")


# ------------------------------------------------------------------------ boundary


def test_seven_read_tool_results_in_one_batch_bind_six_names_newest_first():
    snap = snapshot()
    names = ["doc_email", "doc_metadata", "doc_sources", "table_page", "table_cell",
             "folder_list", "pdf_search"]
    assert CATALOGUE_MATCH_COUNT == 6
    assert bound_names_from_thread(snap, thread_of(names)) == tuple(names[:6])
    later = bound_names_from_thread(snap, thread_of(names[:6], ["pdf_search"]))
    assert later == ("pdf_search",) + tuple(names[:5])


async def test_read_tool_of_a_bound_tool_is_ready_now_and_binds_nothing_new():
    snap = snapshot()
    _, content = await call(snap, "read_tool", name="search_collections")
    assert json.loads(content)["ready"] == "now"
    assert bound_names_from_thread(snap, thread_of(["search_collections"])) == ()


def test_the_planner_packs_hold_the_skills_pack():
    assert "skills" in packs_for("planner", "collections,web,plan")


def test_the_plan_tools_the_run_read_stay_bound_outside_the_cap():
    snap = snapshot("planner", "collections,web,plan", "planner")
    bound = bound_names_from_thread(snap, thread_of(PLAN_TOOLS, ["search_histogram"]))
    assert len(bound) == 7 and set(PLAN_TOOLS) <= set(bound)


def test_the_cap_applies_to_the_research_tools_only():
    snap = snapshot()
    research = ["doc_email", "doc_metadata", "doc_sources", "table_page", "table_cell",
                "folder_list", "pdf_search"]
    bound = bind_names(snap, (), research + ["read_plan"])
    assert [n for n in bound if n in PACKS["plan"]] == ["read_plan"]
    assert [n for n in bound if n not in PACKS["plan"]] == research[:6]


def test_a_plan_tool_that_the_snapshot_does_not_hold_is_left_out():
    snap = snapshot("chat", "collections,conversation")
    assert bind_names(snap, (), ["read_plan", "doc_email"]) == ("doc_email",)


# ------------------------------------------------------------------------- failure


async def test_read_skill_of_another_profile_is_refused():
    snap = snapshot(profile="full_research")
    status, content = await call(snap, "read_skill", name="method_organizer")
    data = json.loads(content)
    assert status == "error"
    assert data["success"] is False and data["error"] == "unknown_skill"
    assert data["message"].startswith("No skill is named 'method_organizer'. The skills are ")


async def test_read_tool_of_an_unknown_name_is_refused():
    snap = snapshot()
    status, content = await call(snap, "read_tool", name="nope")
    data = json.loads(content)
    assert status == "error" and data["error"] == "tool_unavailable"
    assert data["message"] == (
        "No tool of this run is named 'nope'. Find tools with search_agent_tools.")
    planner = snapshot("planner", "collections,web,plan", "planner")
    _, content = await call(planner, "read_tool", name="nope")
    assert json.loads(content)["message"] == "No tool of this run is named 'nope'."
    assert bound_names_from_thread(snap, [
        RunMessage(role="human", content="q"),
        RunMessage(role="ai", content="", tool_calls=[
            {"id": "c", "name": "read_tool", "args": {"name": "nope"}}]),
        RunMessage(role="tool", content=content, tool_call_id="c", name="read_tool",
                   status="error"),
    ]) == ()


def test_the_chat_lead_defers_the_web_and_the_entity_tools():
    snap = snapshot()
    for name in ("web_search", "list_document_entities", "read_more"):
        assert name in snap.deferred_names


@pytest.mark.parametrize("kind", ["planner", "organizer"])
def test_the_plan_runs_defer_the_plan_tools(kind):
    snap = snapshot(kind)
    assert "read_plan" in snap.deferred_names
    if kind == "organizer":
        assert "run_subagent" in snap.deferred_names


# --------------------------------------------------------------------------- table

ROWS = [
    ("chat", "all", "full_research",
     ["search", "thorough", "method_chat_full", "citation", "plan_first"], ALWAYS_BOUND),
    ("chat", "all", "internal_search",
     ["search", "thorough", "method_chat_internal", "citation", "plan_first"], ALWAYS_BOUND),
    ("subagent", "all", "research_subagent",
     ["search", "thorough", "method_subagent", "citation", "plan_first"], ALWAYS_BOUND),
    ("planner", "collections,web,plan", "planner",
     ["search", "thorough", "method_planner", "citation"],
     {"search_skills", "read_skill", "read_tool", "list_collections", "search_collections",
      "search_passages", "read_documents", "cite_documents"}),
    ("organizer", "all", "organizer",
     ["search", "thorough", "method_organizer", "citation", "plan_first"], ALWAYS_BOUND),
]


@pytest.mark.parametrize("kind, packs, profile, reads, core", ROWS)
def test_each_run_kind_reads_its_skills_and_binds_its_set(kind, packs, profile, reads, core):
    snap = snapshot(kind, packs, profile)
    assert always_read(snap.skill_context) == reads
    assert set(snap.core_names) == set(core)
    if kind == "planner":
        assert len(snap.core_names) == 8
    else:
        assert len(snap.core_names) == 13


async def test_the_tool_call_route_returns_the_name_that_read_tool_binds():
    from research_agent import steps

    snap = snapshot()

    class _Agent:
        async def context_for(self, *args, **kwargs):
            return type("Context", (), {"snapshot": snap})()

    request = steps.ToolCallRequest(
        run_id="r", kind="chat", depth=0, username="u", session_id="s",
        call={"id": "c", "name": "read_tool", "args": {"name": "doc_email"}},
        idempotency_key="k",
    )
    result = await steps.run_tool_call(_Agent(), request)
    assert result["status"] == "ok" and result["matched_names"] == ["doc_email"]
    request.call.args = {"name": "nope"}
    result = await steps.run_tool_call(_Agent(), request)
    assert result["status"] == "error" and result["matched_names"] == []


async def test_read_tool_of_a_tool_that_the_step_bound_is_ready_now_and_binds_nothing_new():
    from research_agent import steps

    snap = snapshot()

    class _Agent:
        async def context_for(self, *args, **kwargs):
            return type("Context", (), {"snapshot": snap})()

    request = steps.ToolCallRequest(
        run_id="r", kind="chat", depth=0, username="u", session_id="s",
        call={"id": "c", "name": "read_tool", "args": {"name": "doc_email"}},
        bound_names=["doc_email"], idempotency_key="k",
    )
    result = await steps.run_tool_call(_Agent(), request)
    assert result["status"] == "ok" and result["matched_names"] == []
    assert json.loads(result["content"])["ready"] == "now"
    earlier = bound_names_from_thread(snap, thread_of(["doc_email"]))
    later = bound_names_from_thread(snap, thread_of(["doc_email"], ["doc_email"]))
    assert set(later) == set(earlier) == {"doc_email"}
