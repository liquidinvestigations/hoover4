"""Operation kinds that run collection-wide recovery and backfill work."""

from database.operations import DRIVEN_KINDS, KINDS


def test_collection_backfill_kinds_are_registered_and_driven():
    assert KINDS["purge_unattributed_entities"] == {
        "target_kind": "collection", "destructive": True
    }
    assert KINDS["backfill_vectors"] == {
        "target_kind": "collection", "destructive": False
    }
    assert {"purge_unattributed_entities", "backfill_vectors"} <= set(DRIVEN_KINDS)
