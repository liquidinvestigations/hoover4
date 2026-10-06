"""A conversation's running context peak survives every other writer of its row.

`chat_sessions` is a `ReplacingMergeTree(updated_at)` and every writer of it does a
read-modify-write of the whole row. A writer that omits a column therefore writes a
*fresher* row carrying that column's default, and silently erases what another writer
put there. That is not hypothetical here: the summariser's title write ran after the
turn's peak was recorded and reset it to 0, which presents as accounting that works and
then quietly forgets.

The website has a third writer with the same shape (`db_chat::ChatSessionRow`), which
carries the column for the same reason.
"""

import inspect

import pytest

from tasks.P_agent import activities


class FakeClient:
    """Enough of clickhouse_connect to see what a session write carries."""

    def __init__(self, rows):
        self._rows = rows
        self.inserted = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def query(self, sql, parameters=None):
        class Result:
            result_rows = self._rows

        return Result()

    def insert(self, table, rows, column_names=None):
        self.inserted.append((table, rows, column_names))


@pytest.fixture
def fake(monkeypatch):
    def make(rows):
        client = FakeClient(rows)
        monkeypatch.setattr(
            "database.clickhouse.get_global_client", lambda: client, raising=False
        )
        return client

    return make


#: The whole row, in the order both writers select it.
COLUMNS = [
    "session_id", "username", "title", "collections", "summary",
    "use_internet_tools", "options_locked",
    "created_at", "updated_at", "is_deleted", "peak_context_tokens",
]


def _row(peak: int) -> list:
    return ["s1", "u1", "a title", ["c"], "a summary", 1, 1,
            "2020-01-01", "2020-01-01", 0, peak]


def test_a_bigger_peak_is_recorded(fake):
    client = fake([_row(1000)])
    activities._raise_session_peak("u1", "s1", 26432)
    _, rows, columns = client.inserted[0]
    assert columns == COLUMNS
    assert rows[0][columns.index("peak_context_tokens")] == 26432


def test_a_smaller_peak_leaves_the_row_alone(fake):
    """A maximum, not a last-write-wins. A quiet turn after a large one must not shrink
    the number a compaction trigger is sized against."""
    client = fake([_row(26432)])
    activities._raise_session_peak("u1", "s1", 900)
    assert client.inserted == []


def test_re_applying_the_same_turn_changes_nothing(fake):
    """The write activity is retried, so this runs more than once for one turn."""
    client = fake([_row(26432)])
    activities._raise_session_peak("u1", "s1", 26432)
    assert client.inserted == []


def test_the_title_writer_carries_the_peak_forward(fake):
    client = fake([_row(26432)])
    activities._set_session_title("u1", "s1", "new title", "new summary")
    _, rows, columns = client.inserted[0]
    assert columns == COLUMNS
    assert rows[0][columns.index("peak_context_tokens")] == 26432


def test_both_session_writers_name_the_same_columns():
    """Read as source, because the failure is a column one writer does not
    mention -- which no amount of exercising the other writer can reveal."""
    for fn in (activities._set_session_title, activities._raise_session_peak):
        source = inspect.getsource(fn)
        for column in COLUMNS:
            assert f'"{column}"' in source, f"{fn.__name__} does not write {column}"


# ------------------------------------------------ the model that answered sizes the row

from test_agent_run import _frames, _serve, _step, step_events, store  # noqa: E402,F401


def test_the_answer_row_takes_the_window_of_the_model_that_answered(store, monkeypatch):
    """The transcript row names the model of the `model_turn` frame, and its context window
    is that model's window, not the window of the environment default."""
    from tasks.P_agent import stream_writer

    windows = {"selected-model": 131_072, "test-model": 8_192}
    monkeypatch.setattr(stream_writer, "context_window_for", lambda model: windows.get(model, 0))
    _serve(monkeypatch, store, _frames(
        text="The answer.", model="selected-model",
        usage={"input_tokens": 900, "output_tokens": 40, "total_tokens": 940}))
    _step()
    [answer] = [r for r in store["chat"] if r["role"] == "assistant"]
    assert (answer["model"], answer["context_window"], answer["context_tokens"]) == (
        "selected-model", 131_072, 900)
