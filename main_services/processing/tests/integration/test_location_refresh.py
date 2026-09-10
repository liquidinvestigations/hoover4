"""Known content that gains a location must become searchable there without extraction.

Requires the docker stack. Run inside the worker container:

``docker exec hoover4-worker uv run pytest tests/integration/test_location_refresh.py --integration -q``
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

import pytest

from database.clickhouse import get_collection_client
from database.manticore import get_manticore_client, list_shard_tables
from tasks.P6_index_data.activities import FILENAME_EXTRACTED_BY, build_vfs_nodes, refresh_stale_document_locations
from tasks.P6_index_data.location_refresh import (
    list_stale_location_hashes,
    parse_mva_ids,
)
from tasks.P6_index_data.params import (
    BuildVfsNodesParams,
    RefreshDocumentLocationsParams,
)
from tasks.P6_index_data.vfs_nodes import ancestor_node_keys, container_parents_from_nodes
from tasks.P6_index_data.string_term_encodings import hash_string_to_uint63

from .helpers import ingest_dataset, wait_for_plans_finished

pytestmark = [pytest.mark.integration, pytest.mark.timeout(3600)]

HELLO = "hello.txt"


def _content_hash(path: Path) -> str:
    return hashlib.sha3_256(path.read_bytes()).hexdigest()


def _counts(collectionname: str, collection_dataset: str, file_hash: str) -> dict[str, int]:
    with get_collection_client(collectionname) as client:
        plans = client.query(
            "SELECT count() FROM processing_plans FINAL "
            "WHERE collection_dataset = {cd:String}",
            parameters={"cd": collection_dataset},
        ).result_rows[0][0]
        text = client.query(
            "SELECT count() FROM text_content FINAL "
            "WHERE collection_dataset = {cd:String} AND file_hash = {h:String}",
            parameters={"cd": collection_dataset, "h": file_hash},
        ).result_rows[0][0]
        nlp = client.query(
            "SELECT count() FROM nlp_processed FINAL "
            "WHERE collection_dataset = {cd:String} AND file_hash = {h:String}",
            parameters={"cd": collection_dataset, "h": file_hash},
        ).result_rows[0][0]
        vectors = client.query(
            "SELECT count() FROM text_chunk_vectors FINAL "
            "WHERE collection_dataset = {cd:String} AND file_hash = {h:String}",
            parameters={"cd": collection_dataset, "h": file_hash},
        ).result_rows[0][0]
        locations = client.query(
            "SELECT count() FROM vfs_files FINAL "
            "WHERE collection_dataset = {cd:String} AND hash = {h:String}",
            parameters={"cd": collection_dataset, "h": file_hash},
        ).result_rows[0][0]
    return {
        "plans": int(plans),
        "text": int(text),
        "nlp": int(nlp),
        "vectors": int(vectors),
        "hello_locations": int(locations),
    }


def _hello_hash(collectionname: str, collection_dataset: str) -> str:
    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT hash FROM vfs_files FINAL "
            "WHERE collection_dataset = {cd:String} AND path LIKE {p:String} "
            "LIMIT 1",
            parameters={"cd": collection_dataset, "p": f"%/{HELLO}"},
        ).result_rows
    assert rows, f"no vfs_files row for {HELLO}"
    return rows[0][0]


def _indexed_path_ids(collectionname: str, collection_dataset: str, file_hash: str) -> frozenset[int]:
    with get_manticore_client() as cnx:
        cur = cnx.cursor()
        for table in list_shard_tables(collectionname):
            if not table.endswith("_pages"):
                continue
            cur.execute(
                f"SELECT file_paths FROM {table} "
                "WHERE collection_dataset = %s AND file_hash = %s "
                "AND extracted_by = %s "
                "LIMIT 1 OPTION max_matches=1",
                (collection_dataset, file_hash, FILENAME_EXTRACTED_BY),
            )
            row = cur.fetchone()
            if row:
                return parse_mva_ids(row[0])
    return frozenset()


def _expected_path_ids(collectionname: str, collection_dataset: str, file_hash: str) -> frozenset[int]:
    with get_collection_client(collectionname) as client:
        vfs_rows = client.query_arrow("""
            SELECT container_hash, path FROM vfs_files FINAL
            WHERE collection_dataset = {cd:String} AND hash = {h:String}
        """, {"cd": collection_dataset, "h": file_hash}).to_pylist()
        node_rows = client.query_arrow("""
            SELECT container_hash, path, kind, file_hash
            FROM vfs_nodes FINAL
            WHERE collection_dataset = {cd:String}
        """, {"cd": collection_dataset}).to_pylist()
    locations = [(r["container_hash"] or "", r["path"]) for r in vfs_rows]
    keys, _ = ancestor_node_keys(
        collection_dataset, locations, container_parents_from_nodes(node_rows)
    )
    return frozenset(hash_string_to_uint63(k) for k in keys)


def _rescan(collectionname: str, dataset_name: str, path: str) -> None:
    import asyncio

    from tasks.P0_scan_disk.submit_job import add_disk_dataset
    from tasks.P1_compute_plans.submit_job import submit_compute_plans
    from tasks.P2_execute_plan.submit_job import submit_execute_plans

    add_disk_dataset(collectionname, dataset_name, path)
    from tasks.P0_scan_disk.submit_job import compose_collection_dataset

    collection_dataset = compose_collection_dataset(collectionname, dataset_name)
    asyncio.run(submit_compute_plans(collectionname, collection_dataset))
    asyncio.run(submit_execute_plans(collectionname, collection_dataset))
    wait_for_plans_finished(collectionname)


def test_disk_rescan_of_known_bytes_refreshes_locations(
    temp_collection, tiny_dataset, tmp_path
):
    root = tmp_path / "root"
    shutil.copytree(tiny_dataset, root)
    collectionname = temp_collection
    collection_dataset = ingest_dataset(collectionname, "tiny", str(root))
    wait_for_plans_finished(collectionname)

    hello_hash = _content_hash(root / HELLO)
    assert _hello_hash(collectionname, collection_dataset) == hello_hash
    before = _counts(collectionname, collection_dataset, hello_hash)
    before_ids = _indexed_path_ids(collectionname, collection_dataset, hello_hash)
    assert before_ids

    (root / "copy").mkdir()
    shutil.copy(root / HELLO, root / "copy" / HELLO)

    from tasks.P0_scan_disk.submit_job import add_disk_dataset

    add_disk_dataset(collectionname, "tiny", str(root))
    stale_after_scan = _counts(collectionname, collection_dataset, hello_hash)
    assert stale_after_scan["plans"] == before["plans"]
    assert stale_after_scan["hello_locations"] == before["hello_locations"] + 1
    assert stale_after_scan["text"] == before["text"]
    scan_ids = _indexed_path_ids(collectionname, collection_dataset, hello_hash)
    assert scan_ids == before_ids, (
        "scan-only must leave indexed folder attributes on the previous locations"
    )

    import asyncio
    from tasks.P1_compute_plans.submit_job import submit_compute_plans
    from tasks.P2_execute_plan.submit_job import submit_execute_plans

    asyncio.run(submit_compute_plans(collectionname, collection_dataset))
    asyncio.run(submit_execute_plans(collectionname, collection_dataset))
    wait_for_plans_finished(collectionname)

    after = _counts(collectionname, collection_dataset, hello_hash)
    assert after["plans"] == before["plans"]
    assert after["text"] == before["text"]
    assert after["nlp"] == before["nlp"]
    assert after["vectors"] == before["vectors"]
    assert after["hello_locations"] == before["hello_locations"] + 1
    after_ids = _indexed_path_ids(collectionname, collection_dataset, hello_hash)
    expected = _expected_path_ids(collectionname, collection_dataset, hello_hash)
    assert after_ids == expected
    assert before_ids < after_ids


def test_archive_location_of_known_bytes_refreshes_without_extraction(
    temp_collection, tiny_dataset, tmp_path
):
    root = tmp_path / "root"
    shutil.copytree(tiny_dataset, root)
    collectionname = temp_collection
    collection_dataset = ingest_dataset(collectionname, "tiny", str(root))
    wait_for_plans_finished(collectionname)

    hello_hash = _content_hash(root / HELLO)
    before = _counts(collectionname, collection_dataset, hello_hash)
    before_ids = _indexed_path_ids(collectionname, collection_dataset, hello_hash)

    with zipfile.ZipFile(root / "hello.zip", "w") as archive:
        archive.write(root / HELLO, HELLO)

    _rescan(collectionname, "tiny", str(root))

    after = _counts(collectionname, collection_dataset, hello_hash)
    assert after["text"] == before["text"]
    assert after["nlp"] == before["nlp"]
    assert after["vectors"] == before["vectors"]
    assert after["hello_locations"] > before["hello_locations"]
    after_ids = _indexed_path_ids(collectionname, collection_dataset, hello_hash)
    expected = _expected_path_ids(collectionname, collection_dataset, hello_hash)
    assert after_ids == expected
    assert before_ids < after_ids


def test_local_stale_index_recovery_rewrites_only_affected_hashes(
    temp_collection, tiny_dataset, tmp_path
):
    root = tmp_path / "root"
    shutil.copytree(tiny_dataset, root)
    collectionname = temp_collection
    collection_dataset = ingest_dataset(collectionname, "tiny", str(root))
    wait_for_plans_finished(collectionname)

    hello_hash = _content_hash(root / HELLO)
    before = _counts(collectionname, collection_dataset, hello_hash)
    (root / "copy").mkdir()
    shutil.copy(root / HELLO, root / "copy" / HELLO)

    from tasks.P0_scan_disk.submit_job import add_disk_dataset

    add_disk_dataset(collectionname, "tiny", str(root))
    build_vfs_nodes(BuildVfsNodesParams(
        collectionname=collectionname, collection_dataset=collection_dataset,
    ))
    selected, indexed_count, mechanism = list_stale_location_hashes(
        collectionname, collection_dataset, [],
    )
    assert hello_hash in selected
    assert indexed_count >= 1
    assert mechanism == "affected-documents"
    assert len(selected) < indexed_count

    result = refresh_stale_document_locations(RefreshDocumentLocationsParams(
        collectionname=collectionname,
        collection_dataset=collection_dataset,
        item_hashes=selected,
    ))
    after = _counts(collectionname, collection_dataset, hello_hash)
    assert after["text"] == before["text"]
    assert after["nlp"] == before["nlp"]
    assert after["vectors"] == before["vectors"]
    assert after["plans"] == before["plans"]
    assert hello_hash in result.refreshed_hashes
    after_ids = _indexed_path_ids(collectionname, collection_dataset, hello_hash)
    expected = _expected_path_ids(collectionname, collection_dataset, hello_hash)
    assert after_ids == expected
