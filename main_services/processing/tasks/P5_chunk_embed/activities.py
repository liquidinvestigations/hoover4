"""Chunk+embed stage (P5) activities: chunk every text segment, embed every chunk.

Runs on ``processing-embed-queue``. The stage writes two collection-DB tables:

* ``text_chunks``, the chunks themselves (model-independent: byte offsets and text);
* ``text_chunk_vectors``, the durable embeddings, keyed WITH ``embedding_model`` so a
  model change adds rows rather than replacing them. Manticore's ``_vectors`` shards
  are a disposable HNSW copy of this table, written by the P6 vector indexer.

Failure policy matches P4: errors are NOT swallowed. An exception fails the activity
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
from tasks.heartbeat import HeartbeatClock, stop_if_worker_is_stopping, with_heartbeat
from tasks.remote import post_json
from tasks.text_quality import non_linguistic_reason

from .chunking import chunk_page_text
from .embedding_prefix import embedding_input
from .params import ChunkEmbedParams, ChunkEmbedResult

log = logging.getLogger(__name__)

#: Texts per embeddings request. Bounds request size and makes partial progress
#: possible (today's alternative is the whole activity chunk in one request).
EMBED_BATCH_TEXTS = 32

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

    # Keyset pagination on the ORDER BY prefix, not OFFSET: OFFSET re-reads everything
    # before it, which on a multi-million-segment file is quadratic.
    #
    # FINAL, not a bare read. `text_content` is a ReplacingMergeTree and a re-parse
    # inserts a second row for the same
    # (collection_dataset, file_hash, extracted_by, page_id) that lives until the
    # background merge collapses it. Without FINAL both rows come back, both are
    # chunked, and both survive the anti-join below, because they produce *identical*
    # chunk keys, so neither is in `existing` on the first run. The endpoint is then
    # asked to embed every chunk of the page twice, at full GPU cost, and both vectors
    # are inserted. The filter is on the ORDER BY prefix, so FINAL is cheap here.
    def _segment_pages():
        after = ("", "", 0)
        while True:
            with get_collection_client(params.collectionname) as page_client:
                rows = page_client.query_arrow("""
                    SELECT collection_dataset, file_hash, extracted_by, page_id, text
                    FROM text_content FINAL
                    WHERE collection_dataset = {collection_dataset:String}
                    AND file_hash IN {item_hashes:Array(String)}
                    AND (file_hash, extracted_by, page_id) >
                        ({after_hash:String}, {after_by:String}, {after_page:UInt32})
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

    total_segments = 0
    total_chunk_rows = 0
    total_vectors = 0
    total_skipped_non_linguistic = 0
    saw_any = False

    for text_content in _segment_pages():
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
            existing = {
                (r[0], r[1], int(r[2]), int(r[3]))
                for r in client.query("""
                    SELECT file_hash, extracted_by, page_id, chunk_index
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

        missing = [
            c for c in candidates
            if (c["file_hash"], c["extracted_by"], c["page_id"], c["chunk_index"]) not in existing
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
            prefixed = [embedding_input(serving_model, "passage", c["text"])[0] for c in batch]
            result = post_json(
                [("embeddings", f"{base_url}/embeddings")],
                {"input": prefixed},
                service="embeddings",
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
