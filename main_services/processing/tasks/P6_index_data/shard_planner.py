"""Shard planner for Manticore indexing.

Assigns every document of a processing plan to exactly one Manticore shard of its
collection. Shards are filled append-only: the newest open shard takes documents until
another one would push it over :data:`MAX_SHARD_TEXT_BYTES` **or**
:data:`MAX_SHARD_ROWS`, then it is sealed and the next shard is opened. A document that
alone exceeds a budget gets its own shard (the same rule ``P1_compute_plans`` uses for
oversized blobs).

**Two budgets, whichever binds first.** Bytes per row vary by two orders of magnitude
across a mixed corpus (an email page averages ~1.5 kB and a document page ~57 kB) while
the cost of a facet or a group-by is per ROW and independent of how much text each row
holds. A byte-only budget therefore produces shards whose query cost differs by a factor
of 35, and the largest-by-rows shard is the straggler every broad query waits for. The
byte cap is what binds for document corpora and the row cap for mail.

The durable state lives in the collection database:

* ``manticore_shards``, the ledger: one row per shard with its fill level
  (``text_bytes`` / ``row_count`` / ``doc_count``) and ``is_open`` flag.
  ReplacingMergeTree keyed on ``shard_name`` versioned by ``updated_at``: always read
  with ``FINAL`` and always write complete rows, never partial ones.
* ``manticore_shard_assignments``, ``(collection_dataset, file_hash) -> shard_name``.
  The shard *reservation*: a re-indexed document goes back to its existing shard (the
  writers overwrite in place with ``REPLACE INTO``); it is never duplicated across
  shards. Rows are written at planning time, before the writers run.
* ``index_state``, ``(collection_dataset, file_hash) -> shard_name, indexed_at``.
  Written only *after* a document's writers committed, so it is the record of what
  actually reached a shard. The ledger's fill levels are recomputed from this table,
  never from the reservations.

**Identity contract:** the whole indexing pipeline is keyed on
``(collection_dataset, file_hash)``: Manticore row ids, the pages rows, and the
purge path. A (dataset, document) pair therefore lives in exactly one shard, and the
same content ingested into two datasets of one collection is indexed twice (once per
dataset). Never assume ``file_hash`` alone identifies a document.

**Concurrency: this planner mutates the ledger and must never run twice concurrently
for the same collection.** It therefore runs on the dedicated
``processing-index-planner-queue`` served by exactly one worker process with
``max_concurrent_activities=1`` (see ``tasks/run_worker.py::run_index_planner_worker``).
Running more than one index-planner worker will corrupt the shard ledger.

TODO: if a future need forces multiple planner workers, replace the single-worker
guarantee with a ClickHouse-side compare-and-set or a Temporal per-collection
singleton workflow. Do not just scale the worker count.
"""

from dataclasses import dataclass, field
import logging

from temporalio import activity

from database.clickhouse import get_collection_client
from database.manticore import (
    create_entities_table,
    create_shard_tables,
    create_vfs_table,
    probed_embedding_dims,
)
from .params import FinalizeIndexBatchParams, PlanShardsParams, RecordIndexedParams
from tasks.heartbeat import with_heartbeat

log = logging.getLogger(__name__)

# Per-shard budgets. Changing either only affects shards opened afterwards; run
# `main.py reindex-collection` to redistribute existing shards.
#
# 4 GB of raw text is ~6.9 GB on disk at the measured 1.73x, which keeps a single
# shard's worst-case unfiltered facet scan around 3.6 s (well inside the 30 s search
# budget), and an OPTIMIZE merge down to minutes. Smaller shards are not free: Manticore
# parallelises one table's query across worker threads by itself (`pseudo_sharding`), its
# own benchmarks put the sweet spot at 4-8 physical shards on a 16-core box, and
# throughput falls BELOW the unsharded baseline by 32. So shard size is an operational
# choice (rebuild granularity, merge cost, straggler bound), not a parallelism one.
MAX_SHARD_TEXT_BYTES = 4_000_000_000

# 2.5 M rows is where the row cost of a facet scan is comparable to the byte budget's
# for mail (4 GB of email is ~2.8 M rows) and binds first for anything smaller-grained.
MAX_SHARD_ROWS = 2_500_000

#: Rows a document adds to a shard when its page count is unknown: its filename row.
#: Never 0, a document with no text still occupies a row and still costs a group-by.
MIN_DOCUMENT_ROWS = 1


@dataclass
class ShardState:
    """One row of the ``manticore_shards`` ledger."""

    shard_name: str
    shard_index: int
    text_bytes: int
    doc_count: int
    is_open: bool
    row_count: int = 0


@dataclass
class ShardAssignment:
    """A group of document hashes to be written into one shard."""

    shard_name: str
    shard_index: int
    hashes: list[str] = field(default_factory=list)


def pack_into_shards(
    collectionname: str,
    ledger: list[ShardState],
    candidates: list[tuple[str, int, int]],
    max_bytes: int = MAX_SHARD_TEXT_BYTES,
    max_rows: int = MAX_SHARD_ROWS,
    existing_assignments: dict[str, str] | None = None,
) -> tuple[list[ShardAssignment], list[ShardState]]:
    """Pure shard packing. Returns ``(assignments, new_ledger)``; inputs are not mutated.

    * ``ledger``, current shard states (from ``manticore_shards FINAL``).
    * ``candidates``: ``(file_hash, text_bytes, row_count)`` for documents with no
      assignment yet.
    * ``existing_assignments``, ``file_hash -> shard_name`` for documents that already
      have a shard: they keep it, and their bytes and rows are already in the ledger
      (they are not counted again).

    A shard is sealed when the next document would push it over EITHER budget; see the
    module docstring for why one number is not enough.

    Deterministic: candidates are sorted by hash first, so the output does not depend
    on the order of the candidate list.
    """
    from database.clickhouse import validate_collectionname
    validate_collectionname(collectionname)

    new_ledger = [
        ShardState(s.shard_name, s.shard_index, s.text_bytes, s.doc_count, s.is_open,
                   s.row_count)
        for s in ledger
    ]
    by_index = {s.shard_index: s for s in new_ledger}

    assignments: list[ShardAssignment] = []

    # Already-assigned documents keep their existing shard, grouped per shard.
    by_existing_shard: dict[str, list[str]] = {}
    for file_hash in sorted((existing_assignments or {}).keys()):
        by_existing_shard.setdefault(existing_assignments[file_hash], []).append(file_hash)
    for shard_name in sorted(by_existing_shard):
        try:
            shard_index = int(shard_name.rsplit('_', 1)[1])
        except (IndexError, ValueError) as e:
            raise ValueError(
                f"malformed shard name in existing assignments: {shard_name!r}"
            ) from e
        assignments.append(
            ShardAssignment(shard_name=shard_name, shard_index=shard_index,
                            hashes=by_existing_shard[shard_name])
        )

    def _open_shard(shard_index: int) -> ShardState:
        state = ShardState(
            shard_name=f'{collectionname}_{shard_index}',
            shard_index=shard_index,
            text_bytes=0,
            doc_count=0,
            is_open=True,
            row_count=0,
        )
        new_ledger.append(state)
        by_index[shard_index] = state
        return state

    new_hashes: dict[int, list[str]] = {}
    open_shard = max(
        (s for s in new_ledger if s.is_open),
        key=lambda s: s.shard_index,
        default=None,
    )
    for file_hash, text_bytes, row_count in sorted(candidates):
        if existing_assignments and file_hash in existing_assignments:
            # Callers pre-filter candidates to unassigned hashes, but the packer
            # itself must stay total: an existing assignment always wins and the
            # bytes are already in the ledger.
            continue
        text_bytes = max(0, int(text_bytes))
        row_count = max(MIN_DOCUMENT_ROWS, int(row_count))
        if open_shard is None:
            open_shard = _open_shard(max(by_index, default=0) + 1)
        elif open_shard.doc_count > 0 and (
            open_shard.text_bytes + text_bytes > max_bytes
            or open_shard.row_count + row_count > max_rows
        ):
            open_shard.is_open = False
            open_shard = _open_shard(open_shard.shard_index + 1)
        open_shard.text_bytes += text_bytes
        open_shard.row_count += row_count
        open_shard.doc_count += 1
        new_hashes.setdefault(open_shard.shard_index, []).append(file_hash)
        if open_shard.text_bytes > max_bytes or open_shard.row_count > max_rows:
            # A document larger than a budget gets its own shard; seal it so the
            # next candidate opens a fresh one instead of piling on.
            open_shard.is_open = False
            open_shard = None

    for shard_index in sorted(new_hashes):
        state = by_index[shard_index]
        assignments.append(
            ShardAssignment(shard_name=state.shard_name, shard_index=shard_index,
                            hashes=new_hashes[shard_index])
        )

    return assignments, new_ledger


def _write_ledger_rows(client, shard_states: list[ShardState]) -> None:
    """Insert complete ledger rows (ReplacingMergeTree versions by updated_at)."""
    if not shard_states:
        return
    client.insert(
        'manticore_shards',
        [[s.shard_name, s.shard_index, s.text_bytes, s.doc_count, 1 if s.is_open else 0,
          s.row_count]
         for s in shard_states],
        column_names=['shard_name', 'shard_index', 'text_bytes', 'doc_count', 'is_open',
                      'row_count'],
    )


def merge_ledger_stats(
    ledger_rows: list[tuple[str, int, int]],
    stats_rows: list[tuple[str, int, int, int]],
) -> list[ShardState]:
    """Pure join of the ledger skeleton with per-shard fill statistics.

    * ``ledger_rows``, ``(shard_name, shard_index, is_open)`` from ``manticore_shards
      FINAL``; every ledger shard appears in the output, stats or no stats.
    * ``stats_rows``, ``(shard_name, text_bytes, row_count, doc_count)``; shards
      missing here get zeros (nothing indexed into them yet).

    ``is_open`` is preserved as-is: recomputation never re-opens a sealed shard and
    never compacts or renumbers shards.
    """
    stats = {
        shard_name: (int(text_bytes), int(row_count), int(doc_count))
        for shard_name, text_bytes, row_count, doc_count in stats_rows
    }
    return [
        ShardState(
            shard_name=shard_name,
            shard_index=int(shard_index),
            text_bytes=stats.get(shard_name, (0, 0, 0))[0],
            doc_count=stats.get(shard_name, (0, 0, 0))[2],
            is_open=bool(is_open),
            row_count=stats.get(shard_name, (0, 0, 0))[1],
        )
        for shard_name, shard_index, is_open in ledger_rows
    ]


def recompute_shard_ledger(collectionname: str) -> None:
    """Rebuild ledger ``text_bytes``/``row_count``/``doc_count`` from ``index_state``.

    Single source of truth for fill levels: what actually reached a shard, not the
    reservations. A permanently failed writer chunk must not inflate the ledger.
    ``text_bytes`` and ``row_count`` are taken from the assignments row of each indexed
    document (the planner's own estimate at reservation time). Used by
    ``finalize_index_batch`` after the writers finish and by the dataset purge, where it
    shrinks the counters of shards a deleted dataset contributed to.
    """
    with get_collection_client(collectionname) as client:
        ledger_rows = client.query(
            "SELECT shard_name, shard_index, is_open FROM manticore_shards FINAL "
            "ORDER BY shard_index"
        ).result_rows
        if not ledger_rows:
            return
        stats_rows = client.query(
            "SELECT i.shard_name AS shard_name, sum(a.text_bytes) AS text_bytes, "
            "sum(a.row_count) AS row_count, count() AS doc_count "
            "FROM index_state AS i FINAL "
            "INNER JOIN manticore_shard_assignments AS a FINAL "
            "ON a.collection_dataset = i.collection_dataset "
            "AND a.file_hash = i.file_hash "
            "GROUP BY i.shard_name"
        ).result_rows
        _write_ledger_rows(client, merge_ledger_stats(ledger_rows, stats_rows))


@activity.defn
@with_heartbeat
def plan_shards(params: PlanShardsParams) -> list[ShardAssignment]:
    """Assign every hash of a plan to a shard, persist ledger + assignments, create tables.

    Reads the ledger, computes, and writes in one activity invocation; the single
    planner worker makes that read-modify-write safe.
    """
    collectionname = params.collectionname
    collection_dataset = params.collection_dataset
    hashes = sorted(set(params.hashes))
    if not hashes:
        return []

    with get_collection_client(collectionname) as client:
        # Documents already assigned keep their shard: a re-index overwrites in
        # place (REPLACE INTO with deterministic ids), never duplicates across shards.
        existing = dict(client.query(
            "SELECT file_hash, shard_name FROM manticore_shard_assignments FINAL "
            "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)}",
            parameters={"cd": collection_dataset, "hashes": hashes},
        ).result_rows)

        unassigned = [h for h in hashes if h not in existing]
        text_bytes_by_hash: dict[str, int] = {}
        rows_by_hash: dict[str, int] = {}
        if unassigned:
            # Manticore rows the document will occupy: one per text segment plus its
            # filename row, counted rather than derived from bytes. The ratio between
            # the two is exactly what varies across the corpus, which is why there are
            # two budgets.
            rows_by_hash = {
                row[0]: int(row[1]) + 1
                for row in client.query(
                    "SELECT file_hash, count() AS segments "
                    "FROM text_content FINAL "
                    "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
                    "GROUP BY file_hash",
                    parameters={"cd": collection_dataset, "hashes": unassigned},
                ).result_rows
            }
            nlp_sums = {
                row[0]: int(row[1])
                for row in client.query(
                    "SELECT file_hash, sum(text_bytes) AS text_bytes "
                    "FROM nlp_processed FINAL "
                    "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
                    "GROUP BY file_hash",
                    parameters={"cd": collection_dataset, "hashes": unassigned},
                ).result_rows
            }
            # Raw text length, computed for EVERY unassigned hash, not only for
            # those with no nlp_processed row at all. A partially-processed document
            # (NER succeeded on page 0, failed on pages 1..n) has a watermark that
            # covers only some of its pages, so neither sum alone is safe; the
            # larger one is the honest upper estimate for shard budgeting.
            text_sums = {
                row[0]: int(row[1])
                for row in client.query(
                    "SELECT file_hash, sum(length(text)) AS text_bytes "
                    "FROM text_content FINAL "
                    "WHERE collection_dataset = {cd:String} AND file_hash IN {hashes:Array(String)} "
                    "GROUP BY file_hash",
                    parameters={"cd": collection_dataset, "hashes": unassigned},
                ).result_rows
            }
            for h in unassigned:
                text_bytes_by_hash[h] = max(nlp_sums.get(h, 0), text_sums.get(h, 0))

        ledger_rows = client.query(
            "SELECT shard_name, shard_index, text_bytes, doc_count, is_open, row_count "
            "FROM manticore_shards FINAL ORDER BY shard_index"
        ).result_rows

    ledger = [
        ShardState(shard_name=r[0], shard_index=int(r[1]), text_bytes=int(r[2]),
                   doc_count=int(r[3]), is_open=bool(r[4]), row_count=int(r[5]))
        for r in ledger_rows
    ]
    candidates = [
        (h, text_bytes_by_hash.get(h, 0), rows_by_hash.get(h, MIN_DOCUMENT_ROWS))
        for h in unassigned
    ]

    assignments, new_ledger = pack_into_shards(
        collectionname,
        ledger,
        candidates,
        max_bytes=MAX_SHARD_TEXT_BYTES,
        max_rows=MAX_SHARD_ROWS,
        existing_assignments=existing,
    )

    # Create the Manticore tables of every shard before any writer can be scheduled
    # against it. Idempotent (`create table if not exists`), and deliberately run for
    # EXISTING shards too, not only newly-opened ones: a shard planned before the
    # vectors stage existed has no `_vectors` table, and this is the self-heal path
    # that creates it (from the probed dimension, never the ini) without a reindex.
    old_indexes = {s.shard_index for s in ledger}
    vector_dims = probed_embedding_dims()
    for state in new_ledger:
        create_shard_tables(collectionname, state.shard_index, vector_dims=vector_dims)
    # The collection's structure and facet-term indexes, neither of which is sharded.
    # Created here as well as in `manticore_migrate` because a collection created and
    # indexed between two migrate runs would otherwise have nowhere for
    # `index_vfs_structure` and `index_entity_terms` to write.
    create_vfs_table(collectionname)
    create_entities_table(collectionname)

    # The read above and the write below are deliberately separate client blocks
    # with the pure packing in between. Correctness relies on the single planner
    # worker serialising this activity (see the module docstring). Do not
    # "optimise" the two blocks into one.
    with get_collection_client(collectionname) as client:
        _write_ledger_rows(client, new_ledger)
        # Only newly assigned hashes need rows; existing ones keep their row (and
        # thereby their shard) untouched.
        new_assignment_rows = [
            [collection_dataset, file_hash, a.shard_name,
             text_bytes_by_hash.get(file_hash, 0),
             rows_by_hash.get(file_hash, MIN_DOCUMENT_ROWS)]
            for a in assignments
            for file_hash in a.hashes
            if file_hash not in existing
        ]
        if new_assignment_rows:
            client.insert(
                'manticore_shard_assignments',
                new_assignment_rows,
                column_names=['collection_dataset', 'file_hash', 'shard_name', 'text_bytes',
                              'row_count'],
            )

    total_new = sum(len(a.hashes) for a in assignments) - len(existing)
    log.info(
        "[P6] plan_shards %s (plan %s): %d new docs, %d re-assigned, %d shards (%d new)",
        collection_dataset, params.plan_hash[:8], total_new, len(existing),
        len(new_ledger), len(new_ledger) - len(old_indexes),
    )
    return assignments


@activity.defn
@with_heartbeat
def finalize_index_batch(params: FinalizeIndexBatchParams) -> str:
    """Refresh the shard ledger after a plan's writers finished.

    Runs on the planner queue (single worker) so it cannot race a concurrent
    ``plan_shards`` for the same collection.
    """
    recompute_shard_ledger(params.collectionname)
    log.info(
        "[P6] finalize_index_batch %s (plan %s): ledger refreshed",
        params.collection_dataset, params.plan_hash[:8],
    )
    return "ok"


@activity.defn
@with_heartbeat
def record_indexed(params: RecordIndexedParams) -> str:
    """Record successfully indexed documents in ``index_state``.

    Called by ``IndexDatasetPlan`` with only the hashes whose writers committed,
    so the ledger recomputation (``recompute_shard_ledger``) counts what actually
    reached a shard, never the reservations. Idempotent: ``index_state`` is a
    ReplacingMergeTree keyed on ``(collection_dataset, file_hash)``, so a retried
    call just replaces the row. Runs on the planner queue so it cannot race a
    concurrent ``plan_shards``.
    """
    if not params.entries:
        return "ok"
    with get_collection_client(params.collectionname) as client:
        client.insert(
            'index_state',
            [[params.collection_dataset, file_hash, shard_name]
             for shard_name, file_hash in params.entries],
            column_names=['collection_dataset', 'file_hash', 'shard_name'],
        )
    log.info(
        "[P6] record_indexed %s (plan %s): %d documents recorded",
        params.collection_dataset, params.plan_hash[:8], len(params.entries),
    )
    return "ok"
