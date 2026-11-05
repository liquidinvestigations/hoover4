"""Verify archive reconciliation and per-row search output in isolated datastores."""

import pytest

from database import clickhouse, manticore
from tasks.P3_parse_files import parse_archives
from tasks.P6_index_data import activities, location_refresh
from tasks.P_admin.updates import table_receipts
from .test_table_publication_receipts import collection

pytestmark = pytest.mark.integration


@pytest.fixture
def search_collection(collection):
    manticore.create_shard_tables(collection, 1)
    manticore.create_vectors_table(collection, 1, 16)
    manticore.create_vfs_table(collection)
    try:
        yield collection
    finally:
        manticore.drop_collection_tables(collection)


def page(collection, identity, file_hash, source, language, page_number=None):
    with manticore.get_manticore_client() as connection:
        cursor = connection.cursor()
        cursor.execute(
            f"REPLACE INTO {manticore.shard_table_name(collection, 1)} "
            "(id, page_text, collection_dataset, file_hash, extracted_by, page_id, "
            f"file_paths, language, ocr_script, ocr_language) VALUES (%s, %s, %s, %s, %s, %s, (1), (2), (3), ({int(language)}))",
            (identity, "text", "dataset", file_hash, source, identity if page_number is None else page_number))
        connection.commit()


def test_partial_attribute_refresh_remains_stale_until_every_row_matches(search_collection):
    name = search_collection
    page(name, 1, "source", "filename_index", 4)
    page(name, 2, "source", "text", 9, page_number=1)
    with clickhouse.get_collection_client(name) as client:
        client.insert("text_content", [["dataset", "source", "text", 1, "text", 4, 1]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
    assignments = {"source": name + "_1"}
    values = location_refresh.load_indexed_ids(name, "dataset", assignments)
    assert values[3]["source"] != frozenset({4})
    page(name, 2, "source", "text", 4, page_number=1)
    values = location_refresh.load_indexed_ids(name, "dataset", assignments)
    assert values[3]["source"] == frozenset({4})
    with clickhouse.get_collection_client(name) as client:
        client.insert("text_content", [["dataset", "source", "text", 2, "second page", 11, 2]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
    assert location_refresh.load_indexed_ids(name, "dataset", assignments)[3]["source"] != frozenset({4})
    page(name, 3, "source", "text", 4, page_number=2)
    assert location_refresh.load_indexed_ids(name, "dataset", assignments)[3]["source"] == frozenset({4})
    with manticore.get_manticore_client() as connection:
        connection.cursor().execute(f"DELETE FROM {manticore.shard_table_name(name, 1)} WHERE id = 1")
        connection.commit()
    values = location_refresh.load_indexed_ids(name, "dataset", assignments)
    assert values[3]["source"] != frozenset({4})


def test_removed_archive_subtree_loses_search_and_text_but_keeps_shared_content(search_collection, tmp_path):
    name = search_collection
    with clickhouse.get_collection_client(name) as client:
        client.insert("vfs_files", [
            ["dataset", "", "/archive", "entry"],
            ["dataset", "", "/shared", "shared"],
            ["dataset", "entry", "/nested", "nested"],
            ["dataset", "nested", "/dead", "dead"],
            ["dataset", "nested", "/shared", "shared"],
            ["dataset", "shared", "/child", "shared_child"]],
            column_names=["collection_dataset", "container_hash", "path", "hash"])
        client.insert("text_content", [["dataset", value, "raw_text", 1, "stored output", 13, 1]
                                      for value in ("nested", "dead", "shared", "shared_child")],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
        client.insert("index_state", [["dataset", value, name + "_1"] for value in ("nested", "dead", "shared")],
                      column_names=["collection_dataset", "file_hash", "shard_name"])
        client.insert("manticore_shard_assignments", [["dataset", value, name + "_1"] for value in ("nested", "dead", "shared")],
                      column_names=["collection_dataset", "file_hash", "shard_name"])
    for identity, value in enumerate(("nested", "dead", "shared"), 1):
        page(name, identity, value, "raw_text", 4)
    assert parse_archives._tombstone_absent_members(name, "dataset", "entry", str(tmp_path)) == 1
    from tasks.P3_parse_files.archive_reconciliation import reconcile_archive_descendants
    from tasks.P6_index_data.params import BuildVfsNodesParams
    reconcile_archive_descendants(BuildVfsNodesParams(name, "dataset"))
    with clickhouse.get_collection_client(name) as client:
        assert {row[0] for row in client.query("SELECT DISTINCT file_hash FROM text_content").result_rows} == {
            "shared", "shared_child"}
        live = client.query("SELECT container_hash, hash FROM vfs_files FINAL WHERE is_deleted = 0").result_rows
        assert ("shared", "shared_child") in live
        assert ("nested", "dead") not in live
    with manticore.get_manticore_client() as connection:
        cursor = connection.cursor()
        cursor.execute(f"SELECT file_hash FROM {manticore.shard_table_name(name, 1)} LIMIT 100")
        assert cursor.fetchall() == [("shared",)]
    assert location_refresh.load_shard_assignments(name, "dataset") == {"shared": name + "_1"}
    assert not ({"nested", "dead"} & set(location_refresh.list_stale_location_hashes(name, "dataset")[0]))


def test_vector_receipt_requires_the_exact_indexed_identities(search_collection, monkeypatch):
    name = search_collection
    monkeypatch.setattr(clickhouse, "get_server_setting", lambda _key: "model")
    expected = activities.vectors_row_id("dataset", "source", "table_text", 1, 0, "model")
    with clickhouse.get_collection_client(name) as client:
        client.insert("text_chunk_vectors", [["dataset", "source", "table_text", 1, 0, "model", 16, [0.1] * 16]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "chunk_index", "embedding_model", "dims", "embedding"])
        client.insert("index_state", [["dataset", "source", name + "_1"]],
                      column_names=["collection_dataset", "file_hash", "shard_name"])
        params = table_receipts.TableReceiptParams(name, "dataset", "operation", ["source"])
        with pytest.raises(RuntimeError, match="incomplete stored output"):
            table_receipts.verify_vector_index(client, params)
        with manticore.get_manticore_client(manticore.VECTORS) as connection:
            cursor = connection.cursor()
            cursor.execute(f"REPLACE INTO {manticore.vectors_table_name(name, 1)} "
                           f"(id, collection_dataset, file_hash, extracted_by, page_id, chunk_index, embedding) "
                           f"VALUES (%s, %s, %s, %s, 1, 0, ({','.join(['0.1'] * 16)}))",
                           (expected, "dataset", "source", "table_text"))
            connection.commit()
        table_receipts.verify_vector_index(client, params)


def test_later_nested_scan_preserves_a_shared_container_before_reconciliation(search_collection, tmp_path):
    import hashlib
    from tasks.P3_parse_files.archive_reconciliation import reconcile_archive_descendants
    from tasks.P3_parse_files.member_scan import scan_folder_tree
    from tasks.P6_index_data.params import BuildVfsNodesParams
    name = search_collection
    content = b"shared container source"
    shared = hashlib.sha3_256(content).hexdigest()
    with clickhouse.get_collection_client(name) as client:
        client.insert("vfs_files", [["dataset", "", "/old.zip", "entry"],
                                     ["dataset", "", "/later.zip", "later"],
                                     ["dataset", "entry", "/removed.zip", "removed"],
                                     ["dataset", "removed", "/shared.bin", shared],
                                     ["dataset", shared, "/child.txt", "child"]],
                      column_names=["collection_dataset", "container_hash", "path", "hash"])
        client.insert("blobs", [["dataset", shared, len(content)], ["dataset", "later", 1]],
                      column_names=["collection_dataset", "blob_hash", "blob_size_bytes"])
        client.insert("processing_plan_hits", [["dataset", shared, "known_plan"]],
                      column_names=["collection_dataset", "item_hash", "plan_hash"])
        client.insert("processing_plan_finished", [["dataset", "known_plan"]],
                      column_names=["collection_dataset", "plan_hash"])
        client.insert("text_content", [["dataset", "child", "raw_text", 1, "retained output", 15, 1]],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
    current = tmp_path / "current"
    current.mkdir()
    parse_archives._tombstone_absent_members(name, "dataset", "entry", str(current))
    params = BuildVfsNodesParams(name, "dataset")
    with pytest.raises(RuntimeError, match="unfinished processing"):
        reconcile_archive_descendants(params)
    later = tmp_path / "later"
    later.mkdir()
    (later / "shared.bin").write_bytes(content)
    scan_folder_tree(name, "dataset", str(later), "later")
    with clickhouse.get_collection_client(name) as client:
        client.insert("processing_plan_hits", [["dataset", "later", "known_plan"]],
                      column_names=["collection_dataset", "item_hash", "plan_hash"])
    reconcile_archive_descendants(params)
    with clickhouse.get_collection_client(name) as client:
        assert client.query("SELECT hash FROM vfs_files FINAL WHERE container_hash = {parent:String} AND is_deleted = 0",
                            parameters={"parent": shared}).result_rows == [("child",)]
        assert client.query("SELECT text FROM text_content WHERE file_hash = 'child'").result_rows == [("retained output",)]


def test_every_volume_rejects_conflicting_live_occurrences(collection, monkeypatch):
    from temporalio.exceptions import ApplicationError
    from tasks.P3_parse_files.batch_runner import BatchFile
    with clickhouse.get_collection_client(collection) as client:
        client.insert("vfs_files", [["dataset", "", "/a/archive.001", "entry"],
                                     ["dataset", "", "/a/archive.002", "later_a"],
                                     ["dataset", "", "/b/archive.001", "entry"],
                                     ["dataset", "", "/b/archive.002", "later_b"]],
                      column_names=["collection_dataset", "container_hash", "path", "hash"])
    monkeypatch.setattr(parse_archives, "extract_split_set", lambda *_args: pytest.fail("Ambiguous extraction started"))
    for file_hash in ("entry", "later_a", "later_b"):
        for batch in ({file_hash}, {"entry", file_hash}):
            with pytest.raises(ApplicationError) as error:
                parse_archives.split_step(collection, "dataset", BatchFile(file_hash, "/unused", 1), batch, set())
            assert error.value.type == "SplitArchiveAmbiguous"
