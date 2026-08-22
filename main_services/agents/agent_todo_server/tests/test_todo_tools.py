"""The tool boundary: identity, argument coercion, and refusals reaching the model.

The store's own rules are tested where they live. What can be wrong *here* and nowhere
else is the wrapper: reading the caller out of headers instead of an argument, coercing
the shapes a model sends into the shapes the store takes, and returning a refusal the
model can read rather than an exception it cannot. The two load-bearing rules are
asserted through the tools as well -- not to test them twice, but because relaxing them
at this layer is exactly the mistake these tests exist to catch.

Storage is replaced with a dict, so no ClickHouse is needed; the validation that runs is
the real one.
"""

from __future__ import annotations

import pytest

from agent_todo_server import server
from agent_todo_server.identity import CallerUnknown, parse_caller
from database import chat_todos

HEADERS = {"X-Hoover4-User": "ann", "X-Hoover4-Chat-Session": "s1"}


def call(tool, **kwargs):
    """Invoke a registered tool's body. FastMCP rebinds the name to a Tool object."""
    return getattr(tool, "fn", tool)(**kwargs)


@pytest.fixture(autouse=True)
def store(monkeypatch):
    """An in-memory stand-in for the `chat_todos` table, keyed as the real one is."""
    rows: dict[tuple[str, str], dict] = {}

    def fake_read(username, session_id):
        return rows.get((username, session_id)) or chat_todos.empty_todo(
            session_id, username
        )

    def fake_insert(row):
        import json

        rows[(row["username"], row["session_id"])] = {
            "session_id": row["session_id"],
            "username": row["username"],
            "version": row["version"],
            "goal": row["goal"],
            "items": json.loads(row["items"]),
            "updated_at": row["updated_at"],
        }

    monkeypatch.setattr(chat_todos, "read_todo", fake_read)
    monkeypatch.setattr(chat_todos, "_insert", fake_insert)
    return rows


@pytest.fixture(autouse=True)
def caller(monkeypatch):
    monkeypatch.setattr(server, "get_http_headers", lambda: dict(HEADERS))


class TestIdentity:
    def test_the_session_comes_from_the_header_not_an_argument(self):
        caller = parse_caller(HEADERS)
        assert (caller.username, caller.session_id) == ("ann", "s1")

    def test_header_casing_does_not_matter(self):
        caller = parse_caller({"x-hoover4-user": "bob", "x-hoover4-chat-session": "s2"})
        assert (caller.username, caller.session_id) == ("bob", "s2")

    def test_a_call_naming_no_conversation_is_refused(self):
        with pytest.raises(CallerUnknown):
            parse_caller({"X-Hoover4-User": "ann"})

    def test_the_tools_refuse_it_in_words_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(server, "get_http_headers", lambda: {})
        result = call(server.read_todo)
        assert result.success is False
        assert "chat-session" in result.error
        assert result.items == []


class TestWriteAndRead:
    def test_an_empty_list_asks_for_a_plan(self):
        result = call(server.read_todo)
        assert result.success is True
        assert result.needs_plan is True
        assert result.version == 0

    def test_a_written_plan_reads_back(self):
        call(
            server.write_todo,
            goal="find the contract",
            items=[{"id": "a", "text": "search"}, {"id": "b", "text": "read"}],
        )
        result = call(server.read_todo)
        assert result.goal == "find the contract"
        assert [i.id for i in result.items] == ["a", "b"]
        assert result.needs_plan is False
        assert result.version == 1

    def test_every_write_is_a_new_version(self):
        call(server.write_todo, goal="one", items=[{"id": "a", "text": "x"}])
        second = call(server.write_todo, goal="two", items=[{"id": "a", "text": "x"}])
        assert second.version == 2

    def test_a_fully_resolved_plan_asks_for_a_new_one(self):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        result = call(server.mark_todo, marks=[{"id": "a", "status": "done"}])
        assert result.needs_plan is True
        assert result.summary == "1/1 items resolved"


class TestArgumentShapes:
    def test_items_arrive_as_a_json_string(self):
        # What an XML-style tool-call parser hands across for a list parameter.
        result = call(server.write_todo, goal="g", items='[{"id": "a", "text": "x"}]')
        assert result.success is True
        assert [i.id for i in result.items] == ["a"]

    def test_a_lone_item_object_is_a_one_element_plan(self):
        result = call(server.write_todo, goal="g", items={"id": "a", "text": "x"})
        assert [i.id for i in result.items] == ["a"]

    def test_marks_arrive_as_a_json_string(self):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        result = call(server.mark_todo, marks='[{"id": "a", "status": "in_progress"}]')
        assert result.items[0].status == "in_progress"


class TestEdit:
    def test_the_goal_survives_an_edit(self):
        call(server.write_todo, goal="keep me", items=[{"id": "a", "text": "x"}])
        result = call(
            server.edit_todo,
            items=[{"id": "a", "text": "x"}, {"id": "b", "text": "y"}],
        )
        assert result.goal == "keep me"
        assert [i.id for i in result.items] == ["a", "b"]

    def test_a_row_left_out_is_removed(self):
        call(
            server.write_todo,
            goal="g",
            items=[{"id": "a", "text": "x"}, {"id": "b", "text": "y"}],
        )
        result = call(server.edit_todo, items=[{"id": "b", "text": "y"}])
        assert [i.id for i in result.items] == ["b"]


class TestRefusalsReachTheModel:
    def test_cancelling_without_a_note_is_refused_through_the_tool(self):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        result = call(server.mark_todo, marks=[{"id": "a", "status": "cancelled"}])
        assert result.success is False
        assert "note" in result.error
        # The plan is returned unchanged, so the model sees what it still has.
        assert result.items[0].status == "pending"
        assert result.version == 1

    def test_cancelling_with_a_note_is_accepted(self):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        result = call(
            server.mark_todo,
            marks=[{"id": "a", "status": "cancelled", "note": "the file is gone"}],
        )
        assert result.success is True
        assert result.items[0].status == "cancelled"

    def test_marking_an_id_that_is_not_in_the_plan_is_refused(self):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        result = call(server.mark_todo, marks=[{"id": "zz", "status": "done"}])
        assert result.success is False
        assert "zz" in result.error

    def test_marking_before_any_plan_exists_is_refused(self):
        result = call(server.mark_todo, marks=[{"id": "a", "status": "done"}])
        assert result.success is False
        assert "write_todo" in result.error

    def test_an_item_with_no_text_is_refused(self):
        result = call(server.write_todo, goal="g", items=[{"id": "a"}])
        assert result.success is False
        assert "text" in result.error


class TestMaterialChange:
    """The nag counter's reset condition, read through what the tools store."""

    def test_a_bare_status_flip_is_not_a_change(self, store):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        before = dict(store[("ann", "s1")])
        call(server.mark_todo, marks=[{"id": "a", "status": "in_progress"}])
        after = store[("ann", "s1")]
        assert chat_todos.is_material_change(before, after) is False

    def test_adding_a_row_is_a_change(self, store):
        call(server.write_todo, goal="g", items=[{"id": "a", "text": "x"}])
        before = dict(store[("ann", "s1")])
        call(
            server.edit_todo,
            items=[{"id": "a", "text": "x"}, {"id": "b", "text": "y"}],
        )
        assert chat_todos.is_material_change(before, store[("ann", "s1")]) is True
