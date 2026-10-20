"""A stop from the website stop button after one written file, for the browser check.

The test runs only when `HOOVER4_BROWSER_STOP_USER` names the account that the browser
signs in as. It reuses the stub agent, the test barrier and the workspace write of
`test_agent_run_workflow`. One `AgentRun` writes `a.md` through the real workspace
activities. The write of `b.md` then waits at the test barrier. The test prints
`BARRIER REACHED` and waits for the stop row. The browser case
`ai-chat-stop-after-written-file` opens the conversation and presses the stop button. The
website writes the stop row and cancels the workflow through its normal stop endpoint.
The test then cancels the barrier and verifies the versions and the ending row.

The conversation has a fixed id for the account. A run first removes the rows and the
workflows of that conversation only, and keeps the rows of the run for the browser.
"""

import asyncio
import os
import time
import uuid
from datetime import datetime

import pytest
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode

from database import agent_runs
from database.clickhouse import get_global_client, insert_durable
from tasks.P_agent import activities

from . import test_agent_run_workflow as flow

pytestmark = [pytest.mark.integration, pytest.mark.timeout(1200)]

USER = os.environ.get("HOOVER4_BROWSER_STOP_USER", "")
TITLE = "Browser check: stop after one written file"
SESSION_NAMESPACE = uuid.UUID("5b0e9f61-8d0c-4f7e-9b2a-1c3d4e5f6a7b")
#: The time that the browser has to press the stop button.
STOP_WAIT_SECONDS = 900
SESSION_TABLES = ("agent_runs", "agent_run_messages", "agent_turn_stops", "chat_messages",
                  "chat_message_stream", "chat_todos", "chat_workspace_files",
                  "chat_workspace_receipts")


def session_of(username: str) -> str:
    return str(uuid.uuid5(SESSION_NAMESPACE, f"browser-stop/{username}"))


def _workflow_ids(username: str, session_id: str) -> set[str]:
    with get_global_client() as client:
        return {r[0] for r in client.query(
            "SELECT DISTINCT workflow_id FROM agent_runs FINAL WHERE username = {u:String} "
            "AND session_id = {s:String}", parameters={"u": username, "s": session_id}).result_rows
            if r[0]}


async def _remove_workflows(client, workflow_ids):
    """Terminate and delete each named workflow. A missing workflow is already gone."""
    for workflow_id in sorted(workflow_ids):
        handle = client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
            if description.status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="the browser stop check ended")
            await client.workflow_service.delete_workflow_execution(DeleteWorkflowExecutionRequest(
                namespace=client.namespace,
                workflow_execution=WorkflowExecution(workflow_id=workflow_id,
                                                     run_id=description.run_id)))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


class _BrowserCase(flow._Case):
    """A case in the conversation of the browser account, the newest in its list."""

    def __init__(self):
        self.username = USER
        self.session_id = session_of(USER)
        self.run_id = str(uuid.uuid4())
        self.turn_uuid = str(uuid.uuid4())
        self.turn_seq = 1
        self.start_seq = 2
        stamp = datetime.now()
        with get_global_client() as client:
            insert_durable(client, "chat_sessions", [[
                self.session_id, self.username, TITLE, ["testdata"], "", 0, 1, stamp, stamp, 0,
            ]], column_names=["session_id", "username", "title", "collections", "summary",
                              "use_internet_tools", "options_locked", "created_at",
                              "updated_at", "is_deleted"])
        activities._insert_chat_row(self.username, self.session_id, self.turn_seq, "user",
                                    content="Write a.md and b.md.")

    def delete(self):
        """Keep the rows of the run, so the browser can read the stopped turn."""


def _clear_session(username: str, session_id: str) -> None:
    with get_global_client() as client:
        for table in SESSION_TABLES:
            client.command(f"DELETE FROM {table} WHERE username = {{u:String}} "
                           "AND session_id = {s:String}",
                           parameters={"u": username, "s": session_id})


@pytest.mark.skipif(not USER, reason="HOOVER4_BROWSER_STOP_USER names no browser account")
def test_the_stop_button_after_one_written_file_keeps_it_while_the_next_file_is_pending(monkeypatch):
    barrier = flow._Barrier()
    session_id = session_of(USER)
    held = set()

    def tool(request, n):
        if request["call"]["args"]["name"] == "b.md" and not barrier.wait(STOP_WAIT_SECONDS + 60):
            return 503, {"detail": "the test barrier cancelled this call before its write"}
        return flow._write_tool(request, flow._workspace_write(request))

    async def end_workflows(client, case):
        await _remove_workflows(client, held | _workflow_ids(case.username, case.session_id))

    async def body(client, case, stub, queue, titled):
        held.add(f"w6-test-{case.run_id}")
        handle = await flow._start(client, case, queue)
        assert await asyncio.to_thread(barrier.reached.wait, 60), "the second write did not start"
        assert [r[:2] for r in flow._versions(case)] == [("a.md", 1)]
        print(f"BARRIER REACHED session={case.session_id}", flush=True)
        deadline = time.monotonic() + STOP_WAIT_SECONDS
        while not agent_runs.turn_is_stopped(case.username, case.session_id, case.turn_seq):
            assert time.monotonic() < deadline, "nobody pressed the stop button"
            await asyncio.sleep(0.5)
        print("STOP ROW WRITTEN", flush=True)
        barrier.cancel()
        lead = await flow._wait_terminal(case, seconds=120)
        assert lead.state == "cancelled"
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert [r[:2] for r in flow._versions(case)] == [("a.md", 1)]
        [files] = flow._ending_files(case)
        assert files["report"] == {"name": "a.md", "version": 1}
        assert [(r["name"], r["version"]) for r in files["reports"]] == [("a.md", 1)]
        assert len(stub.requests) == 2
        print("RUN ENDED cancelled", flush=True)

    async def prepare():
        from temporalio.client import Client
        client = await Client.connect("temporal:7233")
        await _remove_workflows(client, _workflow_ids(USER, session_id))

    asyncio.run(prepare())
    _clear_session(USER, session_id)
    monkeypatch.setattr(flow, "_Case", _BrowserCase)
    monkeypatch.setattr(flow, "_end_workflows", end_workflows)
    asyncio.run(flow._run_case(monkeypatch, flow._write_script("a.md", "b.md"), body, tool=tool))
