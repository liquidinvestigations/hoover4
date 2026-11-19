"""Chunk+embed stage (P5) activities: chunk every text segment, embed every chunk.

Runs on ``processing-embed-queue``. The stage writes two collection-DB tables:

* ``text_chunks``, the chunks themselves (model-independent: byte offsets and text);
* ``text_chunk_vectors``, the durable embeddings, keyed WITH ``embedding_model`` so a
  model change adds rows rather than replacing them. Manticore's ``_vectors`` shards
  are a disposable HNSW copy of this table, written by the P6 vector indexer.

Failure policy matches P4: errors are NOT swallowed. An exception fails the activity
so Temporal retries it, and only after retries are exhausted does the workflow record
the failure in ``processing_errors``. The two non-retryable cases are configuration mismatches
(a missing probe, or a server serving a different model/dimension than the probe
recorded): retrying those cannot help, and proceeding would write vectors under a
convention or dimension the search side does not share.

Idempotency: the left-anti join against ``text_chunk_vectors`` on
``(collection_dataset, file_hash, extracted_by, page_id, chunk_index, embedding_model)``
makes a re-run embed exactly the chunks that never got a current vector. Chunking is
deterministic (``chunking.py``), so the re-run reproduces the same chunk keys.

A vector is current when it is not older than its page text: its ``updated_at`` second
is not before the second of the page's newest ``text_content.version``. A page whose
text was replaced is embedded again. Vectors and chunk rows of chunk indexes that the
current text no longer has, and of pages that the text no longer has, are deleted.
A page without a chunk worth a vector gets an empty-page receipt
(``EMPTY_PAGE_RECEIPT``) for its text version, so the vector update selects it once.
"""

import logging
import os

from temporalio import activity
from temporalio.exceptions import ApplicationError

from database.clickhouse import get_collection_client, get_server_setting
from database.manticore import limit_encoded_runs
from tasks.remote_busy_retry import with_remote_outage_retry
from tasks.heartbeat import HeartbeatClock, stop_if_worker_is_stopping, with_heartbeat
from tasks.remote import gpu_headers, post_json
from tasks.text_quality import non_linguistic_reason
from tasks.text_sources import pages_over_work_limit

from .chunking import chunk_page_text
from .embedding_prefix import embedding_input
from .params import ChunkEmbedParams, ChunkEmbedResult

log = logging.getLogger(__name__)

#: Texts per embeddings request. Bounds request size and makes partial progress
#: possible (today's alternative is the whole activity chunk in one request).
EMBED_BATCH_TEXTS = 32

#: The `processing_output_receipts.output_kind` of a page that has no chunk worth a
#: vector. `output_identity` is `<extracted_by>:<page_id>`, `fingerprint` is
#: `<model>:<text version>`. The vector update selector reads it.
EMPTY_PAGE_RECEIPT = "vector_page_empty"

#: Keys in one DELETE of obsolete chunk or vector rows.
DELETE_KEY_BATCH = 2000


def _delete_chunk_keys(client, collection_dataset: str, model: str, keys) -> None:
    """Delete the vector rows of `model` and the chunk rows of the given chunk keys."""
    keys = sorted(keys)
    for start in range(0, len(keys), DELETE_KEY_BATCH):
        batch = keys[start:start + DELETE_KEY_BATCH]
        for table, model_clause in (("text_chunk_vectors", " AND embedding_model = {model:String}"),
                                    ("text_chunks", "")):
            client.command(
                f"DELETE FROM {table} WHERE collection_dataset = {{cd:String}} "
                "AND (file_hash, extracted_by, page_id, chunk_index) IN "
                "{keys:Array(Tuple(String, String, UInt32, UInt32))}" + model_clause +
                " SETTINGS mutations_sync = 2",
                parameters={"cd": collection_dataset, "keys": batch, "model": model})


def _write_empty_page_receipts(client, params: ChunkEmbedParams, model: str, pages) -> None:
    """Record the pages, `(file_hash, extracted_by, page_id, text version)`, without a vector."""
    if not pages:
        return
    rows = [[params.collection_dataset, file_hash, EMPTY_PAGE_RECEIPT, f"{source}:{int(page)}",
             f"{model}:{int(version)}", "embed", params.op_id]
            for file_hash, source, page, version in sorted(pages)]
    client.insert("processing_output_receipts", rows,
                  column_names=["collection_dataset", "file_hash", "output_kind", "output_identity",
                                "fingerprint", "stage", "op_id"])


def _delete_removed_pages(client, collection_dataset: str, model: str, hashes) -> int:
    """Delete chunk and vector rows of pages that `text_content` no longer has."""
    keys = [tuple(row) for row in client.query(
        "SELECT file_hash, extracted_by, page_id, chunk_index FROM text_chunk_vectors "
        "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
        "AND embedding_model = {model:String} AND (file_hash, extracted_by, page_id) NOT IN "
        "(SELECT file_hash, extracted_by, page_id FROM text_content "
        "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)})",
        parameters={"cd": collection_dataset, "hashes": list(hashes), "model": model}).result_rows]
    _delete_chunk_keys(client, collection_dataset, model, set(keys))
    return len(keys)

#: Text segments pulled into memory at once, per pass.
#:
#: The unit of work here is a SEGMENT, never a file. A hash is one file and a file is
#: not bounded: a single 209 MB text document is one hash whose `text_content` expands
#: to millions of chunks, and materialising all of them -- the rows, the chunk dicts,
#: the anti-join key set and the insert rows are four separate copies -- took the worker
#: container past its memory limit. The kernel then killed the process inside the
#: cgroup, Temporal lost the activity, and the retry did exactly the same thing.
#:
#: No amount of batching by the CALLER can fix that, because one hash is indivisible
#: there. The activity has to page, and this is the page size.
SEGMENT_PAGE_ROWS = 200


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
@with_remote_outage_retry
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
        # Embeddings off is a valid configuration: the stage does nothing and succeeds.
        # Logged so an unexpected skip is traceable.
        log.info(
            "%s (plan %s): EMBEDDINGS_URL is empty ([ai_services] embeddings_enabled or the GPU tier is off); skipping chunk+embed",
            collection_dataset, plan_hash[:8],
        )
        return ChunkEmbedResult(text_segments=0, chunks_written=0, vectors_written=0)
    from tasks.dataset_config import collection_vectors_enabled
    if not collection_vectors_enabled(params.collectionname):
        # The collection switch `features.vectors` is off. Stored vectors stay, and no
        # new vector is written until the switch is on again.
        log.info("%s (plan %s): vectors are off for collection %s; skipping chunk+embed",
                 collection_dataset, plan_hash[:8], params.collectionname)
        return ChunkEmbedResult(text_segments=0, chunks_written=0, vectors_written=0)

    serving_model, serving_dims = _probed_serving()
    heartbeat.beat("querying text_content")

    # Keyset pagination on the ORDER BY prefix, not OFFSET: OFFSET re-reads everything
    # before it, which on a multi-million-segment file is quadratic.
    #
    # Group versions before applying the page limit.
    def _segment_pages():
        after = ("", "", 0)
        while True:
            with get_collection_client(params.collectionname) as page_client:
                rows = page_client.query_arrow("""
                    SELECT collection_dataset, file_hash, extracted_by, page_id, argMax(text, version) AS text,
                           max(version) AS version
                    FROM text_content
                    WHERE collection_dataset = {collection_dataset:String}
                    AND file_hash IN {item_hashes:Array(String)}
                    AND (file_hash, extracted_by, page_id) >
                        ({after_hash:String}, {after_by:String}, {after_page:UInt32})
                    GROUP BY collection_dataset, file_hash, extracted_by, page_id
                    ORDER BY file_hash, extracted_by, page_id
                    LIMIT {page_rows:UInt32}
                """, {
                    "collection_dataset": collection_dataset,
                    "item_hashes": item_hashes,
                    "after_hash": after[0],
                    "after_by": after[1],
                    "after_page": after[2],
                    "page_rows": SEGMENT_PAGE_ROWS,
                }).to_pylist()
            if not rows:
                return
            last = rows[-1]
            after = (last["file_hash"], last["extracted_by"], int(last["page_id"]))
            yield rows

    with get_collection_client(params.collectionname) as limit_client:
        over_limit = pages_over_work_limit(limit_client, collection_dataset, item_hashes)

    total_segments = 0
    total_chunk_rows = 0
    total_vectors = 0
    total_skipped_non_linguistic = 0
    saw_any = False

    for text_content in _segment_pages():
        # A page over the work limit gets no vector on purpose. Its receipt keeps the
        # vector update from selecting it again.
        skipped_pages = {(row["file_hash"], row["extracted_by"], int(row["page_id"]), int(row["version"]))
                         for row in text_content
                         if (row["file_hash"], row["extracted_by"], int(row["page_id"])) in over_limit}
        text_content = [row for row in text_content if (
            row["file_hash"], row["extracted_by"], int(row["page_id"])) not in over_limit]
        # Page boundary. Every page before this one is fully written, and the anti-join
        # above skips it on the next attempt, so a worker being drained gives the batch
        # back here rather than being killed part-way through a page.
        stop_if_worker_is_stopping(
            f"{collection_dataset} plan {plan_hash[:8]}: {total_vectors} vectors written")
        saw_any = True
        total_segments += len(text_content)
        # Scoped to this page: the anti-join below must not pull back the key set of a
        # whole multi-million-chunk file.
        page_keys = sorted({
            (r["file_hash"], r["extracted_by"], int(r["page_id"])) for r in text_content
        })
        # Chunk every segment, then keep only the chunks with no vector for the serving
        # model. The anti-join key is the full vector-row identity, chunk_index included:
        # a crash between batches leaves a page half-embedded, and only the missing
        # chunks may be redone.
        candidates: list[dict] = []
        skipped_non_linguistic = 0
        skip_examples: list[str] = []
        for row in text_content:
            for chunk in chunk_page_text(row["text"]):
                # Text extraction is greedy on purpose, so it also yields an email
                # attachment's base64 and an image's pixel rows. Embedding those costs GPU
                # time to produce a vector that then wins searches it has no business
                # winning: live, an `.xpm` colour table was the top hit for "Eiffel Tower
                # height". `text_content` still holds every byte; only the embedding and the
                # KNN index skip them.
                reason = non_linguistic_reason(chunk.text)
                if reason:
                    skipped_non_linguistic += 1
                    if len(skip_examples) < 3:
                        skip_examples.append(
                            f"{row['file_hash'][:8]} p{row['page_id']}#{chunk.chunk_index}: {reason}"
                        )
                    continue
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
        if skipped_non_linguistic:
            log.info(
                "%s (plan %s): skipped %d non-linguistic chunk(s) before embedding, e.g. %s",
                collection_dataset, plan_hash[:8], skipped_non_linguistic, "; ".join(skip_examples),
            )
        total_skipped_non_linguistic += skipped_non_linguistic
        heartbeat.beat(f"chunked {total_segments} segments so far; "
                       f"{len(candidates)} chunks on this page")

        with get_collection_client(params.collectionname) as client:
            # Each existing vector with the second of its write.
            existing = {
                (r[0], r[1], int(r[2]), int(r[3])): int(r[4])
                for r in client.query("""
                    SELECT file_hash, extracted_by, page_id, chunk_index,
                           toUInt64(toUnixTimestamp(updated_at))
                    FROM text_chunk_vectors FINAL
                    WHERE collection_dataset = {collection_dataset:String}
                    AND (file_hash, extracted_by, page_id) IN {page_keys:Array(Tuple(String, String, UInt32))}
                    AND embedding_model = {model:String}
                """, {
                    "collection_dataset": collection_dataset,
                    "page_keys": page_keys,
                    "model": serving_model,
                }).result_rows
            }
            stored_chunks = {
                (r[0], r[1], int(r[2]), int(r[3]))
                for r in client.query("""
                    SELECT file_hash, extracted_by, page_id, chunk_index FROM text_chunks FINAL
                    WHERE collection_dataset = {collection_dataset:String}
                    AND (file_hash, extracted_by, page_id) IN {page_keys:Array(Tuple(String, String, UInt32))}
                """, {"collection_dataset": collection_dataset, "page_keys": page_keys}).result_rows
            }
            # The second of the newest text of each page. A vector of an earlier second
            # belongs to replaced text.
            page_seconds = {(r["file_hash"], r["extracted_by"], int(r["page_id"])): int(r["version"]) // 1_000_000_000
                            for r in text_content}
            current = {(c["file_hash"], c["extracted_by"], c["page_id"], c["chunk_index"]) for c in candidates}
            obsolete = {key for key in set(existing) | stored_chunks if key not in current}
            pages_with_chunks = {key[:3] for key in current}
            empty_pages = {(r["file_hash"], r["extracted_by"], int(r["page_id"]), int(r["version"]))
                           for r in text_content
                           if (r["file_hash"], r["extracted_by"], int(r["page_id"])) not in pages_with_chunks
                           } | skipped_pages
            _delete_chunk_keys(client, collection_dataset, serving_model, obsolete)
            _write_empty_page_receipts(client, params, serving_model, empty_pages)

        missing = [
            c for c in candidates
            if existing.get((c["file_hash"], c["extracted_by"], c["page_id"], c["chunk_index"]), -1)
            < page_seconds[(c["file_hash"], c["extracted_by"], int(c["page_id"]))]
        ]
        if not missing:
            log.info(
                "%s (plan %s): all %d chunks of this page already embedded via %s",
                collection_dataset, plan_hash[:8], len(candidates), serving_model,
            )
            continue

        # Chunk rows go in before the first vector of their page: a vector without its
        # chunk row would be a KNN hit with no text to rerank or render. Only pages with
        # missing vectors are (re)written: text_chunks is keyed without the model, and
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

        page_vectors = 0
        for i in range(0, len(missing), EMBED_BATCH_TEXTS):
            # Embed-batch boundary, and the finest one worth honouring: the previous
            # batch's vectors are already inserted and the anti-join is keyed on
            # chunk_index, so only the chunks with no vector are redone.
            stop_if_worker_is_stopping(
                f"{collection_dataset} plan {plan_hash[:8]}: "
                f"{total_vectors + page_vectors} vectors written")
            batch = missing[i:i + EMBED_BATCH_TEXTS]
            # Keep stored source text and byte offsets. Bound encoded data in model input.
            prefixed = [embedding_input(
                serving_model, "passage", limit_encoded_runs(c["text"]),
            )[0] for c in batch]
            result = post_json(
                [("embeddings", f"{base_url}/embeddings")],
                {"input": prefixed},
                service="embeddings",
                headers=gpu_headers(),
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
            page_vectors += len(batch)
            # In-loop heartbeat: evidence of forward progress, not merely of a live thread.
            heartbeat.beat(f"embedded {total_vectors + page_vectors} chunks "
                           f"({page_vectors}/{len(missing)} of this page)")
            log.info(
                "%s (plan %s): embedded %d/%d chunks via %s",
                collection_dataset, plan_hash[:8], page_vectors, len(missing), served_model,
            )
        total_chunk_rows += len(chunk_rows)
        total_vectors += page_vectors

    with get_collection_client(params.collectionname) as client:
        removed = _delete_removed_pages(client, collection_dataset, serving_model, item_hashes)
    if removed:
        log.info("%s (plan %s): deleted %d vectors of pages that the text no longer has",
                 collection_dataset, plan_hash[:8], removed)

    if not saw_any:
        log.info("%s (plan %s): nothing to chunk+embed", collection_dataset, plan_hash[:8])
        return ChunkEmbedResult(text_segments=0, chunks_written=0, vectors_written=0)

    log.info(
        "%s (plan %s): chunked %d segments, wrote %d chunk rows and %d vectors",
        collection_dataset, plan_hash[:8], total_segments, total_chunk_rows, total_vectors,
    )
    return ChunkEmbedResult(
        text_segments=total_segments,
        chunks_written=total_chunk_rows,
        vectors_written=total_vectors,
        chunks_skipped_non_linguistic=total_skipped_non_linguistic,
    )
