"""CLI entry point for processing services, including migrations and workers."""

import click
import asyncio

import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

@click.group()
def cli():
    pass

@cli.command()
def version():
    print("0.0.0")


@cli.command()
def migrate():
    """Run all database migrations."""
    from database.clickhouse import clickhouse_migrate
    from database.s3 import SYSTEM_BUCKET
    clickhouse_migrate()
    from database.s3 import ensure_bucket
    # Only the system bucket. A collection's bucket is created with the collection, so
    # there is nothing here that knows which collections exist yet.
    ensure_bucket(SYSTEM_BUCKET)
    from database.manticore import manticore_migrate
    manticore_migrate()


@cli.command()
@click.argument("collectionname", type=str)
def ensure_collection(collectionname: str):
    """Create a collection's ClickHouse database and bucket if missing, and migrate it.

    Idempotent. Note this does NOT create the `collections` row - collections are
    created in the admin UI; this only provisions the storage for one that exists.
    """
    from database.s3 import ensure_collection_storage

    try:
        db_name = ensure_collection_storage(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))
    log.info("Collection database ready: %s", db_name)
    print(db_name)


@cli.command(name="create-collection")
@click.argument("collectionname", type=str)
@click.option("--fullname", type=str, default="", help="Human-readable display name.")
@click.option("--public/--no-public", "is_public", default=False,
              help="Readable by every user (and by guests), rather than by group grant only.")
def create_collection(collectionname: str, fullname: str, is_public: bool):
    """Register a collection and provision its storage.

    The scripted equivalent of creating a collection in the admin UI: it writes the
    `collections` row the UI writes and then does what `ensure-collection` does, so one
    command leaves a collection that can be ingested into. Idempotent, so an ingest
    script that re-runs is safe.

    `--public` is worth stating explicitly. A collection is restricted by default and is
    then visible only through a group grant; a demo that shows its collections anyway is
    relying on `demo_mode` and the `guest_permissions_mode` setting both being open,
    which is two independent defaults holding rather than one intent recorded.
    """
    from database.clickhouse import get_global_client, validate_collectionname
    from database.s3 import ensure_collection_storage

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    with get_global_client() as client:
        existing = client.query(
            "SELECT fullname, is_public FROM collections FINAL "
            "WHERE collectionname = {name:String} AND is_deleted = 0",
            parameters={"name": collectionname},
        ).result_rows
        if existing:
            log.info("Collection row already present: %s", collectionname)
        else:
            client.insert(
                "collections",
                [[collectionname, fullname or collectionname, int(is_public)]],
                column_names=["collectionname", "fullname", "is_public"],
            )
            log.info("Collection row created: %s (is_public=%d)", collectionname, int(is_public))

    log.info("Collection database ready: %s", ensure_collection_storage(collectionname))
    print(collectionname)


@cli.command()
@click.option("--no-defaults", is_flag=True,
              help="Refresh the model list without touching the chat/summarisation choices.")
def refresh_llm_catalog(no_defaults: bool = False):
    """Discover models from the configured LLM provider into `llm_models`.

    Model ids are matched by PATTERN against what the account actually returns, never
    hardcoded: NIM retires ids, and a hardcoded one becomes a 404 months later in a path
    nobody exercises until a user opens the chat.
    """
    from tasks.llm_catalog import (
        SETTING_CHAT_MODEL, SETTING_SUMMARIZATION_MODEL, refresh_catalog,
    )

    results = refresh_catalog(choose_defaults=not no_defaults)
    if not results:
        print("no provider configured (LLM_BASE_URL is empty), or a refresh is in flight")
        return
    for result in results:
        if result.ok:
            print(f"{result.provider}: {result.model_count} models")
        else:
            print(f"{result.provider}: FAILED {result.error}")
    if not no_defaults:
        from database.clickhouse import get_global_client
        with get_global_client() as client:
            rows = client.query(
                "SELECT key, argMax(value, updated_at) FROM server_settings "
                "WHERE key IN ({a:String}, {b:String}) GROUP BY key",
                parameters={"a": SETTING_CHAT_MODEL, "b": SETTING_SUMMARIZATION_MODEL},
            ).result_rows
        for key, value in rows:
            print(f"{key} = {value}")


@cli.command(name="probe-embeddings")
def probe_embeddings_cmd():
    """Probe the embeddings endpoint and record what it ACTUALLY serves.

    Writes ``embeddings_serving_model`` and ``embeddings_serving_dim`` to
    ``server_settings``. The index builder reads those (never the ini), because
    the ini is the request and this probe is the truth, and a Manticore ``_vectors``
    table's ``knn_dims`` cannot be altered after creation.

    The embed and indexing workers now run the same probe at startup, so this command is
    for re-probing after a model change without a restart, and for `verify-stack.sh`.
    """
    import os

    from tasks.remote import record_embeddings_probe

    if not (os.getenv("EMBEDDINGS_URL") or "").strip():
        print("EMBEDDINGS_URL is empty (embeddings_provider = none); nothing to probe")
        return
    probed = record_embeddings_probe()
    if not probed:
        raise SystemExit("embeddings probe failed; server_settings unchanged (see the log)")
    model, dims = probed
    print(f"embeddings_serving_model = {model}")
    print(f"embeddings_serving_dim = {dims}")


@cli.command()
def test_extract_ner_from_text():
    from tasks.P4_extract_entities.extract_ner_from_text import extract_ner_from_texts
    with open('/etc/dictionaries-common/words') as f:
        words = f.readlines()
    import random
    random.shuffle(words)
    words = " ".join(words)
    entities = extract_ner_from_texts([words])
    print(entities)


@cli.command()
@click.argument("collectionname", type=str)
@click.argument("dataset_name", type=str)
@click.argument("path", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=str))
@click.option("--wait/--no-wait", default=True, show_default=True,
              help="Block until ingestion finishes. --no-wait submits the workflow "
                   "and returns, leaving it to run server-side.")
def add_disk_dataset(collectionname: str, dataset_name: str, path: str, wait: bool):
    """Create a dataset inside an existing collection and start disk ingestion.

    Submits an `add_dataset` operation, prints its id, and then follows it. All three
    stages -- scan, compute plans, execute plans -- are sequenced server-side by the
    operation, so this command holds nothing the work depends on.

    Ctrl-C therefore DETACHES: it stops the watching, never the ingest. `--no-wait`
    skips the watching from the start. Either way the operation id names the work for
    as long as the log exists, which is for ever.

    An existing dataset is a rescan, not a collision: the scan re-ingests every path it
    finds and tombstones what it no longer finds, which is how an edited or deleted
    file is picked up. A second dispatch is refused only while the first one is still
    running.
    """
    from tasks.P0_scan_disk.submit_job import (
        compose_collection_dataset, prepare_disk_dataset,
    )
    from tasks.P_ops.cli import submit_operation, tail_operation, where_to_look
    from database.operations import OperationLocked

    collection_dataset = compose_collection_dataset(collectionname, dataset_name)
    path = prepare_disk_dataset(collectionname, dataset_name, path)
    try:
        op_id = submit_operation(
            "add_dataset", collectionname=collectionname,
            collection_dataset=collection_dataset, dataset_path=path,
            detail={"dataset_path": path, "dataset_name": dataset_name},
        )
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {op_id}")
    if not wait:
        click.echo(where_to_look(op_id))
        return
    state = tail_operation(op_id)
    if state == "errored":
        raise click.ClickException(f"{op_id} failed.")


@cli.group()
def operations():
    """Inspect and control long-running operations.

    Every significant command in this CLI dispatches one of these and then watches it.
    The operation, not the command, is what the work belongs to: these subcommands are
    how a caller that detached, or a caller that never attached, finds it again.
    """


@operations.command(name="list")
# `default=None`, not `default=""`: click validates a non-None default against the
# choice list, so an empty-string default makes the option impossible to omit.
@click.option("--state", type=click.Choice(["pending", "running", "finished",
                                            "errored", "cancelled"]), default=None)
@click.option("--collection", "collectionname", type=str, default="")
@click.option("--kind", type=str, default="")
@click.option("--limit", type=int, default=25, show_default=True)
def operations_list(state: str, collectionname: str, kind: str, limit: int):
    """Recent operations, newest first."""
    from database.operations import list_operations
    from tasks.P_ops.cli import format_row

    rows = list_operations(state=state or "", collectionname=collectionname, kind=kind,
                           limit=limit)
    if not rows:
        click.echo("No operations match.")
        return
    for row in rows:
        click.echo(format_row(row))


@operations.command(name="show")
@click.argument("op_id", type=str)
@click.option("--follow/--no-follow", default=False, show_default=True,
              help="Keep printing until it reaches a terminal state.")
def operations_show(op_id: str, follow: bool):
    """One operation in full, including the parameters it was dispatched with."""
    from database.operations import get_operation
    from tasks.P_ops.cli import format_row, tail_operation

    row = get_operation(op_id)
    if row is None:
        raise click.ClickException(f"No operation with id {op_id}.")
    click.echo(format_row(row))
    click.echo(f"started   {row['started_at']}")
    if row["finished_at"].timestamp() > 0:
        click.echo(f"finished  {row['finished_at']}")
    click.echo(f"user      {row['user_id']}")
    if row["rerun_of"]:
        click.echo(f"rerun of  {row['rerun_of']}")
    if row["detail"]:
        click.echo(f"detail    {row['detail']}")
    if row["error"]:
        click.echo(f"error     {row['error']}")
    if follow:
        tail_operation(op_id)


@operations.command(name="rerun")
@click.argument("op_id", type=str)
@click.option("--wait/--no-wait", default=True, show_default=True)
def operations_rerun(op_id: str, wait: bool):
    """Dispatch a fresh operation with the same kind and target as an existing one.

    A new id and a new row, never a resumption: the original run's record is what the
    log is for, and overwriting it would hide the attempt that made a re-run necessary.
    """
    import json
    from database.operations import OperationLocked, get_operation
    from tasks.P_ops.cli import submit_operation, tail_operation, where_to_look

    row = get_operation(op_id)
    if row is None:
        raise click.ClickException(f"No operation with id {op_id}.")
    try:
        detail = json.loads(row["detail"] or "{}")
    except ValueError:
        detail = {}
    try:
        new_id = submit_operation(
            row["kind"], collectionname=row["collectionname"],
            collection_dataset=row["collection_dataset"],
            dataset_path=detail.get("dataset_path", ""),
            detail=detail, rerun_of=op_id,
        )
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {new_id}")
    if not wait:
        click.echo(where_to_look(new_id))
        return
    tail_operation(new_id)


@operations.command(name="cancel")
@click.argument("op_id", type=str)
def operations_cancel(op_id: str):
    """Cancel an operation and release the lock it holds.

    `cancelled` is a state of its own, not a failure, and it is re-runnable: every
    pipeline stage is idempotent, so stopping one part-way loses progress and nothing
    else.
    """
    from tasks.P_ops.cli import request_cancel

    request_cancel(op_id)
    click.echo(f"{op_id} cancelled")


async def _open_index_workflows(collectionname: str) -> list[str]:
    """Ids of the collection's still-open indexing workflows.

    Asked of Temporal rather than of a table: the writers are workflows, and the only
    authority on whether one is still running is the server that is running it. The
    `CollectionDataset` search attribute is per dataset and every dataset of a collection
    is prefixed with the collection's name, so the filter is a prefix match done here.
    """
    from temporalio.client import Client as TemporalClient

    client = await TemporalClient.connect("temporal:7233")
    prefix = f"{collectionname}_"
    open_ids = []
    async for execution in client.list_workflows(
        "WorkflowType = 'IndexDatasetPlan' AND ExecutionStatus = 'Running'"
    ):
        dataset = (execution.search_attributes or {}).get("CollectionDataset") or []
        values = dataset if isinstance(dataset, list) else [dataset]
        if any(str(v).startswith(prefix) for v in values):
            open_ids.append(execution.id)
    return open_ids


@cli.command(name="export-collection")
@click.argument("collectionname", type=str)
@click.option("--destination", default="", metavar="NAME",
              help="Subdirectory of the backup root to write into. Defaults to the "
                   "operation id, which is unique per run.")
@click.option("--wait/--no-wait", default=True, show_default=True,
              help="--no-wait prints the operation id and returns immediately.")
def export_collection(collectionname: str, destination: str, wait: bool):
    """Back a collection up into one directory under the configured backup root.

    Writes the collection's objects, its ClickHouse database and its Manticore tables,
    in that order, with a manifest naming every artifact and its size. Original source
    data is not included: it is held outside this system.

    DESTINATION names a subdirectory and never a path, so a directory that is not
    mounted into the operations container cannot be asked for. A run that fails leaves a
    `.partial-<op_id>` directory that blocks no later attempt.
    """
    from database.clickhouse import validate_collectionname
    from database.operations import OperationLocked
    from tasks.P_ops.cli import submit_operation, tail_operation, where_to_look

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    try:
        op_id = submit_operation("export_collection", collectionname=collectionname,
                                 detail={"destination": destination} if destination
                                 else {})
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {op_id}")
    if not wait:
        click.echo(where_to_look(op_id))
        return
    state = tail_operation(op_id)
    if state == "errored":
        raise click.ClickException(f"{op_id} failed.")


@cli.command(name="import-collection")
@click.argument("collectionname", type=str)
@click.option("--source", required=True, metavar="NAME",
              help="Subdirectory of the backup root holding the backup to restore.")
@click.option("--confirm", default="", metavar="COLLECTIONNAME",
              help="The collection name again. Asked for interactively if omitted.")
@click.option("--wait/--no-wait", default=True, show_default=True,
              help="--no-wait prints the operation id and returns immediately.")
def import_collection(collectionname: str, source: str, confirm: str, wait: bool):
    """Restore a collection from a backup directory under the configured backup root.

    Restores the collection's objects, its ClickHouse database and its Manticore tables,
    in that order, then its configuration rows, from the manifest the export wrote.

    The target must be an empty collection of the SAME name: a collection is restored
    under its own name because the name is part of the database name, of every dataset
    id, of every search table and of every object key. A target that still holds data is
    refused naming what is in the way. Delete the collection first, or do not import.
    """
    from database.clickhouse import validate_collectionname
    from database.operations import OperationLocked
    from tasks.P_ops.cli import submit_operation, tail_operation, where_to_look

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    # A destructive kind is confirmed by typing its target, here as in the interface: an
    # import replaces a collection, and the one thing worth being sure of is which.
    typed = confirm or click.prompt(
        f"This replaces the collection {collectionname} from the backup in {source}. "
        f"Type the collection name to continue", default="", show_default=False)
    if typed != collectionname:
        raise click.ClickException(
            f"{typed!r} is not {collectionname!r}; nothing was imported.")

    try:
        op_id = submit_operation("import_collection", collectionname=collectionname,
                                 detail={"source": source})
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {op_id}")
    if not wait:
        click.echo(where_to_look(op_id))
        return
    state = tail_operation(op_id)
    if state == "errored":
        raise click.ClickException(f"{op_id} failed.")


@cli.command(name="reindex-collection")
@click.argument("collectionname", type=str)
def reindex_collection(collectionname: str):
    """Drop a collection's Manticore tables + shard ledger and re-index every finished plan.

    Recovery path for a lost Manticore volume, for a change to
    MAX_SHARD_TEXT_BYTES, and for shard fragmentation. This is the substitute
    for a compaction feature: shards are never compacted or renumbered in
    place, they are rebuilt from scratch here.

    This truncates the shard ledger, the assignments and index_state, so it refuses
    while ANY operation for the collection is non-terminal, and while any
    IndexDatasetPlan workflow is open for it: an in-flight writer would otherwise
    record index_state rows into shards this is about to drop, and the result is a
    ledger that claims documents no table holds. The docstring used to ask the caller
    to stop the indexing workers first; the operations lock is what enforces it.

    Dispatched as an operation and then followed, so Ctrl-C detaches rather than
    abandoning a collection with a truncated ledger.
    """
    from database.clickhouse import validate_collectionname
    from database.operations import OperationLocked, open_operations_for_collection
    from tasks.P_ops.cli import submit_operation, tail_operation

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    # Two guards, and they answer different questions. The operations lock refuses a
    # second dispatch of anything that is writing to this collection; the Temporal
    # query catches an indexing run started before operations existed, or started by a
    # surface that does not go through them yet.
    holding = open_operations_for_collection(collectionname)
    if holding:
        names = ", ".join(f"{r['op_id']} ({r['kind']}, {r['state']})" for r in holding[:5])
        raise click.ClickException(
            f"{len(holding)} operation(s) are still open for {collectionname}: "
            f"{names}. Wait for them, or cancel one with `main.py operations cancel "
            f"<op_id>`, then run this again."
        )

    running = asyncio.run(_open_index_workflows(collectionname))
    if running:
        raise click.ClickException(
            f"{len(running)} IndexDatasetPlan workflow(s) are still open for "
            f"{collectionname}: {', '.join(running[:5])}. Wait for them, or cancel "
            f"them in the Temporal UI, then run this again."
        )

    try:
        op_id = submit_operation("reindex_collection", collectionname=collectionname)
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {op_id}")
    state = tail_operation(op_id)
    if state == "errored":
        raise click.ClickException(f"{op_id} failed.")


@cli.command(name="purge-dataset")
@click.argument("collectionname", type=str)
@click.argument("collection_dataset", type=str)
@click.option("--apply/--dry-run", default=False, show_default=True,
              help="--dry-run (the default) only reports what would be deleted.")
@click.option("--registered", "allow_registered", is_flag=True,
              help="Also purge a dataset that still has a live `dataset` registry row. "
                   "Without this the command refuses one, because deleting a live "
                   "dataset belongs in the admin UI, which purges AND removes the row.")
def purge_dataset(collectionname: str, collection_dataset: str, apply: bool, allow_registered: bool):
    """Delete one dataset's rows from a collection's Manticore tables and ClickHouse.

    The recovery path for a dataset that was abandoned rather than deleted. A failed
    ingest, or a re-ingest under a new name, which leaves the old name's rows in the
    index for ever. Those rows are what makes the Collections filter offer a dataset
    that no longer exists, and what makes every document of a twice-ingested dataset
    count twice in an unfiltered search.

    COLLECTION_DATASET is the full `<collectionname>_<dataset_name>` id and must be
    named in full: there is no pattern, no wildcard and no "all datasets of" form,
    because this deletes indexed data and a typo that widens the match is unrecoverable.

    Idempotent, and safe to re-run: purging a dataset with no rows left prints that and
    changes nothing. The shard ledger is recomputed afterwards from the surviving
    `index_state` rows, so the shards the deleted dataset contributed to shrink; shards
    are never compacted or renumbered.

    The dry run is a local read-only report. `--apply` dispatches a `purge_dataset`
    operation and follows it, so the deletion takes the dataset's lock, leaves a row in
    the operations log, and outlives this terminal: Ctrl-C detaches from the watching
    and stops nothing.
    """
    from database.clickhouse import get_global_client, validate_collectionname
    from database.operations import OperationLocked
    from tasks.P_admin.activities import count_dataset_rows
    from tasks.P_ops.cli import submit_operation, tail_operation

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))
    if not collection_dataset.startswith(f"{collectionname}_"):
        raise click.ClickException(
            f"{collection_dataset!r} is not a dataset of {collectionname!r}: a dataset id "
            f"is composed as <collectionname>_<dataset_name>, so it must start with "
            f"{collectionname + '_'!r}"
        )

    with get_global_client() as client:
        registry = client.query(
            "SELECT is_deleted FROM dataset FINAL WHERE collection_dataset = {cd:String}",
            parameters={"cd": collection_dataset},
        ).result_rows
    live_row = any(int(row[0]) == 0 for row in registry)
    if live_row and not allow_registered:
        raise click.ClickException(
            f"{collection_dataset} still has a live `dataset` registry row. Delete the "
            f"dataset in the admin UI (it soft-deletes the row and runs this same purge), "
            f"or pass --registered to purge the data and leave the row behind."
        )

    counts = count_dataset_rows(collectionname, collection_dataset)
    total = sum(counts["manticore"].values()) + sum(counts["clickhouse"].values())
    print(f"{collection_dataset}: {total} row(s) to purge"
          + (" (registry row present)" if registry else " (no registry row)"))
    for store in ("manticore", "clickhouse"):
        for table, count in sorted(counts[store].items()):
            if count:
                print(f"  {store:10s} {table:32s} {count}")
    if not total:
        print("nothing to purge")
        return
    if not apply:
        print("dry run; pass --apply to delete these rows")
        return

    try:
        op_id = submit_operation("purge_dataset", collectionname=collectionname,
                                 collection_dataset=collection_dataset)
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {op_id}")
    state = tail_operation(op_id)
    if state == "errored":
        raise click.ClickException(f"{op_id} failed.")


@cli.command(name="retry-failed-files")
@click.argument("collectionname", type=str)
@click.option("--dataset", "collection_dataset", type=str, default="",
              help="Limit to one `<collectionname>_<dataset_name>`.")
@click.option("--task", "task_name", type=str, default="",
              help="The `processing_errors.task_name` to retry, e.g. P4_ExtractEntities. "
                   "Required for --apply.")
@click.option("--apply/--dry-run", default=False, show_default=True,
              help="--dry-run (the default) only reports what failed and how it would be retried.")
def retry_failed_files(collectionname: str, collection_dataset: str, task_name: str, apply: bool):
    """Re-run one failed stage for the file hashes recorded in `processing_errors`.

    A plan is marked finished when its stages have RUN, not when every document
    succeeded, a stage that records per-document errors without failing the plan (P4
    entity extraction is the common case) still lets the plan finish. `execute-plans` is
    therefore a no-op for exactly those failures, and this is the way back: the failed
    hashes are re-run through the stage that failed them, with no re-ingest and no new
    dataset name.

    What re-runs depends on the task, and the dry run says which before anything
    happens: NER failures clear the failed hashes' watermarks and re-run P4 + P6 for
    their plans; index failures re-run P6 alone; embedding failures re-run P5 + P6;
    parse failures have no per-file entry point and reopen the whole plan, which
    re-processes its other documents too.

    The `processing_errors` rows are cleared only after the re-run has finished and the
    documents have a watermark again. A document that fails again keeps exactly one row.
    The one this run wrote, replacing the one it started from. The count is what the file
    browser and the admin processing page show, so appending instead would double the
    failures a visitor sees, and again on every further retry.

    The dry run is a local read-only report. `--apply` dispatches a `retry_failed_files`
    operation and follows it, so the retry takes the dataset's lock, leaves a row saying
    what was retried and how it ended, and outlives this terminal: Ctrl-C detaches from
    the watching and stops nothing.
    """
    from database.clickhouse import validate_collectionname
    from database.operations import OperationLocked
    from tasks.P_admin.failed_file_retry import list_failures
    from tasks.P_ops.cli import submit_operation, tail_operation

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    groups = list_failures(collectionname, collection_dataset)
    if collection_dataset:
        groups = [g for g in groups if g.collection_dataset == collection_dataset]
    if task_name:
        groups = [g for g in groups if g.task_name == task_name]
    if not groups:
        print(f"{collectionname}: no recorded failures for that selection")
        return

    print(f"{'dataset':28s} {'task':28s} {'errors':>7s} {'docs':>7s}  retry     last failure")
    for g in groups:
        print(f"{g.collection_dataset:28s} {g.task_name:28s} {g.errors:7d} {g.documents:7d}  "
              f"{g.retry_kind:8s}  {g.last_seen}")

    if not apply:
        print("dry run; pass --task <name> --apply to retry one of these")
        return
    if not task_name:
        raise click.ClickException(
            "--apply needs --task: retrying every stage at once would re-run the whole "
            "pipeline for every failed document, which is the thing this command exists "
            "to avoid"
        )
    datasets = sorted({g.collection_dataset for g in groups})
    if len(datasets) > 1 and not collection_dataset:
        raise click.ClickException(
            f"--apply needs --dataset: {task_name} failed in {len(datasets)} datasets "
            f"({', '.join(datasets)})"
        )
    collection_dataset = datasets[0]

    # Which documents to retry, what to clear before the re-run and which error rows may
    # be cleared after it are all decided inside the operation, against the corpus as it
    # is when the retry starts rather than as it was when this command was typed.
    try:
        op_id = submit_operation("retry_failed_files", collectionname=collectionname,
                                 collection_dataset=collection_dataset,
                                 detail={"task_name": task_name})
    except OperationLocked as e:
        raise click.ClickException(str(e))
    click.echo(f"operation {op_id}")
    state = tail_operation(op_id)
    if state == "errored":
        raise click.ClickException(f"{op_id} failed.")


@cli.command(name="purge-unattributed-entities")
@click.argument("collectionname", type=str)
@click.option("--apply/--dry-run", default=False, show_default=True,
              help="--dry-run (the default) only reports what would change.")
def purge_unattributed_entities(collectionname: str, apply: bool):
    """Clear `entity_hit` rows with an empty `nlp_model`, re-running NER for their pages.

    These are rows written before `nlp_model` existed. `nlp_model` is part of the table's
    ORDER BY (deliberately, so two NER providers can coexist), which means a later run
    under a real provider name **adds** rows rather than replacing them: the unattributed
    set is immortal, and the admin UI renders it as a phantom third provider whose entities
    nothing can be filtered by.

    Deleting them alone is not safe in general, and the live stack proved it: one
    collection's entire entity set was unattributed, so a bare DELETE would have removed
    every entity it had. So this also clears the `nlp_processed` watermark for the affected
    pages, which is what makes P4 extract them again. The watermark is the only reason it
    would skip a page it has already seen.

    Order matters: watermarks first, then the rows, then the re-run. A crash between the
    two deletes leaves pages that will be re-extracted, which is the harmless
    direction.
    """
    from database.clickhouse import get_collection_client, validate_collectionname

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    with get_collection_client(collectionname) as client:
        rows = client.query(
            "SELECT count() FROM entity_hit FINAL WHERE nlp_model = ''"
        ).result_rows
        orphan_rows = int(rows[0][0]) if rows else 0
        pages = client.query(
            "SELECT uniqExact((file_hash, extracted_by, page_id)) FROM entity_hit FINAL "
            "WHERE nlp_model = ''"
        ).result_rows
        orphan_pages = int(pages[0][0]) if pages else 0

    if not orphan_rows:
        print(f"{collectionname}: no unattributed entity_hit rows")
        return

    print(f"{collectionname}: {orphan_rows} unattributed entity_hit row(s) "
          f"over {orphan_pages} page(s)")
    if not apply:
        print("dry run; pass --apply to delete them and re-run NER for those pages")
        return

    with get_collection_client(collectionname) as client:
        # `ALTER TABLE ... DELETE` is a mutation: asynchronous by default, and the next
        # step depends on it having landed. `mutations_sync=2` waits for every replica.
        settings = {"mutations_sync": 2}
        client.command("""
            ALTER TABLE nlp_processed DELETE WHERE (file_hash, extracted_by, page_id) IN (
                SELECT file_hash, extracted_by, page_id FROM entity_hit FINAL
                WHERE nlp_model = ''
            )
        """, settings=settings)
        client.command(
            "ALTER TABLE entity_hit DELETE WHERE nlp_model = ''", settings=settings
        )
        plans = client.query(
            "SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL "
            "ORDER BY collection_dataset, plan_hash"
        ).result_rows

    print(f"deleted; re-running NER + index for {len(plans)} finished plan(s)")

    async def _run():
        from temporalio.client import Client as TemporalClient
        import temporalio.common
        from tasks.P4_extract_entities.workflows import ExtractEntitiesForPlan
        from tasks.P4_extract_entities.params import ExtractEntitiesForPlanParams
        from tasks.P6_index_data.workflows import IndexDatasetPlan
        from tasks.P6_index_data.params import IndexDatasetPlanParams
        from tasks.visibility import dataset_search_attributes

        client = await TemporalClient.connect("temporal:7233")
        for collection_dataset, plan_hash in plans:
            # P4 then P6: the index copies the entity rows P4 writes, and the Manticore
            # `ner` term dictionary is built from them.
            handle = await client.start_workflow(
                ExtractEntitiesForPlan.run,
                ExtractEntitiesForPlanParams(
                    collectionname=collectionname,
                    collection_dataset=collection_dataset,
                    plan_hash=plan_hash,
                ),
                id=f"reattribute-ner-{collection_dataset}-{plan_hash}",
                task_queue="processing-common-queue",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )
            log.info("NER re-run: %s plan %s", collection_dataset, plan_hash[:8])
            await handle.result()
            handle = await client.start_workflow(
                IndexDatasetPlan.run,
                IndexDatasetPlanParams(
                    collectionname=collectionname,
                    collection_dataset=collection_dataset,
                    plan_hash=plan_hash,
                ),
                id=f"reattribute-index-{collection_dataset}-{plan_hash}",
                task_queue="processing-common-queue",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )
            log.info("re-index: %s plan %s", collection_dataset, plan_hash[:8])
            await handle.result()

    asyncio.run(_run())
    print(f"purge-unattributed-entities of {collectionname}: done")


@cli.command(name="backfill-vectors")
@click.argument("collectionname", type=str)
def backfill_vectors(collectionname: str):
    """Run chunk+embed (P5) and re-index (P6) every finished plan of a collection.

    The backfill path for data ingested before P5 existed: the normal pipeline runs
    ChunkEmbedForPlan inside ExecuteSinglePlan, but a plan that finished earlier has
    no chunks or vectors. Both stages are idempotent (left-anti join on the vector
    key; REPLACE INTO with deterministic row ids), so re-running over already-embedded
    plans costs a scan, not a re-embed.

    Blocks until every plan's two workflows have completed. ClickHouse keeps the
    vectors, so this never drops anything; use `reindex-collection` instead when the
    Manticore tables themselves must be rebuilt (lost volume, knn_dims change).
    """
    from database.clickhouse import get_collection_client, validate_collectionname

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    with get_collection_client(collectionname) as client:
        plans = client.query(
            "SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL "
            "ORDER BY collection_dataset, plan_hash"
        ).result_rows

    if not plans:
        log.warning("No finished plans found for %s - nothing to backfill", collectionname)
        return

    async def _run():
        from temporalio.client import Client as TemporalClient
        import temporalio.common
        from tasks.P5_chunk_embed.workflows import ChunkEmbedForPlan
        from tasks.P5_chunk_embed.params import ChunkEmbedForPlanParams
        from tasks.P6_index_data.workflows import IndexDatasetPlan
        from tasks.P6_index_data.params import IndexDatasetPlanParams
        from tasks.visibility import dataset_search_attributes

        client = await TemporalClient.connect("temporal:7233")
        for collection_dataset, plan_hash in plans:
            # P5 before P6: the vector indexer copies the rows P5 writes.
            handle = await client.start_workflow(
                ChunkEmbedForPlan.run,
                ChunkEmbedForPlanParams(collectionname=collectionname, collection_dataset=collection_dataset, plan_hash=plan_hash),
                id=f"backfill-embed-{collection_dataset}-{plan_hash}",
                task_queue="processing-common-queue",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )
            log.info("chunk+embed running: %s plan %s", collection_dataset, plan_hash[:8])
            await handle.result()
            handle = await client.start_workflow(
                IndexDatasetPlan.run,
                IndexDatasetPlanParams(collectionname=collectionname, collection_dataset=collection_dataset, plan_hash=plan_hash),
                id=f"backfill-index-{collection_dataset}-{plan_hash}",
                task_queue="processing-common-queue",
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )
            log.info("re-index running: %s plan %s", collection_dataset, plan_hash[:8])
            await handle.result()

    asyncio.run(_run())
    print(f"backfill-vectors of {collectionname}: {len(plans)} plan(s) done")


@cli.command(name="list-collections")
def list_collections_cmd():
    """Print each collection's name, ClickHouse database and dataset count."""
    from database.clickhouse import collection_db_name, get_global_client

    with get_global_client() as client:
        collections = client.query(
            "SELECT collectionname FROM collections FINAL "
            "WHERE is_deleted = 0 ORDER BY collectionname"
        ).result_rows
        counts = dict(client.query(
            "SELECT collectionname, count() FROM dataset FINAL "
            "WHERE is_deleted = 0 GROUP BY collectionname"
        ).result_rows)

    for (collectionname,) in collections:
        print(f"{collectionname}\t{collection_db_name(collectionname)}\t{counts.get(collectionname, 0)}")

@cli.command()
@click.argument("worker_type", required=False, type=click.Choice(["common", "tika", "ocr", "nlp", "embed", "indexing", "index-planner", "operations", "chat"]))
def worker(worker_type: str | None = None):
    """Run worker(s). If worker_type provided, runs that worker; else spawns all.

    `operations` is deliberately NOT in the spawn set below: it runs in its own
    container, with its own memory and CPU budget and the datastore volumes mounted,
    so that a backup or a restore cannot take capacity from ingestion. Adding it here
    would run a second copy of it beside the pipeline fleet.
    """
    import sys
    import subprocess

    # Map to function names in tasks.run_worker
    if worker_type:
        # Run single worker in current process
        if worker_type == "common":
            from tasks.run_worker import run_common_worker
            asyncio.run(run_common_worker())
        elif worker_type == "tika":
            from tasks.run_worker import run_tika_worker
            asyncio.run(run_tika_worker())
        elif worker_type == "ocr":
            from tasks.run_worker import run_ocr_worker
            asyncio.run(run_ocr_worker())
        elif worker_type == "nlp":
            from tasks.run_worker import run_nlp_worker
            asyncio.run(run_nlp_worker())
        elif worker_type == "embed":
            from tasks.run_worker import run_embed_worker
            asyncio.run(run_embed_worker())
        elif worker_type == "indexing":
            from tasks.run_worker import run_indexing_worker
            asyncio.run(run_indexing_worker())
        elif worker_type == "index-planner":
            from tasks.run_worker import run_index_planner_worker
            asyncio.run(run_index_planner_worker())
        elif worker_type == "operations":
            from tasks.run_worker import run_operations_worker
            asyncio.run(run_operations_worker())
        elif worker_type == "chat":
            from tasks.run_worker import run_chat_worker
            asyncio.run(run_chat_worker())
        else:
            raise click.ClickException(f"Unknown worker type: {worker_type}")
        return

    # No type: spawn subprocesses for each worker and monitor/restart
    import signal
    import time
    from tasks.run_worker import graceful_shutdown_timeout
    this = sys.argv[0]
    workers = []  # [{ 'type': str, 'cmd': List[str], 'proc': Popen|None, 'restart_at': float|None }]
    shutting_down = False

    # WHY THIS EXISTS: a container runtime signals PID 1 only. This process is
    # the supervisor, and every Temporal worker is a CHILD of it -- so without forwarding
    # here, no worker ever sees SIGTERM, none of them drains, and the graceful shutdown
    # period each one is configured with is unreachable. The setting looks right in
    # `tasks/run_worker.py` and does nothing.
    def request_shutdown(signum, _frame):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        log.warning("%s received. Draining %d worker processes.",
                    signal.Signals(signum).name, len(workers))
        for w in workers:
            p = w["proc"]
            if p is not None:
                try:
                    p.send_signal(signal.SIGTERM)
                except Exception:
                    pass

    signal.signal(signal.SIGTERM, request_shutdown)

    # Initial spawn set. "index-planner" MUST stay at exactly one process:
    # a second planner worker would corrupt the Manticore shard ledger. The common tier
    # is where the fan-out lands, so its process count follows the host rather than a
    # constant -- see tasks/run_worker.py:common_worker_processes.
    from tasks.run_worker import common_worker_processes
    common_count = common_worker_processes()
    log.info("Spawning %d common workers", common_count)
    # `chat` is one process and is listed first on purpose: it is the only queue with a
    # person waiting on the other end, so it must exist before anything competes for the
    # host's memory. It polls its own queue and never touches the ingestion one.
    for wt in ["chat", "tika", "ocr", "nlp", "embed", "indexing", "index-planner"] + ["common"] * common_count:
        cmd = [sys.executable, this, "worker", wt]
        log.info("Spawning worker: %s", " ".join(cmd))
        p = subprocess.Popen(cmd)
        workers.append({"type": wt, "cmd": cmd, "proc": p, "restart_at": None})

    try:
        # Monitor loop: restart crashed/ended processes after 10s
        while not shutting_down:
            now = time.time()
            for w in workers:
                p = w["proc"]
                # If process exists, check if it has ended
                if p is not None:
                    code = p.poll()
                    if code is not None:
                        # Ended or crashed
                        log.warning("Worker '%s' exited with code %s. Will restart in 10s.", w["type"], code)
                        w["proc"] = None
                        w["restart_at"] = now + 10
                # If process not running and we are not shutting down, maybe restart
                elif not shutting_down and w["restart_at"] is not None and now >= w["restart_at"]:
                    log.info("Restarting worker: %s", " ".join(w["cmd"]))
                    try:
                        p2 = subprocess.Popen(w["cmd"])
                        w["proc"] = p2
                        w["restart_at"] = None
                    except Exception as e:
                        # If spawn fails, try again in 10s
                        log.warning("Failed to restart worker '%s': %s. Retrying in 10s.", w["type"], e)
                        w["restart_at"] = now + 10

            time.sleep(1)
    except KeyboardInterrupt:
        # Immediate kill on Ctrl-C with warning
        shutting_down = True
        log.warning("Ctrl-C received. Killing all worker processes immediately.")
        for w in workers:
            p = w["proc"]
            if p is not None:
                try:
                    log.warning("Killing worker '%s' (pid=%s)", w["type"], getattr(p, "pid", "?"))
                    p.kill()
                except Exception:
                    pass
    finally:
        # Wait out the drain. A one-second wait was right when the only way out was
        # Ctrl-C and a kill, and it is wrong now: a worker told to stop is finishing
        # in-flight activities, and hurrying it here throws away exactly what the
        # graceful period was configured to buy. Ctrl-C still kills, so this only
        # lengthens the SIGTERM path.
        deadline = time.time() + graceful_shutdown_timeout().total_seconds()
        for w in workers:
            p = w["proc"]
            if p is not None:
                try:
                    p.wait(timeout=max(1.0, deadline - time.time()))
                except Exception:
                    log.warning("Worker '%s' did not exit before the drain deadline",
                                w["type"])


if __name__ == '__main__':
    cli()