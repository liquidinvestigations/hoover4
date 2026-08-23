"""System prompts as templates, rendered from what the deployment actually binds.

**A prompt here is a function of the deployment, not a constant.** The text lives in the
`.md.j2` files beside this module and this loader is the only thing that renders them.
That is not tidiness: a prompt written as a string literal asserts things about the tool
set that nothing checks, and it goes stale silently. Renaming one tool used to mean
correcting the same sentence by hand in several prose files, and the file that was missed
told the model to call a name that no longer existed.

Two of the named parameters carry the whole contract:

* **`tools`** is the list of tool names actually bound on the graph, read off the MCP
  connections at graph-construction time. The tool section of every prompt is generated
  from it, so a tool that is not bound cannot be described and a tool that is bound cannot
  be left out. `tests/test_prompts.py` fails when a template names a tool outside it.
* **`max_tool_turns`** is the budget the graph will really enforce, so the number in the
  prose is the number in the code. `default_tool_turns` reads it from the module that
  enforces it rather than restating it.

The rest (`profile`, `subagents_enabled`, `collections_hint`, `web_enabled`) are the
facts that change what a correct instruction says: which of the three profiles this is,
whether delegation is available, whether the caller can read any collection at all, and
whether the open web is reachable from this agent.

`SYSTEM_PROMPT` still overrides the rendered text outright, which is what an experiment
wants. It deliberately does not change the profile: the profile name decides tool binding
(`subagents.delegates`), and an experiment on the wording must not silently turn
delegation off. See `active_profile`.

**The Manticore MATCH syntax is deliberately not rendered here.** It reaches the model
through the collection-search server's own `instructions`, which is read at
tool-discovery time by whichever agent connects, and which renders from templates of its
own for the same reasons.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

log = logging.getLogger(__name__)

#: Where the templates live: this package's own directory, and `_blocks/` inside it for
#: the fragments more than one profile includes.
TEMPLATE_DIR = Path(__file__).parent

#: The three profiles, and the template each renders from.
PROFILES: Dict[str, str] = {
    "internal_search": "internal_search.md.j2",
    "full_research": "full_research.md.j2",
    "research_subagent": "research_subagent.md.j2",
}

DEFAULT_PROFILE = "internal_search"


class UnboundToolError(RuntimeError):
    """A template named a tool that is not bound on the profile being rendered.

    Raised only under `strict=True`, which is what the drift test renders with. At runtime
    the name is rendered and the mismatch logged instead: a stale sentence is a defect, but
    an agent that refuses to start because of one is a worse defect.
    """


@dataclass(frozen=True)
class ToolGroup:
    """One line of the tool section: the tools it describes, and what to say about them.

    A group renders only when at least one of its tools is bound, and it names only the
    bound ones. That is what makes the section a description of the real surface rather
    than a claim about it.
    """

    tools: Tuple[str, ...]
    note: str


#: The tool section, in the order a model should read it. Every tool any profile binds
#: belongs to exactly one group; a tool that belongs to none still reaches the prompt,
#: through the catch-all line `_render_tool_surface` adds, because an unmentioned tool is
#: an invisible tool.
#:
#: These notes are about *when to reach for a tool*, deliberately short. The detail lives
#: in the tool's own description, which the model reads in context at the moment it picks
#: one; piling it into the system prompt is what made an earlier draft loop forever.
TOOL_GROUPS: Tuple[ToolGroup, ...] = (
    ToolGroup(
        ("list_collections",),
        "the collections this user can read. Call it first so you use real names.",
    ),
    ToolGroup(
        ("search_collections", "read_documents"),
        "the user's own documents. Both take lists: send several query angles at once "
        "and read several hits at once.",
    ),
    ToolGroup(
        ("list_document_entities",),
        "the names, dates and places found in one document — where the next query "
        "usually comes from.",
    ),
    ToolGroup(
        ("web_search",),
        "several search engines at once, merged so that pages more than one engine "
        "returned rank highest. Each result lists which engines found it; a page three "
        "engines agree on is better corroborated than one only a single engine returned.",
    ),
    ToolGroup(
        ("list_search_sources",),
        "which engines are configured and which are currently degraded.",
    ),
    ToolGroup(
        ("read_page",),
        "open promising results in a real browser and read their full text. Search "
        "snippets are short by design; when a result matters, open it. Pass several URLs "
        "at once and say what you are looking for in `goal`.",
    ),
    ToolGroup(
        (
            "browser_navigate",
            "browser_snapshot",
            "browser_click",
            "browser_type",
            "browser_select_option",
            "browser_press_key",
        ),
        "for pages that have to be *operated* rather than read — a form, a login, a "
        "control that reveals the content. Reading a page needs none of them.",
    ),
    ToolGroup(
        ("whois_lookup",),
        "who registered a domain, and when.",
    ),
    ToolGroup(
        ("cite_documents",),
        "turn the documents you relied on into handles you can write into your prose.",
    ),
    # Two groups, not one, because a worker binds the reader and none of the writers: a
    # single group would describe writing a plan to a profile that cannot write one, which
    # is the exact class of claim these templates exist to make impossible.
    ToolGroup(
        ("read_todo",),
        "this conversation's plan, and the context an objective came out of.",
    ),
    ToolGroup(
        ("write_todo", "edit_todo", "mark_todo"),
        "write the plan, change it, and mark its steps done.",
    ),
    ToolGroup(
        ("run_subagent",),
        "delegate independent parts of a hard question to several researchers at once, "
        "each starting fresh. They cannot see each other and cannot delegate further.",
    ),
)


def default_tool_turns(profile: str) -> int:
    """The tool-turn budget this profile's graph will really enforce.

    Imported lazily, and from the module that enforces the number rather than restated
    here: a prompt promising a budget the code does not use is precisely the drift these
    templates exist to prevent. `agent` imports this package, so the import cannot happen
    at module scope.
    """
    if (profile or "").strip().lower() == "research_subagent":
        from research_agent import subagents

        return subagents.WORKER_TOOL_TURNS

    from research_agent.agent import MAX_TOOL_TURNS

    return MAX_TOOL_TURNS


def _environment() -> Environment:
    """The Jinja environment. `StrictUndefined` so a mistyped parameter is loud."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        # Kept, so that a block ends with its own newline and the blank line that follows
        # an `{% include %}` survives as a paragraph break. With it stripped, `trim_blocks`
        # eats the other half of the pair and two paragraphs run together.
        keep_trailing_newline=True,
    )


def _tool_names(tools: Iterable) -> List[str]:
    """Tool names out of whatever the caller has: name strings, or bound tool objects."""
    names: List[str] = []
    for tool in tools or []:
        name = tool if isinstance(tool, str) else getattr(tool, "name", "")
        if name:
            names.append(str(name))
    return names


def _render_tool_surface(bound: Sequence[str]) -> str:
    """The tool section, generated from the bound names.

    Every bound tool appears exactly once. Groups render in `TOOL_GROUPS` order, naming
    only their bound members; anything bound that no group covers is listed at the end,
    so a tool added to an MCP server reaches the prompt on the next connection rather
    than waiting for somebody to write a sentence about it.
    """
    present = set(bound)
    lines: List[str] = []
    described: set = set()
    for group in TOOL_GROUPS:
        named = [name for name in group.tools if name in present]
        if not named:
            continue
        described.update(named)
        lines.append("* " + " / ".join(f"`{name}`" for name in named) + " — " + group.note)
    rest = sorted(present - described)
    if rest:
        lines.append(
            "* also bound, described by their own tool descriptions: "
            + ", ".join(f"`{name}`" for name in rest)
            + "."
        )
    return "\n".join(lines)


def render(
    profile: str,
    *,
    tools: Iterable,
    max_tool_turns: Optional[int] = None,
    collections_hint: bool = True,
    web_enabled: Optional[bool] = None,
    subagents_enabled: Optional[bool] = None,
    strict: bool = False,
) -> str:
    """Render one profile's system prompt for the deployment it will run in.

    `tools` is the bound tool list (names or tool objects), and everything the prompt
    says about the tool surface is derived from it. `web_enabled` and `subagents_enabled`
    default to what that list implies and are overridable only so a test can pin them.

    `strict` turns a template naming an unbound tool into `UnboundToolError` instead of a
    logged warning. The drift test renders strict; the running agent does not.
    """
    name = (profile or "").strip().lower()
    template_name = PROFILES.get(name)
    if template_name is None:
        raise KeyError(f"unknown agent profile: {profile!r}")

    bound = _tool_names(tools)
    present = set(bound)

    def tool(tool_name: str) -> str:
        """A tool named in running prose, checked against what is bound."""
        if tool_name not in present:
            if strict:
                raise UnboundToolError(
                    f"profile {name!r} does not bind {tool_name!r}, but its prompt names it"
                )
            log.warning(
                "prompt for profile %s names %s, which is not bound", name, tool_name
            )
        return f"`{tool_name}`"

    context = {
        "profile": name,
        "tools": bound,
        "tool": tool,
        "has": lambda tool_name: tool_name in present,
        "tool_surface": _render_tool_surface(bound),
        "max_tool_turns": (
            int(max_tool_turns) if max_tool_turns is not None else default_tool_turns(name)
        ),
        "collections_hint": bool(collections_hint),
        # Defaults for the shared blocks, so a profile template that forgets to set one
        # renders sensible prose rather than raising on StrictUndefined.
        "citation_artefact": "answer",
        "citation_resolver": "reader",
        "web_enabled": (
            bool(web_enabled) if web_enabled is not None else "web_search" in present
        ),
        "subagents_enabled": (
            bool(subagents_enabled)
            if subagents_enabled is not None
            else "run_subagent" in present
        ),
    }
    return _environment().get_template(template_name).render(**context).strip()


def active_profile() -> str:
    """The profile this container runs, normalised.

    Read separately from `system_prompt` because the profile decides more than the words:
    it decides whether the delegation tool is bound (`subagents.delegates`). An unknown
    name is returned as it stands so the tool-binding decision sees the same string a
    reader of the compose file does, and falls through to the narrow behaviour.
    """
    return (os.getenv("AGENT_PROFILE") or DEFAULT_PROFILE).strip().lower()


def system_prompt_override() -> str:
    """`SYSTEM_PROMPT`, the experiment override, or empty when it is not set."""
    return (os.getenv("SYSTEM_PROMPT") or "").strip()


def system_prompt(
    profile: Optional[str] = None,
    *,
    tools: Optional[Iterable] = None,
    **kwargs,
) -> str:
    """This container's system prompt: the override if set, otherwise the rendered one.

    An unknown profile renders the internal-search template rather than raising: a typo in
    compose must not leave the agent with no instructions at all, and the narrow prompt is
    the safe one to fall back to.
    """
    override = system_prompt_override()
    if override:
        return override
    name = (profile or active_profile()).strip().lower()
    if name not in PROFILES:
        log.warning("unknown agent profile %r; falling back to %s", name, DEFAULT_PROFILE)
        name = DEFAULT_PROFILE
    return render(name, tools=tools or [], **kwargs)


__all__ = [
    "PROFILES",
    "DEFAULT_PROFILE",
    "TEMPLATE_DIR",
    "TOOL_GROUPS",
    "ToolGroup",
    "UnboundToolError",
    "active_profile",
    "default_tool_turns",
    "render",
    "system_prompt",
    "system_prompt_override",
]
