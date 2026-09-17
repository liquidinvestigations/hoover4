"""Operation kinds that run collection-wide recovery and backfill work."""

from database.operations import DRIVEN_KINDS, KINDS


def test_submit_refuses_undriven_kind_before_row_write(monkeypatch):
    from tasks.P_ops import cli
    from database import operations
    import pytest

    monkeypatch.setattr(operations, "create_operation", lambda *_args, **_kwargs:
                        pytest.fail("undriven kind wrote a row"))
    with pytest.raises(ValueError, match="no workflow driver"):
        cli.submit_operation("unknown")


def test_collection_backfill_kinds_are_registered_and_driven():
    assert KINDS["purge_unattributed_entities"] == {
        "target_kind": "collection", "destructive": True
    }
    assert KINDS["backfill_vectors"] == {
        "target_kind": "collection", "destructive": False
    }
    assert {"purge_unattributed_entities", "backfill_vectors"} <= set(DRIVEN_KINDS)
