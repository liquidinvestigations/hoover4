"""The skill store: loading, listing, rendering, and the text that moved into the skills.

`prompt_fixtures/` holds the prompt templates as they were before the skills held their
text. The equality cases render those templates and the skills with the same tool names,
and compare the two texts after each run of whitespace becomes one space.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from agent_common.tool_packs import PACKS
from research_agent import skill_store
from research_agent.skill_store import (
    ROLE_CONTEXT,
    SkillContext,
    SkillFileError,
    UnboundToolError,
    listed_skills,
    load_skills,
    render_skill,
)

FIXTURES = Path(__file__).parent / "prompt_fixtures"

EVERY_TOOL = frozenset().union(*PACKS.values())
NARROW_TOOLS = PACKS["collections"] | PACKS["conversation"] | PACKS["skills"]
PROFILES = sorted(ROLE_CONTEXT)

#: The descriptions of the general skills that the prompt lists.
GENERAL_DESCRIPTIONS = {
    "search": "how to search document collections and use the query syntax",
    "thorough": "how to choose further searches when a question needs research",
    "citation": "how to cite documents and captured web pages that support an answer",
}

#: The descriptions of the technique and stumble skills that the classifier forms were
#: calibrated on, byte for byte.
NEW_DESCRIPTIONS = {
    name: row["description"]
    for name, row in json.loads((FIXTURES / "skill_descriptions.json").read_text()).items()
}
TECHNIQUE_SKILLS = sorted([
    "browser_use", "web_research", "spreadsheets", "emails", "folders_and_files", "passages",
    "entities",
])
STUMBLE_SKILLS = sorted([
    "after_a_result", "todo_upkeep", "document_ids", "call_arguments", "collection_names",
    "no_results",
])
#: The most characters of a technique or stumble skill.

#: The lines that the skills `search` and `citation` hold and the old templates did not.
SEARCH_LINES = (
    "8. One call takes at most 12 queries. Split a longer list into two calls.",
    "9. Give each query at least one word to search for. A query of -word terms alone is refused.",
    "10. Set filename_only to true or false. It takes no text.",
)
CITATION_LINE = "When a search or read returned documents that support a claim, cite those documents."


def context(profile="full_research", tools=EVERY_TOOL, **kwargs):
    return SkillContext(profile=profile, tool_names=frozenset(tools), **kwargs)


def normalised(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# -------------------------------------------------------------------------- normal


def test_the_store_holds_the_migrated_and_the_new_skills():
    skills = load_skills()
    groups = {group: sorted(n for n, s in skills.items() if s.group == group)
              for group in skill_store.GROUPS}
    assert groups == {
        "role": sorted(["method_chat_full", "method_chat_internal"]),
        "general": sorted(["search", "thorough", "citation"]),
        "technique": TECHNIQUE_SKILLS,
        "stumble": STUMBLE_SKILLS,
    }


@pytest.mark.parametrize("name", sorted(GENERAL_DESCRIPTIONS))
def test_a_general_skill_keeps_its_description(name):
    assert load_skills()[name].description == GENERAL_DESCRIPTIONS[name]




# ------------------------------------------------------------------------ boundary


def test_a_skill_of_the_web_is_not_listed_without_the_web(tmp_path):
    for name, group, tools in (
        ("method_chat_internal", "role", ""),
        ("web_research", "technique", "web_search, read_page"),
        ("search", "general", "search_collections"),
    ):
        (tmp_path / f"{name}.md.j2").write_text(
            f"---\nname: {name}\ngroup: {group}\ndescription: d\ntools: {tools}\n---\nbody\n"
        )
    skills = load_skills(tmp_path)
    names = [s.name for s in listed_skills(context("internal_search", NARROW_TOOLS), skills)]
    assert names == ["search"]
    with_web = [s.name for s in listed_skills(context("internal_search", EVERY_TOOL), skills)]
    assert "web_research" in with_web


def test_no_run_lists_a_role_skill_and_each_profile_gets_its_own_role_text():
    for profile, name in skill_store.ROLE_SKILLS.items():
        listed = [s.name for s in listed_skills(context(profile))]
        assert not [n for n in listed if skill_store.SKILLS[n].group == "role"]
        body = skill_store.render_body(name, context(profile), strict=True)
        assert skill_store.role_method(context(profile)) == body




@pytest.mark.parametrize("profile", sorted(skill_store.ROLE_SKILLS))
def test_a_role_text_asks_for_no_search_heading_or_todo_update(profile):
    """A role text gives the objective, the sources, the evidence rule and the role's duty.
    It asks for no search before an answer, no report heading and no todo update."""
    text = normalised(skill_store.role_method(context(profile))).lower()
    for phrase in ("todo", "##", "search relevant", "identify the people"):
        assert phrase not in text, (profile, phrase)


# ------------------------------------------------------------------------- failure


def test_a_file_with_no_group_raises_and_names_the_file(tmp_path):
    (tmp_path / "broken.md.j2").write_text(
        "---\nname: broken\ndescription: d\ntools:\n---\nbody\n"
    )
    with pytest.raises(SkillFileError, match="broken.md.j2"):
        load_skills(tmp_path)


def test_a_strict_render_of_a_tool_outside_every_pack_raises(tmp_path):
    (tmp_path / "odd.md.j2").write_text(
        "---\nname: odd\ngroup: technique\ndescription: d\ntools:\n---\n"
        "Call {{ tool('no_such_tool') }}.\n"
    )
    skills = load_skills(tmp_path)
    with pytest.raises(UnboundToolError):
        render_skill("odd", context(), strict=True, skills=skills)
    assert "`no_such_tool`" in render_skill("odd", context(), skills=skills)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("name", sorted(load_skills()))
def test_every_skill_renders_strictly_for_every_profile(profile, name):
    assert render_skill(name, context(profile), strict=True)


# ------------------------------------------------------------------------ equality


def _old_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(FIXTURES)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )


def _old_variables(profile, tools):
    artefact, resolver = ROLE_CONTEXT[profile]
    return {
        "has": lambda name: name in tools,
        "tool": lambda name: f"`{name}`",
        "web_enabled": "web_search" in tools,
        "citation_artefact": artefact,
        "citation_resolver": resolver,
        "collections_hint": True,
        "profile": profile,
    }


def _lines(template: str, first: int, last: int) -> str:
    return "".join((FIXTURES / template).read_text().splitlines(keepends=True)[first - 1:last])


#: The template lines that each role skill took, in template order. `method_planner` and
#: `method_organizer` are left out, because their texts now hold the plan caps and the
#: packing numbers, which the old templates did not.
ROLE_SOURCES = {
    "method_chat_internal": ("internal_search", [("internal_search.md.j2", 27, 36)]),
    "method_chat_full": (
        "full_research",
        [("full_research.md.j2", 23, 33), ("full_research.md.j2", 36, 40)],
    ),
}

#: Old text that a skill holds in a corrected form, and the form it holds. The old text
#: holds a dash that the prose rules of the repository do not allow.
DASH = chr(0x2014)
CORRECTED = {
    f"thread {DASH} a delegated turn": "thread, because a delegated turn",
}


def _old_text(source: str, profile: str, tools) -> str:
    text = _old_environment().from_string(source).render(**_old_variables(profile, tools))
    for old, new in CORRECTED.items():
        text = text.replace(old, new)
    return normalised(text)


def _new_text(name: str, profile: str, tools) -> str:
    text = render_skill(name, context(profile, tools))
    first, _, rest = text.partition("\n")
    assert first == f"Skill `{name}`."
    for line in SEARCH_LINES + (CITATION_LINE.format(artefact=ROLE_CONTEXT[profile][0]),):
        rest = rest.replace(line, "")
    return normalised(rest)


TOOL_SETS = {"every pack": EVERY_TOOL, "narrow": NARROW_TOOLS}


@pytest.mark.parametrize("tools", sorted(TOOL_SETS))
@pytest.mark.parametrize("name", sorted(ROLE_SOURCES))
def test_a_role_skill_holds_the_text_of_its_old_template_lines(name, tools):
    profile, ranges = ROLE_SOURCES[name]
    names = TOOL_SETS[tools]
    text = render_skill(name, context(profile, names), strict=True)
    assert text.startswith(f"Skill `{name}`.")
    assert "insults or emotive words" not in text
    if name.startswith("method_chat"):
        assert "can need no tool call" in text


def test_the_search_and_citation_skills_hold_the_new_lines():
    search = render_skill("search", context("internal_search", NARROW_TOOLS))
    for line in SEARCH_LINES:
        assert line in search
    citation = render_skill("citation", context("internal_search", NARROW_TOOLS))
    assert CITATION_LINE.format(artefact="answer") in citation
    assert "You can also name a" in citation


# ------------------------------------------------ the technique and stumble skills


@pytest.mark.parametrize("name", TECHNIQUE_SKILLS + STUMBLE_SKILLS)
def test_a_new_skill_loads_with_its_calibrated_description(name):
    skill = load_skills()[name]
    assert skill.description
    assert skill.group == ("technique" if name in TECHNIQUE_SKILLS else "stumble")


@pytest.mark.parametrize("name", TECHNIQUE_SKILLS + STUMBLE_SKILLS)
def test_a_new_skill_renders_strictly_for_the_full_chat(name):
    skill = load_skills()[name]
    text = render_skill(name, context("full_research"), strict=True)
    assert text.startswith(f"Skill `{name}`.\n\n")
    assert skill.body.strip()
    assert "{{" not in text and "{%" not in text


def test_the_full_chat_lists_every_new_skill():
    names = {s.name for s in listed_skills(context("full_research"))}
    assert set(TECHNIQUE_SKILLS + STUMBLE_SKILLS) <= names


def test_the_internal_chat_lists_no_browser_and_no_web_skill():
    internal = PACKS["collections"] | PACKS["conversation"] | PACKS["skills"] \
        | PACKS["catalogue"]
    names = {s.name for s in listed_skills(context("internal_search", internal))}
    assert "browser_use" not in names and "web_research" not in names
    assert {"spreadsheets", "emails", "document_ids", "todo_upkeep"} <= names


def test_todo_upkeep_shows_a_plain_id_and_one_status_per_call():
    text = normalised(render_skill("todo_upkeep", context("full_research")))
    assert 'Write ids ["1", "2"].' in text
    assert 'Do not write ids ["\\"1\\""].' in text
    assert "Give one status in each `mark_todo` call" in text


def test_document_ids_names_the_hash_and_the_supported_path():
    text = normalised(render_skill("document_ids", context("full_research")))
    assert "A document hash has 64 hexadecimal characters." in text
    assert "`read_documents` can also resolve a file name or path" in text


def test_web_only_citation_skill_keeps_page_instructions():
    context = SkillContext(profile="full_research", tool_names=frozenset({"cite_pages", "read_page", "web_search"}))
    body = render_skill("citation", context, strict=True)
    assert "`cite_pages`" in body and "[W1]" in body
    assert "`cite_documents`" not in body


def test_web_citation_role_does_not_request_bare_source_links():
    context = SkillContext(profile="full_research", tool_names=frozenset({"cite_pages", "read_page", "web_search"}))
    body = skill_store.role_method(context, strict=True)
    assert "returned `cite_pages` handle" in body
    assert "Put a direct page link" not in body
    assert "give the link of each web page" not in body
    assert "Never number citations yourself." in body
    assert "omit its claims until a later citation succeeds" in body
