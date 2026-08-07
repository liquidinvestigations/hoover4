"""Chunk+embed stage (P5) activities: chunk every text segment, embed every chunk.

Runs on ``processing-embed-queue``. The stage writes two collection-DB tables:

* ``text_chunks`` — the chunks themselves (model-independent: byte offsets and text);
* ``text_chunk_vectors`` — the durable embeddings, keyed WITH ``embedding_model`` so a
  model change adds rows rather than replacing them. Manticore's ``_vectors`` shards
  are a disposable HNSW copy of this table, written by the P6 vector indexer.

Failure policy matches P4: errors are NOT swallowed — an exception fails the activity
so Temporal retries it, and only after retries are exhausted does the workflow record
the failure in ``processing_errors``. The two non-retryable cases are config lies
(a missing probe, or a server serving a different model/dimension than the probe
recorded): retrying those cannot help, and proceeding would write vectors under a
convention or dimension the search side does not share.

Idempotency: the left-anti join against ``text_chunk_vectors`` on
``(collection_dataset, file_hash, extracted_by, page_id, chunk_index, embedding_model)``
makes a re-run embed exactly the chunks that never got a vector. Chunking is
deterministic (``chunking.py``), so the re-run reproduces the same chunk keys.
"""

import logging
import os

from temporalio import activity
from temporalio.exceptions import ApplicationError

from database.clickhouse import get_collection_client, get_server_setting
from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.remote import post_json

from .chunking import chunk_page_text
from .embedding_prefix import embedding_input
from .params import ChunkEmbedParams, ChunkEmbedResult

log = logging.getLogger(__name__)

#: Texts per embeddings request. Bounds request size and makes partial progress
#: possible (today's alternative is the whole activity chunk in one request).
EMBED_BATCH_TEXTS = 32


def _probed_serving() -> tuple[str, int]:
    """The ``(model, dims)`` the GPU tier actually serves, from the startup probe.

    Never the ini: the ini is the request and this probe is the truth, and a Manticore
    ``_vectors`` table's ``knn_dims`` is fixed at creation, so building on the requested
    dimension instead of the served one is the failure the probe exists to prevent.
    """
    model = get_server_setting("embeddings_serving_model")
    dims_raw = get_server_setting("embeddings_serving_dim")
    if not model or not dims_raw:
        raise ApplicationError(
            "embeddings_serving_model/_dim are not in server_settings; run "
            "`main.py probe-embeddings` (it records what the endpoint ACTUALLY serves)",
            non_retryable=True,
        )
    return model, int(dims_raw)


@activity.defn
@with_heartbeat
def chunk_embed_for_hashes(params: ChunkEmbedParams) -> ChunkEmbedResult:
    """Chunk the plan's text segments and embed the chunks that have no vector yet.

    Segments already present in ``text_chunk_vectors`` for the probed serving model are
    skipped (left-anti join), which makes the stage cheaply re-runnable.
    """
    collection_dataset: str = params.collection_dataset
    item_hashes: list[str] = params.hashes
    plan_hash: str = params.plan_hash
    heartbeat = HeartbeatClock()

    base_url = (os.getenv("EMBEDDINGS_URL") or "").strip().rstrip("/")
    if not base_url:
        # embeddings_provider = none is a legitimate configuration: the stage is a
        # no-op, not a failure. Logged so an unexpected skip is traceable.
        log.info(
            "%s (plan %s): EMBEDDINGS_URL is empty (embeddings_provider = none); skipping chunk+embed",
            collection_dataset, plan_hash[:8],
        )
        return ChunkEmbedResult(text_segments=0, chunks_written=0, vectors_written=0)

    serving_model, serving_dims = _probed_serving()
    heartbeat.beat("querying text_content")

    with get_collection_client(params.collectionname) as client:
        text_content = client.query_arrow("""
            SELECT collection_dataset, file_hash, extracted_by, page_id, text
            FROM text_content
            WHERE collection_dataset = {collection_dataset:String}
            AND file_hash IN {item_hashes:Array(String)}
            ORDER BY file_hash, extracted_by, page_id
        """, {
            "collection_dataset": collection_dataset,
            "item_hashes": item_hashes,
        }).to_pylist()

    if not text_content:
        log.info("%s (plan %s): nothing to chunk+embed", collection_dataset, plan_hash[:8])
        return ChunkEmbedResult(text_segments=0, chunks_written=0, vectors_written=0)

    # Chunk every segment, then keep only the chunks with no vector for the serving
    # model. The anti-join key is the full vector-row identity, chunk_index included:
    # a crash between batches leaves a page half-embedded, and only the missing
    # chunks may be redone.
    candidates: list[dict] = []
    for row in text_content:
        for chunk in chunk_page_text(row["text"]):
            candidates.append({
                "collection_dataset": row["collection_dataset"],
                "file_hash": row["file_hash"],
                "extracted_by": row["extracted_by"],
                "page_id": row["page_id"],
                "chunk_index": chunk.chunk_index,
                "index_start": chunk.index_start,
                "index_end": chunk.index_end,
                "text": chunk.text,
            })
    heartbeat.beat(f"chunked {len(text_content)} segments into {len(candidates)} chunks")

    with get_collection_client(params.collectionname) as client:
        existing = {
            (r[0], r[1], int(r[2]), int(r[3]))
            for r in client.query("""
                SELECT file_hash, extracted_by, page_id, chunk_index
                FROM text_chunk_vectors FINAL
                WHERE collection_dataset = {collection_dataset:String}
                AND file_hash IN {item_hashes:Array(String)}
                AND embedding_model = {model:String}
            """, {
                "collection_dataset": collection_dataset,
                "item_hashes": item_hashes,
                "model": serving_model,
            }).result_rows
        }

    missing = [
        c for c in candidates
        if (c["file_hash"], c["extracted_by"], c["page_id"], c["chunk_index"]) not in existing
    ]
    if not missing:
        log.info(
            "%s (plan %s): all %d chunks already embedded via %s",
            collection_dataset, plan_hash[:8], len(candidates), serving_model,
        )
        return ChunkEmbedResult(text_segments=len(text_content), chunks_written=0, vectors_written=0)

    # Chunk rows go in before the first vector of their page: a vector without its
    # chunk row would be a KNN hit with no text to rerank or render. Only pages with
    # missing vectors are (re)written — text_chunks is keyed without the model, and
    # the content is deterministic, so a rewrite would only bump updated_at.
    pages_needing_work = {
        (c["file_hash"], c["extracted_by"], c["page_id"]) for c in missing
    }
    chunk_rows = [
        [c["collection_dataset"], c["file_hash"], c["extracted_by"], c["page_id"],
         c["chunk_index"], c["index_start"], c["index_end"], c["text"],
         len(c["text"].encode("utf-8"))]
        for c in candidates
        if (c["file_hash"], c["extracted_by"], c["page_id"]) in pages_needing_work
    ]
    with get_collection_client(params.collectionname) as client:
        client.insert(
            "text_chunks",
            chunk_rows,
            column_names=["collection_dataset", "file_hash", "extracted_by", "page_id",
                          "chunk_index", "index_start", "index_end", "text", "text_bytes"],
        )
    heartbeat.beat(f"wrote {len(chunk_rows)} chunk rows")

    vectors_written = 0
    for i in range(0, len(missing), EMBED_BATCH_TEXTS):
        batch = missing[i:i + EMBED_BATCH_TEXTS]
        prefixed = [embedding_input(serving_model, "passage", c["text"])[0] for c in batch]
        result = post_json(
            [("embeddings", f"{base_url}/embeddings")],
            {"input": prefixed},
        )
        data = result.data
        served_model = data.get("model") or ""
        if served_model != serving_model:
            # The probe is stale. The rows would be written under a model the anti-join
            # never matches (re-embedding forever) and possibly under the wrong prefix
            # convention. Refuse loudly instead.
            raise ApplicationError(
                f"embeddings endpoint serves {served_model!r} but the probe recorded "
                f"{serving_model!r}; run `main.py probe-embeddings`",
                non_retryable=True,
            )
        embeddings = [None] * len(batch)
        for item in data["data"]:
            embeddings[int(item["index"])] = [float(v) for v in item["embedding"]]
        if any(e is None for e in embeddings):
            raise ApplicationError(
                f"embeddings endpoint returned {sum(e is not None for e in embeddings)} "
                f"vectors for {len(batch)} texts",
                non_retryable=True,
            )
        dims = {len(e) for e in embeddings}
        if dims != {serving_dims}:
            raise ApplicationError(
                f"embeddings endpoint served dims {sorted(dims)} but the probe recorded "
                f"{serving_dims}; run `main.py probe-embeddings`",
                non_retryable=True,
            )

        with get_collection_client(params.collectionname) as client:
            client.insert(
                "text_chunk_vectors",
                [
                    [c["collection_dataset"], c["file_hash"], c["extracted_by"], c["page_id"],
                     c["chunk_index"], served_model, serving_dims, embedding]
                    for c, embedding in zip(batch, embeddings)
                ],
                column_names=["collection_dataset", "file_hash", "extracted_by", "page_id",
                              "chunk_index", "embedding_model", "dims", "embedding"],
            )
        vectors_written += len(batch)
        # In-loop heartbeat: evidence of forward progress, not merely of a live thread.
        heartbeat.beat(f"embedded {vectors_written}/{len(missing)} chunks")
        log.info(
            "%s (plan %s): embedded %d/%d chunks via %s",
            collection_dataset, plan_hash[:8], vectors_written, len(missing), served_model,
        )

    log.info(
        "%s (plan %s): chunked %d segments, wrote %d chunk rows and %d vectors",
        collection_dataset, plan_hash[:8], len(text_content), len(chunk_rows), vectors_written,
    )
    return ChunkEmbedResult(
        text_segments=len(text_content),
        chunks_written=len(chunk_rows),
        vectors_written=vectors_written,
    )
