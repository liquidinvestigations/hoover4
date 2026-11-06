"""Verify table generation commands through the Temporal transport and worker restart."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import uuid

import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from database import clickhouse
from tasks.P3_parse_files.table_generations import (
    GenerationCommand, TableGenerationCommand, apply_table_generation_command, send_command,
)
from tasks.temporal_readiness import TEMPORAL_ADDRESS

pytestmark = pytest.mark.integration


@pytest.fixture
def collection():
    name = "bridge_" + uuid.uuid4().hex[:12] + "a"
    clickhouse.migrate_collection(name)
    try:
        yield name
    finally:
        client = clickhouse._client("default")
        client.command(f"DROP DATABASE {clickhouse.collection_db_name(name)}")
        client.close()


def common(client):
    return Worker(client, task_queue="processing-common-queue", workflows=[TableGenerationCommand])


def planner(client, executor):
    return Worker(client, task_queue="processing-index-planner-queue",
                  activities=[apply_table_generation_command], activity_executor=executor,
                  max_concurrent_activities=1)


def test_competing_commands_allocate_distinct_generations(collection):
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        with ThreadPoolExecutor(max_workers=1) as executor:
            async with common(client), planner(client, executor):
                values = await asyncio.gather(*[
                    asyncio.to_thread(send_command, GenerationCommand(collection, "source", "allocate", token))
                    for token in ("attempt_a", "attempt_b")])
                assert sorted(values) == [1, 2]
                value = await asyncio.to_thread(send_command, GenerationCommand(
                    collection, "source", "allocate", "attempt_a"))
                assert value == values[0]
    asyncio.run(run())


def test_waiting_command_survives_common_worker_restart(collection):
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        first = common(client)
        task = asyncio.create_task(first.run())
        pending = asyncio.create_task(asyncio.to_thread(send_command, GenerationCommand(
            collection, "restart_source", "allocate", "attempt")))
        handle = client.get_workflow_handle(f"table-generation-{collection}-restart_source")
        for _ in range(100):
            try:
                description = await handle.describe()
                if description.raw_description.pending_activities:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.05)
        else:
            pytest.fail("The generation activity was not scheduled")
        await first.shutdown()
        await task
        with ThreadPoolExecutor(max_workers=1) as executor:
            async with common(client), planner(client, executor):
                assert await asyncio.wait_for(pending, 30) == 1
    asyncio.run(run())


def test_bridge_deadline_cancels_its_waiting_command(collection):
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        async with common(client):
            with pytest.raises(TimeoutError, match="deadline"):
                await asyncio.to_thread(send_command, GenerationCommand(
                    collection, "deadline_source", "allocate", "attempt"), deadline_seconds=0.2)
            handle = client.get_workflow_handle(f"table-generation-{collection}-deadline_source")
            for _ in range(100):
                description = await handle.describe()
                if description.status.name == "CANCELED":
                    break
                await asyncio.sleep(0.05)
            assert description.status.name == "CANCELED"
    asyncio.run(run())


def test_parent_cancellation_stops_the_bridge_and_its_waiting_command(collection, monkeypatch):
    import threading
    from temporalio.exceptions import CancelledError
    from tasks import heartbeat
    cancelled = threading.Event()

    def stop(*_args):
        if cancelled.is_set():
            raise CancelledError("parent cancelled")

    monkeypatch.setattr(heartbeat, "stop_if_worker_is_stopping", stop)

    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        async with common(client):
            pending = asyncio.create_task(asyncio.to_thread(send_command, GenerationCommand(
                collection, "cancelled_source", "allocate", "attempt")))
            handle = client.get_workflow_handle(f"table-generation-{collection}-cancelled_source")
            for _ in range(100):
                try:
                    if (await handle.describe()).raw_description.pending_activities:
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.05)
            else:
                pytest.fail("The generation command did not start")
            cancelled.set()
            with pytest.raises(CancelledError, match="parent cancelled"):
                await pending
            for _ in range(100):
                description = await handle.describe()
                if description.status.name == "CANCELED":
                    break
                await asyncio.sleep(0.05)
            assert description.status.name == "CANCELED"
    asyncio.run(run())


def test_concurrent_automatic_plan_claims_pin_one_executable_candidate(collection):
    import json
    from tasks.automatic_ocr import make_plan
    from tasks.P3_parse_files.automatic_ocr import write_plan, pinned_plan
    plans = [make_plan("dataset", "ocr-source", "source", "image",
                       [dict(page_id=1, has_text=True, script="Latin", language="und")],
                       dict(tesseract=[model], easyocr=[]), 1) for model in ("Latin", "eng")]
    # Both first claims use executable script coverage with different capability identities.
    plans[1] = make_plan("dataset", "ocr-source", "source", "image",
                        [dict(page_id=1, has_text=True, script="Latin", language="en")],
                        dict(tesseract=["eng"], easyocr=[]), 1)
    for plan in plans:
        plan["source_parts"] = []
        with clickhouse.get_collection_client(collection) as db:
            write_plan(db, plan, "candidate")
    def command(plan, op="ocr-operation"):
        return GenerationCommand(collection, "ocr-source", "claim_ocr_plan", owner_op=op,
            manifest=json.dumps(dict(dataset="dataset", plan_digest=plan["plan_digest"])).encode())
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        with ThreadPoolExecutor(max_workers=1) as executor:
            async with common(client), planner(client, executor):
                assert await asyncio.gather(*[asyncio.to_thread(send_command, command(plan)) for plan in plans]) == [1, 1]
                with clickhouse.get_collection_client(collection) as db:
                    chosen = pinned_plan(db, "dataset", "ocr-source", "ocr-operation")
                    assert chosen["plan_digest"] in {plan["plan_digest"] for plan in plans}
                    assert db.query("SELECT count() FROM processing_output_receipts FINAL WHERE stage = 'planned'").result_rows == [(1,)]
                    assert chosen["claim_version"] == 1
                await asyncio.to_thread(send_command, command(plans[1], "next-operation"))
                with clickhouse.get_collection_client(collection) as db:
                    assert pinned_plan(db, "dataset", "ocr-source", "next-operation")["claim_version"] == 2
                from temporalio.worker import Replayer
                from tasks.run_worker import sandboxed_runner
                history = await client.get_workflow_handle(f"table-generation-{collection}-ocr-source").fetch_history()
                await Replayer(workflows=[TableGenerationCommand], workflow_runner=sandboxed_runner()).replay_workflow(history)
                import os
                from pathlib import Path
                if os.getenv("AUTOMATIC_CLAIM_HISTORY"):
                    Path(os.environ["AUTOMATIC_CLAIM_HISTORY"]).write_text(json.dumps({"automatic-plan-claim": dict(
                        workflow_id=history.workflow_id, workflow_type="TableGenerationCommand", history=json.loads(history.to_json()))}, indent=2))

    asyncio.run(run())


def test_non_executable_automatic_candidate_cannot_claim(collection):
    import json
    from tasks.automatic_ocr import make_plan
    from tasks.P3_parse_files.automatic_ocr import write_plan
    from temporalio.exceptions import ApplicationError
    plan = make_plan("dataset", "blocked", "source", "image", [dict(page_id=1, has_text=True, script="", language="und")], {}, 1)
    with clickhouse.get_collection_client(collection) as db:
        write_plan(db, plan, "incomplete")
    with pytest.raises(ApplicationError, match="not executable"):
        apply_table_generation_command(GenerationCommand(collection, "blocked", "claim_ocr_plan", owner_op="operation",
            manifest=json.dumps(dict(dataset="dataset", plan_digest=plan["plan_digest"])).encode()))
    with clickhouse.get_collection_client(collection) as db:
        assert db.query("SELECT count() FROM processing_output_receipts FINAL").result_rows == [(0,)]
