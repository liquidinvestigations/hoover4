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

from tasks.llm_catalog import RefreshResult, provider_label, store_models


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
    client = fake([("nvidia/keep-off", 0, 0), ("nvidia/fine", 1, 0)])
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
    client = fake([("nvidia/keep-off", 0, 0)])
    assert store_models(RefreshResult(provider="nvidia", ok=False, models=[]), "u") == 0
    assert client.inserted is None


def test_the_column_is_typed_uint8_like_the_table(fake):
    client = fake([("nvidia/keep-off", 0, 0)])
    store_models(
        RefreshResult(provider="nvidia", ok=True, models=["nvidia/keep-off"]),
        "http://provider/v1",
    )
    assert client.inserted[1].schema.field("is_allowed").type == pa.uint8()


def test_a_stated_context_window_is_written(fake):
    client = fake([])
    store_models(
        RefreshResult(provider="selfhosted", ok=True, models=["local/x"],
                      context_windows={"local/x": 262144}),
        "http://provider/v1",
    )
    assert _column(client, "context_window") == [262144]


def test_a_window_the_provider_stopped_stating_is_not_blanked(fake):
    """The denominator survives a refresh that says nothing about it.

    A provider that listed `max_model_len` once and omits it on the next round would
    otherwise erase the only number a context percentage can be computed against, and
    the footer would go from a percentage to "unknown" with nothing having changed.
    """
    client = fake([("local/x", 1, 262144)])
    store_models(
        RefreshResult(provider="selfhosted", ok=True, models=["local/x"]),
        "http://provider/v1",
    )
    assert _column(client, "context_window") == [262144]


def test_an_unknown_window_stays_zero_rather_than_being_guessed(fake):
    """0 is the representation of "the provider did not say".

    Every reader must render that as unknown. A plausible default here is worse than an
    absent number, because the compaction trigger downstream would believe it.
    """
    client = fake([])
    store_models(
        RefreshResult(provider="selfhosted", ok=True, models=["local/mystery"]),
        "http://provider/v1",
    )
    assert _column(client, "context_window") == [0]


@pytest.mark.parametrize(
    "host,expected",
    [
        ("api.moonshot.ai", "moonshot"),
        ("integrate.api.nvidia.com", "nvidia"),
        # An IP literal has no registrable label, and taking the second-to-last one names
        # the provider after an octet. The admin page synthesises `host:port` for a
        # configured endpoint with no rows yet, so the two must agree or a refresh writes
        # its models beside the provider the page is already showing.
        ("192.0.2.10:21960", "192.0.2.10:21960"),
        ("127.0.0.1", "127.0.0.1"),
        ("[fd00::1]:8000", "[fd00::1]:8000"),
        ("localhost:8000", "localhost"),
    ],
)
def test_a_provider_label_survives_an_address_literal(host, expected):
    assert provider_label(host) == expected
