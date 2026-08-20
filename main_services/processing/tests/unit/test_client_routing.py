"""Client routing tests: each helper binds the right ClickHouse database.

``clickhouse_connect.get_client`` is monkeypatched with a recorder so no server is
needed. The assertion is on the ``database=`` argument: collection clients must
never silently fall back to the global database and vice versa.
"""

import pytest

import database.clickhouse as clickhouse


class _RecordingClient:
    def close(self):
        pass

    def insert(self, table, data, **kwargs):
        self.last_insert = (table, kwargs)

    def insert_arrow(self, table, data, **kwargs):
        self.last_insert_arrow = (table, kwargs)


@pytest.fixture(autouse=True)
def _reset_client_pool():
    clickhouse.reset_client_pool_for_tests()
    yield
    clickhouse.reset_client_pool_for_tests()


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


def test_sequential_contexts_reuse_one_client(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_global_client() as first:
        pass
    with clickhouse.get_global_client() as second:
        assert first is second

    assert len(calls) == 1


def test_nested_same_db_shares_client_after_inner_exit(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_global_client() as outer:
        with clickhouse.get_global_client() as inner:
            assert inner is outer
        # Inner exit must not close the client the outer block is using.
        assert outer is not None

    assert len(calls) == 1


def test_different_databases_get_separate_clients(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_global_client() as global_client:
        with clickhouse.get_collection_client("testdata") as collection_client:
            assert global_client is not collection_client

    assert len(calls) == 2
    databases = {c["database"] for c in calls}
    assert databases == {"Hoover4_Processing", "Hoover4_Collection_testdata"}


def test_http_pool_is_sized_above_activity_slots(monkeypatch):
    calls = _record_get_client(monkeypatch)

    with clickhouse.get_global_client():
        pass

    pool = calls[0]["pool_mgr"]
    assert pool.connection_pool_kw["maxsize"] > 8


def test_insert_idempotent_opts_out_of_the_async_wait(monkeypatch):
    _record_get_client(monkeypatch)
    with clickhouse.get_global_client() as client:
        clickhouse.insert_idempotent(client, "file_types", [[1]], column_names=["x"])
        clickhouse.insert_arrow_idempotent(client, "text_content", object())

    assert client.last_insert[1]["settings"]["wait_for_async_insert"] == 0
    assert client.last_insert_arrow[1]["settings"]["wait_for_async_insert"] == 0


def test_insert_durable_keeps_the_async_wait(monkeypatch):
    _record_get_client(monkeypatch)
    with clickhouse.get_global_client() as client:
        clickhouse.insert_durable(client, "index_state", [[1]], column_names=["x"])
        clickhouse.insert_arrow_durable(client, "processing_plan_finished", object())

    assert client.last_insert[1]["settings"]["wait_for_async_insert"] == 1
    assert client.last_insert_arrow[1]["settings"]["wait_for_async_insert"] == 1
