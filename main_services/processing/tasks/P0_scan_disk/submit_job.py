"""CLI helper to register disk datasets and start ingestion workflows."""

import click
import asyncio
from datetime import datetime, timezone
import re
import pyarrow as pa
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def _slugify_dataset_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return slug or "dataset"


def compose_collection_dataset(collectionname: str, dataset_name: str) -> str:
    """Globally unique dataset id, composed as ``<collectionname>_<dataset_name>``.

    Not a parsing contract: never split this string to recover the collection
    (a dataset name may contain ``_``). Resolve via the ``dataset`` table instead.
    """
    return f"{collectionname}_{dataset_name}"


def _insert_dataset_row(client, collectionname, dataset_name, collection_dataset,
                        path, now):
    """Write the registry row for a dataset that does not have one yet."""
    table = pa.table({
        "collection_dataset": pa.array([collection_dataset], type=pa.string()),
        "collectionname": pa.array([collectionname], type=pa.string()),
        "dataset_name": pa.array([dataset_name], type=pa.string()),
        "dataset_display_name": pa.array([dataset_name], type=pa.string()),
        "dataset_type": pa.array(["disk"], type=pa.string()),
        "dataset_path": pa.array([path], type=pa.string()),
        "dataset_access_json": pa.array([None], type=pa.string()),
        "user_id": pa.array(["system"], type=pa.string()),
        "date_created": pa.array([now], type=pa.timestamp("s")),
        "date_modified": pa.array([now], type=pa.timestamp("s")),
        "is_deleted": pa.array([0], type=pa.uint8()),
    })
    client.insert_arrow("dataset", table)
    log.info("Dataset row created")


def prepare_disk_dataset(collectionname: str, dataset_name: str, path: str) -> str:
    """Validate the request and make sure the dataset can be scanned. Returns the path.

    Everything a dispatch needs to do BEFORE any workflow exists: check the names,
    check the collection, provision the collection's storage, and write the registry
    row if it is missing. Separate from starting the work because both entry points —
    the direct workflow start and the operation — need exactly this and nothing more,
    and because a caller must learn that a path does not exist from the command it
    typed rather than from a workflow that fails a minute later.
    """
    from database.clickhouse import (
        get_global_client,
        validate_collectionname,
    )
    from database.s3 import ensure_collection_storage
    import os

    try:
        validate_collectionname(collectionname)
    except ValueError as e:
        raise click.ClickException(str(e))

    collection_dataset = compose_collection_dataset(collectionname, dataset_name)
    if _slugify_dataset_name(dataset_name) != dataset_name:
        raise click.ClickException("Dataset name must contain only lowercase alphanumeric characters and underscores.\n         For example, use the name '{}' instead of '{}'".format(_slugify_dataset_name(dataset_name), dataset_name))
    path = os.path.abspath(path).replace("\\", "/")
    if not os.path.isdir(path):
        raise click.ClickException("Path does not exist or is not a directory: {}. Aborting.".format(path))
    log.info("Adding disk dataset: %s (collection %s)", collection_dataset, collectionname)
    log.info("Path: %s", path)

    # The collection row must exist already; a typo must not silently create a
    # stray collection and database.
    with get_global_client() as client:
        rows = client.query(
            "SELECT count() FROM collections FINAL "
            "WHERE collectionname = {name:String} AND is_deleted = 0",
            parameters={"name": collectionname},
        ).result_rows
    if not rows or not rows[0][0]:
        raise click.ClickException(
            f"Collection '{collectionname}' does not exist. Create it in the admin UI "
            "or with `main.py ensure-collection` first. Aborting."
        )

    # Idempotent, and the catch-up for a collection whose storage is incomplete: an
    # ingest must not be the thing that discovers a missing database or bucket.
    ensure_collection_storage(collectionname)

    # Duplicate check and dataset row insert go to the GLOBAL database.
    # ClickHouse DateTime columns are naive UTC; datetime.now(timezone.utc)
    # without the tzinfo drop would insert with an offset-naive mismatch.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_global_client() as client:
        existing = client.query(
            "SELECT count() FROM dataset FINAL "
            "WHERE collection_dataset = {cd:String} AND is_deleted = 0",
            parameters={"cd": collection_dataset},
        ).result_rows
        already_registered = bool(existing and existing[0][0])

        # An existing registry row is a RESCAN, not a collision. Refusing here was a dead
        # end: the row is written before the walk, so any interrupted ingest left a
        # dataset that could never be added again and could only be purged. The scan is
        # idempotent -- every path it finds is re-ingested or touched, and
        # `reconcile_deleted_files` tombstones what it no longer finds -- so running it
        # again over the same root is how an edited or deleted file is picked up.
        if already_registered:
            log.info("Dataset %s already exists; rescanning %s", collection_dataset, path)
        else:
            log.info("Creating dataset row")
            _insert_dataset_row(
                client, collectionname, dataset_name, collection_dataset, path, now
            )
    return path


def add_disk_dataset(collectionname: str, dataset_name: str, path: str, wait: bool = True):
    """Prepare a disk dataset and start `IngestDiskDataset` for it directly.

    The scan only. Plan computation and execution are separate workflows and must not
    start until the scan has finished, so a caller of this drives them itself.
    """
    from temporalio.client import Client as TemporalClient
    import temporalio.common
    from tasks.visibility import dataset_search_attributes

    collection_dataset = compose_collection_dataset(collectionname, dataset_name)
    path = prepare_disk_dataset(collectionname, dataset_name, path)

    async def _start_workflow():
        log.info("Starting temporal workflow...")
        client = await TemporalClient.connect("temporal:7233")
        # Do not assume the worker registered this first. On a fresh
        # --reset the CLI regularly wins that race, and an unregistered
        # search attribute makes the start below fail outright.
        from tasks.visibility import ensure_search_attributes_ready, start_with_attribute_retry
        await ensure_search_attributes_ready(client)
        from tasks.P0_scan_disk.workflows import IngestDiskDataset

        args = (
            IngestDiskDataset.run,
            {
                "collectionname": collectionname,
                "collection_dataset": collection_dataset,
                "dataset_path": path,
            },
        )
        # One id per RUN, not per dataset. A dataset is scanned again every time it is
        # rescanned, so an id derived from the dataset alone can be started exactly once
        # and every later rescan either collides or silently attaches to the finished
        # run. With a unique id the reuse policy stops mattering, and
        # `id_conflict_policy` still guards the one case that is a real conflict: two
        # dispatches inside the same second.
        run_id = int(datetime.now(timezone.utc).timestamp())
        kwargs = dict(
            id=f"ingest-disk-{collection_dataset}-{run_id}",
            task_queue="processing-common-queue",
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
            search_attributes=dataset_search_attributes(collection_dataset),
        )
        if wait:
            await start_with_attribute_retry(
                lambda: client.execute_workflow(*args, **kwargs)
            )
            log.info("Temporal workflow finished.")
        else:
            # start_workflow returns as soon as the server has the workflow
            # durably recorded. The caller is then free to die -- which is the
            # point: execute_workflow ties the ingest's fate to a CLI process
            # that a redeploy will SIGKILL.
            handle = await start_with_attribute_retry(
                lambda: client.start_workflow(*args, **kwargs)
            )
            log.info("Temporal workflow started: %s (not waiting)", handle.id)

    asyncio.run(_start_workflow())