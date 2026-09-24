"""Duplicate blob rows must produce one processing-plan item."""

import pyarrow as pa
import pytest

from database.clickhouse import get_collection_client
from tasks.P1_compute_plans.activities import ComputePlansParams, compute_plans


pytestmark = pytest.mark.integration


def test_compute_plans_groups_duplicate_blob_hashes(temp_collection):
    collection_dataset = f"{temp_collection}_duplicate_blobs"
    with get_collection_client(temp_collection) as client:
        client.insert_arrow("blobs", pa.table({
            "collection_dataset": pa.array([collection_dataset, collection_dataset]),
            "blob_hash": pa.array(["duplicate-hash", "duplicate-hash"]),
            "blob_size_bytes": pa.array([7, 11], type=pa.uint64()),
            "md5": pa.array(["", ""]),
            "sha1": pa.array(["", ""]),
            "sha256": pa.array(["", ""]),
            "s3_path": pa.array(["", ""]),
            "stored_in_clickhouse": pa.array([1, 1], type=pa.uint8()),
        }))

    assert compute_plans(ComputePlansParams(temp_collection, collection_dataset)) == 1

    with get_collection_client(temp_collection) as client:
        rows = client.query(
            "SELECT item_hashes, plan_size_bytes FROM processing_plans FINAL "
            "WHERE collection_dataset = {dataset:String}",
            parameters={"dataset": collection_dataset},
        ).result_rows
    assert rows == [(["duplicate-hash"], 11)]
