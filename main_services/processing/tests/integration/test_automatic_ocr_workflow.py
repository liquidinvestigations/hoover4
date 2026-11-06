"""Verify the automatic workflow transport, strict payloads, restart, and replay."""

import asyncio
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker, Replayer

from tasks.P_admin.workflows import RerunOcr
from tasks.P_admin.ocr_rerun import RerunOcrParams
from tasks.P_admin.automatic_ocr import AutomaticOcrScope
from tasks.run_worker import sandboxed_runner
from tasks.temporal_readiness import TEMPORAL_ADDRESS

from .test_table_publication_receipts import collection

pytestmark = pytest.mark.integration


@workflow.defn(name="ExtractEntitiesForPlan")
class Entities:
    @workflow.run
    async def run(self, params: dict) -> str:
        if not params["fail_on_errors"]:
            raise RuntimeError("Automatic OCR requires strict dependent processing")
        return "complete"


@workflow.defn(name="ScanRegexEntitiesForPlan")
class Signals(Entities):
    @workflow.run
    async def run(self, params: dict) -> str:
        return await super().run(params)


@workflow.defn(name="ChunkEmbedForPlan")
class Embedding(Entities):
    @workflow.run
    async def run(self, params: dict) -> str:
        return await super().run(params)


@workflow.defn(name="IndexDatasetPlan")
class Indexing(Entities):
    @workflow.run
    async def run(self, params: dict) -> str:
        return await super().run(params)


def test_automatic_workflow_survives_restart_and_replays(monkeypatch):
    from tasks.P_admin import workflows
    monkeypatch.setattr(workflows, "dataset_search_attributes", lambda dataset: {})
    verified = []

    @activity.defn(name="list_automatic_ocr_files")
    async def listed(params: AutomaticOcrScope) -> list[dict]:
        return [] if params.after else [dict(item_hash="source")]

    @activity.defn(name="run_automatic_ocr_files")
    async def executed(params: AutomaticOcrScope) -> dict[str, str]:
        return {"source": "a" * 64}

    @activity.defn(name="verify_automatic_ocr_files")
    async def verify(params: AutomaticOcrScope) -> None:
        assert params.plans == {"source": "a" * 64}
        verified.append(params.plans)

    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        def common():
            return Worker(client, task_queue="processing-common-queue", workflows=[RerunOcr, Entities, Signals, Embedding, Indexing],
                          activities=[listed, verify], workflow_runner=sandboxed_runner())
        first = common()
        first_task = asyncio.create_task(first.run())
        handle = await client.start_workflow(RerunOcr.run, RerunOcrParams("collection", "dataset", "operation", listed=True),
            id="automatic-restart-" + uuid.uuid4().hex, task_queue="processing-common-queue", execution_timeout=timedelta(minutes=2))
        for _ in range(200):
            description = await handle.describe()
            if description.raw_description.pending_activities:
                names = [pending.activity_type.name for pending in description.raw_description.pending_activities]
                if "run_automatic_ocr_files" in names:
                    break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("Automatic execution was not durably scheduled")
        await first.shutdown()
        await first_task
        async with common(), Worker(client, task_queue="processing-ocr-queue", activities=[executed]):
            assert await handle.result() == {"plans": 0, "files": 1, "batches": 1,
                "execution_counts": {"plans_run": 0, "failed_plans": 0, "failed_dataset_steps": 0}}
        assert verified == [{"source": "a" * 64}]
        history = await handle.fetch_history()
        await Replayer(workflows=[RerunOcr], workflow_runner=sandboxed_runner()).replay_workflow(history)
        output = os.getenv("AUTOMATIC_OCR_HISTORY")
        if output:
            Path(output).write_text(json.dumps({"automatic-restart": dict(workflow_id=history.workflow_id,
                workflow_type="RerunOcr", history=json.loads(history.to_json()))}, indent=2))
    asyncio.run(run())


def test_unsupported_file_keeps_later_progress_and_final_operation_failure(monkeypatch,collection):
    from tasks.P_admin import workflows
    from tasks.P2_execute_plan.activities import record_processing_error_groups
    from concurrent.futures import ThreadPoolExecutor
    from temporalio.exceptions import ApplicationError
    from temporalio.client import WorkflowFailureError
    from database.clickhouse import get_collection_client
    monkeypatch.setattr(workflows,"dataset_search_attributes",lambda _dataset:{})
    verified=[]
    @activity.defn(name="list_automatic_ocr_files")
    async def listed(params:AutomaticOcrScope)->list[dict]:
        return [] if params.after else [{"item_hash":"bad"},{"item_hash":"good"}]
    @activity.defn(name="run_automatic_ocr_files")
    async def executed(params:AutomaticOcrScope)->dict[str,str]:
        if params.hashes==["bad"]:
            raise ApplicationError("Unsupported fixture script",type="OcrCoverageUnavailable",non_retryable=True)
        return {"good":"pinned-good-plan"}
    @activity.defn(name="verify_automatic_ocr_files")
    async def verify(params:AutomaticOcrScope)->None:
        assert params.hashes==["good"]
        assert params.plans=={"good":"pinned-good-plan"}
        verified.append("good")
    async def run():
        client=await Client.connect(TEMPORAL_ADDRESS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            async with Worker(client,task_queue="processing-common-queue",workflows=[RerunOcr,Entities,Signals,Embedding,Indexing],
                              activities=[listed,verify,record_processing_error_groups],activity_executor=pool,workflow_runner=sandboxed_runner()), Worker(client,task_queue="processing-ocr-queue",activities=[executed]):
                handle=await client.start_workflow(RerunOcr.run,RerunOcrParams(collection,"dataset","mixed-operation",listed=True),
                    id="automatic-mixed-"+uuid.uuid4().hex,task_queue="processing-common-queue",execution_timeout=timedelta(minutes=2))
                with pytest.raises(WorkflowFailureError,match="Workflow execution failed"):
                    await handle.result()
        assert verified==["good"]
        with get_collection_client(collection) as stored:
            assert stored.query("SELECT hash,task_name FROM processing_errors FINAL WHERE collection_dataset='dataset'").result_rows==[("bad","run_automatic_ocr_files")]
        history=await handle.fetch_history()
        await Replayer(workflows=[RerunOcr],workflow_runner=sandboxed_runner()).replay_workflow(history)
    asyncio.run(run())
