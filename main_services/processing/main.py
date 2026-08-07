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
    ``server_settings``. Phase 4's index builder reads those — never the ini — because
    the ini is the request and this probe is the truth, and a Manticore ``_vectors``
    table's ``knn_dims`` cannot be altered after creation.
    """
    import os

    from tasks.llm_catalog import set_server_setting
    from tasks.remote import probe_embeddings

    base_url = (os.getenv("EMBEDDINGS_URL") or "").strip()
    if not base_url:
        print("EMBEDDINGS_URL is empty (embeddings_provider = none); nothing to probe")
        return
    model, dims = probe_embeddings(base_url)
    set_server_setting("embeddings_serving_model", model)
    set_server_setting("embeddings_serving_dim", str(dims))
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
@click.argument("worker_type", required=False, type=click.Choice(["common", "tika", "ocr", "nlp", "indexing", "index-planner"]))
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
    for wt in ["tika", "ocr", "nlp", "indexing", "index-planner"] + ["common"] * 2:
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