"""The storage identity of database/storage_identity.py and its consumers."""

import importlib

import pytest

from database import storage_identity

DEFINITION = storage_identity.DEFINITION


@pytest.mark.parametrize("case", DEFINITION["cases"], ids=lambda case: str(sorted(case["environment"])))
def test_names_follow_the_shared_cases(case):
    environ = case["environment"]
    name = case["collectionname"]
    assert storage_identity.global_database(environ) == case["global_database"]
    assert storage_identity.collection_database_prefix(environ) + name == case["collection_database"]
    assert storage_identity.manticore_table(f"{name}_vfs", environ) == case["manticore_table"]
    assert storage_identity.collection_bucket_name(name, environ) == case["collection_bucket"]


@pytest.mark.parametrize("environ", DEFINITION["invalid"], ids=str)
def test_an_invalid_prefix_is_refused_by_variable_name(environ):
    variable, = environ
    with pytest.raises(ValueError) as refused:
        storage_identity.global_database(environ)
        storage_identity.manticore_table("x_vfs", environ)
    assert str(refused.value) == f"{variable} is invalid."


def test_an_absent_variable_keeps_the_compose_names_and_users():
    assert storage_identity.global_database({}) == "Hoover4_Processing"
    assert storage_identity.collection_database_prefix({}) == "Hoover4_Collection_"
    assert storage_identity.setting("clickhouse_user", {}) == "hoover4"
    assert storage_identity.setting("manticore_user", {}) == "manticore"
    assert storage_identity.setting("system_bucket", {}) == "hoover4-system"


def test_a_set_empty_password_is_kept():
    assert storage_identity.setting("clickhouse_password", {"CLICKHOUSE_PASSWORD": ""}) == ""


def test_the_manticore_tables_carry_the_prefix(monkeypatch):
    from database import manticore
    monkeypatch.setenv("HOOVER4_MANTICORE_TABLE_PREFIX", "zone_a_")
    assert manticore.shard_table_name("docs", 2) == "zone_a_docs_2_pages"
    assert manticore.vectors_table_name("docs", 2) == "zone_a_docs_2_vectors"
    assert manticore.vfs_table_name("docs") == "zone_a_docs_vfs"
    assert manticore.entities_table_name("docs") == "zone_a_docs_entities"
    assert manticore.shard_table_from_name("docs_2") == "zone_a_docs_2_pages"
    monkeypatch.delenv("HOOVER4_MANTICORE_TABLE_PREFIX")
    assert manticore.shard_table_name("docs", 2) == "docs_2_pages"


def test_the_database_names_carry_the_prefix(monkeypatch):
    from database import clickhouse
    try:
        monkeypatch.setenv("HOOVER4_CLICKHOUSE_DB_PREFIX", "zone_a")
        importlib.reload(clickhouse)
        assert clickhouse.GLOBAL_DB == "zone_a_Processing"
        assert clickhouse.collection_db_name("docs") == "zone_a_Collection_docs"
    finally:
        monkeypatch.delenv("HOOVER4_CLICKHOUSE_DB_PREFIX")
        importlib.reload(clickhouse)
    assert clickhouse.GLOBAL_DB == "Hoover4_Processing"
