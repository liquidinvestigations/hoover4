"""The system prompt of every run kind, rendered from the run's snapshot and skills.

One template, `agent.md.j2`, renders for every profile. It holds the role line of the
profile, the role text of the profile (the rendered role skill, `skill_store.role_method`),
the listed skills by name and description, and the tools of the run's snapshot by name and
summary in one list. The other method texts are in the skill store
(`research_agent.skill_store`), which the model reads with `read_skill` when it chooses to.

The prompt depends on the profile, `collections_hint`, the model and the snapshot. None of these changes during a run, so the step context renders it once, and the
prompt cache of the system text holds for the whole run.

`SYSTEM_PROMPT` overrides the rendered text outright, which is what an experiment wants. It
does not change the tool list, which the tool packs of the run kind decide
(`agent_common.tool_packs`). See `active_profile`.

The Manticore match syntax reaches the model through the skill `search` and through the
descriptions of the search tools.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agent_common.tool_packs import pack_of
from research_agent.skill_store import (
    DEFAULT_PROFILE,
    Skill,
    SkillContext,
    UnboundToolError,
    environment,
    render_skill,
    role_method,
)

log = logging.getLogger(__name__)

#: Where the templates live: this package's own directory.
TEMPLATE_DIR = Path(__file__).parent

#: The template of the system prompt of every profile.
AGENT_TEMPLATE = "agent.md.j2"

#: Each profile, and the run kind that renders it.
PROFILE_KINDS: Dict[str, str] = {
    "internal_search": "chat",
    "full_research": "chat",
}

#: The role line of each profile, as Jinja source. It reads `web_enabled` and
#: `collections_hint`.
ROLE_LINES: Dict[str, str] = {
    "internal_search": (
        "You are Hoover4's assistant. You can read the user's document collections.\n"
        "{% if not collections_hint %}\n\n"
        "This conversation can read no document collections.\n"
        "{% endif %}"
    ),
    "full_research": (
        "You are a research assistant. You can read the user's own document\n"
        "collections{% if web_enabled %} and search the open web{% endif %}.\n"
        "{% if not collections_hint %}\n\n"
        "This conversation can read no document collections.\n"
        "{% endif %}"
    ),
}

#: The longest summary of one tool in the tool lists.
SUMMARY_MAX_CHARS = 160

#: The todo tools. The todo rule renders when the run has all four.
TODO_TOOLS = ("read_todo", "write_todo", "edit_todo", "mark_todo")

_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def _environment() -> Environment:
    """The Jinja environment of the templates. `StrictUndefined` so a mistyped name is loud."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        # Kept, so that a block ends with its own newline and the blank line that follows
        # it survives as a paragraph break.
        keep_trailing_newline=True,
    )


def tool_summary(description: str) -> str:
    """The first sentence of the first line of a description, cut at a word boundary to at
    most `SUMMARY_MAX_CHARS` characters."""
    lines = (description or "").strip().splitlines()
    first = lines[0].strip() if lines else ""
    sentence = _SENTENCE_END.split(first, maxsplit=1)[0].strip()
    if len(sentence) <= SUMMARY_MAX_CHARS:
        return sentence
    cut = sentence[:SUMMARY_MAX_CHARS + 1].rsplit(" ", 1)[0]
    return cut if cut else sentence[:SUMMARY_MAX_CHARS]


def _pairs(snapshot: Any, names: Sequence[str]) -> List[Tuple[str, str]]:
    tools = snapshot.tools_by_name
    return [(n, tool_summary(getattr(tools[n], "description", "") or "")) for n in names]


def render(
    profile: str,
    *,
    snapshot: Any,
    skills: Sequence[Skill],
    collections_hint: bool = True,
    strict: bool = False,
) -> str:
    """Render the system prompt of one profile for one run.

    `snapshot` is the run's `CatalogueSnapshot`, and `skills` are its listed skills
    (`skill_store.listed_skills`).

    `strict` raises `UnboundToolError` when a listed skill names a tool that no pack holds,
    in its front matter or in its text. The tests render strict, and the running agent does
    not. An unknown profile raises `KeyError`.
    """
    name = (profile or "").strip().lower()
    if name not in ROLE_LINES:
        raise KeyError(f"unknown agent profile: {profile!r}")
    tool_names = frozenset(snapshot.tools_by_name)
    ctx = SkillContext(profile=name, tool_names=tool_names,
                       collections_hint=bool(collections_hint))
    if strict:
        by_name = {skill.name: skill for skill in skills}
        for skill in skills:
            unknown = [t for t in skill.tools if pack_of(t) is None]
            if unknown:
                raise UnboundToolError(f"skill {skill.name!r} names {unknown}, which no pack holds")
            render_skill(skill.name, ctx, strict=True, skills=by_name)
    role_line = environment().from_string(ROLE_LINES[name]).render(
        web_enabled="web_search" in tool_names, collections_hint=bool(collections_hint),
    ).strip()
    return _environment().get_template(AGENT_TEMPLATE).render(
        role_line=role_line,
        role_method=role_method(ctx, strict=strict),
        skills=list(skills),
        tools=_pairs(snapshot, snapshot.callable_names()),
        catalogue_search="search_agent_tools" in tool_names,
        chat_lead=name in {"internal_search", "full_research"},
        todo_rule=all(t in tool_names for t in TODO_TOOLS),
    ).strip()


def active_profile() -> str:
    """The profile this container runs, normalised.

    Read separately from `system_prompt`, so a `SYSTEM_PROMPT` override keeps the profile
    name. An unknown name is returned as it stands, and `system_prompt` renders the
    internal-search profile for it.
    """
    return (os.getenv("AGENT_PROFILE") or DEFAULT_PROFILE).strip().lower()


def system_prompt_override() -> str:
    """`SYSTEM_PROMPT`, the experiment override, or empty when it is not set."""
    return (os.getenv("SYSTEM_PROMPT") or "").strip()


def system_prompt(profile: Optional[str] = None, **kwargs) -> str:
    """This container's system prompt: the override if set, otherwise the rendered one.

    An unknown profile renders the internal-search profile rather than raising. A typo in
    compose must not leave the agent with no instructions at all, and the narrow prompt is
    the safe one to fall back to.
    """
    override = system_prompt_override()
    if override:
        return override
    name = (profile or active_profile()).strip().lower()
    if name not in ROLE_LINES:
        log.warning("unknown agent profile %r; falling back to %s", name, DEFAULT_PROFILE)
        name = DEFAULT_PROFILE
    return render(name, **kwargs)


__all__ = [
    "AGENT_TEMPLATE",
    "DEFAULT_PROFILE",
    "PROFILE_KINDS",
    "ROLE_LINES",
    "SUMMARY_MAX_CHARS",
    "TEMPLATE_DIR",
    "UnboundToolError",
    "active_profile",
    "render",
    "system_prompt",
    "system_prompt_override",
    "tool_summary",
]
