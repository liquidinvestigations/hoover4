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

#: Derived, never listed: a worker's pool is the lead's minus what it is denied, and that
#: subtraction is the code that enforces the depth limit. Writing the ten names out here
#: would let this test agree with itself while disagreeing with the graph.
RESEARCH_SUBAGENT_TOOLS = frozenset(
    name for name in FULL_RESEARCH_TOOLS if name not in subagents.WORKER_DENIED_TOOLS
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
NOT_TOOLS = frozenset({"needs_plan", "cancelled", "goal", "degraded", "max_results"})

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


def test_the_lead_prompt_offers_delegation_and_the_narrow_one_does_not():
    assert subagents.DELEGATION_TOOL in rendered("full_research")
    assert subagents.DELEGATION_TOOL not in rendered("internal_search")


def test_the_budget_in_the_prose_is_the_budget_in_the_code():
    """The number the model is told is the number `should_continue` enforces.

    Read from the modules that enforce it rather than restated here: the lead's budget is
    `agent.MAX_TOOL_TURNS`, a worker's is `subagents.WORKER_TOOL_TURNS`, and a prompt
    asserting anything else is telling the model something the code contradicts.
    """
    from research_agent.agent import MAX_TOOL_TURNS

    assert prompts.default_tool_turns("full_research") == MAX_TOOL_TURNS
    assert prompts.default_tool_turns("internal_search") == MAX_TOOL_TURNS
    assert (
        prompts.default_tool_turns("research_subagent") == subagents.WORKER_TOOL_TURNS
    )

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
    would keep passing while checking nothing.
    """
    with pytest.raises(prompts.UnboundToolError):
        prompts.render(
            "internal_search",
            tools=sorted(INTERNAL_SEARCH_TOOLS - {"list_collections"}),
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
