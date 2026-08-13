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
    from database.minio import BUCKET_NAME
    clickhouse_migrate()
    from database.minio import ensure_bucket
    ensure_bucket(BUCKET_NAME)
    from database.manticore import manticore_migrate
    manticore_migrate()


@cli.command()
@click.argument("collectionname", type=str)
def ensure_collection(collectionname: str):
    """Create a collection's ClickHouse database if missing and migrate it.

    Idempotent. Note this does NOT create the `collections` row - collections are
    created in the admin UI; this only provisions the database for one that exists.
    """
    from database.clickhouse import collection_db_name, migrate_collection

    try:
        db_name = collection_db_name(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))
    migrate_collection(collectionname)
    log.info("Collection database ready: %s", db_name)
    print(db_name)


@cli.command(name="create-collection")
@click.argument("collectionname", type=str)
@click.option("--fullname", type=str, default="", help="Human-readable display name.")
@click.option("--public/--no-public", "is_public", default=False,
              help="Readable by every user (and by guests), rather than by group grant only.")
def create_collection(collectionname: str, fullname: str, is_public: bool):
    """Register a collection and provision its ClickHouse database.

    The scripted equivalent of creating a collection in the admin UI: it writes the
    `collections` row the UI writes and then does what `ensure-collection` does, so one
    command leaves a collection that can be ingested into. Idempotent, so an ingest
    script that re-runs is safe.

    `--public` is worth stating explicitly. A collection is restricted by default and is
    then visible only through a group grant; a demo that shows its collections anyway is
    relying on `demo_mode` and the `guest_permissions_mode` setting both being open,
    which is two independent defaults holding rather than one intent recorded.
    """
    from database.clickhouse import (
        collection_db_name, get_global_client, migrate_collection, validate_collectionname,
    )

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

    migrate_collection(collectionname)
    log.info("Collection database ready: %s", collection_db_name(collectionname))
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
    ``server_settings``. The index builder reads those — never the ini — because
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

    By default this BLOCKS through all three stages in order -- scan, compute
    plans, execute plans -- because each one needs the previous to have
    finished. Killing the CLI (a redeploy, a lost ssh session) does not stop
    the workflows: they keep running server-side while the caller sees only a
    dead command.

    --no-wait submits ONLY the disk scan and returns. It deliberately does not
    submit the plan stages: computing plans over a half-scanned dataset would
    silently plan a subset of the files. Use it when something else drives the
    later stages, and poll processing_plan_finished to know when it is done.
    """
    from tasks.P0_scan_disk.submit_job import add_disk_dataset, compose_collection_dataset
    add_disk_dataset(collectionname, dataset_name, path, wait=wait)
    if not wait:
        click.echo(
            "Submitted the disk scan only. Plan computation and execution were "
            "NOT started: they must not run until the scan has finished. Run "
            "`main.py compute-plans` / `execute-plans` once the scan completes."
        )
        return
    collection_dataset = compose_collection_dataset(collectionname, dataset_name)

    from tasks.P1_compute_plans.submit_job import submit_compute_plans
    asyncio.run(submit_compute_plans(collectionname, collection_dataset))

    from tasks.P2_execute_plan.submit_job import submit_execute_plans
    asyncio.run(submit_execute_plans(collectionname, collection_dataset))


@cli.command(name="reindex-collection")
@click.argument("collectionname", type=str)
def reindex_collection(collectionname: str):
    """Drop a collection's Manticore tables + shard ledger and re-index every finished plan.

    Recovery path for a lost Manticore volume, for a change to
    MAX_SHARD_TEXT_BYTES, and for shard fragmentation. This is the substitute
    for a compaction feature: shards are never compacted or renumbered in
    place, they are rebuilt from scratch here.

    WARNING: this truncates the shard ledger, the assignments and index_state
    with no guard against in-flight indexing. Stop the indexing workers first,
    or ensure no IndexDatasetPlan workflow is running for this collection —
    otherwise an in-flight writer can record index_state rows into shards the
    reindex is about to drop.
    """
    from database.clickhouse import get_collection_client, validate_collectionname
    from database.manticore import drop_collection_tables

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    dropped = drop_collection_tables(collectionname)
    log.info("Dropped %d Manticore shard tables of %s", len(dropped), collectionname)

    with get_collection_client(collectionname) as client:
        client.command("TRUNCATE TABLE manticore_shards")
        client.command("TRUNCATE TABLE manticore_shard_assignments")
        client.command("TRUNCATE TABLE index_state")
        plans = client.query(
            "SELECT collection_dataset, plan_hash FROM processing_plan_finished FINAL "
            "ORDER BY collection_dataset, plan_hash"
        ).result_rows

    if not plans:
        log.warning("No finished plans found for %s - nothing to re-index", collectionname)
        return

    async def _start_workflows():
        from temporalio.client import Client as TemporalClient
        import temporalio.common
        from tasks.P6_index_data.workflows import IndexDatasetPlan
        from tasks.P6_index_data.params import IndexDatasetPlanParams
        from tasks.visibility import dataset_search_attributes

        client = await TemporalClient.connect("temporal:7233")
        for collection_dataset, plan_hash in plans:
            await client.start_workflow(
                IndexDatasetPlan.run,
                IndexDatasetPlanParams(collectionname=collectionname, collection_dataset=collection_dataset, plan_hash=plan_hash),
                id=f"reindex-{collection_dataset}-{plan_hash}",
                task_queue="processing-common-queue",
                # Every CLI invocation must actually re-index: allow reusing the id of
                # a previous (completed) run, and dedupe only concurrent invocations
                # while one is still running.
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )
            log.info("Re-index queued: %s plan %s", collection_dataset, plan_hash[:8])

    asyncio.run(_start_workflows())
    print(f"reindex of {collectionname}: {len(plans)} plan(s) queued")


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

    The recovery path for a dataset that was abandoned rather than deleted — a failed
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
    """
    from database.clickhouse import get_global_client, validate_collectionname
    from tasks.P_admin.activities import (
        CollectionDatabaseParams,
        PurgeDatasetParams,
        count_dataset_rows,
        purge_dataset_from_clickhouse,
        purge_dataset_from_manticore,
        recompute_shard_ledger_activity,
    )

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

    purge_dataset_from_manticore(PurgeDatasetParams(
        collectionname=collectionname, collection_dataset=collection_dataset))
    purge_dataset_from_clickhouse(PurgeDatasetParams(
        collectionname=collectionname, collection_dataset=collection_dataset))
    recompute_shard_ledger_activity(CollectionDatabaseParams(collectionname=collectionname))

    # ClickHouse lightweight deletes are asynchronous, so the after-count is polled
    # rather than read once. Manticore deletes are synchronous and must be zero on the
    # first look; a non-zero count there is a failure, not a race.
    import time
    deadline = time.monotonic() + 120
    while True:
        after = count_dataset_rows(collectionname, collection_dataset)
        left = sum(after["manticore"].values()) + sum(after["clickhouse"].values())
        if not left or time.monotonic() > deadline:
            break
        time.sleep(2)
    if left:
        for store in ("manticore", "clickhouse"):
            for table, count in sorted(after[store].items()):
                if count:
                    print(f"  LEFT {store:10s} {table:32s} {count}")
        raise click.ClickException(
            f"purge of {collection_dataset} left {left} row(s) behind after 120s"
        )
    print(f"purge-dataset {collection_dataset}: {total} row(s) deleted, 0 left")


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
    succeeded — a stage that records per-document errors without failing the plan (P4
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
    documents have a watermark again, so a retry that fails a second time leaves the
    record it started from.
    """
    from database.clickhouse import get_collection_client, validate_collectionname
    from tasks.P_admin.failed_file_retry import (
        RETRY_EMBED, RETRY_INDEX, RETRY_NLP, RETRY_PLAN,
        clear_error_rows, clear_nlp_state, failed_hashes, hashes_without_entities,
        list_failures, plans_for_hashes, reopen_plans, retry_kind_for_task,
    )

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
    kind = retry_kind_for_task(task_name)

    hashes = failed_hashes(collectionname, collection_dataset, task_name)
    if not hashes:
        raise click.ClickException(
            f"{task_name} has only dataset-level error rows (no file hash) in "
            f"{collection_dataset}; there is nothing per-file to retry"
        )
    plans = plans_for_hashes(collectionname, collection_dataset, hashes)
    if not plans:
        raise click.ClickException(
            f"none of the {len(hashes)} failed hashes are in a plan of {collection_dataset}"
        )
    print(f"retrying {task_name} ({kind}) for {len(hashes)} document(s) in {len(plans)} plan(s)")

    # The server's clock, not this process's: the "did it fail again" check below compares
    # against `processing_errors.timestamp`, which is written by ClickHouse's neighbours
    # on another host.
    with get_collection_client(collectionname) as client:
        started_at = client.query("SELECT now()").result_rows[0][0]

    if kind == RETRY_NLP:
        watermarks, hits = clear_nlp_state(collectionname, collection_dataset, hashes)
        print(f"cleared {watermarks} watermark(s) and {hits} entity row(s)")
    elif kind == RETRY_PLAN:
        reopen_plans(collectionname, collection_dataset, plans)
        print(f"reopened {len(plans)} plan(s) — their other documents will be reprocessed too")

    async def _run():
        from temporalio.client import Client as TemporalClient
        import temporalio.common
        from tasks.P2_execute_plan.workflows import ExecutePlans, ExecutePlansParams
        from tasks.P4_extract_entities.workflows import ExtractEntitiesForPlan
        from tasks.P4_extract_entities.params import ExtractEntitiesForPlanParams
        from tasks.P5_chunk_embed.workflows import ChunkEmbedForPlan
        from tasks.P5_chunk_embed.params import ChunkEmbedForPlanParams
        from tasks.P6_index_data.workflows import IndexDatasetPlan
        from tasks.P6_index_data.params import IndexDatasetPlanParams
        from tasks.visibility import dataset_search_attributes

        client = await TemporalClient.connect("temporal:7233")

        async def _await_workflow(workflow, params, wf_id):
            handle = await client.start_workflow(
                workflow, params,
                id=wf_id,
                task_queue="processing-common-queue",
                # Every invocation must actually re-run: reuse the id of a completed
                # run, and dedupe only against one that is still going.
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                search_attributes=dataset_search_attributes(collection_dataset),
            )
            await handle.result()

        if kind == RETRY_PLAN:
            # One ExecutePlans run picks up every reopened plan of the dataset.
            await _await_workflow(
                ExecutePlans.run,
                ExecutePlansParams(collectionname=collectionname,
                                   collection_dataset=collection_dataset,
                                   base_temp_dir="/tmp/hoover4"),
                f"retry-execute-plans-{collection_dataset}",
            )
            return

        for i, plan_hash in enumerate(plans, 1):
            if kind == RETRY_NLP:
                # P4 then P6, in that order: the Manticore `ner` attributes and term
                # dictionary are built from the entity rows P4 writes.
                await _await_workflow(
                    ExtractEntitiesForPlan.run,
                    ExtractEntitiesForPlanParams(collectionname=collectionname,
                                                 collection_dataset=collection_dataset,
                                                 plan_hash=plan_hash),
                    f"retry-ner-{collection_dataset}-{plan_hash}",
                )
            elif kind == RETRY_EMBED:
                await _await_workflow(
                    ChunkEmbedForPlan.run,
                    ChunkEmbedForPlanParams(collectionname=collectionname,
                                            collection_dataset=collection_dataset,
                                            plan_hash=plan_hash),
                    f"retry-embed-{collection_dataset}-{plan_hash}",
                )
            await _await_workflow(
                IndexDatasetPlan.run,
                IndexDatasetPlanParams(collectionname=collectionname,
                                       collection_dataset=collection_dataset,
                                       plan_hash=plan_hash),
                f"retry-index-{collection_dataset}-{plan_hash}",
            )
            log.info("retry %d/%d done: plan %s", i, len(plans), plan_hash[:8])

    asyncio.run(_run())

    # Clear only what is demonstrably fixed. For an NER retry that is "the document has
    # a watermark for its text again"; for the other kinds the workflow completing IS
    # the result, since they record their own errors on failure.
    if kind == RETRY_NLP:
        still_missing = set(hashes_without_entities(collectionname, collection_dataset, hashes))
        fixed = [h for h in hashes if h not in still_missing]
    else:
        with get_collection_client(collectionname) as client:
            rows = client.query(
                "SELECT DISTINCT hash FROM processing_errors "
                "WHERE collection_dataset = {ds:String} AND task_name = {task:String} "
                "AND hash != '' AND timestamp >= {since:DateTime}",
                parameters={"ds": collection_dataset, "task": task_name, "since": started_at},
            ).result_rows
        failed_again = {row[0] for row in rows}
        fixed = [h for h in hashes if h not in failed_again]
        still_missing = set(hashes) - set(fixed)

    if fixed:
        clear_error_rows(collectionname, collection_dataset, task_name, fixed)
    print(f"retry-failed-files {collection_dataset} {task_name}: "
          f"{len(fixed)} document(s) recovered, {len(still_missing)} still failing")
    if still_missing:
        raise click.ClickException(
            f"{len(still_missing)} document(s) still failing; their processing_errors "
            f"rows were kept. First few: {sorted(still_missing)[:5]}"
        )


@cli.command(name="purge-unattributed-entities")
@click.argument("collectionname", type=str)
@click.option("--apply/--dry-run", default=False, show_default=True,
              help="--dry-run (the default) only reports what would change.")
def purge_unattributed_entities(collectionname: str, apply: bool):
    """Clear `entity_hit` rows with an empty `nlp_model`, re-running NER for their pages.

    These are rows written before `nlp_model` existed. `nlp_model` is part of the table's
    ORDER BY — deliberately, so two NER providers can coexist — which means a later run
    under a real provider name **adds** rows rather than replacing them: the unattributed
    set is immortal, and the admin UI renders it as a phantom third provider whose entities
    nothing can be filtered by.

    Deleting them alone is not safe in general, and the live stack proved it: one
    collection's entire entity set was unattributed, so a bare DELETE would have removed
    every entity it had. So this also clears the `nlp_processed` watermark for the affected
    pages, which is what makes P4 extract them again — the watermark is the only reason it
    would skip a page it has already seen.

    Order matters: watermarks first, then the rows, then the re-run. A crash between the
    two deletes leaves pages that will simply be re-extracted, which is the harmless
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
@click.argument("worker_type", required=False, type=click.Choice(["common", "tika", "ocr", "nlp", "embed", "indexing", "index-planner"]))
def worker(worker_type: str | None = None):
    """Run worker(s). If worker_type provided, runs that worker; else spawns all."""
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
        else:
            raise click.ClickException(f"Unknown worker type: {worker_type}")
        return

    # No type: spawn subprocesses for each worker and monitor/restart
    import time
    this = sys.argv[0]
    workers = []  # [{ 'type': str, 'cmd': List[str], 'proc': Popen|None, 'restart_at': float|None }]
    shutting_down = False

    # Initial spawn set. "index-planner" MUST stay at exactly one process:
    # a second planner worker would corrupt the Manticore shard ledger.
    for wt in ["tika", "ocr", "nlp", "embed", "indexing", "index-planner"] + ["common"] * 2:
        cmd = [sys.executable, this, "worker", wt]
        log.info("Spawning worker: %s", " ".join(cmd))
        p = subprocess.Popen(cmd)
        workers.append({"type": wt, "cmd": cmd, "proc": p, "restart_at": None})

    try:
        # Monitor loop: restart crashed/ended processes after 10s
        while True:
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
        # Best-effort short wait for processes to exit
        for w in workers:
            p = w["proc"]
            if p is not None:
                try:
                    p.wait(timeout=1)
                except Exception:
                    pass


if __name__ == '__main__':
    cli()