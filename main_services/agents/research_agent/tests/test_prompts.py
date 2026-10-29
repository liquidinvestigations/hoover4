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

from agent_common.tool_packs import PACKS, allowed_tools, run_tools
from research_agent import prompts, skill_store
from research_agent.skill_store import Skill, SkillContext, listed_skills
from research_agent.tool_catalogue import build_snapshot

FIXTURES = Path(__file__).parent / "prompt_fixtures"

#: The first description line of each tool that the MCP servers and the agent list.
TOOL_DESCRIPTIONS = json.loads((FIXTURES / "tool_descriptions.json").read_text())

#: The size budget of the system text of every profile.
MAX_PROMPT_CHARS = 12_500

#: Any backticked snake_case word in a rendered prompt.
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")

#: Backticked words that are not tools: fields and states that the prompt names.
NOT_TOOLS = frozenset({"in_progress", "done", "cancelled", "pending"})

#: Every tool of a chat run. The `board` pack belongs to board turns only.
EVERY_TOOL = frozenset().union(*(t for p, t in PACKS.items() if p != "board"))
LOCAL_TOOLS = {"search_agent_tools", "search_skills", "read_skill", "read_tool", "write_note"}


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
    assert len(skills) == 17
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


#: The skills whose tools are all in the `collections` pack.
COLLECTION_SKILLS = {"citation", "collection_names", "document_ids", "emails", "entities",
                     "folders_and_files", "passages", "search", "spreadsheets"}
#: The sentence of the role line of a run without collections.
NO_COLLECTIONS = "This conversation can read no document collections."


def snapshot_of_sources(profile, sources):
    """The snapshot of a run whose sources are `sources`, as the agent builds it."""
    kind = prompts.PROFILE_KINDS[profile]
    allowed = run_tools(kind, "all", frozenset(sources))
    return build_snapshot(fake_tools(allowed), allowed, kind,
                          SkillContext(profile=profile, tool_names=frozenset()))


SOURCE_SETS = {"documents": {"documents"}, "web": {"web"}, "both": {"documents", "web"},
               "neither": set()}


@pytest.mark.parametrize("profile", sorted(prompts.PROFILE_KINDS))
@pytest.mark.parametrize("sources", sorted(SOURCE_SETS))
def test_each_source_set_renders_strictly_and_names_only_its_sources(profile, sources):
    """The role text, the listed skills and the callable tools come from one snapshot. A
    run without documents names no collection and lists no collection skill. A run without
    the web names no web tool."""
    names = SOURCE_SETS[sources]
    snap = snapshot_of_sources(profile, names)
    skills = listed_skills(snap.skill_context)
    prompt = prompts.render(profile, snapshot=snap, skills=skills, strict=True)
    tools = set(snap.tools_by_name)
    assert {w for w in BACKTICKED.findall(prompt) if w in EVERY_TOOL} <= tools
    texts = [prompt] + [skill_store.render_skill(s.name, snap.skill_context, strict=True)
                        for s in skills]
    if "documents" in names:
        assert NO_COLLECTIONS not in prompt
        assert {"search", "citation"} <= {s.name for s in skills}
    else:
        assert not tools & PACKS["collections"]
        assert not {s.name for s in skills} & COLLECTION_SKILLS
        assert NO_COLLECTIONS in prompt
        for text in texts:
            assert "collection" not in text.replace(NO_COLLECTIONS, "").lower(), text[:200]
            assert "not found in the documents" not in text
    if "web" in names:
        assert "`web_search`" in prompt and "web_research" in {s.name for s in skills}
    else:
        assert not tools & (PACKS["web"] | PACKS["browser"])
        assert "search the open web" not in prompt
    if not names:
        # A source-free run gets no instruction to search or cite any source.
        assert "Use the document collections" not in prompt and "Use the web" not in prompt
        assert "cannot read the web" in prompt
        assert "Citations\n" not in prompt
    assert "ask_user" not in prompt


def test_the_citation_skill_is_listed_only_with_cite_documents():
    web = listed_skills(snapshot_of_sources("full_research", {"web"}).skill_context)
    both = listed_skills(snapshot_of_sources("full_research", {"web", "documents"}).skill_context)
    assert "citation" not in {s.name for s in web}
    assert {"citation", "web_research"} <= {s.name for s in both}
    assert skill_store.SKILLS["citation"].tools == ("cite_documents",)


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


def test_a_run_without_the_plan_tool_has_no_plan_rule():
    narrow = rendered("full_research", packs="collections,web")
    assert "Your plan" not in narrow
    full = rendered("full_research")
    assert "Your plan" in full
    assert "`update_plan` only keeps the plan. Write a report or another file with `write_file`." in full




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


class _FakeClient:
    tools = EVERY_TOOL

    def __init__(self, servers):
        pass

    async def get_tools(self):
        return fake_tools(self.tools)


async def _context(monkeypatch, profile, acl, tools=EVERY_TOOL, kind="board"):
    from research_agent import agent as agent_module

    client = type("Client", (_FakeClient,), {"tools": tools})
    monkeypatch.setattr(agent_module, "MultiServerMCPClient", client)
    monkeypatch.setenv("LLM_API_KEY", "test")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.delenv("SYSTEM_PROMPT", raising=False)
    monkeypatch.delenv("AGENT_PACKS_CHAT", raising=False)
    gateway = agent_module.MCPGatewayAgent([], "test", "", profile=profile)
    return await gateway._create_context(None, acl, kind=kind)


@pytest.mark.parametrize("acl", [[], None])
async def test_a_context_with_an_empty_acl_binds_no_collection_tool(monkeypatch, acl):
    """The collection server lists its tools, and a run without collections binds none of
    them, lists no collection skill, and says that it reads no collection."""
    context = await _context(monkeypatch, "full_research", acl)
    tools = set(context.snapshot.tools_by_name)
    assert not tools & PACKS["collections"]
    assert {"web_search", "read_page", "cite_pages"} <= tools
    assert context.skill_context.collections_hint is False
    listed = {s.name for s in listed_skills(context.skill_context)}
    assert not listed & COLLECTION_SKILLS and "web_research" in listed
    text = context.system_text_for(())
    assert NO_COLLECTIONS in text and "`search_collections`" not in text
    assert "You can search the open web." in text


async def test_a_context_with_collections_binds_the_collection_tools(monkeypatch):
    context = await _context(monkeypatch, "full_research", ["enron"])
    assert PACKS["collections"] <= set(context.snapshot.tools_by_name)
    assert context.skill_context.collections_hint is True
    assert NO_COLLECTIONS not in context.system_text_for(())


async def test_an_internal_context_without_collections_reads_no_source(monkeypatch):
    """The internal agent connects no web server. Without collections, its run has neither
    source, and its role text orders no collection search."""
    tools = PACKS["collections"] | PACKS["conversation"] | PACKS["workspace"]
    context = await _context(monkeypatch, "internal_search", [], tools=tools, kind="chat")
    bound = set(context.snapshot.tools_by_name)
    assert not bound & (PACKS["collections"] | PACKS["web"] | PACKS["browser"])
    text = context.system_text_for(())
    assert NO_COLLECTIONS in text and "cannot read the web" in text
    assert "Use the document collections" not in text
    assert "not found in the documents" not in text


def test_list_constraints_apply_before_any_optional_skill_read():
    text = rendered("full_research")
    assert "For each listed item, verify every constraint against the source text" in text
    assert "Give fewer items when the sources establish fewer matches" in text
    assert "Verify in the source each property that the request requires of an item." in text
    assert "Count one case, event or entity once, even when several sources report its stages." in text
    assert "When a page read fails, use another readable source or omit its claims and address." in text
    assert "Read every page that you cite before you write the report." in text
    assert "Call `read_page` for every web source before you use its claims." in text
    assert "Use its `find` field to read the passage that supports each claim." in text
    assert "State when the sources do not establish the ranking." in text
    assert "Search snippets and security check pages cannot establish a matching item." in text


def test_the_prompt_uses_the_observed_utc_date(monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2026, 10, 7, tzinfo=timezone.utc)

    monkeypatch.setattr(prompts, "datetime", Clock)
    assert "The current UTC date is 2026-10-07." in rendered("full_research")
