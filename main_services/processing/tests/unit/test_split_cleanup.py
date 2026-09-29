"""Cleanup sends each search table to its owning daemon."""

from contextlib import contextmanager
import pytest

from database import clickhouse, manticore
from tasks.P0_scan_disk import activities as scan
from tasks.P_admin import ocr_languages as ocr


class _Rows:
    def __init__(self, rows):
        self.result_rows = rows

    def to_pylist(self):
        return self.result_rows


class _SearchConnection:
    def __init__(self, table, calls, fail_vector=False):
        self.table = table
        self.calls = calls
        self.fail_vector = fail_vector

    def cursor(self):
        return self

    def execute(self, sql, params):
        self.calls.append((self.table, sql, params))
        if self.fail_vector:
            raise ConnectionError("vectors unavailable")

    def commit(self):
        self.calls.append((self.table, "COMMIT", ()))


def test_sweep_retries_vector_delete_before_removing_index_state(monkeypatch):
    state = {"deleted": False, "vector_failures": 1}
    calls = []

    class _Collection:
        def query_arrow(self, _sql, _params):
            return _Rows([])

        def query(self, _sql, _params):
            return _Rows([] if state["deleted"] else [("orphan",)])

        def command(self, sql, parameters):
            assert "DELETE FROM index_state" in sql
            assert parameters["hashes"] == ["orphan"]
            state["deleted"] = True

    @contextmanager
    def collection(_name):
        yield _Collection()

    @contextmanager
    def search(table):
        assert manticore.endpoint_for_table(table) == (
            manticore.VECTORS if table.endswith("_vectors") else manticore.TEXT)
        fail = table.endswith("_vectors") and state["vector_failures"] > 0
        if fail:
            state["vector_failures"] -= 1
        yield _SearchConnection(table, calls, fail)

    monkeypatch.setattr(scan, "get_collection_client", collection)
    monkeypatch.setattr(manticore, "client_for_table", search)
    monkeypatch.setattr(manticore, "list_shard_tables",
                        lambda _name: ["sample_1_pages", "sample_1_vectors"])
    monkeypatch.setattr(manticore, "vfs_table_name", lambda _name: "sample_vfs")
    params = scan.ReconcileDeletedFilesParams("sample", "sample_data", 0)

    with pytest.raises(ConnectionError, match="vectors unavailable"):
        scan.reconcile_deleted_files(params)
    assert not state["deleted"]

    result = scan.reconcile_deleted_files(params)
    assert result.deindexed == 1
    assert state["deleted"]
    assert sum(table == "sample_1_pages" and sql.startswith("DELETE")
               for table, sql, _ in calls) == 2
    assert any(table == "sample_1_vectors" and sql == "COMMIT"
               for table, sql, _ in calls)


def test_ocr_variant_cleanup_routes_vector_table(monkeypatch):
    calls = []

    class _Collection:
        def query(self, sql):
            assert sql == "SHOW TABLES"
            return _Rows([])

    @contextmanager
    def collection(_name):
        yield _Collection()

    @contextmanager
    def search(table):
        assert manticore.endpoint_for_table(table) == (
            manticore.VECTORS if table.endswith("_vectors") else manticore.TEXT)
        yield _SearchConnection(table, calls)

    monkeypatch.setattr(clickhouse, "get_collection_client", collection)
    monkeypatch.setattr(manticore, "client_for_table", search)
    monkeypatch.setattr(manticore, "list_shard_tables",
                        lambda _name: ["sample_1_pages", "sample_1_vectors"])
    result = ocr.purge_dropped_ocr_variants(
        ocr.PurgeVariantsParams("sample", "sample_data", ["ocr_tesseract_eng"], []))

    assert result["manticore_tables"] == 2
    assert {table for table, sql, _ in calls if sql == "COMMIT"} == {
        "sample_1_pages", "sample_1_vectors"}
