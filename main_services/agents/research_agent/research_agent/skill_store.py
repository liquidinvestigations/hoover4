"""The skill store: short texts that each teach one method, read by the model on request.

Each skill is one file, `skills/<name>.md.j2`. The file starts with front matter between two
`---` lines, one `key: value` per line, and then a Jinja body.

* `name` is `[a-z_]{1,64}` and equals the file name.
* `group` is `role`, `general`, `technique` or `stumble`.
* `description` is one line of at most 200 characters. The system prompt lists it, and
  `search_skills` searches it. The classifier forms of the preload read the same bytes, so
  a change of a description changes what the classifier picks.
* `tools` is a comma list of tool names that a pack of `agent_common.tool_packs` holds, or
  empty. A skill is listed in a run when the list is empty or one of its names is a tool of
  the run.

The role skill of a profile is listed for that profile only. `render_skill` renders a body
with the context that its caller passes, and it keeps no state of its own. `has()` in a body
reads every tool of the run, bound or deferred, because a model can bind a deferred tool
with `read_tool`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from jinja2 import Environment, StrictUndefined

from agent_common.tool_packs import pack_of

SKILL_DIR = Path(__file__).parent / "skills"
GROUPS = ("role", "general", "technique", "stumble")

#: The longest description a skill may have.
DESCRIPTION_MAX_CHARS = 200

_NAME = re.compile(r"[a-z_]{1,64}")
_KEYS = ("name", "group", "description", "tools")

#: The prompt profile of each run kind that has its own. A chat lead keeps the profile of its
#: container, `internal_search` or `full_research`.
RUN_KIND_PROFILES = {
    "subagent": "research_subagent",
    "planner": "planner",
    "organizer": "organizer",
}

#: The profile of a chat lead when the caller names none.
DEFAULT_PROFILE = "internal_search"

ROLE_SKILLS = {
    "internal_search": "method_chat_internal",
    "full_research": "method_chat_full",
    "research_subagent": "method_subagent",
    "planner": "method_planner",
    "organizer": "method_organizer",
}

#: The values of `citation_artefact` and `citation_resolver` for each profile.
ROLE_CONTEXT = {
    "internal_search": ("answer", "reader"),
    "full_research": ("report", "reader"),
    "research_subagent": ("report", "lead"),
    "planner": ("orientation", "reader"),
    "organizer": ("report", "reader"),
}

#: The place of the role skill in `GENERAL_ORDER`.
ROLE = "role"

#: The order of the skills that a run reads at its start.
GENERAL_ORDER = ("search", "thorough", ROLE, "citation", "plan_first")

#: The tools a run needs before it reads a general skill at its start: `any` of the names,
#: or `all` of them.
ALWAYS_READ_NEEDS: Dict[str, Tuple[str, FrozenSet[str]]] = {
    "search": ("any", frozenset({"search_collections"})),
    "thorough": ("any", frozenset({"search_collections", "web_search"})),
    "citation": ("any", frozenset({"cite_documents"})),
    "plan_first": ("all", frozenset({"read_todo", "write_todo", "edit_todo", "mark_todo"})),
}


class UnboundToolError(RuntimeError):
    """A text names a tool that no pack holds.

    Raised only under `strict=True`, which the tests render with. At runtime the name is
    rendered as it stands, because an agent that refuses to start for one stale sentence
    answers nobody.
    """


class SkillFileError(ValueError):
    """A skill file has front matter that the loader cannot use."""


@dataclass(frozen=True)
class Skill:
    name: str
    group: str
    description: str
    tools: Tuple[str, ...]
    body: str  # the Jinja source after the front matter


@dataclass(frozen=True)
class SkillContext:
    profile: str  # one of the keys of ROLE_SKILLS
    tool_names: FrozenSet[str]  # every tool of the run's snapshot, bound or deferred
    collections_hint: bool = True
    # Empty in the step context. The preload passes a copy with the classes.
    request_classes: Tuple[str, ...] = ()


# ------------------------------------------------------------------------ loading


def _parse(path: Path) -> Skill:
    text = path.read_text()
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise SkillFileError(f"{path.name}: the file must start with a --- line")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise SkillFileError(f"{path.name}: the front matter has no closing --- line") from None
    fields: Dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if not sep:
            raise SkillFileError(f"{path.name}: front matter line {line!r} has no colon")
        fields[key.strip()] = value.strip()
    missing = [key for key in _KEYS if key not in fields]
    if missing:
        raise SkillFileError(f"{path.name}: the front matter has no {', '.join(missing)}")
    name, group, description = fields["name"], fields["group"], fields["description"]
    if not _NAME.fullmatch(name) or name + ".md.j2" != path.name:
        raise SkillFileError(f"{path.name}: the name {name!r} must be [a-z_] and equal the file name")
    if group not in GROUPS:
        raise SkillFileError(f"{path.name}: the group {group!r} is not one of {GROUPS}")
    if not description or len(description) > DESCRIPTION_MAX_CHARS:
        raise SkillFileError(
            f"{path.name}: the description must hold 1 to {DESCRIPTION_MAX_CHARS} characters"
        )
    tools = tuple(t.strip() for t in fields["tools"].split(",") if t.strip())
    unknown = [t for t in tools if pack_of(t) is None]
    if unknown:
        raise UnboundToolError(f"{path.name}: no pack holds the tools {unknown}")
    return Skill(name, group, description, tools, "\n".join(lines[end + 1:]))


def load_skills(directory: Path = SKILL_DIR) -> Dict[str, Skill]:
    """Read every skill file of `directory`, in file name order. Raise on bad front matter."""
    skills: Dict[str, Skill] = {}
    for path in sorted(directory.glob("*.md.j2")):
        skill = _parse(path)
        skills[skill.name] = skill
    return skills


#: The skills of this image, read once at import.
SKILLS: Dict[str, Skill] = load_skills()


# ------------------------------------------------------------------------ listing


def _tools_rule(skill: Skill, tool_names: FrozenSet[str]) -> bool:
    return not skill.tools or any(name in tool_names for name in skill.tools)


def listed_skills(ctx: SkillContext, skills: Optional[Dict[str, Skill]] = None) -> List[Skill]:
    """The skills of one run: the role skill of its profile, then the general, technique and
    stumble skills whose `tools` rule holds, each group in file name order."""
    skills = SKILLS if skills is None else skills
    out: List[Skill] = []
    role = skills.get(ROLE_SKILLS.get(ctx.profile, ""))
    if role is not None:
        out.append(role)
    for group in GROUPS[1:]:
        for name in sorted(skills):
            skill = skills[name]
            if skill.group == group and _tools_rule(skill, ctx.tool_names):
                out.append(skill)
    return out


def always_read(ctx: SkillContext) -> List[str]:
    """The skills a run reads at its start, in `GENERAL_ORDER`. A general skill is kept only
    when the run has the tools of `ALWAYS_READ_NEEDS`."""
    out: List[str] = []
    for name in GENERAL_ORDER:
        if name == ROLE:
            role = ROLE_SKILLS.get(ctx.profile)
            if role:
                out.append(role)
            continue
        mode, needs = ALWAYS_READ_NEEDS[name]
        test = all if mode == "all" else any
        if test(tool in ctx.tool_names for tool in needs):
            out.append(name)
    return out


# ---------------------------------------------------------------------- rendering


def environment() -> Environment:
    """The Jinja settings of the prompt templates. `StrictUndefined` makes a mistyped name
    fail loudly."""
    return Environment(
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def tool_function(strict: bool):
    """The `tool()` of a template: the name in backticks. Under `strict`, a name that no pack
    holds raises `UnboundToolError`."""

    def tool(name: str) -> str:
        if strict and pack_of(name) is None:
            raise UnboundToolError(f"no pack holds the tool {name!r}, but a text names it")
        return f"`{name}`"

    return tool


def skill_variables(ctx: SkillContext, strict: bool = False) -> Dict[str, object]:
    """The names a skill body can read."""
    names = ctx.tool_names
    artefact, resolver = ROLE_CONTEXT.get(ctx.profile, ROLE_CONTEXT[DEFAULT_PROFILE])
    return {
        "has": lambda name: name in names,
        "tool": tool_function(strict),
        "web_enabled": "web_search" in names,
        "subagents_enabled": "run_subagent" in names,
        "citation_artefact": artefact,
        "citation_resolver": resolver,
        "collections_hint": bool(ctx.collections_hint),
        "profile": ctx.profile,
        "request_classes": list(ctx.request_classes),
    }


def render_skill(name: str, ctx: SkillContext, *, strict: bool = False,
                 skills: Optional[Dict[str, Skill]] = None) -> str:
    """The text of one skill for one run. The first line is ``Skill `name`.``, and a blank
    line follows it. An unknown name raises `KeyError`."""
    skill = (SKILLS if skills is None else skills)[name]
    body = environment().from_string(skill.body).render(**skill_variables(ctx, strict))
    return f"Skill `{name}`.\n\n{body.strip()}"


# ---------------------------------------------------------------------- searching

_STOP_WORDS = frozenset({
    "a", "an", "and", "the", "of", "to", "in", "on", "for", "by", "with", "or", "is",
    "are", "it", "its", "this", "that", "from", "at", "as", "be", "i", "me", "my", "all",
    "one", "tool", "tools",
})


def words(text: str) -> List[str]:
    """The lowercase words of a text, split at every character that is not a letter or a
    digit."""
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


def rank_matches(query: str, items: Iterable[Tuple[str, str]]) -> List[str]:
    """Rank `(name, text)` items against a request and return the names that match.

    The order is an exact name, then the whole request as words of the text, then a name
    that starts with the request, then the count of shared words, then the name. An item
    that matches in none of these ways is left out.
    """
    text = (query or "").strip().lower()
    joined = "_".join(words(text))
    query_words = [w for w in words(text) if w not in _STOP_WORDS]
    phrase = " ".join(words(text))
    ranked = []
    for name, item_text in items:
        text_words = words(item_text)
        name_words = words(name)
        if joined and name == joined:
            rank = 0
        elif phrase and re.search(rf"\b{re.escape(phrase)}\b", " ".join(text_words)):
            rank = 1
        elif joined and name.startswith(joined):
            rank = 2
        else:
            rank = 3
        overlap = len(set(query_words) & (set(name_words) | set(text_words)))
        if rank == 3 and overlap == 0:
            continue
        ranked.append((rank, -overlap, name))
    ranked.sort()
    return [name for _, _, name in ranked]


def search_skills(query: str, ctx: SkillContext, limit: int = 6,
                  skills: Optional[Dict[str, Skill]] = None) -> List[Dict[str, str]]:
    """The listed skills that match a request, best first. An empty request returns every
    listed skill."""
    listed = listed_skills(ctx, skills)
    if not (query or "").strip():
        return [{"name": s.name, "description": s.description} for s in listed]
    by_name = {s.name: s for s in listed}
    names = rank_matches(query, [(s.name, s.description) for s in listed])[:limit]
    return [{"name": n, "description": by_name[n].description} for n in names]


__all__ = [
    "ALWAYS_READ_NEEDS", "DEFAULT_PROFILE", "GENERAL_ORDER", "GROUPS", "ROLE_CONTEXT",
    "ROLE_SKILLS", "RUN_KIND_PROFILES", "SKILLS", "SKILL_DIR", "Skill", "SkillContext",
    "SkillFileError", "UnboundToolError", "always_read", "listed_skills", "load_skills",
    "rank_matches", "render_skill", "search_skills", "skill_variables", "words",
]
