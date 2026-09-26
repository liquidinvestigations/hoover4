"""The drift test: a prompt that claims a tool it does not have fails here.

A system prompt is prose about a tool surface, and prose about a tool surface goes stale
silently. Renaming one tool used to mean correcting the same sentence by hand in several
files, and the one that was missed told the model to call a name that no longer existed.
Nothing failed; the model just wasted a turn.

These tests are what makes that a failure. They render each profile against the tool list
it really binds and check three things a reader cannot check by eye:

* every tool name the prompt mentions is bound on that profile (`strict=True` raises, and
  a second pass re-reads the rendered text so a hardcoded literal cannot slip past the
  `tool()` helper);
* every tool that *is* bound reaches the prompt, because an unmentioned tool is an
  invisible one;
* the tool-turn budget in the prose is the number the graph enforces, read from the
  module that enforces it.

`PROFILE_TOOLS` below is the surface as deployed, and it is pinned deliberately: a change
to what an MCP server advertises has to be made here too, which is the point at which
somebody reads the prompts again.
"""

from __future__ import annotations

import re

import pytest

from research_agent import prompts, subagents
from agent_common.tool_packs import PACKS

#: Everything the collection-search and todo servers advertise, the narrow profile.
INTERNAL_SEARCH_TOOLS = frozenset(
    {
        "cite_documents",
        "list_collections",
        "list_document_entities",
        "read_documents",
        "search_collections",
        "read_todo",
        "write_todo",
        "edit_todo",
        "mark_todo",
    }
)

#: The narrow set plus metasearch, the browser and whois. `run_subagent` is appended by
#: `agent._create_graph` after the MCP tools, so it belongs to the lead and to nothing else.
FULL_RESEARCH_TOOLS = INTERNAL_SEARCH_TOOLS | {
    "web_search",
    "list_search_sources",
    "read_page",
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select_option",
    "browser_press_key",
    "whois_lookup",
    subagents.DELEGATION_TOOL,
}

#: A depth 2 sub-agent with narrow packs: no browser, no todo writers and no delegation.
RESEARCH_SUBAGENT_TOOLS = frozenset(
    name for name in FULL_RESEARCH_TOOLS
    if name not in PACKS["browser"] | {"write_todo", "edit_todo", "mark_todo",
                                       subagents.DELEGATION_TOOL}
)

PROFILE_TOOLS = {
    "internal_search": INTERNAL_SEARCH_TOOLS,
    "full_research": FULL_RESEARCH_TOOLS,
    "research_subagent": RESEARCH_SUBAGENT_TOOLS,
}

#: Any backticked snake_case word in a rendered prompt. The prompts use backticks for tool
#: names and for a handful of field names, so a match is a candidate, not a verdict.
BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")

#: Backticked words that are deliberately not tools: fields, arguments and states the
#: prompts name. Listed so that a genuinely new tool name cannot hide among them.
NOT_TOOLS = frozenset(
    {"needs_plan", "cancelled", "goal", "steps", "degraded", "max_results", "queries"}
)

#: The union of every name any profile binds. A backticked word inside it, in a prompt for
#: a profile that does not bind it, is drift, which is what the second pass looks for.
ALL_TOOLS = frozenset().union(*PROFILE_TOOLS.values())


def rendered(profile: str, **kwargs) -> str:
    return prompts.render(profile, tools=sorted(PROFILE_TOOLS[profile]), strict=True, **kwargs)


@pytest.mark.parametrize("profile", sorted(PROFILE_TOOLS))
def test_every_profile_renders(profile):
    """Each of the three profiles renders, strictly, against its real tool list."""
    text = rendered(profile)
    assert text.strip()
    assert len(text) > 400, "a profile prompt this short has lost a block"


@pytest.mark.parametrize("profile", sorted(PROFILE_TOOLS))
def test_a_prompt_never_names_a_tool_it_does_not_bind(profile):
    """The drift test proper.

    `strict=True` catches a name that went through `tool()`; this second pass re-reads the
    rendered text, so a name written straight into a template as a backticked literal
    fails too. Both directions matter: the first is the mechanism, the second is what
    happens when somebody bypasses it.
    """
    bound = PROFILE_TOOLS[profile]
    text = rendered(profile)
    named = {word for word in BACKTICKED.findall(text) if word not in NOT_TOOLS}
    claimed_but_unbound = (named & ALL_TOOLS) - bound
    assert not claimed_but_unbound, (
        f"the {profile} prompt names tools it does not bind: "
        f"{sorted(claimed_but_unbound)}"
    )
    unknown = named - ALL_TOOLS
    assert not unknown, (
        f"the {profile} prompt backticks {sorted(unknown)}, which is neither a tool any "
        "profile binds nor a declared non-tool word (see NOT_TOOLS)"
    )


@pytest.mark.parametrize("profile", sorted(PROFILE_TOOLS))
def test_every_bound_tool_reaches_the_prompt(profile):
    """A tool the model has and the prompt never mentions is a tool it will not use."""
    text = rendered(profile)
    named = set(BACKTICKED.findall(text))
    missing = PROFILE_TOOLS[profile] - named
    assert not missing, f"the {profile} prompt never mentions {sorted(missing)}"


def test_a_worker_prompt_has_no_plan_first_block_and_no_delegation():
    """Two structural facts about the worker, asserted on the rendered text.

    Neither is a special case in the worker's template: the plan-first block renders only
    where the todo writers are bound, and `run_subagent` is absent from the worker's pool,
    so the tool section cannot mention it.
    """
    text = rendered("research_subagent")
    assert "write_todo" not in text
    assert subagents.DELEGATION_TOOL not in text
    assert "read_todo" in text


@pytest.mark.parametrize("profile", sorted(PROFILE_TOOLS))
def test_the_todo_text_names_the_steps_argument(profile):
    """`write_todo` takes `steps`. No chat profile tells the model to send the steps as items,
    and each profile that binds the todo writers names the `steps` argument."""
    text = rendered(profile)
    assert "as items" not in text
    if "write_todo" in PROFILE_TOOLS[profile]:
        assert "`steps`" in text


def test_the_lead_prompt_offers_delegation_and_the_narrow_one_does_not():
    assert subagents.DELEGATION_TOOL in rendered("full_research")
    assert subagents.DELEGATION_TOOL not in rendered("internal_search")


@pytest.mark.parametrize("profile", sorted(PROFILE_TOOLS))
def test_the_delegation_paragraph_follows_the_binding(profile):
    """Each profile has the delegation paragraph when `run_subagent` is bound, and none when
    it is not. No profile says that a worker cannot delegate."""
    tools = set(PROFILE_TOOLS[profile])
    with_tool = prompts.render(profile, tools=sorted(tools | {subagents.DELEGATION_TOOL}))
    without = prompts.render(profile, tools=sorted(tools - {subagents.DELEGATION_TOOL}))
    assert f"`{subagents.DELEGATION_TOOL}` in one call" in with_tool.replace("\n", " ")
    assert subagents.DELEGATION_TOOL not in without
    assert "cannot delegate" not in with_tool + without


def test_a_review_briefing_gets_the_verdict_block():
    tools = sorted(PROFILE_TOOLS["research_subagent"])
    review = prompts.render("research_subagent", tools=tools, purpose="review")
    execute = prompts.render("research_subagent", tools=tools, purpose="execute")
    assert '{"verdict": "accept", "defect_classes": []}' in review
    assert "verdict" not in execute


def test_the_budget_in_the_prose_is_the_budget_in_the_code():
    """The number the model is told is the number `should_continue` enforces.

    Read from the modules that enforce it rather than restated here: the lead's budget is
    `agent.MAX_TOOL_TURNS` for every run kind, and a prompt asserting anything else is
    telling the model something the code contradicts.
    """
    from research_agent.agent import MAX_TOOL_TURNS

    assert prompts.default_tool_turns("full_research") == MAX_TOOL_TURNS
    assert prompts.default_tool_turns("internal_search") == MAX_TOOL_TURNS
    assert prompts.default_tool_turns("research_subagent") == MAX_TOOL_TURNS

    for profile in PROFILE_TOOLS:
        budget = prompts.default_tool_turns(profile)
        assert f"{budget} tool-calling turns" in rendered(profile)


def test_a_changed_budget_changes_the_prose():
    """A hardcoded number in a template would survive this; a rendered one does not."""
    text = rendered("full_research", max_tool_turns=97)
    assert "97 tool-calling turns" in text
    from research_agent.agent import MAX_TOOL_TURNS

    assert f"{MAX_TOOL_TURNS} tool-calling turns" not in text


def test_naming_an_unbound_tool_is_an_error_under_strict_rendering():
    """The mechanism the drift test relies on, tested directly.

    Without this, a template could stop using `tool()` and every other assertion here
    would keep passing while checking nothing. The delegation paragraph is guarded by
    `subagents_enabled` alone, so forcing it on without the tool names an unbound tool.
    """
    with pytest.raises(prompts.UnboundToolError):
        prompts.render(
            "full_research",
            tools=sorted(INTERNAL_SEARCH_TOOLS),
            subagents_enabled=True,
            strict=True,
        )


def test_a_prompt_survives_a_tool_disappearing():
    """A shrunken surface renders, smaller and without the missing tool.

    The running agent must not refuse to start because an MCP server is down and its
    tools are therefore unbound. It renders what is left, which is also the truth.
    """
    text = prompts.render("full_research", tools=sorted(INTERNAL_SEARCH_TOOLS))
    assert "web_search" not in text
    assert "search_collections" in text
    assert "open web" not in text


def test_no_readable_collection_is_said_plainly():
    """`collections_hint` is a parameter because an empty ACL changes what is true."""
    assert "no collections at all" in rendered("internal_search", collections_hint=False)
    assert "no collections at all" not in rendered("internal_search")


def test_an_unknown_profile_falls_back_rather_than_raising(monkeypatch):
    monkeypatch.delenv("SYSTEM_PROMPT", raising=False)
    text = prompts.system_prompt("typo_profile", tools=sorted(INTERNAL_SEARCH_TOOLS))
    assert "Hoover4's document research assistant" in text


def test_the_environment_override_still_wins(monkeypatch):
    monkeypatch.setenv("SYSTEM_PROMPT", "  be brief  ")
    assert prompts.system_prompt_override() == "be brief"
    assert (
        prompts.system_prompt("full_research", tools=sorted(FULL_RESEARCH_TOOLS))
        == "be brief"
    )


@pytest.mark.parametrize("profile", ["planner", "organizer"])
def test_the_plan_profiles_render_strictly_with_the_plan_tools(profile):
    tools = sorted(FULL_RESEARCH_TOOLS | PACKS["plan"])
    text = prompts.render(profile, tools=tools, strict=True)
    assert "`read_plan`" in text
    if profile == "organizer":
        assert "`plan_node_id`" in text and "`correct`" in text


THOROUGH = "Investigate thoroughly for the user"


@pytest.mark.parametrize("profile", ["internal_search", "full_research", "research_subagent"])
def test_every_researching_profile_asks_for_a_thorough_investigation(profile):
    assert THOROUGH in rendered(profile)


def test_the_thorough_block_names_the_web_only_where_it_is_bound():
    assert "open web" in rendered("full_research")
    narrow = rendered("internal_search")
    assert THOROUGH in narrow
    assert "open web" not in narrow


def test_the_narrow_profile_no_longer_stops_after_two_or_three_searches():
    text = rendered("internal_search")
    assert "Search two or three" not in text
    assert "Go from broad searches to narrow searches." in text


def test_the_planner_plans_a_thorough_investigation():
    tools = sorted(FULL_RESEARCH_TOOLS | PACKS["plan"])
    assert "Research method for a plan" in prompts.render(
        "planner", tools=tools, strict=True)


def test_the_organizer_tells_each_researcher_to_try_every_tool():
    tools = sorted(FULL_RESEARCH_TOOLS | PACKS["plan"] | {"run_subagent"})
    assert "How to write an execute briefing" in prompts.render(
        "organizer", tools=tools, strict=True)


#: Every tool of every pack. A profile rendered with all of them must still render strictly,
#: because each sentence of a block that names a tool is guarded by `has()`.
EVERY_PACK_TOOLS = sorted(frozenset().union(*PACKS.values()))

#: The method block of each profile, and its first line.
METHOD_TITLES = {
    "full_research": "Research method",
    "internal_search": "Research method",
    "planner": "Research method for a plan",
    "organizer": "Research method for running a plan",
    "research_subagent": "Research method for a researcher",
}

#: The words that no method block holds.
ETHICS_WORDS = ("ethic", "moral", "privacy", "consent", "harm", "victim", "safety")


@pytest.mark.parametrize("profile", sorted(prompts.PROFILES))
def test_every_profile_renders_strictly_with_every_pack(profile):
    text = prompts.render(profile, tools=EVERY_PACK_TOOLS, strict=True)
    assert METHOD_TITLES[profile] + "\n" in text


@pytest.mark.parametrize("profile", sorted(prompts.PROFILES))
def test_every_tool_a_block_names_is_backticked_and_bound(profile):
    """A method block names a tool only through `tool()`, so no bare tool name is left."""
    tools = sorted(PROFILE_TOOLS.get(profile, FULL_RESEARCH_TOOLS | PACKS["plan"]))
    text = prompts.render(profile, tools=tools, strict=True)
    every = frozenset().union(*PACKS.values())
    bare = {word for word in re.findall(r"(?<![`\w])([a-z]+_[a-z_]+)(?![`\w])", text)}
    assert not (bare & every), f"bare tool names in {profile}: {sorted(bare & every)}"


def test_the_narrow_profile_without_the_web_says_nothing_of_the_web():
    tools = sorted(INTERNAL_SEARCH_TOOLS)
    text = prompts.render("internal_search", tools=tools, strict=True)
    assert "web_search" not in text
    assert "Use the web only after the documents" not in text
    assert "Search the documents first." in text


def test_the_full_profile_searches_the_documents_before_the_web():
    text = rendered("full_research")
    assert "Search the documents first. Use the web only after the documents" in text
    assert "as its queries list" in text


def test_the_planner_with_its_packs_names_no_todo_tool():
    from agent_common.tool_packs import allowed_tools

    tools = sorted(allowed_tools("planner", "collections,web,plan"))
    text = prompts.render("planner", tools=tools, strict=True)
    assert "todo" not in text
    assert "Research method for a plan" in text
    assert "`append_child`" in text


def test_the_method_blocks_hold_no_ethics_wording():
    for path in sorted((prompts.TEMPLATE_DIR / "_blocks").glob("method_*.md.j2")):
        body = path.read_text().lower()
        found = [word for word in ETHICS_WORDS if word in body]
        assert not found, f"{path.name} holds {found}"


def test_the_todo_tools_are_a_checklist_and_not_the_plan():
    text = rendered("internal_search")
    assert "your working checklist for this conversation" in text
    assert "write the plan" not in text
