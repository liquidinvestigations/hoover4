import click
import asyncio
from datetime import datetime
import re
import pyarrow as pa
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def _slugify_dataset_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return slug or "dataset"


def add_disk_dataset(dataset_name: str, path: str):
    from database.clickhouse import get_clickhouse_client
    from temporalio.client import Client as TemporalClient
    import temporalio.common
    import os

    collection_dataset = _slugify_dataset_name(dataset_name)
    if collection_dataset != dataset_name:
        raise click.ClickException("Dataset name must contain only lowercase alphanumeric characters and underscores.\n         For example, use the name '{}' instead of '{}'".format(collection_dataset, dataset_name))
    path = os.path.abspath(path).replace("\\", "/")
    if not os.path.isdir(path):
        raise click.ClickException("Path does not exist or is not a directory: {}. Aborting.".format(path))
    log.info("Adding disk dataset: %s", collection_dataset)
    log.info("Path: %s", path)

    # Check duplicates and insert dataset row using Arrow
    now = datetime.utcnow()
    with get_clickhouse_client() as client:
        # Duplicate check
        existing = client.query_arrow(
            f"""
            SELECT collection_dataset, dataset_name, dataset_path
            FROM dataset
            WHERE dataset_name = '{dataset_name.replace("'", "''")}'
               OR dataset_path = '{path.replace("'", "''")}'
            LIMIT 1
            """
        )
        if existing and existing.num_rows > 0:
            # raise click.ClickException("Dataset with same name or path already exists. Aborting.")
            log.warning("Dataset with same path already exists. Re-running once more!")
        log.info("Creating dataset row")

        table = pa.table({
            "collection_dataset": pa.array([collection_dataset], type=pa.string()),
            "dataset_name": pa.array([dataset_name], type=pa.string()),
            "dataset_type": pa.array(["disk"], type=pa.string()),
            "dataset_path": pa.array([path], type=pa.string()),
            "dataset_access_json": pa.array([None], type=pa.string()),
            "user_id": pa.array(["system"], type=pa.string()),
            "date_created": pa.array([now], type=pa.timestamp("s")),
            "date_modified": pa.array([now], type=pa.timestamp("s")),
        })
        client.insert_arrow("dataset", table)
        log.info("Dataset row created")

    async def _start_workflow():
        log.info("Starting temporal workflow...")
        client = await TemporalClient.connect("temporal:7233")
        from tasks.P0_scan_disk.workflows import IngestDiskDataset

        await client.execute_workflow(
            IngestDiskDataset.run,
            {
                "collection_dataset": collection_dataset,
                "dataset_path": path,
            },
            id=f"ingest-disk-{collection_dataset}",
            task_queue="processing-common-queue",
            id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
        )
        log.info("Temporal workflow finished.")

    asyncio.run(_start_workflow())