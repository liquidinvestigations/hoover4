"""Shared fixtures of the unit tests."""

import pytest


@pytest.fixture(autouse=True)
def _shard_tables_have_every_column(monkeypatch):
    """The page writer asks Manticore which columns a shard table has. A unit test has no
    Manticore, so every table has every column of the current schema."""
    from database import manticore

    monkeypatch.setattr(manticore, "table_has_column", lambda table, column: True)


@pytest.fixture
def table_generation_commands(monkeypatch):
    """Publish fixture manifests without a live Temporal server."""
    import pyarrow as pa
    from database import clickhouse
    from tasks.P3_parse_files import table_generations

    generation = 0

    def command(value):
        nonlocal generation
        if value.action == "allocate":
            generation += 1
            return generation
        assert value.action == "publish"
        with clickhouse.get_collection_client(value.collectionname) as client:
            clickhouse.insert_arrow_durable(client, "table_documents",
                                            pa.ipc.open_stream(value.manifest).read_all())
        return value.generation

    monkeypatch.setattr(table_generations, "send_command", command)


@pytest.fixture(autouse=True)
def _unit_timing_sink(monkeypatch):
    """Capture unit-test telemetry and flush it without a datastore or background thread."""
    from tasks import task_timing
    recorder = task_timing._Recorder()
    recorder.inserts = []
    recorder.ensure_started = lambda: None
    recorder._insert = lambda collection, table, columns, rows: recorder.inserts.append(
        (collection, table, columns, list(rows)))
    monkeypatch.setattr(task_timing, "_recorder", recorder)
    yield recorder
    recorder.flush()
