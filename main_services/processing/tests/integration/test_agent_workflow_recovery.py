"""Verify workspace and board retry recovery through actual Temporal transport."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
import uuid

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from database import chat_workspace, clickhouse, boards
from tasks.P_workspace import workflows as writer
from tasks.P_workspace.mutations import Command
from tasks.P_board import activities as board, fold
from tasks.P_board import model as m
from tasks.temporal_readiness import TEMPORAL_ADDRESS
from .test_agent_recovery import global_store

pytestmark = pytest.mark.integration


async def until(check, seconds=30):
    for _ in range(seconds*20):
        if await asyncio.to_thread(check):
            return
        await asyncio.sleep(.05)
    raise AssertionError("The bounded recovery wait ended")


def test_workspace_receipt_exhaustion_head_advancement_and_replacement_worker(global_store, monkeypatch):
    original = chat_workspace.write_receipt
    failures = []
    allow = False
    def receipt(owner, session, value):
        if value.operation_id == "original" and not allow:
            failures.append(value.version)
            raise ApplicationError("Receipt storage unavailable", non_retryable=True)
        original(owner, session, value)
    monkeypatch.setattr(chat_workspace, "write_receipt", receipt)
    monkeypatch.setattr(writer, "COMMIT_PAUSE", timedelta(milliseconds=10))
    from tasks.P_agent import reports
    monkeypatch.setattr(reports, "session_citation_entries", lambda *args: [])
    session = uuid.uuid4().hex
    first = Command("owner", session, "original", "run", "write", "report.md", content="10.")
    later = Command("owner", session, "later", "run", "write", "report.md", content="10. Later.", expected_version=1)
    async def run():
        nonlocal allow
        client = await Client.connect(TEMPORAL_ADDRESS)
        queue = "workspace-recovery-"+uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=3) as executor:
            def worker():
                return Worker(client, task_queue=queue, workflows=[writer.WorkspaceWriter],
                              activities=[writer.prepare_workspace_mutation, writer.commit_workspace_mutation],
                              workflow_runner=UnsandboxedWorkflowRunner(), activity_executor=executor)
            first_worker = worker()
            async with first_worker:
                handle = await client.start_workflow(writer.WorkspaceWriter.run,
                    writer.WriterStart("owner", session, [first, later]), id="workspace-test-"+session, task_queue=queue)
                await until(lambda: chat_workspace.read_receipt("owner", session, "later") is not None)
            assert len(failures) == writer.COMMIT_ROUNDS
            allow = True
            async with worker():
                await handle.signal(writer.WorkspaceWriter.submit, first)
                await until(lambda: chat_workspace.read_receipt("owner", session, "original") is not None)
                assert chat_workspace.read_receipt("owner", session, "original").version == 1
                assert chat_workspace.read_version("owner", session, "report.md").version == 2
                await handle.signal(writer.WorkspaceWriter.submit, first)
                await asyncio.sleep(.2)
                assert chat_workspace.read_version("owner", session, "report.md").version == 2
                await handle.cancel()
                try:
                    await handle.result()
                except Exception:
                    pass
    asyncio.run(run())


@workflow.defn
class OpeningRetry:
    @workflow.run
    async def run(self, request: board.TurnRequest) -> board.OpenedTurn:
        return await workflow.execute_activity("open_retry_fixture", request,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=2), maximum_attempts=3),
            result_type=board.OpenedTurn)


def test_board_opening_retry_after_worker_replacement_keeps_stored_language(global_store, monkeypatch):
    board_row = boards.BoardRow("board", "owner", "Board", "Goal", collections=["enron"], internet_tools=0)
    intent = fold.Intent("intent", 1, [], "Find the date", "")
    folded = fold.Folded("board", intents={"intent": intent})
    monkeypatch.setattr(boards, "read_board", lambda *args: board_row)
    monkeypatch.setattr(boards, "read_citations", lambda *args: [])
    monkeypatch.setattr(boards, "read_labels", lambda *args: [])
    monkeypatch.setattr(board, "_read", lambda *args: ([], [], folded))
    monkeypatch.setattr(board, "_chat_closed", lambda: False)
    monkeypatch.setattr(clickhouse, "list_collections", lambda: ["enron"])
    chosen = ["de"]
    monkeypatch.setattr(board, "explore_language", lambda *args: chosen[0])
    persisted = []
    @activity.defn(name="open_retry_fixture")
    def opening(request: board.TurnRequest) -> board.OpenedTurn:
        result = board.open_explore_turn(request)
        persisted.append(result)
        if len(persisted) == 1:
            raise ApplicationError("The opening response was lost")
        return result
    async def run():
        client = await Client.connect(TEMPORAL_ADDRESS)
        queue = "opening-recovery-"+uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as executor:
            def worker():
                return Worker(client, task_queue=queue, workflows=[OpeningRetry], activities=[opening],
                              workflow_runner=UnsandboxedWorkflowRunner(), activity_executor=executor)
            async with worker():
                handle = await client.start_workflow(OpeningRetry.run, board.TurnRequest("board", "intent", 1),
                                                     id=queue, task_queue=queue)
                await until(lambda: bool(persisted))
            chosen[0] = "fr"
            async with worker():
                result = await asyncio.wait_for(handle.result(), 30)
            assert result.run_input.language == persisted[0].run_input.language == "de"
            assert result.run_input.turn_uuid == persisted[0].run_input.turn_uuid
            later = await asyncio.to_thread(board.open_explore_turn, board.TurnRequest("board", "intent", 2))
            assert later.run_input.language == "fr"
            assert later.run_input.turn_uuid != result.run_input.turn_uuid
    asyncio.run(run())
