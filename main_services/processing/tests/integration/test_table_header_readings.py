"""Verify the stored readings of row 1 against a temporary collection database.

The test applies the collection migrations before `00061`, stores a sheet row as an older
reader wrote it, and applies the rest. It then parses delimited files with the production
activity, claims one parse for a second dataset, parses one file again, and offers a parse
of an older reader version for reuse.
"""

from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

import clickhouse_connect
import pytest

from database import clickhouse as db
from tasks.P3_parse_files import parse_table
from tasks.P3_parse_files.table_formats import READER_VERSION

pytestmark = pytest.mark.integration

HEADER_MIGRATION = "00061"


@pytest.fixture
def collection(tmp_path):
    name = "tablereadings" + uuid4().hex[:8]
    database = db.COLLECTION_DB_PREFIX + name
    cluster = db._cluster()
    admin = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
                                          password=db.CLICKHOUSE_PASS, settings=db.CLIENT_SETTINGS)
    with TemporaryDirectory() as folder:
        for path in Path(db.COLLECTION_MIGRATIONS_PATH).glob("*.sql"):
            if path.name < HEADER_MIGRATION:
                shutil.copy(path, folder)
        cluster.migrate(database, folder, cluster_name=None, create_db_if_no_exists=True, multi_statement=True)
        client = clickhouse_connect.get_client(host=db.CLICKHOUSE_HOST, username=db.CLICKHOUSE_USER,
                                               password=db.CLICKHOUSE_PASS, database=database,
                                               settings=db.CLIENT_SETTINGS)
        try:
            yield name, client, cluster, folder
        finally:
            db.reset_client_pool_for_tests()
            admin.command(f"DROP DATABASE IF EXISTS `{database}`")
            client.close()
            admin.close()


def apply_rest(client, cluster, folder):
    for path in Path(db.COLLECTION_MIGRATIONS_PATH).glob("*.sql"):
        if path.name >= HEADER_MIGRATION:
            shutil.copy(path, folder)
    cluster.migrate(client.database, folder, cluster_name=None, create_db_if_no_exists=True, multi_statement=True)


def parse(collectionname, dataset, path, file_hash):
    return parse_table.parse_table_and_store(parse_table.ParseTableParams(
        collectionname=collectionname, collection_dataset=dataset, file_hash=file_hash,
        file_path=str(path), timeout_seconds=120, mime_types=["text/csv"], file_names=[path.name],
    ))


def readings(client, dataset, file_hash):
    return client.query(
        "SELECT header_row, header_state, header_basis, header_candidates, row_count "
        "FROM table_sheets FINAL WHERE collection_dataset = {ds:String} AND hash = {h:String} ORDER BY sheet_id",
        parameters={"ds": dataset, "h": file_hash}).result_rows


def counted(client, table, file_hash):
    column = "file_hash" if table == "table_cells" else "hash"
    return client.query(f"SELECT count() FROM `{table}` FINAL WHERE {column} = {{h:String}}",
                        parameters={"h": file_hash}).result_rows[0][0]


def test_an_older_sheet_row_reads_as_legacy_after_the_migration(collection):
    _, client, cluster, folder = collection
    client.command(
        "INSERT INTO table_sheets (collection_dataset, hash, sheet_id, row_count, column_count, header_row) "
        "VALUES ('legacy_ds', 'legacy', 0, 19, 3, 1)")
    apply_rest(client, cluster, folder)
    assert readings(client, "legacy_ds", "legacy") == [(1, "legacy", "missing", [], 19)]
    # The migration is additive and can run again.
    apply_rest(client, cluster, folder)
    assert readings(client, "legacy_ds", "legacy") == [(1, "legacy", "missing", [], 19)]


def test_the_parser_stores_both_readings_and_a_reuse_copies_them(collection, tmp_path):
    name, client, cluster, folder = collection
    apply_rest(client, cluster, folder)
    ambiguous = tmp_path / "people.csv"
    ambiguous.write_text("Alice,Paris\nBob,Rome\nCarol,Oslo\n", encoding="utf-8")
    labelled = tmp_path / "amounts.csv"
    labelled.write_text("office,amount\nNorth,10\nSouth,20\n", encoding="utf-8")

    assert parse(name, f"{name}_a", ambiguous, "ambiguous")["status"] == "ok"
    assert parse(name, f"{name}_a", labelled, "labelled")["status"] == "ok"
    assert readings(client, f"{name}_a", "ambiguous") == [(1, "ambiguous", "heuristic", [0, 1], 3)]
    assert readings(client, f"{name}_a", "labelled") == [(1, "established", "heuristic", [1], 3)]
    manifest = client.query("SELECT reader_version FROM table_documents FINAL WHERE hash = 'ambiguous'").result_rows
    assert manifest == [(READER_VERSION,)]

    # Another dataset with the same file reuses the parse, and the reuse copies the readings.
    reused = parse(name, f"{name}_b", ambiguous, "ambiguous")
    assert reused.get("deduped") is True
    assert readings(client, f"{name}_b", "ambiguous") == readings(client, f"{name}_a", "ambiguous")

    # A second parse of the same dataset and file adds no cell and no reading.
    cells = counted(client, "table_cells", "ambiguous")
    assert parse(name, f"{name}_a", ambiguous, "ambiguous")["status"] == "ok"
    assert counted(client, "table_cells", "ambiguous") == cells == 6
    assert len(readings(client, f"{name}_a", "ambiguous")) == 1


def test_a_parse_of_an_older_reader_version_is_not_reused(collection, tmp_path):
    name, client, cluster, folder = collection
    apply_rest(client, cluster, folder)
    path = tmp_path / "older.csv"
    path.write_text("Alice,Paris\nBob,Rome\nCarol,Oslo\n", encoding="utf-8")
    client.command(
        "INSERT INTO table_documents (collection_dataset, hash, status, reader, reader_version, table_format, "
        "sheet_count, row_count, column_count, cell_count) "
        "VALUES ({ds:String}, 'older', 'ok', 'csv', {v:UInt16}, 'csv', 1, 3, 2, 6)",
        parameters={"ds": f"{name}_old", "v": READER_VERSION - 1})
    client.command(
        "INSERT INTO table_sheets (collection_dataset, hash, sheet_id, row_count, column_count, header_row) "
        "VALUES ({ds:String}, 'older', 0, 3, 2, 1)", parameters={"ds": f"{name}_old"})
    assert parse_table._existing_parse(client, "older") is None
    result = parse(name, f"{name}_new", path, "older")
    assert result["status"] == "ok" and not result.get("deduped")
    assert readings(client, f"{name}_new", "older") == [(1, "ambiguous", "heuristic", [0, 1], 3)]
    # The older dataset keeps its own legacy row.
    assert readings(client, f"{name}_old", "older") == [(1, "legacy", "missing", [], 3)]
