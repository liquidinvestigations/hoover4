"""The single system prompt: what it lists, how large it is, and that it stays fixed.

The prompt is rendered from the run's snapshot and listed skills. These tests render it for
each profile against the tools of its packs and check that it lists every tool of the
snapshot, names no tool outside it, and stays inside its size budget.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent_common.tool_packs import PACKS, allowed_tools
from research_agent import prompts, skill_store
from research_agent.skill_store import Skill, SkillContext, listed_skills
from research_agent.tool_catalogue import build_snapshot

FIXTURES = Path(__file__).parent / "prompt_fixtures"

#: The first description line of each tool that the MCP servers and the agent list.
TOOL_DESCRIPTIONS = json.loads((FIXTURES / "tool_descriptions.json").read_text())

#: The size budget of the system text of every profile.
MAX_PROMPT_CHARS = 11_000

#: Any backticked snake_case word in a rendered prompt.
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")

#: Backticked words that are not tools: fields and states that the prompt names.
NOT_TOOLS = frozenset({"in_progress", "done", "cancelled", "pending"})

EVERY_TOOL = frozenset().union(*PACKS.values())
LOCAL_TOOLS = {"search_agent_tools", "search_skills", "read_skill", "read_tool", "ask_user", "write_note"}


class FakeTool:
    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.args_schema = {"type": "object", "properties": {}}


def fake_tools(names):
    return [FakeTool(n, TOOL_DESCRIPTIONS.get(n, f"{n}.")) for n in sorted(names)
            if n not in LOCAL_TOOLS]


def snapshot_for(profile, packs="all", tools=None):
    kind = prompts.PROFILE_KINDS[profile]
    allowed = allowed_tools(kind, packs)
    return build_snapshot(
        fake_tools(tools if tools is not None else allowed), allowed, kind,
        SkillContext(profile=profile, tool_names=frozenset()),
    )


def rendered(profile, packs="all", tools=None, skills=None, **kwargs):
    snap = snapshot_for(profile, packs, tools)
    if skills is None:
        skills = listed_skills(snap.skill_context)
    return prompts.render(profile, snapshot=snap, skills=skills, strict=True, **kwargs)


def all_skills(profile):
    """The listed skills of a run that has every tool: every general, technique and stumble
    skill of the store. The role skill is in the prompt text and is not listed."""
    return listed_skills(SkillContext(profile=profile, tool_names=EVERY_TOOL))


def listed_lines(text):
    return re.findall(r"^\* `([a-z_]+)`: ", text, re.M)


# -------------------------------------------------------------------------- normal


def test_the_full_chat_lead_lists_every_tool_and_every_skill():
    skills = all_skills("full_research")
    assert len(skills) == 16
    text = rendered("full_research", skills=skills)
    names = listed_lines(text)
    tools = [n for n in names if n in EVERY_TOOL]
    assert sorted(tools) == sorted(EVERY_TOOL)
    assert len(tools) == len(EVERY_TOOL)
    assert [n for n in names if n not in EVERY_TOOL] == [s.name for s in skills]


def test_the_internal_chat_lists_no_web_tool():
    text = rendered("internal_search", packs="collections,conversation,catalogue")
    for name in PACKS["web"] | PACKS["browser"]:
        assert f"`{name}`" not in text
    assert "open web" not in text
    assert "Hoover4's assistant" in text


@pytest.mark.parametrize("profile", sorted(prompts.PROFILE_KINDS))
def test_every_profile_renders_strictly_and_names_only_its_tools(profile):
    snap = snapshot_for(profile)
    text = prompts.render(profile, snapshot=snap, skills=listed_skills(snap.skill_context),
                          strict=True)
    named = {w for w in BACKTICKED.findall(text) if w not in NOT_TOOLS}
    skills = {s.name for s in listed_skills(snap.skill_context)}
    assert (named & EVERY_TOOL) <= set(snap.tools_by_name)
    assert set(snap.tools_by_name) <= named
    assert skills <= named


@pytest.mark.parametrize("profile", sorted(prompts.PROFILE_KINDS))
@pytest.mark.parametrize("web", [False, True])
@pytest.mark.parametrize("collections", [False, True])
def test_each_role_prompt_renders_for_web_and_collection_state(profile, web, collections):
    packs = "all" if web else "catalogue,skills,collections,conversation"
    snap = snapshot_for(profile, packs=packs)
    prompt = prompts.render(profile, snapshot=snap,
                            skills=listed_skills(snap.skill_context),
                            collections_hint=collections, strict=True)
    if profile in {"internal_search", "full_research"}:
        assert bool("no document collections" in prompt) is not collections
    assert bool("`web_search`" in prompt) is web
    assert "`ask_user`" in prompt


def test_every_run_tool_has_one_prompt_line():
    snap = snapshot_for("full_research")
    text = prompts.render("full_research", snapshot=snap, skills=[])
    tools_part = text.split("\nTools\n", 1)[1]
    names = listed_lines(tools_part)
    assert names == list(snap.callable_names())
    assert "Find a tool by a few words with `search_agent_tools`." in text


def test_a_summary_is_the_first_sentence_cut_at_a_word_boundary():
    assert prompts.tool_summary("Read a table. Then more.\nSecond line.") == "Read a table."
    long = "word " * 60
    summary = prompts.tool_summary(long)
    assert len(summary) <= prompts.SUMMARY_MAX_CHARS
    assert not summary.endswith(" ") and summary.split(" ")[-1] == "word"


# ------------------------------------------------------------------------ boundary


@pytest.mark.parametrize("profile", sorted(prompts.PROFILE_KINDS))
def test_the_prompt_stays_inside_its_size_budget(profile):
    text = rendered(profile, skills=all_skills(profile))
    assert len(text) <= MAX_PROMPT_CHARS, len(text)


def test_a_run_with_no_todo_writers_has_no_todo_rule():
    narrow = rendered("full_research", packs="collections,web")
    assert "Your todo list" not in narrow
    assert "Your todo list" in rendered("full_research")




def test_no_readable_collection_is_said_plainly():
    snap = snapshot_for("internal_search")
    text = prompts.render("internal_search", snapshot=snap, skills=[], collections_hint=False)
    assert "no document collections" in text
    assert "no collections at all" not in rendered("internal_search")


def test_the_full_role_line_names_the_web_only_when_the_run_has_it():
    assert "You are a research assistant." in rendered("full_research")
    assert "search the open web" in rendered("full_research")
    narrow = rendered("full_research", packs="collections,conversation")
    assert "search the open web" not in narrow


# ------------------------------------------------------------------------- failure


def test_an_unknown_profile_raises():
    with pytest.raises(KeyError):
        prompts.render("typo_profile", snapshot=snapshot_for("internal_search"), skills=[])


def test_an_unknown_profile_falls_back_to_the_narrow_prompt(monkeypatch):
    monkeypatch.delenv("SYSTEM_PROMPT", raising=False)
    text = prompts.system_prompt("typo_profile", snapshot=snapshot_for("internal_search"),
                                 skills=[])
    assert "Hoover4's assistant" in text


def test_the_environment_override_is_returned_unchanged(monkeypatch):
    monkeypatch.setenv("SYSTEM_PROMPT", "  be brief  ")
    assert prompts.system_prompt_override() == "be brief"
    assert prompts.system_prompt(
        "full_research", snapshot=snapshot_for("full_research"), skills=[]) == "be brief"


def test_a_skill_that_names_a_tool_outside_every_pack_fails_strict_rendering():
    odd = Skill("odd", "technique", "d", (), "Call {{ tool('no_such_tool') }}.")
    snap = snapshot_for("full_research")
    with pytest.raises(prompts.UnboundToolError):
        prompts.render("full_research", snapshot=snap, skills=[odd], strict=True)
    assert prompts.render("full_research", snapshot=snap, skills=[odd])


# ----------------------------------------------------------------------- stability


async def test_the_system_text_is_the_same_for_each_model_step(monkeypatch):
    from research_agent import agent as agent_module

    class FakeClient:
        def __init__(self, servers):
            pass

        async def get_tools(self):
            return fake_tools(EVERY_TOOL)

    monkeypatch.setattr(agent_module, "MultiServerMCPClient", FakeClient)
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.delenv("SYSTEM_PROMPT", raising=False)
    gateway = agent_module.MCPGatewayAgent([], "test", "", profile="full_research")
    context = await gateway._create_context(None, ["c"], kind="chat")
    first = context.system_text_for(("doc_email",))
    second = context.system_text_for(("table_page", "pdf_search"))
    assert first == second
    assert "Skills" in first and "`citation`" in first
    # The role text is in the prompt, and the role skill is not listed.
    assert "Your role" in first and "`method_chat_full`" not in first
    assert context.skill_context.profile == "full_research"
    assert context.skill_context.tool_names == frozenset(context.snapshot.tools_by_name)


def test_list_constraints_apply_before_any_optional_skill_read():
    text = rendered("full_research")
    assert "For each listed item, verify every constraint against the source text" in text
    assert "Give fewer items when the sources establish fewer matches" in text
    assert "Read every page that you cite before you answer." in text
    assert "Call `read_page` for every web source before you use its claims." in text
    assert "Use its `find` field to read the passage that supports each claim." in text
    assert "State when the sources do not establish that ranking." in text
    assert "Search snippets and security check pages cannot establish a matching item." in text


def test_the_prompt_uses_the_observed_utc_date(monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2026, 10, 7, tzinfo=timezone.utc)

    monkeypatch.setattr(prompts, "datetime", Clock)
    assert "The current UTC date is 2026-10-07." in rendered("full_research")
