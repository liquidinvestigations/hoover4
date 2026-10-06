"""Verify collection merge eligibility and submission reporting."""

from contextlib import contextmanager
from database import manticore, operations
from tasks.P6_index_data import activities
from tasks.P6_index_data.params import CompactCollectionShardsParams


def test_compaction_excludes_open_and_active_merges(monkeypatch):
    writes, details = [], []
    status = {"case_1_pages": {"disk_chunks": "13", "optimizing": "0"},
              "case_2_pages": {"disk_chunks": "14", "optimizing": "1"},
              "case_3_pages": {"disk_chunks": "1", "optimizing": "0"}}

    class Ledger:
        def query(self, sql, parameters):
            assert "is_open = 0" in sql
            assert parameters == {"closed_only": True}
            return type("Rows", (), {"result_rows": [("case_1",), ("case_2",), ("case_3",)]})()

    class Cursor:
        table = ""
        def execute(self, sql):
            if sql.startswith("SHOW"):
                self.table = sql.split()[2]
            else:
                writes.append(sql)
        def fetchall(self):
            return list(status[self.table].items())

    class Connection:
        def cursor(self):
            return Cursor()

    @contextmanager
    def ledger(_collection):
        yield Ledger()

    @contextmanager
    def connection():
        yield Connection()

    monkeypatch.setattr(activities, "get_collection_client", ledger)
    monkeypatch.setattr(manticore, "get_manticore_client", connection)
    monkeypatch.setattr(operations, "merge_detail", lambda op, **values: details.append((op, values)))
    assert activities.compact_collection_shards(CompactCollectionShardsParams("case", True, "op")) == ["case_1_pages"]
    assert writes == ["OPTIMIZE TABLE case_1_pages OPTION cutoff=1"]
    assert details[0][1]["compaction"] == "Compaction was submitted for 1 tables."
