"""Tests for Manticore shard table naming: the canonical shard-table names."""

import pytest

from database.manticore import (
    shard_table_from_name,
    shard_table_name,
    vectors_table_from_name,
    vectors_table_name,
)


def test_vectors_table_naming_roundtrip():
    assert vectors_table_name("testdata", 1) == "testdata_1_vectors"
    assert vectors_table_from_name("testdata_1") == "testdata_1_vectors"
    assert vectors_table_from_name("mycollection_12") == "mycollection_12_vectors"


def test_vectors_table_naming_rejects_invalid():
    for bad in ("", "Testdata", "x_1", "x_pages", "x_meta", "x_vectors", "processing"):
        with pytest.raises(ValueError):
            vectors_table_name(bad, 1)
    for bad in ("", "testdata", "testdata_0", "testdata_01", "bad name_1"):
        with pytest.raises(ValueError):
            vectors_table_from_name(bad)


def test_list_shard_tables_regex_covers_vectors():
    # list_shard_tables gates drop_collection_tables and purge_dataset_from_manticore:
    # a suffix missing from this pattern survives a dataset purge. The function itself
    # needs a live Manticore, so pin the pattern it is built from instead.
    from database.manticore import _SHARD_TABLE_RE_TEMPLATE
    import re

    pattern = re.compile(_SHARD_TABLE_RE_TEMPLATE.format(coll="testdata"))
    assert pattern.match("testdata_1_pages")
    assert pattern.match("testdata_12_vectors")
    assert not pattern.match("testdata_1_blobs")
    assert not pattern.match("testdata_x_1_pages")  # a different collection's shard


def test_shard_table_name_canonical():
    assert shard_table_name("testdata", 1) == "testdata_1_pages"
    assert shard_table_name("testdata", 2) == "testdata_2_pages"
    assert shard_table_name("mycollection", 12) == "mycollection_12_pages"


def test_shard_table_from_name_roundtrip():
    assert shard_table_from_name("testdata_1") == "testdata_1_pages"
    assert shard_table_from_name("mycollection_12") == "mycollection_12_pages"


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
def test_shard_table_name_rejects_invalid(name, index):
    with pytest.raises(ValueError):
        shard_table_name(name, index)


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
def test_shard_table_from_name_rejects_invalid(shard_name):
    with pytest.raises(ValueError):
        shard_table_from_name(shard_name)
