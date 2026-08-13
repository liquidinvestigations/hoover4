"""File-level retry for the documents one pipeline stage failed on.

``processing_plan_finished`` records a plan as finished when its stages have *run*,
not when every document in it succeeded: a stage that records per-document errors
without failing the plan — P4 entity extraction is the common case — still lets the
plan finish. So re-submitting ``execute-plans`` is a no-op for exactly the failures
an operator is most likely looking at, and before this module the only recovery was
re-ingesting the dataset under a new name, which leaves the old name's rows behind in
Manticore for ever.

The unit of recovery here is the **file hash**, taken from ``processing_errors``.
What actually re-runs is the stage that failed, for the plans those hashes belong to:

* ``nlp``   — clear the ``nlp_processed`` watermarks (and any ``entity_hit`` rows) of
  the failed hashes, then ``ExtractEntitiesForPlan`` + ``IndexDatasetPlan``. The
  watermark is the only reason P4 skips a page it has seen, so clearing it for those
  hashes and no others is what makes the plan re-run touch only the failed documents.
* ``embed`` — ``ChunkEmbedForPlan`` + ``IndexDatasetPlan``; both stages are idempotent
  and skip what is already embedded, so no state has to be cleared first.
* ``index`` — ``IndexDatasetPlan`` alone.
* ``plan``  — the parse stages. There is no per-file entry point into P3: the file has
  to be downloaded and re-parsed, which is the plan's job. Retrying these means
  deleting the finished marker and re-running ``ExecutePlans``, which re-processes
  every document of the affected plans.

Deletion order everywhere: **watermarks first, then rows**. A crash between the two
leaves pages that are simply re-extracted, which is the harmless direction; the
reverse leaves a page watermarked with no entities and it is never looked at again.

``processing_errors`` is append-only and both the file browser and the admin processing
page count its **rows**, so a retry that fails the same way must not leave a second copy
behind: the failure count a visitor reads would double, and again on the next retry.
One row per ``(document, task)`` is the invariant, kept by
:func:`partition_retry_result` + :func:`drop_superseded_error_rows` — the run's own row
survives and the row it replaces is deleted.
"""

import logging
from typing import NamedTuple

log = logging.getLogger(__name__)

RETRY_NLP = "nlp"
RETRY_EMBED = "embed"
RETRY_INDEX = "index"
RETRY_PLAN = "plan"

# Task names as they are written into `processing_errors` by the stage workflows.
# Anything not listed is a parse-stage failure and needs the whole plan (RETRY_PLAN):
# the parse stages are per-file child workflows of plan execution and have no entry
# point that does not start by downloading the plan's blobs.
_TASK_RETRY_KIND = {
    "P4_ExtractEntities": RETRY_NLP,
    "P5_ChunkEmbed": RETRY_EMBED,
    "P6_IndexTextPages": RETRY_INDEX,
    "P6_IndexMetadata": RETRY_INDEX,
    "P6_IndexVectors": RETRY_INDEX,
    "P6_IndexFilenamesRow": RETRY_INDEX,
}

# Hashes per ClickHouse query. A hash list goes into ONE query parameter, and the
# server rejects a parameter over 128 KiB — 4 392 failed hashes of 40 characters is
# already past it. Sized by bytes, not by "that looks like a lot".
HASH_CHUNK = 500


class FailureGroup(NamedTuple):
    """One (dataset, task) group of ``processing_errors`` rows.

    A tuple rather than a dataclass on purpose: it is a *report* row built straight
    from a query result, never a workflow or activity parameter, and every params
    dataclass carrying a ``collection_dataset`` must also carry a ``collectionname``
    (``tests/unit/test_params_carry_collection.py`` enforces exactly that).
    """

    collection_dataset: str
    task_name: str
    errors: int
    documents: int
    first_seen: str
    last_seen: str

    @property
    def retry_kind(self) -> str:
        return retry_kind_for_task(self.task_name)


def retry_kind_for_task(task_name: str) -> str:
    """Which re-run recovers the documents `task_name` failed on."""
    return _TASK_RETRY_KIND.get(task_name, RETRY_PLAN)


def chunked(values, size: int = HASH_CHUNK):
    """Yield `values` in lists of at most `size`. Empty input yields nothing."""
    values = list(values)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def list_failures(collectionname: str, collection_dataset: str = "") -> list[FailureGroup]:
    """Every (dataset, task) group in ``processing_errors``, newest failure first."""
    from database.clickhouse import get_collection_client

    where = "WHERE collection_dataset = {ds:String}" if collection_dataset else ""
    with get_collection_client(collectionname) as client:
        rows = client.query(f"""
            SELECT collection_dataset,
                   task_name,
                   count() AS errors,
                   uniqExact(hash) AS documents,
                   toString(min(timestamp)) AS first_seen,
                   toString(max(timestamp)) AS last_seen
            FROM processing_errors
            {where}
            GROUP BY collection_dataset, task_name
            ORDER BY last_seen DESC, task_name ASC
        """, parameters={"ds": collection_dataset}).result_rows
    return [FailureGroup(*row) for row in rows]


def failed_hashes(collectionname: str, collection_dataset: str, task_name: str) -> list[str]:
    """The file hashes `task_name` failed on, sorted. Dataset-level rows (empty hash)
    are excluded: they name no file and nothing per-file can be retried for them."""
    from database.clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT hash FROM processing_errors "
            "WHERE collection_dataset = {ds:String} AND task_name = {task:String} "
            "AND hash != '' ORDER BY hash",
            parameters={"ds": collection_dataset, "task": task_name},
        ).result_rows
    return [row[0] for row in rows]


def plans_for_hashes(collectionname: str, collection_dataset: str, hashes) -> list[str]:
    """The plans those hashes belong to, sorted and de-duplicated."""
    from database.clickhouse import get_collection_client

    found: set[str] = set()
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            rows = client.query(
                "SELECT DISTINCT plan_hash FROM processing_plan_hits "
                "WHERE collection_dataset = {ds:String} AND item_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows
            found.update(row[0] for row in rows)
    return sorted(found)


def clear_nlp_state(collectionname: str, collection_dataset: str, hashes) -> tuple[int, int]:
    """Delete the NER watermarks and entity rows of `hashes`. Returns (watermarks, hits).

    Watermarks first, then the hits — see the module docstring. `mutations_sync=2`
    because the re-run that follows depends on the deletes having landed, and an
    `ALTER TABLE ... DELETE` is asynchronous by default.
    """
    from database.clickhouse import get_collection_client

    settings = {"mutations_sync": 2}
    watermarks = hits = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            watermarks += int(client.query(
                "SELECT count() FROM nlp_processed WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows[0][0])
            hits += int(client.query(
                "SELECT count() FROM entity_hit WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
            ).result_rows[0][0])
            client.command(
                "ALTER TABLE nlp_processed DELETE WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
                settings=settings,
            )
            client.command(
                "ALTER TABLE entity_hit DELETE WHERE collection_dataset = {ds:String} "
                "AND file_hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "hashes": chunk},
                settings=settings,
            )
    log.info(
        "[retry] cleared %d nlp_processed and %d entity_hit rows for %s",
        watermarks, hits, collection_dataset,
    )
    return watermarks, hits


def reopen_plans(collectionname: str, collection_dataset: str, plan_hashes) -> int:
    """Delete the finished markers of `plan_hashes` so ``ExecutePlans`` runs them again."""
    from database.clickhouse import get_collection_client

    reopened = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(plan_hashes):
            client.command(
                "ALTER TABLE processing_plan_finished DELETE "
                "WHERE collection_dataset = {ds:String} AND plan_hash IN {plans:Array(String)}",
                parameters={"ds": collection_dataset, "plans": chunk},
                settings={"mutations_sync": 2},
            )
            reopened += len(chunk)
    return reopened


def hashes_without_entities(collectionname: str, collection_dataset: str, hashes) -> list[str]:
    """Which of `hashes` still have stored text but no NER watermark for it.

    The verification a retry is judged by, and deliberately not "has entity rows": a
    document can legitimately contain no entity at all, and a page whose only variant
    is a redundant copy is watermarked without ever reaching the model. A document with
    text and no watermark, on the other hand, is one P4 has not looked at.
    """
    from database.clickhouse import get_collection_client

    missing: list[str] = []
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            rows = client.query("""
                SELECT DISTINCT t.file_hash
                FROM text_content AS t FINAL
                LEFT ANTI JOIN nlp_processed AS n
                    ON n.collection_dataset = t.collection_dataset
                    AND n.file_hash = t.file_hash
                    AND n.extracted_by = t.extracted_by
                    AND n.page_id = t.page_id
                WHERE t.collection_dataset = {ds:String}
                  AND t.file_hash IN {hashes:Array(String)}
            """, parameters={"ds": collection_dataset, "hashes": chunk}).result_rows
            missing.extend(row[0] for row in rows)
    return sorted(missing)


class RetryOutcome(NamedTuple):
    """What happens to each retried hash's ``processing_errors`` rows.

    * ``recovered`` — nothing new was recorded and the kind's own verification passed:
      every row of that document goes.
    * ``superseded`` — the re-run recorded a fresh error row, so the rows it replaces go
      and the new one stays. This is what keeps a repeated failure at one row instead of
      one more row per attempt.
    * ``unchanged`` — still broken but the re-run recorded nothing (it died before it
      could): the original row is the only evidence there is and is left alone.
    """

    recovered: list[str]
    superseded: list[str]
    unchanged: list[str]


def partition_retry_result(hashes, refreshed, still_broken) -> RetryOutcome:
    """Split the retried hashes by what the re-run did to them.

    ``refreshed`` are the hashes that have a ``processing_errors`` row written during the
    run; ``still_broken`` are the ones the kind's own verification rejects (for an NER
    retry: no watermark for their text). A hash that is in neither is recovered.

    A fresh error row wins over the verification: a document that recorded a new failure
    is not recovered even if a watermark appeared for some other page of it.
    """
    fresh = set(refreshed)
    broken = set(still_broken)
    outcome = RetryOutcome([], [], [])
    for file_hash in hashes:
        if file_hash in fresh:
            outcome.superseded.append(file_hash)
        elif file_hash in broken:
            outcome.unchanged.append(file_hash)
        else:
            outcome.recovered.append(file_hash)
    return outcome


def refreshed_hashes(collectionname: str, collection_dataset: str, task_name: str,
                     since) -> list[str]:
    """The hashes `task_name` recorded a NEW error row for at or after `since`.

    `since` is read from the ClickHouse server's clock, not this process's: the rows are
    timestamped by the workers that write them, on another host.
    """
    from database.clickhouse import get_collection_client

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT DISTINCT hash FROM processing_errors "
            "WHERE collection_dataset = {ds:String} AND task_name = {task:String} "
            "AND hash != '' AND timestamp >= {since:DateTime}",
            parameters={"ds": collection_dataset, "task": task_name, "since": since},
        ).result_rows
    return sorted(row[0] for row in rows)


def drop_superseded_error_rows(collectionname: str, collection_dataset: str,
                               task_name: str, hashes, since) -> int:
    """Delete the pre-`since` rows of `hashes`, leaving the ones this run wrote.

    Called for documents that failed AGAIN, and it is what makes a retry replace an error
    record rather than add to it. The newest row is the one kept because it describes the
    code that is running now; the count the file browser shows stays at one per document
    however many times the retry is run.
    """
    from database.clickhouse import get_collection_client

    dropped = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            client.command(
                "ALTER TABLE processing_errors DELETE "
                "WHERE collection_dataset = {ds:String} AND task_name = {task:String} "
                "AND hash IN {hashes:Array(String)} AND timestamp < {since:DateTime}",
                parameters={"ds": collection_dataset, "task": task_name,
                            "hashes": chunk, "since": since},
                settings={"mutations_sync": 2},
            )
            dropped += len(chunk)
    log.info(
        "[retry] superseded the error rows of %d document(s) of %s %s",
        dropped, collection_dataset, task_name,
    )
    return dropped


def clear_error_rows(collectionname: str, collection_dataset: str, task_name: str, hashes) -> int:
    """Delete the `processing_errors` rows of `hashes` for one task of one dataset.

    Called only AFTER the re-run has succeeded for those hashes. The admin UI's retry
    button clears them first, which loses the record if the retry fails again; here the
    row survives until the document it describes is demonstrably fixed.
    """
    from database.clickhouse import get_collection_client

    cleared = 0
    with get_collection_client(collectionname) as client:
        for chunk in chunked(hashes):
            client.command(
                "ALTER TABLE processing_errors DELETE "
                "WHERE collection_dataset = {ds:String} AND task_name = {task:String} "
                "AND hash IN {hashes:Array(String)}",
                parameters={"ds": collection_dataset, "task": task_name, "hashes": chunk},
                settings={"mutations_sync": 2},
            )
            cleared += len(chunk)
    return cleared
