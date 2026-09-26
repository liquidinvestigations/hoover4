"""The catalogue snapshot, the core and deferred split, and `search_agent_tools`."""

import json

import pytest

from agent_common.tool_packs import PACKS, allowed_tools, packs_for
from research_agent import tool_catalogue
from research_agent.tool_catalogue import (
    CATALOGUE_MATCH_COUNT,
    NO_MATCH_TEXT,
    SEARCH_QUERY_MAX_CHARS,
    bind_names,
    build_snapshot,
    search_result,
)


class FakeTool:
    def __init__(self, name, description=""):
        self.name = name
        self.description = description
        self.args_schema = {"type": "object", "properties": {}}


COLLECTION_TOOLS = [
    FakeTool(name, f"{name.replace('_', ' ')}.")
    for name in sorted(PACKS["collections"])
]
OTHER_TOOLS = [
    FakeTool("read_todo", "Read the plan of this conversation."),
    FakeTool("web_search", "Search the open web."),
    FakeTool("read_plan", "Read the research plan tree."),
    FakeTool("append_node", "Add a node to the plan tree."),
]
EVERY_PACK = allowed_tools("chat", "all")


def snapshot(kind="chat", allowed=EVERY_PACK, tools=None):
    return build_snapshot(tools or COLLECTION_TOOLS + OTHER_TOOLS, allowed, kind)


# --------------------------------------------------------------- core and deferred


def test_the_core_set_is_the_named_collection_tools_and_every_other_server():
    snap = snapshot()
    assert set(snap.core_names) == {
        "list_collections", "search_collections", "search_passages", "read_documents",
        "list_document_entities", "cite_documents", "read_more", "search_agent_tools",
        "read_todo", "web_search",
    }
    assert "doc_search_text" in snap.deferred_names
    assert "table_cell" in snap.deferred_names
    assert {"read_plan", "append_node"} <= set(snap.deferred_names)


def test_the_plan_tools_are_core_for_the_planner_and_the_organizer():
    for kind in ("planner", "organizer"):
        assert {"read_plan", "append_node"} <= set(snapshot(kind).core_names)


def test_a_tool_outside_the_packs_is_not_in_the_snapshot():
    snap = snapshot(allowed=allowed_tools("chat", "collections,catalogue"))
    assert "web_search" not in snap.tools_by_name
    assert "web_search" in snap.refused_names
    assert "web_search" not in [m["name"] for m in snap.search("open web")]


def test_every_pack_tool_is_in_exactly_one_pack():
    names = [name for tools in PACKS.values() for name in tools]
    assert len(names) == len(set(names))


def test_an_unknown_pack_name_raises():
    with pytest.raises(ValueError):
        packs_for("chat", "collections,webb")
    with pytest.raises(ValueError):
        packs_for("reviewer", "all")
    assert packs_for("chat", "") == frozenset(PACKS)


# ------------------------------------------------------------------------ ranking


def test_an_exact_name_ranks_first():
    names = [m["name"] for m in snapshot().search("table_page")]
    assert names[0] == "table_page"


def test_a_summary_phrase_ranks_before_a_name_prefix_and_word_overlap():
    tools = [
        FakeTool("table_cell", "Read one cell of a table."),
        FakeTool("table_page", "Read one page of rows."),
        FakeTool("folder_list", "List a folder and its table files."),
    ]
    snap = snapshot(tools=tools)
    names = [m["name"] for m in snap.search("page of rows")]
    assert names[0] == "table_page"
    names = [m["name"] for m in snap.search("table")]
    # `table` is a word of two summaries, which rank before the name prefix of the third.
    assert names == ["folder_list", "table_cell", "table_page"]


def test_word_overlap_orders_by_the_count_of_shared_words():
    tools = [
        FakeTool("doc_email", "Read the headers and attachments of one email."),
        FakeTool("doc_sources", "List the sources of one document."),
    ]
    names = [m["name"] for m in snapshot(tools=tools).search("email attachments headers")]
    assert names == ["doc_email"]


def test_a_search_that_matches_nothing_returns_the_empty_result():
    result = search_result(snapshot(), "zzqx unrelated")
    assert result == {"matches": [], "text": NO_MATCH_TEXT}


def test_the_search_never_lists_itself():
    assert "search_agent_tools" not in [m["name"] for m in snapshot().search("search agent tools")]


# ------------------------------------------------------------------- match count


def test_a_search_returns_at_most_the_match_count():
    assert CATALOGUE_MATCH_COUNT == 6
    assert len(snapshot().search("table folder doc search")) == CATALOGUE_MATCH_COUNT


def test_the_bind_step_keeps_the_newest_matches_first_and_at_most_the_match_count():
    snap = snapshot()
    earlier = ("table_page", "table_cell")
    newest = ["doc_email", "table_page", "search_collections", "pdf_search"]
    bound = bind_names(snap, earlier, newest)
    assert bound == ("doc_email", "table_page", "pdf_search", "table_cell")
    many = [n for n in snap.deferred_names][:10]
    assert len(bind_names(snap, (), many)) == CATALOGUE_MATCH_COUNT


@pytest.mark.parametrize("value, expected", [("", 6), ("6", 6), ("12", 12)])
def test_the_match_count_reads_the_environment(monkeypatch, value, expected):
    monkeypatch.setenv("AGENT_CATALOGUE_MATCH_COUNT", value)
    assert tool_catalogue._match_count() == expected


@pytest.mark.parametrize("value", ["5", "13"])
def test_a_match_count_outside_six_to_twelve_is_refused(monkeypatch, value):
    monkeypatch.setenv("AGENT_CATALOGUE_MATCH_COUNT", value)
    with pytest.raises(ValueError):
        tool_catalogue._match_count()


async def test_the_search_tool_answers_json_with_its_matches():
    snap = snapshot()
    tool = snap.tools_by_name["search_agent_tools"]
    result = json.loads(await tool.ainvoke({"query": "pdf search"}))
    assert result["matches"][0]["name"] == "pdf_search"


@pytest.mark.parametrize("query, error", [
    ("", "invalid_arguments"),
    ("t" * (SEARCH_QUERY_MAX_CHARS + 1), "invalid_arguments"),
    ("read a table " + "t" * (SEARCH_QUERY_MAX_CHARS - 13), None),
])
async def test_the_search_query_takes_one_to_160_characters(query, error):
    from research_agent import steps

    class _Agent:
        async def context_for(self, *args, **kwargs):
            return type("Context", (), {"snapshot": snapshot()})()

    assert SEARCH_QUERY_MAX_CHARS == 160
    request = steps.ToolCallRequest(
        run_id="r", kind="chat", depth=0, username="u", session_id="s",
        call={"id": "s", "name": "search_agent_tools", "args": {"query": query}},
        idempotency_key="k",
    )
    content = json.loads((await steps.run_tool_call(_Agent(), request))["content"])
    if error is None:
        assert "matches" in content and "error" not in content
    else:
        assert content["error"] == error
