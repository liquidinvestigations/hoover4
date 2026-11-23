"""Test skill loading, listing, and strict rendering."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_common.tool_packs import PACKS
from research_agent import prompts, skill_store
from research_agent.skill_store import (
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
PROFILES = sorted(prompts.PROFILE_KINDS)

#: The descriptions of the general skills that the prompt lists.
GENERAL_DESCRIPTIONS = {
    "search": "how to search document collections and use the query syntax",
    "thorough": "how to choose further searches when a question needs research",
    "citation": "how to cite the documents that support an answer",
    "report": ("where a report, a list, a table, a draft or an answer with citations goes, "
               "how to edit it, and how to show it"),
}

#: The descriptions of the technique and stumble skills that the classifier forms were
#: calibrated on, byte for byte.
NEW_DESCRIPTIONS = {
    name: row["description"]
    for name, row in json.loads((FIXTURES / "skill_descriptions.json").read_text()).items()
}
TECHNIQUE_SKILLS = sorted([
    "browser_use", "web_research", "spreadsheets", "emails", "folders_and_files", "passages",
    "entities", "earlier_work", "using_hoover",
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
        "general": sorted(["search", "thorough", "citation", "report"]),
        "technique": TECHNIQUE_SKILLS,
        "stumble": STUMBLE_SKILLS,
    }


@pytest.mark.parametrize("name", sorted(GENERAL_DESCRIPTIONS))
def test_a_general_skill_keeps_its_description(name):
    assert load_skills()[name].description == GENERAL_DESCRIPTIONS[name]




# ------------------------------------------------------------------------ boundary


def test_a_skill_of_the_web_is_not_listed_without_the_web(tmp_path):
    for name, group, tools in (
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
    text = render_skill(name, context(profile), strict=True)
    assert text
    assert "ask_user" not in text


# ------------------------------------------------------------------------ equality


def test_the_search_and_citation_skills_hold_the_new_lines():
    search = render_skill("search", context("internal_search", NARROW_TOOLS))
    for line in SEARCH_LINES:
        assert line in search
    citation = render_skill("citation", context("internal_search", NARROW_TOOLS))
    assert CITATION_LINE.format(artefact="answer") in citation
    assert "When you name, list or describe an internal document, cite it" in citation
    assert "You can also name a" not in citation


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


def test_todo_upkeep_shows_the_whole_list_with_statuses():
    text = normalised(render_skill("todo_upkeep", context("full_research")))
    assert "Send the whole list in every call, in order." in text
    assert "Create report.md with cited results and unresolved rows." in text
    assert "Verify roster group 2. Patch report.md. Check the returned version before group 3." in text
    assert "Reconcile scope, duplicate names and totals. Deliver report.md with the saved version." in text
    assert "report.md v2 holds groups 1 and 2." in text
    assert "Write a report or another file with `write_file`." in text


def test_document_ids_names_the_hash_and_the_supported_path():
    text = normalised(render_skill("document_ids", context("full_research")))
    assert "A document hash has 64 hexadecimal characters." in text
    assert "`read_documents` can also resolve a file name or path" in text


def test_a_web_only_run_lists_no_citation_skill_and_web_research_holds_the_page_rules():
    context = SkillContext(profile="full_research", tool_names=frozenset({"cite_pages", "read_page", "web_search"}))
    assert "citation" not in {s.name for s in listed_skills(context)}
    body = render_skill("web_research", context, strict=True)
    assert "`cite_pages`" in body and "[W1]" in body
    assert "`cite_documents`" not in body and "collection" not in body
    assert "When a citation fails, do not put another handle in its place." in normalised(body)


def test_the_cite_pages_arguments_are_in_one_skill_once():
    """A run with both sources reads the `cite_pages` arguments in `web_research` only, and
    both citation skills give the same failure rules from one partial."""
    tools = EVERY_TOOL
    web = render_skill("web_research", context("full_research", tools), strict=True)
    documents = render_skill("citation", context("full_research", tools), strict=True)
    reference = "`cite_pages` accepts url and terms for one page"
    assert web.count(reference) == 1 and reference not in documents
    assert "cite_pages" not in documents and "[W1]" not in documents
    assert "`cite_documents`" in documents and "`cite_documents`" not in web
    partial = (skill_store.PARTIALS_DIR / "citation_failures.j2").read_text()
    rules = normalised(skill_store.environment().from_string(partial).render(
        **skill_store.skill_variables(context("full_research", tools))))
    assert rules and rules in normalised(web) and rules in normalised(documents)
    assert "citation_failures" not in load_skills()


def test_report_skill_records_a_candidate_before_verification():
    body = render_skill("report", context(), strict=True)
    assert "file hash, and next action before verification" in body
    assert "search scope for an absence and the error for a failed read" in body
    assert "After citation succeeds, patch the report and mark the checklist entry complete." in body
    assert "other four files\nwith their versions in additional" in body


#: Fixed recovery counts that end a recovery before a different method runs.
RECOVERY_QUOTAS = re.compile(
    r"(?<!into )\b(?:two|three|2|3) (?:searches|calls|attempts|tries)\b|\bsecond call\b|\bfails? twice\b"
    r"|\bretry limit\b|\bthird (?:search|call|attempt)\b", re.IGNORECASE)


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("name", sorted(load_skills()))
def test_no_skill_states_a_fixed_recovery_count(profile, name):
    """Recovery continues while a different method remains. A batch size of a tool stays,
    because it is a limit of the accepted input."""
    text = re.sub(r"\s+", " ", render_skill(name, context(profile)))
    found = RECOVERY_QUOTAS.search(text)
    assert not found, found.group(0) if found else ""


def test_the_recovery_skills_show_a_correction_and_a_terminal_lack_of_support():
    def flat(text):
        return re.sub(r"\s+", " ", text)
    web = flat(render_skill("web_research", context("full_research")))
    assert "Do not send a search again with the same words" in web
    assert "the candidate is verified" in web and "do not name it as a case" in web
    citation = flat(render_skill("citation", context("full_research")))
    assert "Do not send a failed call again with the same arguments" in citation
    assert "curly apostrophe" in citation and "the board’s decision was final" in citation
    assert "sources read do not confirm" in citation
    assert "Send the next call with the third page only" in web
    assert "When a citation fails, do not put another handle in its place." in citation
    assert "When a citation fails, do not put another handle in its place." in web


def test_the_earlier_work_and_manual_skills_follow_the_hoover_pack():
    hoover = {"earlier_work", "using_hoover"}
    with_pack = {s.name for s in listed_skills(context("full_research", NARROW_TOOLS | PACKS["hoover"]))}
    assert hoover <= with_pack
    assert not hoover & {s.name for s in listed_skills(context("full_research", NARROW_TOOLS))}
    earlier = render_skill("earlier_work", context("internal_search", NARROW_TOOLS | PACKS["hoover"]), strict=True)
    for name in ("list_chats_and_boards", "read_chat", "read_board", "cite_chats_and_boards"):
        assert f"`{name}`" in earlier
    assert "[C1] or [B1]" in earlier and "(D1)" in earlier
    manual = render_skill("using_hoover", context("internal_search", PACKS["hoover"] | PACKS["skills"]), strict=True)
    assert "`search_manual`" in manual and "[Search](/docs#4-search)" in manual
    assert "Do not give a manual section a citation handle." in manual


def test_a_request_about_earlier_work_or_the_use_of_hoover_finds_its_skill():
    ctx = context("full_research", EVERY_TOOL)
    assert skill_store.search_skills("summary of the earlier boards", ctx)[0]["name"] == "earlier_work"
    assert skill_store.search_skills("how to use Hoover uploads", ctx)[0]["name"] == "using_hoover"


def test_the_worked_roster_exchange_creates_patches_repairs_and_delivers():
    """The direct exchange of `web_research` shows the first create, a later patch, a
    rejected handle, its repair and the delivery of the saved version. The execute example
    is valid JSON."""
    import json
    import re

    text = render_skill("web_research", context("full_research"))
    order = [text.index(part) for part in (
        'write_file {"content"', 'Result: {"citations": ["[W1]", "[W2]"], "name": "report.md"',
        '[W9]', '"version": 2', 'finish_with_report {"name": "report.md", "version": 2}')]
    assert order == sorted(order)
    assert "Unresolved: no read source names a public office." in text
    assert "Daniel Fried" not in text and "ned.org" not in text
    program = re.search(r"```json\n(\{\"language\": \"javascript\".*?)\n```", text, re.S).group(1)
    assert "patch_file" in json.loads(program)["code"]
