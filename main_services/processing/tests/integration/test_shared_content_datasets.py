"""Integration test: two datasets in one collection sharing the same content.

Blobs are content-addressed, so ingesting the same path twice under two dataset
names puts the same file_hash into two datasets of one collection. Document
identity for indexing is the ``(collection_dataset, file_hash)`` PAIR (
contract): each pair lives in exactly one shard, and the shared content is
indexed once per dataset. This is the test that pins that invariant.

Requires the docker stack; run inside the worker container:
``docker exec -it hoover4-worker uv run pytest tests/integration --integration -q``
"""

import pytest

from database.clickhouse import get_collection_client
from database.manticore import get_manticore_client, list_shard_tables

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]


def _manticore_pair_count(collectionname: str) -> int:
    """Distinct (collection_dataset, file_hash) pairs over all shard meta tables.

    Manticore has no ``count(distinct concat(...))``: GROUP BY the pair and
    count the rows.
    """
    total = 0
    with get_manticore_client() as cnx:
        cursor = cnx.cursor()
        for table in list_shard_tables(collectionname):
            if not table.endswith("_pages"):
                continue
            cursor.execute(
                f"SELECT collection_dataset, file_hash FROM {table} "
                "GROUP BY collection_dataset, file_hash LIMIT 100000"
            )
            total += len(cursor.fetchall())
    return total


def test_two_datasets_sharing_content(temp_collection, tiny_dataset):
    collectionname = temp_collection
    cd1 = ingest_dataset(collectionname, "tiny", str(tiny_dataset))
    cd2 = ingest_dataset(collectionname, "tiny2", str(tiny_dataset))
    assert cd1 != cd2
    wait_for_plans_finished(collectionname)

    with get_collection_client(collectionname) as client:
        assignments = client.query(
            "SELECT collection_dataset, file_hash, shard_name "
            "FROM manticore_shard_assignments FINAL"
        ).result_rows
        per_pair = client.query(
            "SELECT collection_dataset, file_hash, uniqExact(shard_name) AS n "
            "FROM manticore_shard_assignments FINAL "
            "GROUP BY collection_dataset, file_hash"
        ).result_rows
        index_state_count = client.query(
            "SELECT count() FROM index_state FINAL"
        ).result_rows[0][0]

    hashes1 = {h for cd, h, _ in assignments if cd == cd1}
    hashes2 = {h for cd, h, _ in assignments if cd == cd2}
    assert hashes1, "first dataset must be indexed"
    assert hashes1 == hashes2, "same path ingested twice must yield the same content hashes"

    docs_per_dataset = len(hashes1)
    # Every (dataset, file_hash) PAIR in exactly one shard, even though the same
    # file_hash legitimately appears twice (once per dataset).
    assert all(int(n) == 1 for _cd, _h, n in per_pair)
    assert len(assignments) == len(per_pair) == 2 * docs_per_dataset
    # What actually reached a shard: one copy per dataset.
    assert int(index_state_count) == 2 * docs_per_dataset
    assert _manticore_pair_count(collectionname) == 2 * docs_per_dataset
