"""Verify durable recursive archive cleanup after a common worker replacement."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from database import clickhouse, manticore
from tasks.P3_parse_files import parse_archives
from tasks.P3_parse_files.archive_reconciliation import reconcile_archive_descendants
from tasks.P6_index_data.params import BuildVfsNodesParams
from tasks.temporal_readiness import TEMPORAL_ADDRESS
from .test_archive_and_index_publication import search_collection, page
from .test_table_publication_receipts import collection
from .test_agent_workflow_recovery import until

pytestmark = pytest.mark.integration


@workflow.defn
class RecursiveArchiveRecovery:
    @workflow.run
    async def run(self, value: dict) -> None:
        await workflow.execute_activity("archive_mark_removed", value, start_to_close_timeout=timedelta(seconds=30))
        await workflow.execute_activity("archive_finish_removed", value, task_queue=value["finish_queue"],
                                        start_to_close_timeout=timedelta(seconds=30))


def test_recursive_cleanup_keeps_shared_descendants_after_worker_replacement(search_collection, tmp_path):
    name = search_collection
    with clickhouse.get_collection_client(name) as client:
        client.insert("vfs_files", [["dataset", "", "/archive", "entry"], ["dataset", "", "/shared", "shared"],
            ["dataset", "entry", "/nested", "nested"], ["dataset", "nested", "/dead", "dead"],
            ["dataset", "nested", "/shared", "shared"], ["dataset", "shared", "/child", "shared_child"]],
            column_names=["collection_dataset", "container_hash", "path", "hash"])
        for table in ("index_state", "manticore_shard_assignments"):
            client.insert(table, [["dataset", h, name+"_1"] for h in ("nested", "dead", "shared")],
                          column_names=["collection_dataset", "file_hash", "shard_name"])
        client.insert("text_content", [["dataset", h, "raw_text", 1, "stored output", 13, 1]
                                      for h in ("nested", "dead", "shared", "shared_child")],
                      column_names=["collection_dataset", "file_hash", "extracted_by", "page_id", "text", "text_bytes", "version"])
    for identity, h in enumerate(("nested", "dead", "shared"), 1):
        page(name, identity, h, "raw_text", 4)
    marked = []
    @activity.defn(name="archive_mark_removed")
    def mark(value: dict) -> int:
        count = parse_archives._tombstone_absent_members(name, "dataset", "entry", str(tmp_path))
        marked.append(count)
        return count
    @activity.defn(name="archive_finish_removed")
    def finish(value: dict) -> None:
        reconcile_archive_descendants(BuildVfsNodesParams(name, "dataset"))
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        queue = "archive-recovery-"+uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as executor:
            def common():
                return Worker(client, task_queue=queue, workflows=[RecursiveArchiveRecovery], activities=[mark],
                              activity_executor=executor, workflow_runner=UnsandboxedWorkflowRunner())
            async with common():
                handle = await client.start_workflow(RecursiveArchiveRecovery.run,
                    {"finish_queue": queue+"-finish"}, id=queue, task_queue=queue)
                await until(lambda: bool(marked))
            async with common(), Worker(client, task_queue=queue+"-finish", activities=[finish], activity_executor=executor):
                await asyncio.wait_for(handle.result(), 30)
    asyncio.run(run())
    with clickhouse.get_collection_client(name) as client:
        assert {r[0] for r in client.query("SELECT DISTINCT file_hash FROM text_content").result_rows} == {"shared", "shared_child"}
        assert ("shared", "shared_child") in client.query("SELECT container_hash,hash FROM vfs_files FINAL").result_rows
    with manticore.get_manticore_client() as connection:
        cursor = connection.cursor()
        cursor.execute(f"SELECT file_hash FROM {manticore.shard_table_name(name, 1)} LIMIT 100")
        assert list(cursor.fetchall()) == [("shared",)]
