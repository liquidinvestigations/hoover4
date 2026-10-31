"""The agent language of a run: translated prompts, skills and tool texts with an English
fallback, protocol values that stay English, and context and snapshot keys that hold the
language."""

from __future__ import annotations

import json

import pytest
from langchain_core.tools import StructuredTool

from agent_common.tool_packs import PACKS
from research_agent import localization, prompts, skill_store, tool_catalogue
from research_agent.agent import MCPGatewayAgent
from research_agent.skill_store import SkillContext, listed_skills, render_skill, search_skills
from research_agent.steps import shown_tool
from research_agent.tool_catalogue import build_snapshot

EVERY_TOOL = frozenset().union(*(t for p, t in PACKS.items() if p != "board"))


class FakeTool:
    def __init__(self, name, description="", schema=None):
        self.name = name
        self.description = description
        self.args_schema = schema or {"type": "object", "properties": {}}


@pytest.fixture
def translated(tmp_path, monkeypatch):
    """A package folder with German files for one skill, the prompt and two tool texts."""
    skills = tmp_path / "skills" / "de"
    (skills / "partials").mkdir(parents=True)
    english = skill_store.SKILLS["search"]
    (skills / "search.md.j2").write_text(
        "---\nname: renamed\ngroup: stumble\ndescription: wie man Sammlungen durchsucht\n"
        "tools: read_skill\n---\nSuche mit {{ tool('search_collections') }}.\n")
    prompts_de = tmp_path / "prompts" / "de"
    prompts_de.mkdir(parents=True)
    (prompts_de / "agent.md.j2").write_text("{{ role_line }}\nAntworte auf {{ language_name }}.\n")
    (prompts_de / "role_lines.json").write_text(json.dumps({"internal_search": "Du bist der Assistent."}))
    texts = tmp_path / "tool_texts"
    texts.mkdir()
    (texts / "de.json").write_text(json.dumps({
        "Search the collections.": "Durchsuche die Sammlungen.",
        "The words to find.": "Die gesuchten Wörter.",
    }))
    monkeypatch.setattr(skill_store, "SKILL_DIR", tmp_path / "skills")
    monkeypatch.setattr(skill_store, "_TRANSLATED", {})
    monkeypatch.setattr(prompts, "TEMPLATE_DIR", tmp_path / "prompts")
    monkeypatch.setattr(localization, "PACKAGE_DIR", tmp_path)
    monkeypatch.setattr(localization, "PROMPT_DIR", tmp_path / "prompts")
    monkeypatch.setattr(localization, "SKILL_DIR", tmp_path / "skills")
    monkeypatch.setattr(localization, "TOOL_TEXT_DIR", texts)
    localization.tool_texts.cache_clear()
    localization.catalog_revision.cache_clear()
    yield english
    localization.tool_texts.cache_clear()
    localization.catalog_revision.cache_clear()


def test_an_unknown_or_empty_code_runs_in_english():
    assert localization.run_language("de") == "de"
    assert localization.run_language("") == "en"
    assert localization.run_language("xx") == "en"
    assert localization.language_name("de") == "Deutsch (German)"
    assert localization.language_name("en") == "English"


def test_a_translated_skill_keeps_the_english_name_group_and_tools(translated):
    german = skill_store.skills_for("de")["search"]
    assert (german.name, german.group, german.tools) == (translated.name, translated.group, translated.tools)
    assert german.description == "wie man Sammlungen durchsucht"
    ctx = SkillContext(profile="internal_search", tool_names=EVERY_TOOL, language="de")
    assert render_skill("search", ctx).endswith("Suche mit `search_collections`.")
    # A skill without a translation stays English.
    assert skill_store.skills_for("de")["citation"] == skill_store.SKILLS["citation"]
    assert [s.name for s in listed_skills(ctx)] == [
        s.name for s in listed_skills(SkillContext("internal_search", EVERY_TOOL))]


def test_a_skill_search_finds_a_translated_skill_in_either_language(translated):
    ctx = SkillContext(profile="internal_search", tool_names=EVERY_TOOL, language="de")
    assert search_skills("Sammlungen durchsucht", ctx)[0]["name"] == "search"
    assert "search" in [m["name"] for m in search_skills("search document collections", ctx)]


def test_words_split_every_script():
    assert skill_store.words("Wörter, über Ämter") == ["wörter", "über", "ämter"]
    assert skill_store.words("搜索文件") == ["搜索", "索文", "文件"]
    assert skill_store.words("read_skill now") == ["read", "skill", "now"]


def test_the_prompt_renders_the_translation_and_names_the_language(translated):
    tools = [FakeTool("search_collections", "Search the collections.")]
    snapshot = build_snapshot(tools, ["search_collections"], "chat",
                              SkillContext(profile="internal_search", tool_names=frozenset(),
                                           language="de"))
    text = prompts.render("internal_search", snapshot=snapshot, skills=[], language="de")
    assert text == "Du bist der Assistent.\nAntworte auf Deutsch (German)."


def test_the_english_prompt_names_english():
    tools = [FakeTool("search_collections", "Search the collections.")]
    snapshot = build_snapshot(tools, ["search_collections"], "chat",
                              SkillContext(profile="internal_search", tool_names=frozenset()))
    text = prompts.render("internal_search", snapshot=snapshot, skills=[])
    assert "Write your answers, questions, plans and files in English" in text


def test_shown_tools_translate_descriptions_and_keep_the_protocol(translated):
    schema = {"type": "object", "properties": {"query": {"type": "string", "description": "The words to find.",
                                                         "enum": ["The words to find."]}},
              "required": ["query"]}
    tool = StructuredTool(name="search_collections", description="Search the collections.",
                          args_schema=schema, func=lambda **_: "")
    english = shown_tool(tool)
    german = shown_tool(tool, "de")
    assert german["function"]["name"] == english["function"]["name"] == "search_collections"
    assert german["function"]["description"] == "Durchsuche die Sammlungen."
    query = german["function"]["parameters"]["properties"]["query"]
    assert query["description"] == "Die gesuchten Wörter."
    assert query["enum"] == ["The words to find."]
    assert german["function"]["parameters"]["required"] == ["query"]
    # The tool object stays English.
    assert tool.description == "Search the collections."


def test_the_snapshot_version_holds_the_language(translated):
    tools = [FakeTool("search_collections", "Search the collections.")]

    def snap(language):
        return build_snapshot(tools, ["search_collections"], "chat",
                              SkillContext("internal_search", frozenset(), language=language))

    english, german = snap("en"), snap("de")
    assert english.version == build_snapshot(tools, ["search_collections"], "chat").version
    assert german.version != english.version
    assert german.summaries["search_collections"] == "Durchsuche die Sammlungen."
    assert [m["name"] for m in german.search("search the collections")] == ["search_collections"]
    assert tool_catalogue.search_result(german, "zzzz")["text"] == tool_catalogue.NO_MATCH_TEXT


def test_the_context_key_holds_the_language_and_its_revision(translated):
    key = MCPGatewayAgent._acl_key
    english = key("u", ["c"], "s", "m", "r", "chat", "rev", "en")
    german = key("u", ["c"], "s", "m", "r", "chat", "rev", "de")
    assert english != german
    assert key("u", ["c"], "s", "m", "r", "chat", "rev", "xx") == english
    assert german.endswith("|de|" + localization.catalog_revision("de"))
    assert localization.catalog_revision("de") and not localization.catalog_revision("en")


TRANSLATED = [code for code in localization.LANGUAGES if localization.translated_files(code)]


@pytest.mark.parametrize("code", TRANSLATED or ["none"])
def test_every_translation_renders_strictly_and_keeps_its_code_spans(code):
    if code == "none":
        pytest.skip("no translation in this tree")
    import re

    for profile in prompts.ROLE_LINES:
        snapshot = build_snapshot([FakeTool(n, f"{n}.") for n in sorted(EVERY_TOOL)], EVERY_TOOL,
                                  prompts.PROFILE_KINDS[profile],
                                  SkillContext(profile=profile, tool_names=frozenset(), language=code))
        text = prompts.render(profile, snapshot=snapshot, skills=listed_skills(snapshot.skill_context),
                              strict=True, language=code)
        assert localization.language_name(code) in text
    spans = re.compile(r"`[^`\n]+`")
    for english, translation in localization.tool_texts(code).items():
        assert sorted(spans.findall(english)) == sorted(spans.findall(translation)), english
