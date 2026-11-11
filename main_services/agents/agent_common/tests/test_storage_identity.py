"""Test the agent copy of the storage identity. scripts/deploy.py_tests compares the copy
with main_services/processing/tasks/storage_identity.json."""

import pytest

from agent_common import storage_identity


def test_an_absent_variable_keeps_the_compose_names():
    assert storage_identity.global_database({}) == "Hoover4_Processing"
    assert storage_identity.collection_database("my_docs", {}) == "Hoover4_Collection_my_docs"
    assert storage_identity.manticore_table("my_docs_1_pages", {}) == "my_docs_1_pages"
    assert storage_identity.collection_bucket("my_docs", {}) == "hoover4-c-my-docs"


def test_the_prefixes_change_every_name():
    environ = {"HOOVER4_CLICKHOUSE_DB_PREFIX": "zone_a", "HOOVER4_MANTICORE_TABLE_PREFIX": "zone_a_",
               "S3_COLLECTION_BUCKET_PREFIX": "zone-a-c-"}
    assert storage_identity.global_database(environ) == "zone_a_Processing"
    assert storage_identity.collection_database("my_docs", environ) == "zone_a_Collection_my_docs"
    assert storage_identity.manticore_table("my_docs_vfs", environ) == "zone_a_my_docs_vfs"
    assert storage_identity.collection_bucket("my_docs", environ) == "zone-a-c-my-docs"


@pytest.mark.parametrize("environ", [{"HOOVER4_CLICKHOUSE_DB_PREFIX": "1zone"},
                                     {"HOOVER4_MANTICORE_TABLE_PREFIX": "Zone_"}])
def test_an_invalid_prefix_names_only_its_variable(environ):
    variable, = environ
    with pytest.raises(ValueError, match=f"^{variable} is invalid.$"):
        storage_identity.global_database(environ)
        storage_identity.manticore_table("x", environ)
