"""The tool boundary: identity, the typed schemas, and refusals reaching the model.

The store's own rules are tested where they live. What can be wrong *here* and nowhere
else is the wrapper: reading the caller out of headers instead of an argument, serving
the schemas the model fills, and returning a refusal the model can read rather than an
exception it cannot. The two rules that must not be relaxed are
asserted through the tools as well -- not to test them twice, but because relaxing them
at this layer is exactly the mistake these tests exist to catch.

Storage is replaced with a dict, so no ClickHouse is needed; the validation that runs is
the real one.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from agent_todo_server import server
from agent_todo_server.identity import CallerUnknown, parse_caller
from database import chat_todos

SECRET = "test-secret"
HEADERS = {
    "Authorization": f"Bearer {SECRET}",
    "X-Hoover4-User": "ann",
    "X-Hoover4-Chat-Session": "s1",
}


def call(tool, **kwargs):
    """Invoke a registered tool's body. FastMCP rebinds the name to a Tool object.

    A refusal is a tool error whose text is the response, so it is read back as one."""
    try:
        return getattr(tool, "fn", tool)(**kwargs)
    except ToolError as exc:
        return server.TodoResponse.model_validate_json(str(exc))


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    """Pin the bearer token the suite authenticates with.

    Without this the suite's result depends on the deployment: the secret is a
    bind-mounted file, so the same tests pass in a bare image (no file, no check) and
    fail inside the composed container (file mounted, every call unauthenticated). A
    test that answers differently in the two places is not testing the server.
    """
    monkeypatch.setenv("MCP_SHARED_SECRET", SECRET)
    monkeypatch.delenv("MCP_SHARED_SECRET_FILE", raising=False)


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
        caller = parse_caller(
            {
                "authorization": f"Bearer {SECRET}",
                "x-hoover4-user": "bob",
                "x-hoover4-chat-session": "s2",
            }
        )
        assert (caller.username, caller.session_id) == ("bob", "s2")

    def test_a_call_naming_no_conversation_is_refused(self):
        with pytest.raises(CallerUnknown):
            parse_caller({"Authorization": f"Bearer {SECRET}", "X-Hoover4-User": "ann"})

    def test_a_wrong_bearer_token_is_refused(self):
        with pytest.raises(CallerUnknown):
            parse_caller({**HEADERS, "Authorization": "Bearer wrong"})

    def test_no_bearer_token_at_all_is_refused(self):
        with pytest.raises(CallerUnknown):
            parse_caller({k: v for k, v in HEADERS.items() if k != "Authorization"})

    def test_with_no_secret_configured_the_check_is_skipped(self, monkeypatch):
        # A prototype on a loopback-bound port runs open rather than refusing to start,
        # and identity.py logs a warning saying so.
        monkeypatch.delenv("MCP_SHARED_SECRET")
        assert parse_caller({"X-Hoover4-Chat-Session": "s1"}).username == "unknown"

    def test_the_tools_refuse_it_in_words(self, monkeypatch):
        authenticated_but_sessionless = {"Authorization": f"Bearer {SECRET}"}
        monkeypatch.setattr(
            server, "get_http_headers", lambda: authenticated_but_sessionless
        )
        result = call(server.read_todo)
        assert result.success is False
        assert "chat-session" in result.error
        assert result.items == []

    def test_an_unauthenticated_call_is_answered_with_no_ones_plan(self, monkeypatch):
        monkeypatch.setattr(server, "get_http_headers", lambda: {})
        result = call(server.read_todo)
        assert result.success is False
        assert "bearer" in result.error
        assert result.items == []


class TestWriteAndRead:
    def test_an_empty_list_asks_for_a_plan(self):
        result = call(server.read_todo)
        assert result.success is True
        assert result.needs_plan is True
        assert result.version == 0

    def test_the_store_numbers_the_steps(self):
        result = call(server.write_todo, goal="Find X", steps=["a", "b"])
        assert result.success is True
        assert [(i.id, i.text, i.status) for i in result.items] == [
            ("1", "a", "pending"), ("2", "b", "pending")]
        read = call(server.read_todo)
        assert read.goal == "Find X"
        assert read.needs_plan is False
        assert read.version == 1

    def test_the_same_write_twice_gives_the_same_items_one_version_higher(self):
        first = call(server.write_todo, goal="Find X", steps=["a", "b"])
        second = call(server.write_todo, goal="Find X", steps=["a", "b"])
        assert second.items == first.items
        assert second.version == first.version + 1

    def test_an_empty_goal_is_refused(self):
        result = call(server.write_todo, goal="  ", steps=["a"])
        assert result.success is False
        assert result.error == "the goal is empty. Write one or two sentences."
        assert result.version == 0

    def test_an_empty_step_list_is_refused(self):
        for steps in ([], ["", "  "]):
            result = call(server.write_todo, goal="g", steps=steps)
            assert result.success is False
            assert result.error == "steps is empty. Give at least one step."

    def test_a_fully_resolved_plan_asks_for_a_new_one(self):
        call(server.write_todo, goal="g", steps=["x"])
        result = call(server.mark_todo, ids=["1"], status="done")
        assert result.needs_plan is True
        assert result.summary == "1/1 items resolved"


class TestEdit:
    def test_a_kept_step_keeps_its_id_and_status_and_a_new_step_gets_the_next_id(self):
        call(server.write_todo, goal="keep me", steps=["a", "b"])
        call(server.mark_todo, ids=["1"], status="done")
        result = call(server.edit_todo, steps=["a", "c"])
        assert result.goal == "keep me"
        assert [(i.id, i.text, i.status) for i in result.items] == [
            ("1", "a", "done"), ("3", "c", "pending")]

    def test_whitespace_does_not_change_which_step_is_kept(self):
        call(server.write_todo, goal="g", steps=["read  the file"])
        call(server.mark_todo, ids=["1"], status="in_progress")
        result = call(server.edit_todo, steps=[" read the file "])
        assert [(i.id, i.status) for i in result.items] == [("1", "in_progress")]

    def test_an_empty_step_list_is_refused(self):
        call(server.write_todo, goal="g", steps=["a"])
        result = call(server.edit_todo, steps=[])
        assert result.success is False
        assert result.items[0].text == "a"


class TestRefusalsReachTheModel:
    def test_cancelling_without_a_note_is_refused_through_the_tool(self):
        call(server.write_todo, goal="g", steps=["x"])
        result = call(server.mark_todo, ids=["1"], status="cancelled")
        assert result.success is False
        assert "note" in result.error
        # The plan is returned unchanged, so the model sees what it still has.
        assert result.items[0].status == "pending"
        assert result.version == 1

    def test_cancelling_with_a_note_is_accepted(self):
        call(server.write_todo, goal="g", steps=["x"])
        result = call(server.mark_todo, ids=["1"], status="cancelled", note="the file is gone")
        assert result.success is True
        assert (result.items[0].status, result.items[0].note) == ("cancelled", "the file is gone")

    def test_several_steps_are_marked_in_one_call(self):
        call(server.write_todo, goal="g", steps=["x", "y", "z"])
        result = call(server.mark_todo, ids=["1", "3"], status="done")
        assert [i.status for i in result.items] == ["done", "pending", "done"]

    def test_marking_an_id_that_is_not_in_the_plan_names_the_real_ids(self):
        call(server.write_todo, goal="g", steps=["x", "y"])
        result = call(server.mark_todo, ids=["9"], status="done")
        assert result.success is False
        assert result.error == "step '9' does not exist. The steps are 1, 2."

    def test_a_refusal_is_a_tool_error(self):
        with pytest.raises(ToolError) as refused:
            getattr(server.write_todo, "fn", server.write_todo)(goal="  ", steps=["a"])
        assert server.TodoResponse.model_validate_json(str(refused.value)).success is False

    def test_editing_before_any_plan_exists_names_write_todo(self):
        result = call(server.edit_todo, steps=["a"])
        assert result.success is False
        assert result.error == "No plan exists yet. Call write_todo first."

    def test_marking_before_any_plan_exists_is_refused(self):
        result = call(server.mark_todo, ids=["1"], status="done")
        assert result.success is False
        assert "write_todo" in result.error


class TestMaterialChange:
    """The nag counter's reset condition, read through what the tools store."""

    def test_a_bare_status_flip_is_not_a_change(self, store):
        call(server.write_todo, goal="g", steps=["x"])
        before = dict(store[("ann", "s1")])
        call(server.mark_todo, ids=["1"], status="in_progress")
        after = store[("ann", "s1")]
        assert chat_todos.is_material_change(before, after) is False

    def test_adding_a_step_is_a_change(self, store):
        call(server.write_todo, goal="g", steps=["x"])
        before = dict(store[("ann", "s1")])
        call(server.edit_todo, steps=["x", "y"])
        assert chat_todos.is_material_change(before, store[("ann", "s1")]) is True


#: The schemas of the todo tools. No schema holds a JSON object. FastMCP leaves the
#: pydantic `title` of each property out of the schema it serves.
EXPECTED_SCHEMAS = {
    "write_todo": {"type": "object", "required": ["goal", "steps"], "properties": {
        "goal": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}}}},
    "edit_todo": {"type": "object", "required": ["steps"], "properties": {
        "steps": {"type": "array", "items": {"type": "string"}}}},
    "mark_todo": {"type": "object", "required": ["ids", "status"], "properties": {
        "ids": {"type": "array", "items": {"type": "string"}},
        "status": {"type": "string", "enum": ["pending", "in_progress", "done", "cancelled"]},
        "note": {"type": "string", "default": ""}}},
}


def served_schemas() -> dict:
    import asyncio

    from agent_todo_server import plan_tools  # noqa: F401  registers the plan tools

    tools = asyncio.run(server.mcp.get_tools())
    return {name: tool.parameters for name, tool in tools.items()}


@pytest.mark.parametrize("name", sorted(EXPECTED_SCHEMAS))
def test_the_served_schema_of_a_todo_tool_is_the_designed_one(name):
    got = served_schemas()[name]
    want = EXPECTED_SCHEMAS[name]
    assert got["type"] == "object"
    assert sorted(got.get("required", [])) == sorted(want["required"])
    assert got["properties"] == want["properties"]


def test_the_plan_tool_positions_are_whole_numbers_from_0():
    schemas = served_schemas()
    assert schemas["move_node"]["properties"]["position"] == {
        "type": "integer", "minimum": 0, "default": 0}
    assert schemas["read_plan_document"]["properties"]["offset"] == {
        "type": "integer", "minimum": 0, "default": 0}


def test_no_todo_tool_text_holds_a_json_example():
    tools = __import__("asyncio").run(server.mcp.get_tools())
    for name in ("write_todo", "edit_todo", "mark_todo"):
        assert "{" not in tools[name].description, name
        assert "[" not in tools[name].description, name
