"""Verify submitted merges and consistent wildcard options on Manticore."""

from contextlib import contextmanager
import time

import pytest

from database.manticore import get_manticore_client
from tasks.P6_index_data import activities
from tasks.P6_index_data.params import CompactCollectionShardsParams

pytestmark = pytest.mark.integration
TABLE = "compactprobe_1_pages"


def query(client, sql):
    cursor = client.cursor()
    cursor.execute(sql)
    return cursor.fetchall()


def test_submission_finishes_with_one_disk_chunk(monkeypatch):
    class Ledger:
        def query(self, _sql, parameters):
            assert parameters == {"closed_only": False}
            return type("Rows", (), {"result_rows": [("compactprobe_1",)]})()

    @contextmanager
    def ledger(_collection):
        yield Ledger()

    monkeypatch.setattr(activities, "get_collection_client", ledger)
    with get_manticore_client() as client:
        query(client, f"DROP TABLE IF EXISTS {TABLE}")
        query(client, f"CREATE TABLE {TABLE} (page_text text, grp int) min_infix_len='3' auto_optimize='0'")
        try:
            for i in range(1, 14):
                query(client, f"INSERT INTO {TABLE} VALUES ({i}, 'document evidence', {i})")
                query(client, f"FLUSH RAMCHUNK {TABLE}")
            before = dict(query(client, f"SHOW TABLE {TABLE} STATUS"))
            assert int(before["disk_chunks"]) > 12
            assert activities.compact_collection_shards(CompactCollectionShardsParams("compactprobe", False)) == [TABLE]
            deadline = time.monotonic() + 60
            while True:
                status = dict(query(client, f"SHOW TABLE {TABLE} STATUS"))
                if status.get("optimizing", "0") == "0" and int(status["disk_chunks"]) == 1:
                    break
                assert time.monotonic() < deadline, status
                time.sleep(0.1)
            assert query(client, f"SELECT count(*) FROM {TABLE}") == [(13,)]
        finally:
            query(client, f"DROP TABLE IF EXISTS {TABLE}")


def test_wildcard_results_count_and_facets_share_expansion():
    table = "wildcardprobe_1_pages"
    with get_manticore_client() as client:
        query(client, f"DROP TABLE IF EXISTS {table}")
        query(client, f"CREATE TABLE {table} (page_text text, file_hash string, grp int) min_infix_len='3'")
        try:
            values = ",".join(f"({i}, 'review{i:04d}', '{i}', {i % 3})" for i in range(1, 1201))
            query(client, f"INSERT INTO {table} VALUES {values}")
            options = "OPTION max_matches=2000,max_query_time=30000,expansion_limit=500"
            where = f"FROM {table} WHERE MATCH('re*')"
            results = query(client, f"SELECT file_hash {where} GROUP BY file_hash LIMIT 2000 {options}")
            count = query(client, f"SELECT count(distinct file_hash) AS n {where} {options}")[0][0]
            facets = query(client, f"SELECT grp, count(distinct file_hash) AS n {where} GROUP BY grp {options}")
            assert 0 < len(results) < 1200
            assert len(results) == count == sum(row[1] for row in facets)
        finally:
            query(client, f"DROP TABLE IF EXISTS {table}")
