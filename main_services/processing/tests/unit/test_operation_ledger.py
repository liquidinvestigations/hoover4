"""Unit tests for the operation Error and plan ledger."""

import pytest

from database.operation_ledger import (
    ERROR_EXCERPT_CHARS,
    event_rows,
    insert_error_events,
    insert_operation_plans,
    pair_key,
)


def test_pair_key_uses_the_unit_separator():
    assert pair_key("hash", "P3_Parse") == "hash\x1fP3_Parse"


def test_event_rows_truncate_error_logs_at_the_limit():
    rows = event_rows(
        "op",
        "dataset",
        [("hash", "P3_Parse")],
        "error",
        {("hash", "P3_Parse"): "x" * (ERROR_EXCERPT_CHARS + 1)},
    )

    assert rows[0]["error_logs"] == "x" * ERROR_EXCERPT_CHARS


def test_event_rows_refuse_an_unknown_event():
    with pytest.raises(ValueError, match="Unknown operation error event"):
        event_rows("op", "dataset", [], "unknown")


def test_empty_inputs_do_not_open_a_collection_client(monkeypatch):
    import database.clickhouse as clickhouse

    def fail_client(*args, **kwargs):
        raise AssertionError("empty ledger input opened a collection client")

    monkeypatch.setattr(clickhouse, "get_collection_client", fail_client)

    assert insert_error_events("testdata", []) == 0
    assert insert_operation_plans("testdata", "op", "dataset", [], "listed") == 0
    assert insert_operation_plans("testdata", "", "dataset", ["plan"], "listed") == 0
