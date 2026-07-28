"""Tests for Manticore shard table naming (plan overview §3 canonical names)."""

import pytest

from database.manticore import shard_table_names, shard_tables_from_name


def test_shard_table_names_canonical():
    assert shard_table_names("testdata", 1) == ("testdata_1_pages", "testdata_1_meta")
    assert shard_table_names("testdata", 2) == ("testdata_2_pages", "testdata_2_meta")
    assert shard_table_names("mycollection", 12) == ("mycollection_12_pages", "mycollection_12_meta")


def test_shard_tables_from_name_roundtrip():
    assert shard_tables_from_name("testdata_1") == ("testdata_1_pages", "testdata_1_meta")
    assert shard_tables_from_name("mycollection_12") == ("mycollection_12_pages", "mycollection_12_meta")


@pytest.mark.parametrize(
    "name,index",
    [
        ("", 1),
        ("Testdata", 1),
        ("bad name", 1),
        ("a; DROP TABLE x", 1),
        ("a.b", 1),
        ("a`b", 1),
        ("x_1", 1),        # shard-like suffix is not a valid collectionname
        ("x_pages", 1),    # reserved suffix
        ("x_meta", 1),     # reserved suffix
        ("processing", 1), # reserved name
        ("testdata", 0),   # 1-based
        ("testdata", -1),
        ("testdata", 1.5), # not an int
        ("testdata", True),# bool is not an int here
        ("testdata", "1"), # no strings
    ],
)
def test_shard_table_names_rejects_invalid(name, index):
    with pytest.raises(ValueError):
        shard_table_names(name, index)


@pytest.mark.parametrize(
    "shard_name",
    [
        "",
        "testdata",        # no numeric suffix
        "testdata_",       # trailing separator only
        "testdata_x",      # non-numeric suffix
        "testdata_1_pages",# a physical table name, not a logical shard name
        "testdata_1_2",    # would imply collectionname ending in _<digits>
        "testdata_1_1",    # same, minimal form
        "bad name_1",
        "1",               # no collectionname part
        "testdata_0",      # shards are 1-based
        "testdata_01",     # leading zero aliases shard 1 with non-canonical tables
        "testdata_-1",     # stray separator: not the canonical spelling
    ],
)
def test_shard_tables_from_name_rejects_invalid(shard_name):
    with pytest.raises(ValueError):
        shard_tables_from_name(shard_name)
