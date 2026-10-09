"""Setting versions in microseconds, and the whole-second versions of earlier rows.

"Run OCR" compares an OCR error with the version of the language setting it was written
under. These tests pin the writer, the reader and the backup restore that keep that
version accurate.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import database.clickhouse as clickhouse
import tasks.dataset_config as dataset_config
from tasks.P_ops.restore import _setting_with_version

KEY = dataset_config.KEY_TESSERACT_LANGUAGES
OTHER = dataset_config.KEY_EASYOCR_LANGUAGES


class SettingsTable:
    """`dataset_settings` with the argMax reader of `tasks/dataset_config.py`."""

    def __init__(self, rows=()):
        self.rows = list(rows)   # dicts with the table's columns
        self.inserts = 0

    def query(self, sql, parameters):
        assert "argMax((value, is_deleted, setting_version_us, version_is_precise), " \
               "setting_version_us)" in sql
        keys = parameters.get("keys")
        latest = {}
        for row in self.rows:
            if row["collection_dataset"] != parameters["cd"]:
                continue
            if keys is not None and row["key"] not in keys:
                continue
            if row["key"] not in latest or (
                    row["setting_version_us"] > latest[row["key"]]["setting_version_us"]):
                latest[row["key"]] = row
        return SimpleNamespace(result_rows=[
            (key, (r["value"], r["is_deleted"], r["setting_version_us"],
                   r["version_is_precise"])) for key, r in latest.items()])

    def insert_arrow(self, table, arrow_table, settings=None):
        assert table == "dataset_settings"
        assert settings == {"async_insert": 1, "wait_for_async_insert": 1}
        self.inserts += 1
        self.rows += [{**row, "is_deleted": 0} for row in arrow_table.to_pylist()]


@pytest.fixture
def table(monkeypatch):
    table = SettingsTable()

    @contextmanager
    def client():
        yield table

    monkeypatch.setattr(clickhouse, "get_global_client", client)
    return table


def at(monkeypatch, microseconds):
    """Fix the writer's clock."""
    moment = datetime.fromtimestamp(microseconds / 1_000_000, tz=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    monkeypatch.setattr(dataset_config, "datetime", Clock)


def test_two_writes_in_one_second_are_ordered(table, monkeypatch):
    at(monkeypatch, 100_100_000)
    dataset_config.set_dataset_setting("ds", KEY, "eng")
    dataset_config.set_dataset_setting("ds", KEY, "eng+deu")
    versions = [row["setting_version_us"] for row in table.rows]
    assert versions == [100_100_000, 100_100_001]
    assert {row["version_is_precise"] for row in table.rows} == {1}
    assert {row["updated_at"] for row in table.rows} == {datetime(1970, 1, 1, 0, 1, 40)}
    assert dataset_config.latest_setting_rows("ds", [KEY])[KEY] == dataset_config.SettingRow(
        "eng+deu", False, 100_100_001, True)


def test_an_unchanged_value_keeps_its_version(table, monkeypatch):
    at(monkeypatch, 100_100_000)
    dataset_config.set_dataset_setting("ds", KEY, "eng")
    at(monkeypatch, 200_000_000)
    dataset_config.set_dataset_setting("ds", KEY, "eng")
    dataset_config.set_dataset_setting("ds", OTHER, "ru")
    rows = dataset_config.latest_setting_rows("ds", [KEY, OTHER])
    assert rows[KEY].version_us == 100_100_000
    assert rows[OTHER].version_us == 200_000_000
    assert table.inserts == 2


def test_a_value_after_a_whole_second_row_gets_a_later_version(table, monkeypatch):
    table.rows.append({"collection_dataset": "ds", "key": KEY, "value": "eng", "is_deleted": 0,
                       "setting_version_us": 100_000_000, "version_is_precise": 0})
    at(monkeypatch, 99_999_000)   # a writer clock behind the copied second
    dataset_config.set_dataset_setting("ds", KEY, "deu")
    assert dataset_config.latest_setting_rows("ds", [KEY])[KEY] == dataset_config.SettingRow(
        "deu", False, 100_000_001, True)


def test_a_deleted_row_reads_as_the_default_with_its_version(table):
    table.rows.append({"collection_dataset": "ds", "key": KEY, "value": "ron", "is_deleted": 0,
                       "setting_version_us": 1, "version_is_precise": 1})
    table.rows.append({"collection_dataset": "ds", "key": KEY, "value": "", "is_deleted": 1,
                       "setting_version_us": 2, "version_is_precise": 1})
    dataset_config.invalidate("ds")
    assert dataset_config.get_setting("ds", KEY) == dataset_config.DEFAULTS[KEY]
    assert dataset_config.latest_setting_rows("ds", [KEY])[KEY].version_us == 2


def test_an_old_backup_row_keeps_its_second_as_a_whole_second_version():
    row = {"collection_dataset": "ds", "key": KEY, "value": "eng",
           "updated_at": "2026-10-09 10:00:05", "is_deleted": 0}
    restored = _setting_with_version(row)
    expected = int(datetime(2026, 10, 9, 10, 0, 5, tzinfo=timezone.utc).timestamp()) * 1_000_000
    assert restored["setting_version_us"] == expected
    assert restored["version_is_precise"] == 0
    assert restored["value"] == "eng"


def test_a_new_backup_row_keeps_its_precise_version():
    row = {"collection_dataset": "ds", "key": KEY, "value": "eng",
           "updated_at": "2026-10-09 10:00:05", "is_deleted": 0,
           "setting_version_us": 1_791_000_000_123_456, "version_is_precise": 1}
    assert _setting_with_version(row) == row
