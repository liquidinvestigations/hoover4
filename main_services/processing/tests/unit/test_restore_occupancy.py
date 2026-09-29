"""Tests for the collection restore target occupancy check."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
import json

from database import clickhouse
from tasks.P_ops import restore, workflows
from tasks.P_ops.restore import _payload_row_count
from tasks.P_ops.params import OperationParams


class _Result:
    def __init__(self, count):
        self.result_rows = [(count,)]


class _Client:
    def __init__(self, count):
        self.count = count
        self.queries = []

    def query(self, query):
        self.queries.append(query)
        return _Result(self.count)


def test_empty_schema_ledger_and_operation_telemetry_do_not_block_import():
    client = _Client(0)

    assert _payload_row_count(client, "schema_versions") == 0
    assert client.queries == []
    assert _payload_row_count(client, "manticore_shards") == 0
    assert _payload_row_count(client, "processing_task_runs") == 0

    assert client.queries == [
        "SELECT count() FROM `manticore_shards` FINAL WHERE doc_count > 0 OR text_bytes > 0",
    ]


def test_payload_rows_block_import():
    client = _Client(2)

    assert _payload_row_count(client, "text_content") == 2
    assert client.queries == ["SELECT count() FROM `text_content`"]


def test_clickhouse_restore_drops_target_after_begin_import_timing(monkeypatch):
    events = []

    class Phase:
        def __init__(self, *_args):
            return None

        def report(self, *_args, **_kwargs):
            return None

        def finish(self, result):
            return result

    class Client:
        def query(self, query, **_kwargs):
            if query.startswith("RESTORE DATABASE"):
                events.append("restore")
                return _Result(0)
            if "system.backups" in query:
                return type("Result", (), {"result_rows": [("RESTORED", "", 10, 10)]})()
            return _Result(51)

    @contextmanager
    def global_client():
        yield Client()

    monkeypatch.setattr(restore, "read_manifest", lambda _directory: {
        "stores": {"clickhouse": {"artifact": "clickhouse/archive.tar", "total_size": 10}},
    })
    monkeypatch.setattr(restore, "_Phase", Phase)
    monkeypatch.setattr(restore.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(clickhouse, "collection_db_name", lambda _name: "collection_db")
    monkeypatch.setattr(clickhouse, "get_global_client", global_client)
    monkeypatch.setattr(clickhouse, "migrate_collection", lambda _name: events.append("migrate"))
    monkeypatch.setattr(clickhouse, "drop_collection_db", lambda _name: events.append("drop"))

    result = restore.import_clickhouse(
        restore.ImportParams("operation", "collection", "backup", "/backups/backup")
    )

    assert result.detail["schema_version"] == 51
    assert events == ["drop", "restore", "migrate"]


def test_import_publishes_configuration_after_vector_children_close(monkeypatch):
    events = []
    child_started = asyncio.Event()
    release_child = asyncio.Event()

    async def execute_activity(activity, *args, **_options):
        events.append(activity.__name__)
        if activity is workflows.begin_import:
            return "/backups/backup"
        if activity is workflows.publish_imported_collection:
            return 4
        return None

    async def execute_child_workflow(_run, _params, **_options):
        events.append("vector children")
        child_started.set()
        await release_child.wait()
        return 2

    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", execute_child_workflow)

    async def check():
        task = asyncio.create_task(workflows.Operation()._import_collection(
            OperationParams(op_id="operation", kind="import_collection",
                            collectionname="collection", detail={"source": "backup"})))
        await child_started.wait()
        assert not task.done()
        assert "publish_imported_collection" not in events
        release_child.set()
        assert await task == "restored collection from backup (4 configuration row(s), 2 vector plan(s))"

    asyncio.run(check())
    assert events[1] == "hide_import_collection"
    assert events[-1] == "publish_imported_collection"


def test_import_replay_uses_the_existing_finish_activity(monkeypatch):
    events = []

    async def execute_activity(activity, *_args, **_options):
        events.append(activity)
        if activity is workflows.begin_import:
            return "/backups/backup"
        if activity is workflows.finish_import:
            return "existing result"
        return None

    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: False)
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute_activity)
    result = asyncio.run(workflows.Operation()._import_collection(OperationParams(
        op_id="operation", kind="import_collection", collectionname="collection",
        detail={"source": "backup"})))

    assert result == "existing result"
    assert events[-1] is workflows.finish_import
    assert workflows.hide_import_collection not in events


def test_import_hides_existing_registry_row_and_publishes_newer_version(monkeypatch):
    commands = []
    written = []
    prior = datetime(2026, 9, 29, 10, 0, 0)

    class Client:
        def command(self, sql, parameters):
            commands.append((sql, parameters))

        def query(self, _sql, **_kwargs):
            return type("Result", (), {"result_rows": [(1, prior)]})()

        def raw_insert(self, table, insert_block, fmt):
            written.append((table, json.loads(insert_block), fmt))

    @contextmanager
    def global_client():
        yield Client()

    monkeypatch.setattr(clickhouse, "get_global_client", global_client)
    params = restore.ImportParams("operation", "collection", "backup", "/backups/backup")
    restore.hide_import_collection(params)
    result = restore._restore_configuration("collection", {
        "collections": [{"collectionname": "collection", "is_deleted": 0}],
    })

    assert result["collections"] == 1
    assert "is_deleted = 0" in commands[0][0]
    assert commands[0][1] == {"name": "collection"}
    assert written[0][0] == "collections"
    assert datetime.fromisoformat(written[0][1]["updated_at"]) > prior
