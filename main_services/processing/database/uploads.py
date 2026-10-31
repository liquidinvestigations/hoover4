"""Readers and writers of the upload tables `upload_batches` and `upload_files`.

Collection migration `00062_upload_batches.sql` creates both tables. The website writes
them while a batch transfers, and the `ingest_upload` operation writes them after it
claims a batch. Each state has one writer.

| Writer | Batch states | File states |
|---|---|---|
| website (`website/backend/src/uploads/`) | `uploading`, `committing`, `queued`, `cancelled` | `pending`, `staged`, `placed`, `rejected` at placement, `not_sent` |
| `ingest_upload` operation (this module) | the claim (`op_id` on a `queued` row), `ingesting`, `processing`, `completed`, `completed_with_errors`, `failed` | `ingested`, `rejected` at ingestion, `file_hash` |

The website writes no batch row after `queued` and no file row after a batch is queued.
The worker writes a batch row only when the stored state is `queued` or one of its own
states, so a transfer snapshot and a processing state never overwrite each other.

Both tables are `ReplacingMergeTree(row_version)`. A writer reads the stored row, then
writes the whole row again with `row_version` one above the stored value. Readers use
`FINAL`. One `UploadQueue` workflow serves each upload dataset, and its activities and
its operation run one at a time, so two worker writers of one batch never interleave.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

#: The longest stored error text, in characters.
ERROR_CHARS = 2000

#: The most batches that one `ingest_upload` operation takes.
BATCHES_PER_OPERATION = 50

BATCH_COLUMNS = (
    "batch_id", "upload_dataset", "folder", "username", "manifest_digest", "request_id",
    "state", "file_count", "byte_count", "op_id", "error", "created_at", "last_write_at",
    "committed_at", "finished_at", "row_version",
)
FILE_COLUMNS = (
    "batch_id", "file_no", "path", "size_bytes", "content_digest", "placement_token",
    "client_mtime", "state", "file_hash", "error", "row_version",
)

#: Batch states that the website writes.
WEBSITE_BATCH_STATES = ("uploading", "committing", "queued", "cancelled")
#: Batch states that the operation writes.
WORKER_BATCH_STATES = ("ingesting", "processing", "completed", "completed_with_errors", "failed")
#: Batch states that never change again.
TERMINAL_BATCH_STATES = ("completed", "completed_with_errors", "failed", "cancelled")
#: Batch states of a claimed batch that has no outcome yet.
OPEN_BATCH_STATES = ("queued", "ingesting", "processing")

#: The name parts of the temporary file that a placement copy writes into the dataset
#: folder. `website/common/src/uploads.rs` defines the same strings as `PART_PREFIX` and
#: `PART_SUFFIX`. Change both together.
PART_PREFIX = ".hoover4-upload-"
PART_SUFFIX = ".hoover4-part"


def is_upload_part_name(name: str) -> bool:
    """Whether a folder entry is a placement part, `.hoover4-upload-<id>.hoover4-part`.

    The folder scan skips these names, so a scan during a copy never ingests a part. The
    website refuses an upload path with either part. The scan skips only the complete
    pattern, so an existing disk file that has one of the parts stays in the index.
    """
    return (name.startswith(PART_PREFIX) and name.endswith(PART_SUFFIX)
            and len(name) > len(PART_PREFIX) + len(PART_SUFFIX))


def _client(collectionname: str):
    from .clickhouse import get_collection_client

    return get_collection_client(collectionname)


def _rows(result) -> list[dict]:
    names = list(result.column_names)
    return [dict(zip(names, row)) for row in result.result_rows]


def _cut(text: str) -> str:
    return (text or "")[:ERROR_CHARS]


def _string_table(name: str, column: str, values):
    """``values`` as an external table with one String column, for long `IN` lists.

    A query parameter above 128 KiB is refused, so paths and long hash lists travel in
    the request body. `tasks/P0_scan_disk/activities.py` `_path_table` uses the same
    method for paths.
    """
    from clickhouse_connect.driver.external import ExternalData

    data = "\n".join(json.dumps([v], ensure_ascii=False) for v in values).encode("utf-8")
    return ExternalData(file_name=name, data=data, fmt="JSONCompactEachRow",
                        structure=f"{column} String")


# Batches ------------------------------------------------------------------------------

def read_batches(collectionname: str, upload_dataset: str, batch_ids) -> list[dict]:
    """The current rows of the given batches of one upload dataset, in `batch_id` order."""
    batch_ids = list(batch_ids)
    if not batch_ids:
        return []
    with _client(collectionname) as client:
        return _rows(client.query(
            f"SELECT {', '.join(BATCH_COLUMNS)} FROM upload_batches FINAL "
            "WHERE upload_dataset = {ds:String} AND batch_id IN {ids:Array(String)} "
            "ORDER BY batch_id",
            parameters={"ds": upload_dataset, "ids": batch_ids},
        ))


def read_batch(collectionname: str, upload_dataset: str, batch_id: str) -> dict | None:
    """One current batch row, or None."""
    rows = read_batches(collectionname, upload_dataset, [batch_id])
    return rows[0] if rows else None


def queued_batches(collectionname: str, upload_dataset: str,
                   limit: int = BATCHES_PER_OPERATION) -> list[dict]:
    """Unclaimed `queued` batches, oldest first by `(committed_at, batch_id)`."""
    with _client(collectionname) as client:
        return _rows(client.query(
            f"SELECT {', '.join(BATCH_COLUMNS)} FROM upload_batches FINAL "
            "WHERE upload_dataset = {ds:String} AND state = 'queued' AND op_id = '' "
            "ORDER BY committed_at, batch_id LIMIT {limit:UInt32}",
            parameters={"ds": upload_dataset, "limit": int(limit)},
        ))


def claimed_open_batches(collectionname: str, upload_dataset: str) -> list[dict]:
    """Claimed batches of the dataset that have no outcome yet."""
    with _client(collectionname) as client:
        return _rows(client.query(
            f"SELECT {', '.join(BATCH_COLUMNS)} FROM upload_batches FINAL "
            "WHERE upload_dataset = {ds:String} AND op_id != '' "
            "AND state IN ('queued', 'ingesting', 'processing') "
            "ORDER BY committed_at, batch_id",
            parameters={"ds": upload_dataset},
        ))


def batches_of_operation(collectionname: str, upload_dataset: str, op_id: str) -> list[dict]:
    """Every batch that the operation claimed, in claim order."""
    with _client(collectionname) as client:
        return _rows(client.query(
            f"SELECT {', '.join(BATCH_COLUMNS)} FROM upload_batches FINAL "
            "WHERE upload_dataset = {ds:String} AND op_id = {op:String} "
            "ORDER BY committed_at, batch_id",
            parameters={"ds": upload_dataset, "op": op_id},
        ))


def datasets_with_open_batches(collectionname: str) -> list[tuple[str, str]]:
    """`(upload_dataset, batch_id)` of one waiting or claimed batch for each dataset."""
    with _client(collectionname) as client:
        rows = client.query(
            "SELECT upload_dataset, min(batch_id) FROM upload_batches FINAL "
            "WHERE state IN ('queued', 'ingesting', 'processing') "
            "GROUP BY upload_dataset ORDER BY upload_dataset",
        ).result_rows
    return [(str(ds), str(batch_id)) for ds, batch_id in rows]


def _insert_batch(collectionname: str, row: dict) -> None:
    from .clickhouse import insert_durable

    with _client(collectionname) as client:
        insert_durable(client, "upload_batches", [[row[c] for c in BATCH_COLUMNS]],
                       column_names=BATCH_COLUMNS)


class BatchStateConflict(Exception):
    """The stored batch state belongs to the website, so the worker may not write it."""


#: The version step of a settle write. The settle of an ended operation and a late
#: finish of its child can read the same row. The child writes at most a few versions of
#: a batch after any read, so the settle row stays above it, and `FINAL` returns the
#: settled outcome whatever the insert order.
SETTLE_VERSION_STEP = 1000


def write_batch(collectionname: str, upload_dataset: str, batch_id: str, *,
                current: dict | None = None, version_step: int = 1,
                **changes) -> dict | None:
    """Rewrite one batch row with the given columns changed. Returns the stored row.

    A terminal row is returned unchanged. A row in a website transfer state other than
    `queued` raises `BatchStateConflict`. `current` skips the read when the caller read
    the row in the same step. The new row has the version of `current` plus
    `version_step`.
    """
    if current is None:
        current = read_batch(collectionname, upload_dataset, batch_id)
    if current is None:
        return None
    if current["state"] in TERMINAL_BATCH_STATES:
        return current
    if current["state"] not in ("queued",) + WORKER_BATCH_STATES:
        raise BatchStateConflict(
            f"upload batch {batch_id} is {current['state']}, a state of the website")
    row = dict(current)
    for key, value in changes.items():
        if key not in BATCH_COLUMNS or key in ("batch_id", "upload_dataset", "row_version"):
            raise ValueError(f"Not an updatable upload_batches column: {key}")
        if key == "state" and value not in ("queued",) + WORKER_BATCH_STATES:
            raise ValueError(f"The worker does not write the batch state {value}")
        row[key] = value
    row["error"] = _cut(row.get("error", ""))
    row["row_version"] = int(current["row_version"]) + version_step
    _insert_batch(collectionname, row)
    return row


def claim_batches(collectionname: str, upload_dataset: str, op_id: str, batch_ids) -> list[str]:
    """Write `op_id` on each given batch that is still `queued` and unclaimed.

    The state stays `queued` until the operation starts the batch. A batch that another
    operation claimed, or that left `queued`, is skipped. Returns every batch id that
    now names `op_id`, so a repeated call returns the same answer.
    """
    for row in read_batches(collectionname, upload_dataset, batch_ids):
        if row["state"] == "queued" and row["op_id"] == "":
            write_batch(collectionname, upload_dataset, row["batch_id"], current=row, op_id=op_id)
    return [row["batch_id"] for row in batches_of_operation(collectionname, upload_dataset, op_id)]


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(tzinfo=None)


def fail_waiting_batches(collectionname: str, upload_dataset: str, error: str) -> int:
    """Settle every unclaimed `queued` batch of the dataset as `failed`."""
    count = 0
    while True:
        rows = queued_batches(collectionname, upload_dataset)
        if not rows:
            return count
        for row in rows:
            write_batch(collectionname, upload_dataset, row["batch_id"], current=row,
                        state="failed", error=error, finished_at=_now())
            count += 1


# Files --------------------------------------------------------------------------------

def read_files(collectionname: str, batch_id: str) -> list[dict]:
    """Every file row of a batch in manifest order (`file_no`)."""
    with _client(collectionname) as client:
        return _rows(client.query(
            f"SELECT {', '.join(FILE_COLUMNS)} FROM upload_files FINAL "
            "WHERE batch_id = {b:String} ORDER BY file_no",
            parameters={"b": batch_id},
        ))


def write_files(collectionname: str, batch_id: str, changes: dict[int, dict]) -> int:
    """Rewrite file rows of one batch. `changes` maps `file_no` to changed columns.

    The worker writes `ingested` or `rejected` on a `placed` row, and the hash of an
    `ingested` row. Any other stored state is left unchanged. Returns the rows written.
    """
    from .clickhouse import insert_durable

    if not changes:
        return 0
    wanted = set(int(n) for n in changes)
    rows = [row for row in read_files(collectionname, batch_id) if int(row["file_no"]) in wanted]
    out = []
    for current in rows:
        if current["state"] not in ("placed", "ingested"):
            continue
        row = dict(current)
        for key, value in changes[int(current["file_no"])].items():
            if key not in ("state", "file_hash", "error"):
                raise ValueError(f"Not an updatable upload_files column: {key}")
            if key == "state" and value not in ("ingested", "rejected"):
                raise ValueError(f"The worker does not write the file state {value}")
            row[key] = value
        row["error"] = _cut(row.get("error", ""))
        row["row_version"] = int(current["row_version"]) + 1
        out.append([row[c] for c in FILE_COLUMNS])
    if out:
        with _client(collectionname) as client:
            insert_durable(client, "upload_files", out, column_names=FILE_COLUMNS)
    return len(out)


# Outcome ------------------------------------------------------------------------------

#: The start of every error text that ingestion writes on a rejected file. The outcome
#: counts such a file as placed. A website rejection never starts with it.
INGEST_REJECTION_PREFIX = "Not ingested: "


#: Nesting levels of archive and email members that the outcome follows.
DESCENDANT_LEVELS = 16


def _descendants(client, upload_dataset: str, roots: list[str]) -> dict[str, set[str]]:
    """Map each member hash to every uploaded root that contains it.

    Each root and member pair is visited once. Shared members affect every containing
    archive, including an uploaded archive nested inside another uploaded archive.
    """
    owner: dict[str, set[str]] = {}
    level = {h: {h} for h in roots if h}
    seen = {(h, h) for h in level}
    for _ in range(DESCENDANT_LEVELS):
        if not level:
            break
        rows = client.query(
            "SELECT DISTINCT container_hash, hash FROM vfs_files FINAL "
            "WHERE collection_dataset = {ds:String} AND is_deleted = 0 "
            "AND container_hash IN (SELECT hash FROM lookup_hashes)",
            parameters={"ds": upload_dataset},
            external_data=_string_table("lookup_hashes", "hash", sorted(level)),
        ).result_rows
        nxt: dict[str, set[str]] = {}
        for container, member in rows:
            if not member:
                continue
            member = str(member)
            for root in level.get(str(container), set()):
                if (root, member) in seen:
                    continue
                seen.add((root, member))
                owner.setdefault(member, set()).add(root)
                nxt.setdefault(member, set()).add(root)
        level = nxt
    return owner


def _plan_state(client, upload_dataset: str, hashes: list[str]) -> dict[str, tuple[int, int]]:
    """`hash -> (plans, finished plans)` from `processing_plan_hits`."""
    if not hashes:
        return {}
    rows = client.query(
        "SELECT h.item_hash, uniqExact(h.plan_hash), uniqExactIf(h.plan_hash, f.plan_hash != '') "
        "FROM (SELECT DISTINCT item_hash, plan_hash FROM processing_plan_hits FINAL "
        "      WHERE collection_dataset = {ds:String} "
        "      AND item_hash IN (SELECT hash FROM lookup_hashes)) AS h "
        "LEFT JOIN (SELECT DISTINCT plan_hash FROM processing_plan_finished FINAL "
        "      WHERE collection_dataset = {ds:String}) AS f ON f.plan_hash = h.plan_hash "
        "GROUP BY h.item_hash",
        parameters={"ds": upload_dataset},
        external_data=_string_table("lookup_hashes", "hash", hashes),
    ).result_rows
    return {str(h): (int(planned), int(done)) for h, planned, done in rows}


def current_error_hashes(client, upload_dataset: str, hashes: list[str]) -> set[str]:
    """The hashes with a current processing error.

    The rule of the document viewer (`DOCUMENT_PROCESSING_SQL` in
    `website/backend/src/api/documents/get_document_sources.rs`): an error is current when
    the latest operation that listed a plan of the hash wrote it. Without such an
    operation, only an error without an operation id is current. An error that an older
    operation wrote and a later operation recovered is not current.
    """
    if not hashes:
        return set()
    rows = client.query(
        "WITH latest AS ("
        "  SELECT h.item_hash AS item_hash, argMax(p.op_id, p.listed_at) AS op_id "
        "  FROM (SELECT DISTINCT item_hash, plan_hash FROM processing_plan_hits FINAL "
        "        WHERE collection_dataset = {ds:String} "
        "        AND item_hash IN (SELECT hash FROM lookup_hashes)) AS h "
        "  INNER JOIN operation_plans AS p FINAL "
        "    ON p.plan_hash = h.plan_hash AND p.collection_dataset = {ds:String} "
        "  GROUP BY h.item_hash) "
        "SELECT DISTINCT e.hash FROM processing_errors AS e FINAL "
        "LEFT JOIN latest AS l ON l.item_hash = e.hash "
        "WHERE e.collection_dataset = {ds:String} AND e.hash != '' "
        "AND e.hash IN (SELECT hash FROM lookup_hashes) AND e.op_id = l.op_id",
        parameters={"ds": upload_dataset},
        external_data=_string_table("lookup_hashes", "hash", hashes),
        settings={"join_use_nulls": 0},
    ).result_rows
    return {str(r[0]) for r in rows}


def operation_file_hashes(collectionname: str, upload_dataset: str, op_id: str) -> list[str] | None:
    """The hashes whose historical errors an `ingest_upload` operation selects.

    These are the stored `file_hash` values of the files of the batches that the operation
    claimed, and the members below them up to `DESCENDANT_LEVELS` levels. A batch that is
    not ingested yet has no `file_hash`, so the selection, which runs after the first
    batch, does not include its files. Returns None when the operation claimed no batch of
    the dataset, so another operation kind keeps its selection of the whole dataset.
    """
    batch_ids = [row["batch_id"] for row in batches_of_operation(collectionname, upload_dataset, op_id)]
    if not batch_ids:
        return None
    with _client(collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT file_hash FROM upload_files FINAL "
            "WHERE batch_id IN {ids:Array(String)} AND file_hash != ''",
            parameters={"ids": batch_ids},
        ).result_rows
        roots = sorted({str(r[0]) for r in rows})
        members = _descendants(client, upload_dataset, roots)
    return sorted(set(roots) | set(members))


def _published(client, upload_dataset: str, paths: list[str]) -> tuple[dict[str, str], set[str]]:
    """Live top-level `vfs_files` hashes and the `vfs_nodes` paths of the given paths.

    An uploaded archive or email has a node of kind `container`, so both kinds count.
    """
    if not paths:
        return {}, set()
    vfs = client.query(
        "SELECT path, hash FROM vfs_files FINAL "
        "WHERE collection_dataset = {ds:String} AND container_hash = '' AND is_deleted = 0 "
        "AND path IN (SELECT path FROM lookup_paths)",
        parameters={"ds": upload_dataset},
        external_data=_string_table("lookup_paths", "path", paths),
    ).result_rows
    nodes = client.query(
        "SELECT DISTINCT path FROM vfs_nodes FINAL "
        "WHERE collection_dataset = {ds:String} AND container_hash = '' "
        "AND kind IN ('file', 'container') "
        "AND path IN (SELECT path FROM lookup_paths)",
        parameters={"ds": upload_dataset},
        external_data=_string_table("lookup_paths", "path", paths),
    ).result_rows
    return {str(p): str(h) for p, h in vfs}, {str(r[0]) for r in nodes}


def batch_outcome(collectionname: str, upload_dataset: str, batch_id: str,
                  operation_state: str = "running") -> dict:
    """The counters and the terminal state of one batch, read from stored state.

    The reads are the file rows of the batch, the live top-level `vfs_files` and
    `vfs_nodes` rows of the ingested paths, the members below each ingested hash, the
    plans of those hashes and their current errors. `classify_outcome` counts them.
    """
    files = read_files(collectionname, batch_id)
    ingested = [row for row in files if row["state"] == "ingested"]
    evidence = OutcomeEvidence()
    if ingested:
        roots = sorted({row["file_hash"] for row in ingested if row["file_hash"]})
        with _client(collectionname) as client:
            evidence.vfs, evidence.nodes = _published(
                client, upload_dataset, [row["path"] for row in ingested])
            evidence.members = _descendants(client, upload_dataset, roots)
            hashes = sorted(set(roots) | set(evidence.members))
            evidence.plans = _plan_state(client, upload_dataset, hashes)
            evidence.failing = current_error_hashes(client, upload_dataset, hashes)
    return classify_outcome(files, evidence, operation_state)


class OutcomeEvidence:
    """The stored facts that `classify_outcome` reads, keyed by path or hash.

    `vfs` maps a path to the hash of its live top-level `vfs_files` row. `nodes` holds the
    paths with a `vfs_nodes` file row.
    `members` maps each member hash to its containing top-level hashes.
    `plans` maps a hash to `(plans, finished plans)`. `failing` holds the hashes with a
    current error.
    """

    def __init__(self, vfs=None, nodes=None, members=None, plans=None, failing=None):
        self.vfs: dict[str, str] = dict(vfs or {})
        self.nodes: set[str] = set(nodes or ())
        self.members: dict[str, set[str]] = {h: ({r} if isinstance(r, str) else set(r))
                                           for h, r in (members or {}).items()}
        self.plans: dict[str, tuple[int, int]] = dict(plans or {})
        self.failing: set[str] = set(failing or ())


def classify_outcome(files: list[dict], evidence: OutcomeEvidence,
                     operation_state: str = "running") -> dict:
    """Count the manifest entries of a batch and choose its terminal state.

    Counters count manifest entries, so a joined row never counts twice. A file
    succeeded when it is `ingested`, its path has a live top-level `vfs_files` row with
    its hash and a `vfs_nodes` file row, its hash has a plan, every plan of its hash and
    of each member below it finished, and none of these hashes has a current error. A
    supported file without text succeeds, because its plan finishes without an error.
    Duplicate content under a new path succeeds through the same checks, with the plans
    of the earlier copy. A `not_sent` or rejected entry never succeeds.

    The state follows these conditions, in order. No file was placed: `cancelled`. The
    operation failed or was cancelled, or a placed file was neither ingested nor
    rejected: `failed`. Every manifest file succeeded: `completed`. Some file succeeded:
    `completed_with_errors`. Otherwise `failed`.
    """
    counts = {
        "files": len(files), "not_sent": 0, "rejected": 0, "placed": 0, "ingested": 0,
        "unaccounted": 0, "published": 0, "processed": 0, "current_errors": 0,
        "succeeded": 0,
    }
    members = evidence.members
    failing_roots = {root for h in evidence.failing for root in ({h} | members.get(h, set()))}
    unfinished_roots = {root for h, (planned, done) in evidence.plans.items()
                        if done < planned for root in ({h} | members.get(h, set()))}
    for row in files:
        state = row["state"]
        if state == "not_sent":
            counts["not_sent"] += 1
        elif state == "rejected":
            counts["rejected"] += 1
            # Ingestion rejects placed files only. The website rejects before placement.
            if (row.get("error") or "").startswith(INGEST_REJECTION_PREFIX):
                counts["placed"] += 1
        elif state in ("pending", "staged"):
            counts["unaccounted"] += 1
        elif state == "placed":
            counts["placed"] += 1
            counts["unaccounted"] += 1
        elif state == "ingested":
            counts["placed"] += 1
            counts["ingested"] += 1
            h = row["file_hash"]
            published = bool(h) and evidence.vfs.get(row["path"]) == h and row["path"] in evidence.nodes
            processed = (bool(h) and evidence.plans.get(h, (0, 0))[0] > 0
                         and h not in unfinished_roots)
            erroring = h in failing_roots
            counts["published"] += int(published)
            counts["processed"] += int(processed)
            counts["current_errors"] += int(erroring)
            counts["succeeded"] += int(published and processed and not erroring)

    if counts["placed"] == 0:
        state = "cancelled"
    elif operation_state in ("errored", "cancelled", "missing") or counts["unaccounted"]:
        state = "failed"
    elif counts["succeeded"] == counts["files"]:
        state = "completed"
    elif counts["succeeded"]:
        state = "completed_with_errors"
    else:
        state = "failed"
    counts["state"] = state
    return counts


def outcome_error(counts: dict) -> str:
    """The batch error text of an outcome, or an empty text for `completed`."""
    if counts["state"] == "completed":
        return ""
    missing = counts["files"] - counts["succeeded"]
    return (f"{missing} of {counts['files']} files did not complete: "
            f"{counts['not_sent']} not sent, {counts['rejected']} rejected, "
            f"{counts['unaccounted']} not ingested, {counts['current_errors']} with processing "
            f"errors.")
