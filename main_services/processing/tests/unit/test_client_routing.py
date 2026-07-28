"""Client routing tests: each helper binds the right ClickHouse database.

``clickhouse_connect.get_client`` is monkeypatched with a recorder so no server is
needed. The assertion is on the ``database=`` argument: collection clients must
never silently fall back to the global database and vice versa.
"""

import database.clickhouse as clickhouse


class _RecordingClient:
    def close(self):
        pass


def _record_get_client(monkeypatch):
    calls = []

    def fake_get_client(**kwargs):
        calls.append(kwargs)
        return _RecordingClient()

    monkeypatch.setattr(clickhouse.clickhouse_connect, "get_client", fake_get_client)
    return calls


def test_get_collection_client_binds_collection_db(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_collection_client("testdata"):
        pass

    assert len(calls) == 1
    assert calls[0]["database"] == "Hoover4_Collection_testdata"


def test_get_global_client_binds_global_db(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_global_client():
        pass

    assert len(calls) == 1
    assert calls[0]["database"] == "Hoover4_Processing"


def test_collection_client_validates_the_name(monkeypatch):
    """A bad collectionname must never reach get_client (SQL injection guard:
    database names cannot be bound parameters)."""
    import pytest

    calls = _record_get_client(monkeypatch)

    with pytest.raises(ValueError):
        with clickhouse.get_collection_client("a; DROP DATABASE x"):
            pass
    assert calls == []


def test_clients_keep_async_insert_settings(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_collection_client("testdata"):
        pass

    assert calls[0]["settings"] == {"async_insert": 1, "wait_for_async_insert": 1}
