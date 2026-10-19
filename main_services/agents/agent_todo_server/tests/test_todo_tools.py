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
from types import SimpleNamespace
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


def step(text, status="pending", note=""):
    return server.PlanStep(text=text, status=status, note=note)


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
        result = call(server.update_plan, goal="g", steps=[step("a")])
        assert result.success is False
        assert "chat-session" in result.error
        assert result.items == []

    def test_an_unauthenticated_call_is_answered_with_no_ones_plan(self, monkeypatch):
        monkeypatch.setattr(server, "get_http_headers", lambda: {})
        result = call(server.update_plan, goal="g", steps=[step("a")])
        assert result.success is False
        assert "bearer" in result.error
        assert result.items == []


class TestUpdatePlan:
    def test_every_result_shows_the_whole_plan(self):
        written = call(server.update_plan, goal="Find X", steps=[step("a"), step("b")])
        assert written.model_dump() == {
            "goal": "Find X", "version": 1, "summary": "0/2 items resolved",
            "items": [{"id": "1", "text": "a", "status": "pending"},
                      {"id": "2", "text": "b", "status": "pending"}]}
        again = call(server.update_plan, goal="Find X", steps=[step("a"), step("b")])
        assert again.model_dump()["unchanged"] is True and again.model_dump()["items"] == written.model_dump()["items"]

    def test_a_step_keeps_its_id_and_a_done_step_keeps_its_note(self):
        call(server.update_plan, goal="g", steps=[step("a"), step("b")])
        result = call(server.update_plan, goal="g", steps=[step("b", "done", "found"), step("c")])
        assert [(i.id, i.text, i.status, i.note) for i in result.items] == [
            ("2", "b", "done", "found"), ("3", "c", "pending", "")]
        assert result.summary == "1/2 items resolved"

    def test_a_done_step_without_a_note_is_accepted_with_the_default_note(self):
        result = call(server.update_plan, goal="g", steps=[step("a", "done")])
        assert (result.success, result.items[0].note) == (True, chat_todos.DONE_NOTE)

    def test_a_new_goal_starts_a_new_plan(self):
        call(server.update_plan, goal="g", steps=[step("a"), step("b")])
        result = call(server.update_plan, goal="other", steps=[step("c")])
        assert (result.goal, [(i.id, i.text) for i in result.items]) == ("other", [("1", "c")])

    def test_legacy_statuses_read_as_pending_and_done(self, store):
        store[("ann", "s1")] = {"session_id": "s1", "username": "ann", "version": 3, "goal": "g",
                               "items": [{"id": "1", "text": "a", "status": "in_progress", "note": ""},
                                         {"id": "2", "text": "b", "status": "cancelled", "note": "gone"}],
                               "updated_at": None}
        result = call(server.update_plan, goal="g", steps=[step("a"), step("b", "done", "gone")])
        assert result.model_dump()["items"] == [{"id": "1", "text": "a", "status": "pending"},
                                                {"id": "2", "text": "b", "status": "done", "note": "gone"}]


class TestRefusalsReachTheModel:
    def test_an_empty_goal_is_refused_with_the_unchanged_plan(self):
        call(server.update_plan, goal="g", steps=[step("x")])
        result = call(server.update_plan, goal="  ", steps=[step("y")])
        assert result.success is False
        assert result.error == "the goal is empty. Write one or two sentences."
        assert (result.version, [i.text for i in result.items]) == (1, ["x"])

    def test_an_empty_step_list_is_refused(self):
        result = call(server.update_plan, goal="g", steps=[])
        assert result.success is False
        assert result.error == "steps is empty. Give at least one step."

    def test_a_refusal_is_a_tool_error_and_writes_nothing(self, store):
        with pytest.raises(ToolError) as refused:
            getattr(server.update_plan, "fn", server.update_plan)(goal="  ", steps=[step("a")])
        assert server.TodoResponse.model_validate_json(str(refused.value)).success is False
        assert store == {}


class TestMaterialChange:
    """The nag counter's reset condition, read through what the tool stores."""

    def test_adding_a_step_is_a_change(self, store):
        call(server.update_plan, goal="g", steps=[step("x")])
        before = dict(store[("ann", "s1")])
        call(server.update_plan, goal="g", steps=[step("x"), step("y")])
        assert chat_todos.is_material_change(before, store[("ann", "s1")]) is True


#: The schema of the plan tool. FastMCP leaves the pydantic `title` of each property out of
#: the schema it serves.
EXPECTED_PROPERTIES = {
    "goal": {"type": "string"},
    "steps": {"type": "array", "items": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string"},
        "status": {"type": "string", "enum": ["pending", "done"], "default": "pending"},
        "note": {"type": "string", "default": ""}}}},
}


def _without_descriptions(schema):
    """`schema` with every description removed, after checking that each property has one."""
    if isinstance(schema, dict):
        for name, value in (schema.get("properties") or {}).items():
            assert value.get("description"), name
        return {key: _without_descriptions(value) for key, value in schema.items() if key != "description"}
    return schema


def served_schemas() -> dict:
    import asyncio

    tools = asyncio.run(server.mcp.get_tools())
    return {name: tool.parameters for name, tool in tools.items()}


def test_the_served_schema_of_the_plan_tool_is_the_designed_one():
    got = served_schemas()["update_plan"]
    assert got["type"] == "object"
    assert sorted(got.get("required", [])) == ["goal", "steps"]
    assert _without_descriptions(got)["properties"] == EXPECTED_PROPERTIES


def test_the_plan_tool_text_holds_no_json_example_and_says_it_writes_no_file():
    tools = __import__("asyncio").run(server.mcp.get_tools())
    text = tools["update_plan"].description
    assert "{" not in text and "[" not in text
    assert "It writes no file and no answer." in text
