"""The skill line of an error: a failed result that shows a known stumble names its skill."""

from __future__ import annotations

import json

from agent_common.tool_packs import PACKS
from research_agent import steps
from research_agent.skill_store import SkillContext, listed_skills
from research_agent.stumbles import SKILL_LINE, stumble_skill, with_skill_line
from test_skill_tools import snapshot

EVERY_TOOL = frozenset().union(*PACKS.values())
LISTED = frozenset(
    s.name for s in listed_skills(SkillContext(profile="full_research", tool_names=EVERY_TOOL))
)
HASH = "a" * 64


def response(name, content, status="error"):
    return {"tool_call_id": "c", "name": name, "content": content, "status": status,
            "error_class": "tool_error" if status == "error" else "", "measure": None,
            "matched_names": []}


def line(skill):
    return SKILL_LINE.format(skill=skill)


# -------------------------------------------------------------------------- normal


def test_a_read_by_file_name_gets_the_document_ids_line_in_its_message():
    content = json.dumps({"success": False, "error": "invalid_argument",
                          "message": "file_hash must be a content hash from search_collections"})
    out = with_skill_line(response("read_documents", content),
                          {"file_hash": "stanley.ec02.pdf"}, LISTED)
    data = json.loads(out["content"])
    assert data["message"] == (
        "file_hash must be a content hash from search_collections " + line("document_ids"))
    assert data["error"] == "invalid_argument"


def test_a_todo_refusal_of_a_quoted_id_gets_the_todo_upkeep_line():
    content = json.dumps({"success": False, "goal": "g", "items": [], "version": 1,
                          "error": 'no item has the id "1"'})
    out = with_skill_line(response("write_todo", content), {"ids": ['"1"']}, LISTED)
    assert json.loads(out["content"])["error"].endswith(line("todo_upkeep"))


def test_each_cause_names_its_skill():
    cases = [
        ("search_collections", {"success": False, "error": "invalid_arguments",
                                "message": "queries: ['a'] is too long"}, {}, "search"),
        ("search_collections", {"success": False, "error": "invalid_argument",
                                "message": "the collection x is outside the permitted collections"},
         {}, "collection_names"),
        ("append_child", {"success": False, "error": "no node 9"}, {}, "plan_editing"),
        ("table_page", {"success": False, "error": "invalid_arguments",
                        "message": "row_start: 'x' is not of type 'integer'"}, {}, "call_arguments"),
        ("doc_email", {"success": False, "error": "not_found", "message": "no dataset holds it"},
         {"file_hash": HASH}, "document_ids"),
    ]
    for name, data, args, skill in cases:
        assert stumble_skill(name, json.dumps(data), "error", args) == skill, name
    browser = "### Error\nstale element reference"
    assert stumble_skill("browser_click", browser, "ok", {}) == "browser_use"


# ------------------------------------------------------------------------- failure


def test_a_result_page_error_gets_no_line():
    content = json.dumps({"kind": "result_page", "success": False,
                          "error": "file_hash must be a content hash from search_collections"})
    out = with_skill_line(response("read_documents", content), {"file_hash": "x.pdf"}, LISTED)
    assert out["content"] == content


def test_an_ok_result_gets_no_line():
    content = json.dumps({"success": True, "results": [{"file_hash": HASH}]})
    out = with_skill_line(response("read_documents", content, "ok"), {"file_hash": HASH}, LISTED)
    assert out["content"] == content


def test_a_skill_that_the_run_does_not_list_gets_no_line():
    content = json.dumps({"success": False, "error": "invalid_argument",
                          "message": "file_hash must be a content hash from search_collections"})
    listed = LISTED - {"document_ids"}
    out = with_skill_line(response("read_documents", content), {"file_hash": "x.pdf"}, listed)
    assert out["content"] == content


def test_a_plain_text_error_gets_the_line_after_a_blank_line_once():
    content = "Error: 1 validation error for mark_todo"
    once = with_skill_line(response("table_page", content), {}, LISTED)
    assert once["content"] == content + "\n\n" + line("call_arguments")
    twice = with_skill_line(once, {}, LISTED)
    assert twice["content"] == once["content"]


def test_a_json_error_with_no_text_gets_the_line_under_next():
    content = json.dumps({"success": False, "error": {"code": 3}})
    out = with_skill_line(response("mark_todo", content), {}, LISTED)
    assert json.loads(out["content"])["next"] == line("todo_upkeep")


def test_a_repeat_refusal_and_a_failed_backend_get_no_line():
    for data in ({"success": False, "error": "repeated_call", "message": "not run"},
                 {"success": False, "error": "tool_unavailable", "message": "down"}):
        assert stumble_skill("read_documents", json.dumps(data), "error",
                             {"file_hash": "x.pdf"}) is None


# ------------------------------------------------------------------------- the route


class _Agent:
    def __init__(self, snap):
        self.snap = snap

    async def context_for(self, *args, **kwargs):
        return type("Context", (), {"snapshot": self.snap})()


def _request(name, args, bound=()):
    return steps.ToolCallRequest(
        run_id="r", kind="chat", depth=0, username="u", session_id="s",
        call={"id": "c", "name": name, "args": args}, bound_names=list(bound),
        idempotency_key="k",
    )


async def test_the_route_adds_the_line_to_a_refused_argument():
    snap = snapshot(profile="full_research")
    result = await steps.run_tool_call(_Agent(snap), _request("search_collections", {}))
    assert result["status"] == "error" and result["error_class"] == "invalid_arguments"
    assert json.loads(result["content"])["message"].endswith(line("call_arguments"))


async def test_the_route_adds_no_line_to_an_ok_result():
    snap = snapshot(profile="full_research")
    result = await steps.run_tool_call(_Agent(snap), _request("read_tool", {"name": "doc_email"}))
    assert result["status"] == "ok" and "read_skill" not in result["content"]
