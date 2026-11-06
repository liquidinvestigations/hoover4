"""Verify historical workspace recovery and durable board language with real ClickHouse."""

import json
import uuid
from types import SimpleNamespace

import pytest

from database import agent_runs, chat_workspace, clickhouse
from tasks.P_board import activities as board

pytestmark = pytest.mark.integration


@pytest.fixture
def global_store(monkeypatch):
    name = "agent_recovery_a" + uuid.uuid4().hex[:12]
    clickhouse._cluster().migrate(
        clickhouse.collection_db_name(name), clickhouse.GLOBAL_MIGRATIONS_PATH,
        cluster_name=None, create_db_if_no_exists=True, multi_statement=True)
    monkeypatch.setattr(clickhouse, "get_global_client", lambda: clickhouse.get_collection_client(name))
    try:
        yield name
    finally:
        client = clickhouse._client("default")
        client.command(f"DROP DATABASE {clickhouse.collection_db_name(name)}")
        client.close()


def test_workspace_historical_operation_is_scoped_and_restores_original_receipt(global_store):
    from tasks.P_workspace import workflows as writer
    from tasks.P_workspace.mutations import Command
    for owner, session, number, operation, text in [
            ("owner", "session", 1, "original", "Original."),
            ("owner", "session", 2, "later", "Later."),
            ("other", "session", 1, "original", "Other owner."),
            ("owner", "other", 1, "original", "Other session.")]:
        chat_workspace.write_version(chat_workspace.FileVersion(
            owner, session, "report.md", number, operation_id=operation, content=text))
    assert chat_workspace.read_version("owner", "session", "report.md").version == 2
    found = chat_workspace.read_operation_version("owner", "session", "original")
    assert found.version == 1 and found.content == "Original."
    cmd = Command("owner", "session", "original", "run", "write", "report.md", content="Original.")
    prepared = writer.prepare_workspace_mutation(cmd)
    writer.commit_workspace_mutation(writer.CommitInput(cmd, prepared))
    assert prepared.found_version == 1 and prepared.version is None
    assert chat_workspace.read_receipt("owner", "session", "original").version == 1
    assert chat_workspace.read_version("owner", "session", "report.md").version == 2
    assert writer.prepare_workspace_mutation(cmd).replay
    assert chat_workspace.read_operation_version("missing", "session", "original") is None


@pytest.mark.parametrize("legacy", [False, True])
def test_board_opening_reuses_stored_or_pinned_language(global_store, monkeypatch, legacy):
    owner = SimpleNamespace(owner="owner", language="en")
    turn = str(uuid.uuid4())
    usage = {"task": {"objective": {"text": "Task"}}}
    if not legacy:
        usage["language"] = "de"
    board._write_turn_rows("owner", "session", 1, "Task", turn, json.dumps(usage))
    monkeypatch.setattr(board, "explore_language", lambda *_: pytest.fail("Settings changed after opening"))
    if legacy:
        monkeypatch.setattr(agent_runs, "read_run", lambda u, s, r: SimpleNamespace(thread_id="thread"))
        monkeypatch.setattr(agent_runs, "read_messages", lambda u, s, t: [
            SimpleNamespace(usage={"control": {"assets": {"language": "de"}}})])
    assert board._opening_language(owner, "session", 1, turn) == "de"
    assert board._opening_language(owner, "session", 1, turn) == "de"
    with pytest.raises(RuntimeError, match="unavailable"):
        board._opening_language(SimpleNamespace(owner="other"), "session", 1, turn)
    with pytest.raises(RuntimeError, match="unavailable"):
        board._opening_language(owner, "other", 1, turn)
    with pytest.raises(RuntimeError, match="unavailable"):
        board._opening_language(owner, "session", 1, str(uuid.uuid4()))


def test_legacy_opening_persists_fallback_before_lost_write_response(global_store, monkeypatch):
    owner = SimpleNamespace(owner="owner", language="en")
    turn = str(uuid.uuid4())
    board._write_turn_rows("owner", "session", 1, "Task", turn, '{"task":{"objective":"Task"}}')
    monkeypatch.setattr(board, "explore_language", lambda *_: "fr")
    original = clickhouse.insert_durable
    def lose_response(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("The durable write response was lost")
    monkeypatch.setattr(clickhouse, "insert_durable", lose_response)
    with pytest.raises(OSError):
        board._opening_language(owner, "session", 1, turn)
    monkeypatch.setattr(clickhouse, "insert_durable", original)
    monkeypatch.setattr(board, "explore_language", lambda *_: "de")
    assert board._opening_language(owner, "session", 1, turn) == "fr"


def test_structured_output_classification_recovers_from_durable_control(global_store, monkeypatch):
    from tasks.P_agent.control import coordinator, output_requirements, task_state
    owner, session, run, thread = "owner", "chat", str(uuid.uuid4()), str(uuid.uuid4())
    state = task_state.derive("Écris trois rapports.", 1)
    recognized = output_requirements.validate(json.dumps({"schema_version": 1, "state": "known", "complete": True,
        "interpretation": "new", "groups": [{"noun": "report", "count": 3, "names": [], "message": 1, "words": "Écris trois rapports."}]}), state)
    message = agent_runs.RunMessageRow(0, "human", "Écris trois rapports.", usage_json=json.dumps({"control": {"task_state": state}}), run_id=run)
    agent_runs.write_message(owner, session, thread, run, message)
    row = SimpleNamespace(username=owner, session_id=session, thread_id=thread, run_id=run)
    decision = {"facts": {"preparation": {"output_requirements": recognized}}}
    original_write = coordinator.write_control
    def lose_response(*args):
        original_write(*args)
        raise OSError("The durable classification write response was lost")
    monkeypatch.setattr(coordinator, "write_control", lose_response)
    with pytest.raises(OSError):
        coordinator.settle_output_requirements(row, [message], decision)
    monkeypatch.setattr(coordinator, "write_control", original_write)
    recovered = agent_runs.read_messages(owner, session, thread)
    coordinator.settle_output_requirements(row, recovered, decision)
    stored = agent_runs.read_messages(owner, session, thread)[0].usage["control"]
    assert stored["output_requirements_applied"]
    assert task_state.delivery(stored["task_state"], ["one.md"])["state"] == "incomplete"
    assert task_state.delivery(stored["task_state"], ["one.md", "two.md", "three.md"])["evidence"]
