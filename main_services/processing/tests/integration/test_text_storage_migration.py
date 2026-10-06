"""Verify text storage migration, replacement versions, and large external key reads."""

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

import clickhouse_connect
from clickhouse_migrations.clickhouse_cluster import ClickhouseCluster
import pytest

from database import clickhouse as db
from tasks.P3_parse_files import parse_common
from tasks.text_sources import fetch_text_batch

pytestmark = pytest.mark.integration


@pytest.fixture
def storage(monkeypatch):
    collection = "textstorage" + uuid4().hex[:8]
    database = db.COLLECTION_DB_PREFIX + collection
    cluster = ClickhouseCluster(db.CLICKHOUSE_HOST, db.CLICKHOUSE_USER, db.CLICKHOUSE_PASS)
    admin = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
        password=db.CLICKHOUSE_PASS, settings=db.CLIENT_SETTINGS)
    with TemporaryDirectory() as folder:
        root = Path(db.COLLECTION_MIGRATIONS_PATH)
        for path in root.glob("*.sql"):
            if path.name < "00052":
                shutil.copy(path, folder)
        cluster.migrate(database, folder, cluster_name=None, create_db_if_no_exists=True, multi_statement=True)
        client = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
            password=db.CLICKHOUSE_PASS, database=database, settings=db.CLIENT_SETTINGS)
        try:
            yield collection, client, cluster, folder
        finally:
            db.reset_client_pool_for_tests()
            admin.command(f"DROP DATABASE IF EXISTS `{database}`")
            client.close()
            admin.close()


def migrate(client, cluster, folder):
    shutil.copy(Path(db.COLLECTION_MIGRATIONS_PATH) / "00052_text_storage.sql", folder)
    cluster.migrate(client.database, folder, cluster_name=None, create_db_if_no_exists=True, multi_statement=True)


def test_migration_preserves_current_rows_and_recovers_stray_tables(storage):
    _collection, client, cluster, folder = storage
    client.command("SYSTEM STOP MERGES text_content")
    columns = ["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes"]
    client.insert("text_content", [["dataset", "file", "raw_text", 1, "Old text", 8]], column_names=columns)
    client.insert("text_content", [["dataset", "file", "raw_text", 1, "New text", 8]], column_names=columns)
    client.insert("blob_values", [["dataset", "blob", 3, b"abc"]])
    client.insert("blob_values", [["dataset", "blob", 3, b"abc"]])
    before = client.query("SELECT file_hash, page_id, text FROM text_content FINAL").result_rows
    client.command("CREATE TABLE text_content_new (dummy UInt8) ENGINE = Memory")
    migrate(client, cluster, folder)
    assert client.query("SELECT file_hash, page_id, text FROM text_content FINAL").result_rows == before
    assert client.query("SELECT count() FROM blob_values FINAL").result_rows == [(1,)]
    for table, block in (("text_content", 1024), ("blob_values", 512)):
        ddl = client.query(f"SHOW CREATE TABLE {table}").result_rows[0][0]
        assert "index_granularity = 1024" in ddl
        assert "index_granularity_bytes = 1048576" in ddl
        assert "max_bytes_to_merge_at_max_space_in_pool = 4294967296" in ddl
        assert f"merge_max_block_size = {block}" in ddl
        assert "PARTITION BY" not in ddl
    assert "ReplacingMergeTree(version)" in client.query("SHOW CREATE TABLE text_content").result_rows[0][0]
    assert client.query("EXISTS TABLE text_storage_ready").result_rows == [(1,)]
    client.command("ALTER TABLE schema_versions DELETE WHERE version = 52 SETTINGS mutations_sync = 2")
    client.command("CREATE TABLE text_content_new (dummy UInt8) ENGINE = Memory")
    migrate(client, cluster, folder)
    assert client.query("SELECT file_hash, page_id, text FROM text_content FINAL").result_rows == before
    assert not client.query("SELECT name FROM system.tables WHERE database = currentDatabase() AND name IN ('text_content_new', 'blob_values_new')").result_rows


def test_text_versions_increase_when_clock_moves_back_and_obsolete_pages_disappear(storage, monkeypatch):
    collection, client, cluster, folder = storage
    migrate(client, cluster, folder)
    client.command("SYSTEM STOP MERGES text_content")
    monkeypatch.setattr(parse_common.time, "time_ns", lambda: 1)
    parse_common.insert_text_pages(collection, "dataset", "file", "raw_text", [(1, "First text"), (2, "Last text")])
    parse_common.insert_text_pages(collection, "dataset", "file", "raw_text", [(1, "Replacement text"), (2, "Last text")])
    assert client.query("SELECT page_id, text, version FROM text_content FINAL ORDER BY page_id").result_rows == [(1, "Replacement text", 2), (2, "Last text", 2)]
    # Mutations need merges enabled before the waited obsolete-page deletion.
    client.command("SYSTEM START MERGES text_content")
    parse_common.insert_text_pages(collection, "dataset", "file", "raw_text", [(1, "Replacement text")])
    parse_common.insert_text_pages(collection, "dataset", "file", "raw_text", [(1, "Replacement text")])
    expected = [(1, "Replacement text", 4)]
    assert client.query("SELECT page_id, text, version FROM text_content FINAL").result_rows == expected
    client.command("SYSTEM START MERGES text_content")
    client.command("OPTIMIZE TABLE text_content FINAL")
    assert client.query("SELECT page_id, text, version FROM text_content FINAL").result_rows == expected


def test_external_segment_keys_exceed_url_field_limits(storage):
    _collection, client, cluster, folder = storage
    migrate(client, cluster, folder)
    keys = [(f"file-{n:064d}", "raw_text", 1) for n in range(24000)]
    columns = ["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"]
    client.insert("text_content", [["dataset", key[0], key[1], key[2], "Stored text", 11, 1] for key in keys], column_names=columns)
    actual = fetch_text_batch(client, "dataset", keys)
    expected = []
    for start in range(0, len(keys), 572):
        expected.extend(fetch_text_batch(client, "dataset", keys[start:start + 572]))
    assert len(actual) == 24000
    assert actual == expected
