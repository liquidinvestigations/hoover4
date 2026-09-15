"""Unit tests for the operation lock clause."""

from database.operations import lock_clause


def test_dataset_lock_clause_blocks_its_dataset_and_collection():
    assert lock_clause("add_dataset", "collection", "collection_dataset") == (
        "state IN ('pending', 'running') AND "
        "(collection_dataset = {collection_dataset:String} OR "
        "(target_kind = 'collection' AND collectionname = {collectionname:String}))",
        {"collection_dataset": "collection_dataset", "collectionname": "collection"},
    )


def test_collection_lock_clause_blocks_its_collection():
    assert lock_clause("reindex_collection", "collection", "") == (
        "state IN ('pending', 'running') AND collectionname = {collectionname:String}",
        {"collectionname": "collection"},
    )
