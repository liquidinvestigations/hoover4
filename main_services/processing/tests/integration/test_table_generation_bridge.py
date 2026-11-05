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
    name = "bridge_" + uuid.uuid4().hex[:12]
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
