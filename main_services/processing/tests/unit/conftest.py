"""Shared fixtures of the unit tests."""

import pytest


@pytest.fixture(autouse=True)
def _shard_tables_have_every_column(monkeypatch):
    """The page writer asks Manticore which columns a shard table has. A unit test has no
    Manticore, so every table has every column of the current schema."""
    from database import manticore

    monkeypatch.setattr(manticore, "table_has_column", lambda table, column: True)
