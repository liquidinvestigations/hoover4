"""Activities that compute and store processing plans for new blobs."""

from temporalio import activity
from typing import Dict, Any
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import pyarrow as pa

from database.clickhouse import get_clickhouse_client


def _escape(v: str) -> str:
    return v.replace("'", "''")


@dataclass
class CountNewBlobsParams:
    collection_dataset: str


@activity.defn
def count_new_blobs(params: CountNewBlobsParams) -> int:
    """Activity that counts blobs not yet included in any processing plan."""
    collection_dataset: str = params.collection_dataset
    sql = f"""
        SELECT count()
        FROM blobs b
        WHERE b.collection_dataset = '{_escape(collection_dataset)}'
          AND NOT EXISTS (
              SELECT 1
              FROM processing_plan_hits h
              WHERE h.collection_dataset = b.collection_dataset
                AND h.item_hash = b.blob_hash
          )
    """
    with get_clickhouse_client() as client:
        tbl = client.query_arrow(sql)
        if tbl and tbl.num_rows:
            return int(tbl.column(0)[0].as_py())
        return 0


@dataclass
class ComputePlansParams:
    collection_dataset: str


@activity.defn
def compute_plans(params: ComputePlansParams) -> int:
    """Activity that computes processing plans and inserts rows for new blobs.

    Batching constraints:
    - max total size: 1GB
    - max items: 1000
    plan_hash = sha1(json.dumps(sorted(item_hashes)))
    Returns number of items planned.
    """
    collection_dataset: str = params.collection_dataset
    max_items = 1000
    max_bytes = 1_000_000_000

    def insert_plan(item_hashes: list, total_bytes: int):
        if not item_hashes:
            return
        sorted_hashes = sorted(item_hashes)
        payload = json.dumps(sorted_hashes, separators=(",", ":")).encode("utf-8")
        plan_hash = hashlib.sha1(payload).hexdigest()
        now = datetime.utcnow()
        with get_clickhouse_client() as client:
            # Insert into processing_plans
            tbl_plan = pa.table({
                "collection_dataset": pa.array([collection_dataset], type=pa.string()),
                "plan_hash": pa.array([plan_hash], type=pa.string()),
                "item_hashes": pa.array([sorted_hashes], type=pa.list_(pa.string())),
                "plan_size_bytes": pa.array([int(total_bytes)], type=pa.uint64()),
                "created_at": pa.array([now], type=pa.timestamp("s")),
            })
            client.insert_arrow("processing_plans", tbl_plan)

            # Insert hits
            tbl_hits = pa.table({
                "collection_dataset": pa.array([collection_dataset] * len(sorted_hashes), type=pa.string()),
                "item_hash": pa.array(sorted_hashes, type=pa.string()),
                "plan_hash": pa.array([plan_hash] * len(sorted_hashes), type=pa.string()),
            })
            client.insert_arrow("processing_plan_hits", tbl_hits)

    planned_items = 0
    cur_hashes = []
    cur_bytes = 0

    # One big SQL session: stream all new blobs ordered by size for better packing
    sql = f"""
        SELECT b.blob_hash, b.blob_size_bytes
        FROM blobs b
        LEFT JOIN processing_plan_hits h
          ON h.collection_dataset = b.collection_dataset AND h.item_hash = b.blob_hash
        WHERE b.collection_dataset = '{_escape(collection_dataset)}'
          AND h.item_hash = ''  AND h.plan_hash = ''
        ORDER BY b.blob_size_bytes ASC
    """
    with get_clickhouse_client() as client:
        with client.query_arrow_stream(sql) as stream:
            for batch in stream:
                if not batch or batch.num_rows == 0:
                    continue
                hh = batch.column("blob_hash")
                ss = batch.column("blob_size_bytes")
                for i in range(batch.num_rows):
                    h = hh[i].as_py()
                    s = int(ss[i].as_py() or 0)
                    # If single blob larger than 1GB, still make a single-item plan
                    if not cur_hashes:
                        cur_hashes = [h]
                        cur_bytes = s
                    else:
                        if len(cur_hashes) >= max_items or (cur_bytes + s) > max_bytes:
                            insert_plan(cur_hashes, cur_bytes)
                            planned_items += len(cur_hashes)
                            cur_hashes = [h]
                            cur_bytes = s
                        else:
                            cur_hashes.append(h)
                            cur_bytes += s

    if cur_hashes:
        insert_plan(cur_hashes, cur_bytes)
        planned_items += len(cur_hashes)

    return planned_items


