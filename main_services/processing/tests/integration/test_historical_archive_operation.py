"""Recover a populated release archive failure through the supported operation driver."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid
import zipfile

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from database import clickhouse, operations
from tasks.P_ops import workflows as operations_workflows, activities as operations_activities
from tasks.P_ops.params import OperationParams
from tasks.P_admin import rerun_selection
from tasks.P3_parse_files import parse_archives
from tasks.P3_parse_files.batch_runner import StageBatchParams, BatchFile
from tasks.task_timing import TaskTimingInterceptor
from tasks.temporal_readiness import TEMPORAL_ADDRESS
from .test_release_schema_upgrade import release_databases

pytestmark = pytest.mark.integration


@workflow.defn(name="ExecutePlans")
class ArchivePlanExecution:
    @workflow.run
    async def run(self, value: dict) -> dict:
        prepared = await workflow.execute_activity("prepare_fixture_archive", value,
            start_to_close_timeout=timedelta(seconds=30), result_type=StageBatchParams)
        result = await workflow.execute_activity(parse_archives.extract_archive_batch, prepared,
                                                  start_to_close_timeout=timedelta(seconds=30))
        if any(file.status not in ("ok", "skipped") for file in result.results):
            raise RuntimeError("The actual archive extraction failed")
        await workflow.execute_activity("finish_fixture_archive", {**value, "out_dirs": [
            file.value["out_dir"] for file in result.results if isinstance(file.value, dict) and file.value.get("out_dir")]},
            start_to_close_timeout=timedelta(seconds=30))
        return {"plans_run": 1, "invocations": 1, "failed_plans": 0}


def test_supported_explicit_retry_recovers_populated_release_archive_error(release_databases, tmp_path, monkeypatch):
    collection, upgrade = release_databases
    archive = tmp_path / "empty.7z"
    with zipfile.ZipFile(archive, "w"):
        pass
    with clickhouse.get_collection_client(collection) as client:
        client.insert("processing_errors", [["dataset", "archive", "archive_scan", "historical failure"]],
                      column_names=["collection_dataset", "hash", "task_name", "error_logs"])
        client.insert("processing_plan_hits", [["dataset", "archive", "legacy_plan"]],
                      column_names=["collection_dataset", "item_hash", "plan_hash"])
        client.insert("processing_plan_finished", [["dataset", "legacy_plan"]], column_names=["collection_dataset", "plan_hash"])
        client.insert("vfs_files", [["dataset", "", "/empty.7z", "archive"]],
                      column_names=["collection_dataset", "container_hash", "path", "hash"])
    upgrade()
    op = operations.create_operation("retry_failed_files", collection, "dataset", detail={"task_name": "archive_scan"})
    queue = "archive-explicit-"+uuid.uuid4().hex
    original_activity, original_child = workflow.execute_activity, workflow.execute_child_workflow
    async def execute(*args, **kwargs):
        kwargs["task_queue"] = queue
        return await original_activity(*args, **kwargs)
    async def child(*args, **kwargs):
        kwargs["task_queue"] = queue
        kwargs["search_attributes"] = {}
        return await original_child(*args, **kwargs)
    monkeypatch.setattr(workflow, "execute_activity", execute)
    monkeypatch.setattr(workflow, "execute_child_workflow", child)
    @activity.defn(name="prepare_fixture_archive")
    def prepare(value: dict) -> StageBatchParams:
        return StageBatchParams(collection, "dataset", "legacy_plan", [BatchFile(
            "archive", str(archive), archive.stat().st_size, mime_types=["application/zip"], file_names=["empty.7z"])], op_id=op["op_id"])
    @activity.defn(name="finish_fixture_archive")
    def finish(value: dict) -> None:
        with clickhouse.get_collection_client(collection) as client:
            client.insert("processing_plan_finished", [["dataset", "legacy_plan"]], column_names=["collection_dataset", "plan_hash"])
        import shutil
        for folder in value.get("out_dirs", []):
            if __import__("os").path.exists(folder):
                shutil.rmtree(folder)
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        with ThreadPoolExecutor(max_workers=4) as executor:
            async with Worker(client, task_queue=queue, workflows=[operations_workflows.Operation, ArchivePlanExecution],
                activities=[operations_activities.admit_operation, operations_activities.record_operation_state,
                    operations_activities.sample_dataset_progress, rerun_selection.select_historical_errors,
                    rerun_selection.reconcile_selected_errors, prepare, finish, parse_archives.extract_archive_batch],
                interceptors=[TaskTimingInterceptor()],
                workflow_runner=UnsandboxedWorkflowRunner(), activity_executor=executor):
                handle = await client.start_workflow(operations_workflows.Operation.run,
                    OperationParams(op["op_id"], "retry_failed_files", collection, "dataset", detail={"task_name": "archive_scan"}),
                    id=op["op_id"], task_queue=queue)
                try:
                    return await asyncio.wait_for(handle.result(), 60)
                except BaseException:
                    await handle.terminate("The isolated acceptance fixture stopped")
                    raise
    result = asyncio.run(run())
    assert operations.get_operation(op["op_id"])["state"] == "finished"
    with clickhouse.get_collection_client(collection) as client:
        assert client.query("SELECT count() FROM processing_errors FINAL WHERE task_name='archive_scan'").result_rows == [(0,)]
        assert client.query("SELECT count() FROM archives WHERE archive_hash='archive'").result_rows[0][0] > 0
        assert client.query("SELECT hash,task_name FROM operation_error_events FINAL WHERE op_id={op:String} "
                            "AND event='recovered'", parameters={"op": op["op_id"]}).result_rows == [("archive", "archive_scan")]
