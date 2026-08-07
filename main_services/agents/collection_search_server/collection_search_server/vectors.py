"""The vector half of collection search: embed the query, KNN every live `_vectors` shard.

A shard's `_vectors` table is the disposable HNSW copy of ClickHouse
`text_chunk_vectors` (see `main_services/processing/database/manticore.py`). The query
is embedded with the PROBED serving model (`server_settings.embeddings_serving_model`)
and its query-side prefix convention (`agent_common.embeddings.embedding_input`) —
never the configured ini value.

Two Manticore behaviours below were verified live against the running daemon
(14.1.0, 2026-08-07), not assumed from the docs:

* **Attribute filters pre-apply before k selection.** `WHERE grp='b' AND knn(v, 2, …)`
  returned the two nearest `b` rows even though the global top-2 were `a` rows. So a
  filtered KNN needs no over-fetch — the recall trap the plan warns about (filters
  applied AFTER k, returning near-empty sets from a healthy index) does not exist in
  this version. Collection search barely filters (the shard is already per-collection);
  what it relies on is the same mechanism.
* **`knn(v, k, …)` bounds nothing by itself** — without a LIMIT the query matched every
  row. The working shape is `WHERE knn(embedding, K, (…)) ORDER BY <alias> ASC LIMIT K`,
  with the alias because `ORDER BY knn_dist()` is a syntax error.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass

from collection_search_server.backends import (
    GLOBAL_DB,
    clickhouse_query,
    collection_db,
    manticore_query,
)

log = logging.getLogger(__name__)

#: Candidates per shard per search. HNSW makes a k=60 probe cheap; the fused pool is
#: capped again after the merge.
VECTOR_PER_SHARD = int(os.getenv("COLLECTION_SEARCH_VECTOR_PER_SHARD", "60"))

#: The serving model changes only when an admin re-probes; a search need not re-read
#: server_settings on every call.
_MODEL_CACHE_SECONDS = 300.0
_model_cache: tuple[float, str | None] = (0.0, None)

_VECTORS_TABLE_RE = re.compile(r"^[a-z0-9_]+_[0-9]+_vectors$")

#: Same content-hash rule as server.py — hashes heading for a SQL literal are validated
#: first. Duplicated rather than imported to keep this module usable without the server.
_HASH_RE = re.compile(r"^[0-9a-f]{32,128}$")


@dataclass
class VectorCandidate:
    collectionname: str
    collection_dataset: str
    file_hash: str
    extracted_by: str
    page_id: int
    chunk_index: int
    dist: float
    #: The chunk text, filled in from ClickHouse `text_chunks` after the KNN round.
    text: str = ""


def serving_model() -> str | None:
    """The probed serving model from `server_settings`, briefly cached."""
    global _model_cache
    fetched_at, model = _model_cache
    now = time.monotonic()
    if now - fetched_at < _MODEL_CACHE_SECONDS:
        return model
    rows = clickhouse_query(
        "SELECT argMax(value, updated_at) AS v FROM server_settings WHERE key = {k:String}",
        database=GLOBAL_DB,
        params={"k": "embeddings_serving_model"},
    )
    value = (rows[0].get("v") or "") if rows else ""
    _model_cache = (now, value or None)
    return _model_cache[1]


def _vector_tables(collectionname: str, existing: set[str]) -> list[str]:
    """Live `_vectors` tables of one collection: the ledger's shards, intersected with
    what Manticore actually has (a shard planned before P5 existed may have none yet).
    """
    rows = clickhouse_query(
        "SELECT DISTINCT shard_name FROM manticore_shards FINAL ORDER BY shard_name DESC",
        database=collection_db(collectionname),
    )
    tables = []
    for row in rows:
        name = f"{row.get('shard_name') or ''}_vectors"
        # Ledger-derived names are trusted, but the table name is interpolated into
        # SQL, so the regex is the belt to that braces.
        if _VECTORS_TABLE_RE.match(name) and name in existing:
            tables.append(name)
    return tables


def _existing_tables() -> set[str]:
    out: set[str] = set()
    for row in manticore_query("SHOW TABLES"):
        out.update(str(v) for v in row.values())
    return out


def search(query_vector: list[float], collections: list[str]) -> list[VectorCandidate]:
    """One distance-ordered vector ranking across every live `_vectors` shard.

    Distances are comparable across shards (one model, cosine), so the per-shard lists
    merge into a single ranking by `knn_dist()` — which is what the RRF fusion then
    consumes as the `vector` source.
    """
    if not query_vector or not collections:
        return []

    vector_csv = ",".join(repr(float(v)) for v in query_vector)
    existing = _existing_tables()
    hits: list[VectorCandidate] = []
    for collectionname in collections:
        for table in _vector_tables(collectionname, existing):
            sql = (
                f"SELECT collection_dataset, file_hash, extracted_by, page_id, chunk_index, "
                f"knn_dist() AS dist FROM {table} "
                f"WHERE knn(embedding, {VECTOR_PER_SHARD}, ({vector_csv})) "
                f"ORDER BY dist ASC LIMIT {VECTOR_PER_SHARD}"
            )
            try:
                rows = manticore_query(sql)
            except Exception as exc:  # noqa: BLE001 - one bad shard must not blank the search
                log.warning("vector shard %s failed: %s", table, exc)
                continue
            for row in rows:
                hits.append(
                    VectorCandidate(
                        collectionname=collectionname,
                        collection_dataset=str(row.get("collection_dataset") or ""),
                        file_hash=str(row.get("file_hash") or ""),
                        extracted_by=str(row.get("extracted_by") or ""),
                        page_id=int(row.get("page_id") or 0),
                        chunk_index=int(row.get("chunk_index") or 0),
                        dist=float(row.get("dist") or 0.0),
                    )
                )

    hits.sort(key=lambda h: h.dist)
    _attach_chunk_texts(hits)
    log.info(
        "vector search: %d candidates from %d collection(s)",
        len(hits), len(collections),
    )
    return hits


def _attach_chunk_texts(hits: list[VectorCandidate]) -> None:
    """Fill in each candidate's chunk text, one query per collection.

    The `_vectors` table carries no text (it is the disposable copy; ClickHouse
    `text_chunks` is the store of record), so a KNN hit is joined back here — the
    snippet the model reads and the document the reranker scores both come from this.
    """
    by_collection: dict[str, list[VectorCandidate]] = {}
    for hit in hits:
        by_collection.setdefault(hit.collectionname, []).append(hit)

    for collectionname, group in by_collection.items():
        hashes = sorted({h.file_hash for h in group if _HASH_RE.match(h.file_hash)})
        if not hashes:
            continue
        try:
            rows = clickhouse_query(
                "SELECT file_hash, extracted_by, page_id, chunk_index, text "
                "FROM text_chunks FINAL WHERE file_hash IN {hashes:Array(String)}",
                database=collection_db(collectionname),
                params={"hashes": "['" + "','".join(hashes) + "']"},
            )
        except Exception as exc:  # noqa: BLE001 - a missing snippet degrades one hit
            log.warning("chunk text lookup failed for %s: %s", collectionname, exc)
            continue
        texts = {
            (r["file_hash"], r["extracted_by"], int(r["page_id"]), int(r["chunk_index"])): r["text"]
            for r in rows
        }
        for hit in group:
            hit.text = texts.get(
                (hit.file_hash, hit.extracted_by, hit.page_id, hit.chunk_index), ""
            )
