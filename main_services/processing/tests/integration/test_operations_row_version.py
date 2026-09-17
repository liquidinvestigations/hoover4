"""Verify the operation table replacement in an isolated ClickHouse database."""

from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager

import pytest

from database.clickhouse import GLOBAL_MIGRATIONS_PATH, _client, _cluster, get_global_client
from database import clickhouse, operations

pytestmark = pytest.mark.integration


def test_fresh_global_migrations_create_versioned_operations():
    database = f"w22_global_{uuid4().hex[:12]}"
    try:
        _cluster().migrate(
            database, GLOBAL_MIGRATIONS_PATH, cluster_name=None,
            create_db_if_no_exists=True, multi_statement=True,
        )
        client = _client(database)
        try:
            engine = client.query(
                "SELECT engine_full FROM system.tables WHERE database = currentDatabase() "
                "AND name = 'operations'"
            ).result_rows[0][0]
            assert "ReplacingMergeTree(row_version)" in engine
            assert client.query("SELECT count() FROM schema_versions").result_rows[0][0] == 30
        finally:
            client.close()
    finally:
        with get_global_client() as admin:
            admin.command(f"DROP DATABASE IF EXISTS {database} SYNC")


def test_fresh_operation_migration_and_late_progress_insert(monkeypatch):
    database = f"w22_operations_{uuid4().hex[:12]}"
    with get_global_client() as admin:
        admin.command(f"CREATE DATABASE {database}")
    client = _client(database)
    try:
        root = Path(GLOBAL_MIGRATIONS_PATH)
        client.command((root / "00025_operations.sql").read_text().rstrip().rstrip(";"))
        client.command(
            "INSERT INTO operations (op_id, kind, target_kind, collectionname, "
            "collection_dataset, state, started_at, updated_at, progress_done, "
            "progress_total, eta_seconds, user_id) VALUES "
            "('op', 'execute_plans', 'dataset', 'c', 'd', 'running', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00', 0, 2, 0, 'test')"
        )
        migration = (root / "00030_operations_row_version.sql").read_text()
        for statement in migration.split(";"):
            if statement.strip():
                client.command(statement)
        engine = client.query(
            "SELECT engine_full FROM system.tables WHERE database = currentDatabase() "
            "AND name = 'operations'"
        ).result_rows[0][0]
        assert "ReplacingMergeTree(row_version)" in engine
        copied = client.query(
            "SELECT state, progress_total, row_version FROM operations FINAL"
        ).result_rows[0]
        assert copied[0:2] == ("running", 2)
        assert copied[2] > 0
        columns = ", ".join(operations.COLUMNS)
        running = dict(zip(
            operations.COLUMNS,
            client.query(f"SELECT {columns} FROM operations FINAL").result_rows[0],
        ))

        client.command(
            "INSERT INTO operations (op_id, kind, target_kind, collectionname, "
            "collection_dataset, state, started_at, updated_at, progress_done, "
            "progress_total, eta_seconds, detail, user_id, row_version) VALUES "
            "('op', 'execute_plans', 'dataset', 'c', 'd', 'cancelled', "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:01', 0, 2, 0, "
            "'{\"failed_tasks\":2}', 'test', 9223372036854775809)"
        )

        @contextmanager
        def isolated_global_client():
            yield client

        monkeypatch.setattr(clickhouse, "get_global_client", isolated_global_client)
        operations.update_operation(
            "op", base_row=running, progress_done=1, detail='{"failed_tasks":0}'
        )
        assert client.query(
            "SELECT state, detail FROM operations FINAL WHERE op_id = 'op'"
        ).result_rows == [("cancelled", '{"failed_tasks":2}')]
    finally:
        client.close()
        with get_global_client() as admin:
            admin.command(f"DROP DATABASE {database} SYNC")
