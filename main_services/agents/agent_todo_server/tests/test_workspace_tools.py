"""The workspace tools at the tool boundary: identity, the writer hand-off, and refusals.

The write and patch rules are tested in the pipeline, where they live. Here storage is a
dict and the Temporal client is a stub, so the tests check what this module adds: the caller
comes from the headers, the operation id comes from the idempotency header, a stored receipt
is returned without a second command, and every failure is a tool error with a JSON body.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp.exceptions import ToolError

from agent_todo_server import workspace
from database import chat_workspace as store

SECRET = "test-secret"
HEADERS = {
    "authorization": f"Bearer {SECRET}",
    "x-hoover4-user": "ann",
    "x-hoover4-chat-session": "s1",
    "x-hoover4-idempotency-key": "op-1",
    "x-hoover4-agent-run": "run-1",
}


class FakeServer:
    """Collects the tool bodies that `register` defines."""

    def __init__(self):
        self.tools = {}

    def tool(self, name, description):
        def add(fn):
            self.tools[name] = fn
            return fn
        return add


class FakeClient:
    def __init__(self, receipts, outcome=None, error=None):
        self.receipts, self.outcome, self.error = receipts, outcome, error
        self.starts = []

    async def start_workflow(self, workflow, start, **kwargs):
        self.starts.append((workflow, start, kwargs))
        if self.error:
            raise self.error
        command = kwargs["start_signal_args"][0]
        if self.outcome is not None:
            key = (command["username"], command["session_id"], command["operation_id"])
            self.receipts[key] = self.outcome(command)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("MCP_SHARED_SECRET", SECRET)
    monkeypatch.delenv("MCP_SHARED_SECRET_FILE", raising=False)
    monkeypatch.setattr(workspace, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(workspace, "WRITER_WAIT_SECONDS", 0.05)


@pytest.fixture
def headers(monkeypatch):
    current = dict(HEADERS)
    monkeypatch.setattr(workspace, "get_http_headers", lambda: current)
    return current


@pytest.fixture
def receipts(monkeypatch):
    rows: dict = {}
    monkeypatch.setattr(store, "read_receipt", lambda u, s, o: rows.get((u, s, o)))
    return rows


@pytest.fixture
def tools():
    server = FakeServer()
    workspace.register(server)
    return server.tools


def use_client(monkeypatch, client):
    async def connect():
        return client
    monkeypatch.setattr(workspace, "temporal_client", connect)


def refusal(fn, *args, **kwargs):
    with pytest.raises(ToolError) as caught:
        result = fn(*args, **kwargs)
        if asyncio.iscoroutine(result):
            asyncio.run(result)
    return json.loads(str(caught.value))


def test_a_write_signals_the_session_writer_with_the_idempotency_key(monkeypatch, headers, receipts, tools):
    def outcome(command):
        return store.Receipt(command["operation_id"], command["name"], 1, True,
                             {"success": True, "name": command["name"], "version": 1})
    client = FakeClient(receipts, outcome)
    use_client(monkeypatch, client)

    result = json.loads(asyncio.run(tools["workspace_write"]("report.md", "Text.")))

    assert result == {"success": True, "name": "report.md", "version": 1}
    [(workflow, start, kwargs)] = client.starts
    assert workflow == "WorkspaceWriter"
    assert kwargs["id"] == "workspace-s1" and kwargs["task_queue"] == "chat-queue"
    assert kwargs["start_signal"] == "submit"
    command = kwargs["start_signal_args"][0]
    assert command["operation_id"] == "op-1" and command["run_id"] == "run-1"
    assert command["username"] == "ann" and command["session_id"] == "s1"
    assert command["op"] == "write" and command["content"] == "Text."
    assert start == {"username": "ann", "session_id": "s1", "pending": []}


def test_a_stored_receipt_answers_a_repeated_call_without_a_command(monkeypatch, headers, receipts, tools):
    receipts[("ann", "s1", "op-1")] = store.Receipt("op-1", "report.md", 2, True,
                                                    {"success": True, "version": 2})
    client = FakeClient(receipts)
    use_client(monkeypatch, client)

    result = json.loads(asyncio.run(tools["workspace_patch"]("report.md", "a", "b")))

    assert result["version"] == 2
    assert client.starts == []


def test_a_failed_receipt_is_a_tool_error_with_its_result(monkeypatch, headers, receipts, tools):
    body = {"success": False, "error": "stale", "current_version": 3}
    client = FakeClient(receipts, lambda c: store.Receipt(c["operation_id"], c["name"], 3, False, body))
    use_client(monkeypatch, client)

    assert refusal(tools["workspace_write"], "report.md", "Text.", 1) == body


def test_an_unreachable_writer_is_a_retryable_failure(monkeypatch, headers, receipts, tools):
    use_client(monkeypatch, FakeClient(receipts, error=RuntimeError("down")))

    body = refusal(tools["workspace_write"], "report.md", "Text.")

    assert body["success"] is False and body["retryable"] is True


def test_a_writer_without_a_receipt_in_time_is_a_retryable_failure(monkeypatch, headers, receipts, tools):
    use_client(monkeypatch, FakeClient(receipts))

    body = refusal(tools["workspace_write"], "report.md", "Text.")

    assert body["retryable"] is True and "no result" in body["error"]


def test_a_call_without_the_session_header_is_refused(monkeypatch, headers, receipts, tools):
    del headers["x-hoover4-chat-session"]

    assert refusal(tools["workspace_read"])["success"] is False


def test_a_read_lists_the_files_or_renders_one_with_the_gutter(monkeypatch, headers, tools):
    version = store.FileVersion("ann", "s1", "report.md", 2, content="One.\nTwo.")
    monkeypatch.setattr(store, "list_files", lambda u, s: [
        {"name": "report.md", "version": 2, "chars": 9, "updated": "t"}])
    monkeypatch.setattr(store, "read_version", lambda u, s, n, v=None: version if n == "report.md" else None)

    listed = json.loads(tools["workspace_read"]())
    read = json.loads(tools["workspace_read"]("report.md"))
    missing = refusal(tools["workspace_read"], "notes.md")

    assert listed == {"files": [{"name": "report.md", "version": 2, "chars": 9}]}
    assert read["content"] == "1|One.\n2|Two." and read["version"] == 2
    assert "report.md" in missing["error"]
