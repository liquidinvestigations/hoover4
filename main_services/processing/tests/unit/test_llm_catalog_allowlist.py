"""The catalog refresh must not re-allow a model an admin disallowed.

`llm_models` is a `ReplacingMergeTree(updated_at, is_deleted)` and every reader takes
`argMax(is_allowed, updated_at)`. `is_allowed` also defaults to 1. Put together, an insert
that omits the column writes a *fresher* "allowed" version than the admin's "disallowed"
one, so the disallow evaporates the next time the catalog refreshes — and the allowlist is
enforced server-side against forged model ids, so this was a security control being reset
on a timer rather than a dropdown being repopulated.

The website has a second writer with the same shape (`api/admin/llm.rs::refresh_catalog_now`);
both carry the state forward, because whichever runs last would otherwise win.
"""

import pyarrow as pa
import pytest

from tasks.llm_catalog import RefreshResult, store_models


class FakeClient:
    """Enough of clickhouse_connect to see what `store_models` writes."""

    def __init__(self, prior_rows):
        self._prior_rows = prior_rows
        self.inserted = None
        self.queries = []

    # context manager, as `get_global_client()` is used
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, sql, parameters=None):
        self.queries.append((sql, parameters))

        class Result:
            result_rows = self._prior_rows

        return Result()

    def insert_arrow(self, table, table_data):
        self.inserted = (table, table_data)


@pytest.fixture
def fake(monkeypatch):
    client_box = {}

    def make(prior_rows):
        client = FakeClient(prior_rows)
        client_box["client"] = client
        monkeypatch.setattr(
            "database.clickhouse.get_global_client", lambda: client, raising=False
        )
        return client

    return make


def _column(client, name):
    table = client.inserted[1]
    return table.column(name).to_pylist()


def test_a_disallowed_model_stays_disallowed(fake):
    client = fake([("nvidia/keep-off", 0), ("nvidia/fine", 1)])
    written = store_models(
        RefreshResult(provider="nvidia", ok=True,
                      models=["nvidia/keep-off", "nvidia/fine"]),
        "http://provider/v1",
    )
    assert written == 2
    assert _column(client, "is_allowed") == [0, 1]


def test_a_model_nobody_has_ruled_on_is_allowed(fake):
    client = fake([])
    store_models(
        RefreshResult(provider="nvidia", ok=True, models=["nvidia/brand-new"]),
        "http://provider/v1",
    )
    assert _column(client, "is_allowed") == [1]


def test_the_previous_state_is_read_for_this_provider_only(fake):
    client = fake([])
    store_models(
        RefreshResult(provider="selfhosted", ok=True, models=["local/x"]),
        "http://provider/v1",
    )
    sql, params = client.queries[0]
    assert "argMax(is_allowed, updated_at)" in sql
    assert params == {"provider": "selfhosted"}


def test_nothing_is_written_when_the_provider_failed(fake):
    client = fake([("nvidia/keep-off", 0)])
    assert store_models(RefreshResult(provider="nvidia", ok=False, models=[]), "u") == 0
    assert client.inserted is None


def test_the_column_is_typed_uint8_like_the_table(fake):
    client = fake([("nvidia/keep-off", 0)])
    store_models(
        RefreshResult(provider="nvidia", ok=True, models=["nvidia/keep-off"]),
        "http://provider/v1",
    )
    assert client.inserted[1].schema.field("is_allowed").type == pa.uint8()
