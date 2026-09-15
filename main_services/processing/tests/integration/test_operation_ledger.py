"""Integration tests for the operation Error and plan ledger."""

import pytest

from database.clickhouse import drop_collection_db, migrate_collection
from database.operation_ledger import (
    event_rows,
    insert_error_events,
    insert_operation_plans,
    pairs_with_event,
    run_plan_counts,
)

pytestmark = pytest.mark.integration


def test_operation_ledger_round_trip():
    collectionname = "ledgercheck"
    drop_collection_db(collectionname)
    try:
        migrate_collection(collectionname)
        rows = event_rows(
            "op", "dataset", [("hash", "P3_Parse")], "error", {("hash", "P3_Parse"): "log"}
        )
        assert insert_error_events(collectionname, rows + rows) == 2
        assert pairs_with_event(collectionname, "op", "dataset", "error") == [
            ("hash", "P3_Parse")
        ]
        assert insert_operation_plans(
            collectionname, "op", "dataset", ["plan"], "listed"
        ) == 1
        assert run_plan_counts(collectionname, "op", "dataset") == (0, 1)
    finally:
        drop_collection_db(collectionname)
