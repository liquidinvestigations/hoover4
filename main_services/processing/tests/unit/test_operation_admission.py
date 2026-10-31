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
    assert len(caps) == 20
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


def _row(state: str, kind: str = "add_dataset") -> dict:
    return {
        "op_id": "op", "kind": kind, "state": state,
        "collectionname": "c", "collection_dataset": "c_d",
        "started_at": datetime(2026, 1, 1),
        "run_started_at": datetime(1970, 1, 1),
    }


@pytest.fixture
def fake_store(monkeypatch):
    """Fake the row read, the admission count and the row write."""
    store = {"row": None, "counts": (0, 0), "writes": [], "conflicts": []}
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: store["row"])
    monkeypatch.setattr(operations, "count_admission", lambda _row: store["counts"])
    monkeypatch.setattr(operations, "admission_conflicts", lambda _row: store["conflicts"])
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


@pytest.mark.parametrize("kind, blocker", [
    ("ingest_upload", "rescan_dataset"),
    ("ingest_upload", "rerun_ocr"),
    ("ingest_upload", "reindex_collection"),
    ("ingest_upload", "delete_dataset"),
    ("rescan_dataset", "ingest_upload"),
    ("reindex_collection", "ingest_upload"),
])
def test_admission_waits_behind_a_running_overlapping_writer_of_another_kind(
        fake_store, kind, blocker):
    fake_store["row"] = _row("pending", kind)
    fake_store["counts"] = (0, 0)
    fake_store["conflicts"] = [{"op_id": "other", "kind": blocker}]
    assert admit_operation("op") == "queued"
    assert fake_store["writes"] == [{"state": "queued"}]
    fake_store["conflicts"] = []
    fake_store["row"] = _row("queued", kind)
    fake_store["writes"].clear()
    assert admit_operation("op") == "running"
    assert fake_store["writes"][0]["state"] == "running"


def test_the_conflict_query_names_running_overlapping_rows_except_itself(monkeypatch):
    captured = []
    monkeypatch.setattr(operations, "_select",
                        lambda where, parameters, limit=None: captured.append((where, parameters)) or [])
    operations.admission_conflicts(_row("pending", "ingest_upload"))
    operations.admission_conflicts(_row("pending", "reindex_collection"))
    (dataset_where, dataset_parameters), (collection_where, collection_parameters) = captured
    assert "state = 'running' OR (state IN ('pending', 'queued')" in dataset_where
    assert "(started_at, op_id) < ({started:DateTime}, {self_op_id:String})" in dataset_where
    assert "collection_dataset = {collection_dataset:String}" in dataset_where
    assert "target_kind = 'collection' AND collectionname = {collectionname:String}" in dataset_where
    assert dataset_parameters == {"collection_dataset": "c_d", "collectionname": "c",
                                  "self_op_id": "op", "started": datetime(2026, 1, 1)}
    assert collection_where.endswith("collectionname = {collectionname:String}")
    assert "collection_dataset" not in collection_where
    assert collection_parameters == {"collectionname": "c", "self_op_id": "op", "started": datetime(2026, 1, 1)}


def test_the_lock_clause_keeps_its_live_states_and_targets():
    where, parameters = operations.lock_clause("ingest_upload", "c", "c_d")
    assert where.startswith("state IN ('pending', 'queued', 'running') AND (collection_dataset")
    assert parameters == {"collection_dataset": "c_d", "collectionname": "c"}


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


def test_the_admission_query_reads_live_rows_of_the_kind_and_running_rows(monkeypatch):
    captured = {}

    class _Result:
        column_names = ("op_id", "kind", "target_kind", "collectionname",
                        "collection_dataset", "state", "started_at")
        result_rows = [
            ("old", "add_dataset", "dataset", "c", "c_x", "queued", datetime(2025, 12, 31)),
            ("ocr", "rerun_ocr", "dataset", "c", "c_x", "running", datetime(2025, 12, 1)),
        ]

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
    # The older row waits for the running OCR of its own dataset, so it is not ahead.
    assert operations.count_admission(_row("pending")) == (0, 0)
    assert "state IN ('pending', 'queued', 'running')" in captured["sql"]
    assert "(kind = {kind:String} OR state = 'running')" in captured["sql"]
    assert captured["parameters"] == {"kind": "add_dataset"}


def _live(op_id: str, kind: str, state: str, dataset: str, day: int,
          collection: str = "c") -> dict:
    return {
        "op_id": op_id, "kind": kind, "state": state,
        "target_kind": KINDS[kind]["target_kind"],
        "collectionname": collection, "collection_dataset": dataset,
        "started_at": datetime(2026, 1, day),
    }


def _upload(dataset: str, day: int = 10, collection: str = "c") -> dict:
    return _live("me", "ingest_upload", "pending", dataset, day, collection)


def test_older_rows_that_wait_for_their_own_target_do_not_fill_the_cap():
    live = [
        _live("ocr-a", "rerun_ocr", "running", "c_a", 1),
        _live("ocr-b", "rerun_ocr", "running", "c_b", 1),
        _live("up-a", "ingest_upload", "queued", "c_a", 2),
        _live("up-b", "ingest_upload", "queued", "c_b", 3),
    ]
    row = _upload("c_c")
    running, ahead = operations.admission_counts(row, live + [row])
    assert (running, ahead) == (0, 0)
    assert admission_decision(running, ahead, 2) == "running"


def test_older_rows_that_can_run_stay_ahead_in_their_order():
    live = [
        _live("up-a", "ingest_upload", "queued", "c_a", 2),
        _live("up-b", "ingest_upload", "pending", "c_b", 3),
        _live("up-later", "ingest_upload", "queued", "c_d", 20),
    ]
    row = _upload("c_c")
    assert operations.admission_counts(row, live + [row]) == (0, 2)
    assert admission_decision(0, 2, 2) == "queued"
    # The newer row waits behind this one, not the reverse.
    assert operations.admission_counts(live[2], live + [row]) == (0, 3)


def test_running_rows_of_the_kind_count_against_the_cap():
    live = [
        _live("up-a", "ingest_upload", "running", "c_a", 2),
        _live("up-b", "ingest_upload", "running", "c_b", 3),
        _live("other", "rerun_ocr", "running", "c_z", 3),
    ]
    row = _upload("c_c")
    assert operations.admission_counts(row, live + [row]) == (2, 0)
    assert admission_decision(2, 0, 2) == "queued"


def test_a_collection_operation_blocks_the_older_dataset_rows_of_its_collection():
    live = [
        _live("reindex", "reindex_collection", "running", "", 1, collection="press"),
        _live("up-press", "ingest_upload", "queued", "press_inbox", 2, collection="press"),
        _live("up-legal", "ingest_upload", "queued", "legal_inbox", 3, collection="legal"),
    ]
    row = _upload("c_c")
    # Only the row of the other collection can run, so only it is ahead.
    assert operations.admission_counts(row, live + [row]) == (0, 1)


def test_the_overlap_rule_matches_the_target_clause():
    dataset_row = _live("d", "ingest_upload", "queued", "c_a", 1)
    assert operations.targets_overlap(dataset_row, _live("x", "rerun_ocr", "running", "c_a", 1))
    assert not operations.targets_overlap(dataset_row, _live("x", "rerun_ocr", "running", "c_b", 1))
    assert operations.targets_overlap(
        dataset_row, _live("x", "reindex_collection", "running", "", 1))
    assert not operations.targets_overlap(
        dataset_row, _live("x", "reindex_collection", "running", "", 1, collection="other"))
    collection_row = _live("r", "reindex_collection", "queued", "", 1)
    assert operations.targets_overlap(collection_row, _live("x", "rerun_ocr", "running", "c_b", 1))
    assert not operations.targets_overlap(
        collection_row, _live("x", "rerun_ocr", "running", "o_b", 1, collection="other"))
