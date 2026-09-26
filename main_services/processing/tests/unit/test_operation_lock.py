"""Unit tests for the operation lock clause."""

import pytest

from database.operations import lock_clause, new_op_id, target_of


def test_immediate_dispatch_ids_differ():
    first = new_op_id("execute_plans", "collection", "dataset")
    second = new_op_id("execute_plans", "collection", "dataset")
    assert first != second


def test_unknown_kind_has_no_target_fallback():
    with pytest.raises(KeyError):
        target_of("unknown", "collection", "dataset")
    with pytest.raises(KeyError):
        lock_clause("unknown", "collection", "dataset")


def test_unknown_target_kind_is_refused(monkeypatch):
    from database import operations

    monkeypatch.setitem(operations.KINDS, "invalid_target", {"target_kind": "unknown"})
    with pytest.raises(ValueError, match="Unknown operation target kind"):
        target_of("invalid_target", "collection", "dataset")
    with pytest.raises(ValueError, match="Unknown operation target kind"):
        lock_clause("invalid_target", "collection", "dataset")


def test_dataset_lock_clause_blocks_its_dataset_and_collection():
    assert lock_clause("add_dataset", "collection", "collection_dataset") == (
        "state IN ('pending', 'queued', 'running') AND "
        "(collection_dataset = {collection_dataset:String} OR "
        "(target_kind = 'collection' AND collectionname = {collectionname:String}))",
        {"collection_dataset": "collection_dataset", "collectionname": "collection"},
    )


def test_collection_lock_clause_blocks_its_collection():
    assert lock_clause("reindex_collection", "collection", "") == (
        "state IN ('pending', 'queued', 'running') AND collectionname = {collectionname:String}",
        {"collectionname": "collection"},
    )


@pytest.mark.parametrize("kind", ["add_dataset", "reindex_collection"])
def test_a_queued_row_holds_the_lock(kind):
    where, _ = lock_clause(kind, "collection", "collection_dataset")
    assert "'queued'" in where
