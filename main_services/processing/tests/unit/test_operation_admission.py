"""Unit tests for the operation caps and for admission."""

import logging
from datetime import datetime

import pytest

from database import operations
from database.operations import (
    DEFAULT_OPERATION_CAP, KINDS, admission_decision, operation_caps,
)
from tasks.P_ops.activities import admit_operation, real_start


@pytest.mark.parametrize("running, ahead, cap, expected", [
    (0, 0, 2, "running"),
    (1, 0, 2, "running"),
    (2, 0, 2, "queued"),
    (1, 1, 2, "queued"),
    (0, 2, 2, "queued"),
    (0, 0, 1, "running"),
])
def test_admission_decision(running, ahead, cap, expected):
    assert admission_decision(running, ahead, cap) == expected


def test_caps_default_to_two_for_every_kind(monkeypatch):
    monkeypatch.delenv("HOOVER4_OPERATION_CAPS", raising=False)
    caps = operation_caps()
    assert set(caps) == set(KINDS)
    assert len(caps) == 16
    assert set(caps.values()) == {DEFAULT_OPERATION_CAP} == {2}


def test_a_named_cap_changes_only_its_kind(monkeypatch):
    monkeypatch.setenv("HOOVER4_OPERATION_CAPS", "add_dataset=1")
    caps = operation_caps()
    assert caps["add_dataset"] == 1
    assert all(value == 2 for kind, value in caps.items() if kind != "add_dataset")


@pytest.mark.parametrize("raw", ["bogus=3", "add_dataset=0", "add_dataset=x", "add_dataset"])
def test_a_bad_pair_warns_and_is_ignored(monkeypatch, caplog, raw):
    monkeypatch.setenv("HOOVER4_OPERATION_CAPS", raw)
    with caplog.at_level(logging.WARNING, logger="database.operations"):
        caps = operation_caps()
    assert set(caps.values()) == {2}
    assert any("HOOVER4_OPERATION_CAPS" in record.message for record in caplog.records)


def test_the_rendered_variable_parses_to_every_kind(monkeypatch):
    rendered = ",".join(f"{kind}=3" for kind in KINDS)
    monkeypatch.setenv("HOOVER4_OPERATION_CAPS", rendered)
    assert set(operation_caps().values()) == {3}


def _row(state: str) -> dict:
    return {
        "op_id": "op", "kind": "add_dataset", "state": state,
        "started_at": datetime(2026, 1, 1),
        "run_started_at": datetime(1970, 1, 1),
    }


@pytest.fixture
def fake_store(monkeypatch):
    """Fake the row read, the admission count and the row write."""
    store = {"row": None, "counts": (0, 0), "writes": []}
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: store["row"])
    monkeypatch.setattr(operations, "count_admission", lambda _row: store["counts"])
    monkeypatch.setattr(
        operations, "update_operation",
        lambda op_id, base_row=None, **changes: store["writes"].append(changes),
    )
    monkeypatch.setenv("HOOVER4_OPERATION_CAPS", "add_dataset=2")
    return store


def test_admission_retry_of_a_running_row_writes_nothing(fake_store):
    fake_store["row"] = _row("running")
    assert admit_operation("op") == "running"
    assert fake_store["writes"] == []


@pytest.mark.parametrize("state", ["cancelled", "errored", "finished"])
def test_admission_of_a_closed_row_returns_its_state(fake_store, state):
    fake_store["row"] = _row(state)
    assert admit_operation("op") == state
    assert fake_store["writes"] == []


def test_admission_with_a_free_slot_writes_running_and_the_real_start(fake_store):
    fake_store["row"] = _row("pending")
    fake_store["counts"] = (1, 0)
    assert admit_operation("op") == "running"
    [write] = fake_store["writes"]
    assert write["state"] == "running"
    assert write["run_started_at"].year > 1970


def test_admission_over_the_cap_writes_queued_once(fake_store):
    fake_store["row"] = _row("pending")
    fake_store["counts"] = (2, 0)
    assert admit_operation("op") == "queued"
    assert fake_store["writes"] == [{"state": "queued"}]

    fake_store["row"] = _row("queued")
    fake_store["writes"].clear()
    assert admit_operation("op") == "queued"
    assert fake_store["writes"] == []


def test_admission_waits_behind_an_older_row(fake_store):
    fake_store["row"] = _row("queued")
    fake_store["counts"] = (1, 1)
    assert admit_operation("op") == "queued"


def test_admission_of_a_missing_row_does_not_retry(fake_store):
    from temporalio.exceptions import ApplicationError

    with pytest.raises(ApplicationError) as raised:
        admit_operation("op")
    assert raised.value.non_retryable


def test_the_estimate_counts_from_the_real_start():
    row = _row("running")
    assert real_start(row) == row["started_at"]
    row["run_started_at"] = datetime(2026, 1, 2)
    assert real_start(row) == datetime(2026, 1, 2)


def test_the_admission_query_counts_only_live_rows(monkeypatch):
    captured = {}

    class _Result:
        column_names = ("running", "ahead")
        result_rows = [(0, 0)]

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def query(self, sql, parameters):
            captured["sql"] = sql
            captured["parameters"] = parameters
            return _Result()

    import database.clickhouse as clickhouse

    monkeypatch.setattr(clickhouse, "get_global_client", lambda: _Client())
    assert operations.count_admission(_row("pending")) == (0, 0)
    assert "state IN ('pending', 'queued', 'running')" in captured["sql"]
    assert "(started_at, op_id) < ({started_at:DateTime}, {op_id:String})" in captured["sql"]
    assert captured["parameters"]["kind"] == "add_dataset"
