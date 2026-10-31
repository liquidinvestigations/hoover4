"""The skill store: short texts that each teach one method, read by the model on request.

Each skill is one file, `skills/<name>.md.j2`. The file starts with front matter between two
`---` lines, one `key: value` per line, and then a Jinja body.

* `name` is `[a-z_]{1,64}` and equals the file name.
* `group` is `role`, `general`, `technique` or `stumble`.
* `description` is one line of at most 200 characters. The system prompt lists it, and
  `search_skills` searches it.
* `tools` is a comma list of tool names that a pack of `agent_common.tool_packs` holds, or
  empty. A skill is listed in a run when the list is empty or one of its names is a tool of
  the run.
* `terms` and `not_for` are optional. `terms` lists the words that requests use for the
  method, and `not_for` names the requests that look similar and do not need it. The
  worker's preparation question reads them with the description. The system prompt lists
  the description only.

The role skill of a profile is not listed. The system prompt holds its text
(`role_method`), so every run of the profile reads it before its first call, and no run reads
it with `read_skill`. `render_skill` renders a body with the context that its caller passes,
and it keeps no state of its own. `has()` in a body reads every tool of the run.

A body can include a partial of `skills/partials/` by its file name. A partial has the
suffix `.j2` only, so `load_skills` never reads it as a skill. An included partial reads the
same names as the body that includes it. The `citation` and `web_research` skills include
`citation_failures.j2`, so both give the same failure rules.

A run in another language reads `skills/<language>/` over the English skills
(`skills_for`). A translated file gives the description, `terms`, `not_for` and the body.
The name, the group and the tools come from the English file, so a translation cannot
change which runs list a skill. A partial of `skills/<language>/partials/` replaces the
English partial of the same name. A skill or a partial without a translation stays English.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Tuple

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

from agent_common.tool_packs import pack_of

log = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).parent / "skills"
#: The texts that more than one skill includes.
PARTIALS_DIR = SKILL_DIR / "partials"
GROUPS = ("role", "general", "technique", "stumble")

#: The longest description a skill may have.
DESCRIPTION_MAX_CHARS = 200

_NAME = re.compile(r"[a-z_]{1,64}")
_KEYS = ("name", "group", "description", "tools")

#: The profile of a chat lead when the caller names none.
DEFAULT_PROFILE = "internal_search"

ROLE_SKILLS = {
    "internal_search": "method_chat_internal",
    "full_research": "method_chat_full",
}

#: The values of `citation_artefact` and `citation_resolver` for each profile. Cited text
#: goes into a workspace file in every profile (`report` skill).
ROLE_CONTEXT = {
    "internal_search": ("report", "reader"),
    "full_research": ("report", "reader"),
}

#: The skill whose short routing text the system prompt holds (`report_rules`).
REPORT_SKILL = "report"


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
    terms: str = ""
    not_for: str = ""


@dataclass(frozen=True)
class SkillContext:
    profile: str  # one of the keys of ROLE_SKILLS
    tool_names: FrozenSet[str]  # every tool of the run's snapshot
    collections_hint: bool = True
    language: str = "en"  # the agent language of the run (`localization.run_language`)


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
    return Skill(name, group, description, tools, "\n".join(lines[end + 1:]),
                 terms=fields.get("terms", ""), not_for=fields.get("not_for", ""))


def load_skills(directory: Path = SKILL_DIR) -> Dict[str, Skill]:
    """Read every skill file of `directory`, in file name order. Raise on bad front matter."""
    skills: Dict[str, Skill] = {}
    for path in sorted(directory.glob("*.md.j2")):
        skill = _parse(path)
        skills[skill.name] = skill
    return skills


#: The skills of this image, read once at import.
SKILLS: Dict[str, Skill] = load_skills()

_TRANSLATED: Dict[str, Dict[str, Skill]] = {}


def skills_for(language: str) -> Dict[str, Skill]:
    """The skills of one language: the English skills, each replaced by its translation
    when `skills/<language>/` has one. A translated file whose front matter the loader cannot
    use is logged and left out, so the English skill stays."""
    if language == "en" or not (SKILL_DIR / language).is_dir():
        return SKILLS
    if language not in _TRANSLATED:
        out = dict(SKILLS)
        for path in sorted((SKILL_DIR / language).glob("*.md.j2")):
            english = SKILLS.get(path.name[:-len(".md.j2")])
            if english is None:
                continue
            try:
                text = path.read_text()
                lines = text.split("\n")
                end = lines.index("---", 1)
                fields = dict(line.partition(":")[::2] for line in lines[1:end])
                fields = {k.strip(): v.strip() for k, v in fields.items()}
            except (OSError, ValueError) as exc:
                log.error("skill %s of %s is not readable: %s", path.name, language, exc)
                continue
            description = fields.get("description") or english.description
            out[english.name] = Skill(
                english.name, english.group, _clip(description), english.tools,
                "\n".join(lines[end + 1:]), terms=fields.get("terms", english.terms),
                not_for=fields.get("not_for", english.not_for))
        _TRANSLATED[language] = out
    return _TRANSLATED[language]


def _clip(text: str) -> str:
    """A translated description cut at a word boundary to `DESCRIPTION_MAX_CHARS`."""
    if len(text) <= DESCRIPTION_MAX_CHARS:
        return text
    return text[:DESCRIPTION_MAX_CHARS + 1].rsplit(" ", 1)[0]


def _store(ctx: SkillContext, skills: Optional[Dict[str, Skill]]) -> Dict[str, Skill]:
    return skills_for(ctx.language) if skills is None else skills


# ------------------------------------------------------------------------ listing


def _tools_rule(skill: Skill, tool_names: FrozenSet[str]) -> bool:
    return not skill.tools or any(name in tool_names for name in skill.tools)


def listed_skills(ctx: SkillContext, skills: Optional[Dict[str, Skill]] = None) -> List[Skill]:
    """The skills that one run can read: the general, technique and stumble skills whose
    `tools` rule holds, each group in file name order. The role skill is in the system
    prompt (`role_method`)."""
    skills = _store(ctx, skills)
    out: List[Skill] = []
    for group in GROUPS[1:]:
        for name in sorted(skills):
            skill = skills[name]
            if skill.group == group and _tools_rule(skill, ctx.tool_names):
                out.append(skill)
    return out


# ---------------------------------------------------------------------- rendering


def environment(language: str = "en") -> Environment:
    """The Jinja settings of the prompt templates. `StrictUndefined` makes a mistyped name
    fail loudly. The loader reads the partials that a skill includes, translated first."""
    folders = [SKILL_DIR / language / "partials"] if language != "en" else []
    return Environment(
        loader=ChoiceLoader([FileSystemLoader(str(f)) for f in folders + [PARTIALS_DIR]]),
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


def skill_variables(ctx: SkillContext, strict: bool = False,
                    routing_only: bool = False) -> Dict[str, object]:
    """The names a skill body can read. `routing_only` is true when the system prompt
    renders the routing text of the `report` skill."""
    names = ctx.tool_names
    artefact, resolver = ROLE_CONTEXT.get(ctx.profile, ROLE_CONTEXT[DEFAULT_PROFILE])
    return {
        "has": lambda name: name in names,
        "tool": tool_function(strict),
        "web_enabled": "web_search" in names,
        "citation_artefact": artefact,
        "citation_resolver": resolver,
        "collections_hint": bool(ctx.collections_hint),
        "profile": ctx.profile,
        "routing_only": routing_only,
    }


def render_body(name: str, ctx: SkillContext, *, strict: bool = False,
                skills: Optional[Dict[str, Skill]] = None) -> str:
    """The rendered body of one skill for one run. An unknown name raises `KeyError`."""
    skill = _store(ctx, skills)[name]
    return environment(ctx.language).from_string(skill.body).render(
        **skill_variables(ctx, strict)).strip()


def render_skill(name: str, ctx: SkillContext, *, strict: bool = False,
                 skills: Optional[Dict[str, Skill]] = None) -> str:
    """The text of one skill for one run. The first line is ``Skill `name`.``, and a blank
    line follows it. An unknown name raises `KeyError`."""
    return f"Skill `{name}`.\n\n{render_body(name, ctx, strict=strict, skills=skills)}"


def report_rules(ctx: SkillContext, *, strict: bool = False,
                 skills: Optional[Dict[str, Skill]] = None) -> str:
    """The routing text of the `report` skill, for the system prompt of every run that
    has the workspace tools. Empty when the run has no `write_file`. The system prompt
    holds it, so compaction cannot remove it, and no skill load is needed."""
    store = _store(ctx, skills)
    if REPORT_SKILL not in store or "write_file" not in ctx.tool_names:
        return ""
    return environment(ctx.language).from_string(store[REPORT_SKILL].body).render(
        **skill_variables(ctx, strict, routing_only=True)).strip()


def role_method(ctx: SkillContext, *, strict: bool = False,
                skills: Optional[Dict[str, Skill]] = None) -> str:
    """The rendered role skill of the run's profile, for the system prompt, or empty when
    the profile has none."""
    name = ROLE_SKILLS.get(ctx.profile, "")
    if name not in _store(ctx, skills):
        return ""
    return render_body(name, ctx, strict=strict, skills=skills)


# ---------------------------------------------------------------------- searching

_STOP_WORDS = frozenset({
    "a", "an", "and", "the", "of", "to", "in", "on", "for", "by", "with", "or", "is",
    "are", "it", "its", "this", "that", "from", "at", "as", "be", "i", "me", "my", "all",
    "one", "tool", "tools",
})


#: Han, Hiragana and Katakana characters. Such text has no spaces between words.
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def words(text: str) -> List[str]:
    """The lowercase words of a text, split at every character that is not a letter or a
    digit, in any script. A run of Han, Hiragana or Katakana characters gives its pairs of
    adjacent characters, because such text has no spaces between words."""
    out: List[str] = []
    for word in re.split(r"[\W_]+", (text or "").lower()):
        if not word:
            continue
        if _CJK.search(word) and len(word) > 2:
            out.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            out.append(word)
    return out


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


def searched_text(skill: Skill) -> str:
    """The text that `search_skills` matches: the description, and the English description
    when the skill is translated."""
    english = SKILLS.get(skill.name)
    if english is None or english.description == skill.description:
        return skill.description
    return f"{skill.description} {english.description}"


def search_skills(query: str, ctx: SkillContext, limit: int = 6,
                  skills: Optional[Dict[str, Skill]] = None) -> List[Dict[str, str]]:
    """The listed skills that match a request, best first. An empty request returns every
    listed skill."""
    listed = listed_skills(ctx, skills)
    if not (query or "").strip():
        return [{"name": s.name, "description": s.description} for s in listed]
    by_name = {s.name: s for s in listed}
    # A translated description is searched with its English text, so a request in either
    # language finds the skill.
    names = rank_matches(query, [(s.name, searched_text(s)) for s in listed])[:limit]
    return [{"name": n, "description": by_name[n].description} for n in names]


__all__ = [
    "DEFAULT_PROFILE", "GROUPS", "ROLE_CONTEXT",
    "PARTIALS_DIR", "ROLE_SKILLS", "SKILLS", "SKILL_DIR", "Skill", "SkillContext",
    "SkillFileError", "UnboundToolError", "listed_skills", "load_skills",
    "REPORT_SKILL", "rank_matches", "render_body", "render_skill", "report_rules",
    "role_method", "search_skills", "searched_text", "skills_for",
    "skill_variables", "words",
]
