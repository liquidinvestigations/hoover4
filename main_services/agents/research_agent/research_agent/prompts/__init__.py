"""The system prompt of every run kind, rendered from the run's snapshot and skills.

One template, `agent.md.j2`, renders for every profile. It holds the role line of the
profile, the role text of the profile (the rendered role skill, `skill_store.role_method`),
the listed skills by name and description, and the tools of the run's snapshot by name and
summary in one list. The other method texts are in the skill store
(`research_agent.skill_store`), which the model reads with `read_skill` when it chooses to.

The prompt uses the profile, `collections_hint`, model, snapshot, and observed UTC date.
The step context renders it once and keeps that text for the run.

`SYSTEM_PROMPT` overrides the rendered text outright, which is what an experiment wants. It
does not change the tool list, which the tool packs of the run kind decide
(`agent_common.tool_packs`). See `active_profile`.

The Manticore match syntax reaches the model through the skill `search` and through the
descriptions of the search tools.

A run in another language renders `prompts/<language>/agent.md.j2` when it exists, and
takes its role line from `prompts/<language>/role_lines.json` when that file has the
profile. Each falls back to English. The prompt names the answer language of the run
(`localization.language_name`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from agent_common.tool_packs import PACKS, pack_of
from research_agent.localization import DEFAULT_LANGUAGE, language_name, localize_text, run_language
from research_agent.skill_store import (
    DEFAULT_PROFILE,
    Skill,
    SkillContext,
    UnboundToolError,
    environment,
    render_skill,
    report_rules,
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
#: `collections_hint`, and names only the sources that the run has.
ROLE_LINES: Dict[str, str] = {
    "internal_search": (
        "{% if collections_hint %}\n"
        "You are Hoover4's assistant. You can read the user's document collections.\n"
        "{% else %}\n"
        "You are Hoover4's assistant.{% if web_enabled %} You can search the open web.{% endif %}\n\n"
        "This conversation can read no document collections.\n"
        "{% endif %}"
    ),
    "full_research": (
        "{% if collections_hint %}\n"
        "You are a research assistant. You can read the user's own document\n"
        "collections{% if web_enabled %} and search the open web{% endif %}.\n"
        "{% else %}\n"
        "You are a research assistant.{% if web_enabled %} You can search the open web.{% endif %}\n\n"
        "This conversation can read no document collections.\n"
        "{% endif %}"
    ),
}

#: The longest summary of one tool in the tool lists.
SUMMARY_MAX_CHARS = 160

#: The plan tool. The plan rule renders when the run has it.
TODO_TOOLS = ("update_plan",)

#: A sentence end: a Latin full stop, question or exclamation mark and a space, or a full-width
#: one, which Chinese and Japanese write with no space after it.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s|(?<=[。！？])")


def _environment(language: str = DEFAULT_LANGUAGE) -> Environment:
    """The Jinja environment of the templates, translated first. `StrictUndefined` so a
    mistyped name is loud."""
    folders = [TEMPLATE_DIR / language] if language != DEFAULT_LANGUAGE else []
    return Environment(
        loader=ChoiceLoader([FileSystemLoader(str(f)) for f in folders + [TEMPLATE_DIR]]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        # Kept, so that a block ends with its own newline and the blank line that follows
        # it survives as a paragraph break.
        keep_trailing_newline=True,
    )


def role_line_source(profile: str, language: str) -> str:
    """The Jinja source of the role line of a profile in `language`, or the English one."""
    path = TEMPLATE_DIR / language / "role_lines.json"
    if language != DEFAULT_LANGUAGE and path.is_file():
        try:
            lines = json.loads(path.read_text())
        except ValueError as exc:
            log.error("the role lines of %s do not parse: %s", language, exc)
            lines = {}
        if isinstance(lines.get(profile), str) and lines[profile].strip():
            return lines[profile]
    return ROLE_LINES[profile]


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


def _pairs(snapshot: Any, names: Sequence[str], language: str) -> List[Tuple[str, str]]:
    tools = snapshot.tools_by_name
    return [(n, tool_summary(localize_text(getattr(tools[n], "description", "") or "", language)))
            for n in names]


def render(
    profile: str,
    *,
    snapshot: Any,
    skills: Sequence[Skill],
    collections_hint: Optional[bool] = None,
    strict: bool = False,
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Render the system prompt of one profile for one run.

    `language` is the agent language of the run. It selects the translated templates and
    skills, and the prompt names it as the answer language.

    `snapshot` is the run's `CatalogueSnapshot`, and `skills` are its listed skills
    (`skill_store.listed_skills`). `collections_hint` is true only when the snapshot holds
    a tool of the `collections` pack. `None` takes the value from the snapshot, and a true
    value without such a tool is false, so the role text names only a source that the run
    can read.

    `strict` raises `UnboundToolError` when a listed skill names a tool that no pack holds,
    in its front matter or in its text. The tests render strict, and the running agent does
    not. An unknown profile raises `KeyError`.
    """
    name = (profile or "").strip().lower()
    if name not in ROLE_LINES:
        raise KeyError(f"unknown agent profile: {profile!r}")
    tool_names = frozenset(snapshot.tools_by_name)
    documents = bool(tool_names & PACKS["collections"])
    collections_hint = documents if collections_hint is None else bool(collections_hint) and documents
    language = run_language(language)
    ctx = SkillContext(profile=name, tool_names=tool_names, collections_hint=collections_hint,
                       language=language)
    if strict:
        by_name = {skill.name: skill for skill in skills}
        for skill in skills:
            unknown = [t for t in skill.tools if pack_of(t) is None]
            if unknown:
                raise UnboundToolError(f"skill {skill.name!r} names {unknown}, which no pack holds")
            render_skill(skill.name, ctx, strict=True, skills=by_name)
    role_line = environment(language).from_string(role_line_source(name, language)).render(
        web_enabled="web_search" in tool_names, collections_hint=collections_hint,
    ).strip()
    return _environment(language).get_template(AGENT_TEMPLATE).render(
        current_date=datetime.now(timezone.utc).date().isoformat(),
        language_name=language_name(language),
        has=lambda name: name in tool_names,
        role_line=role_line,
        role_method=role_method(ctx, strict=strict),
        report_rules=report_rules(ctx, strict=strict),
        skills=list(skills),
        tools=_pairs(snapshot, snapshot.callable_names(), language),
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
