"""The `AgentRun` workflow against the stack's Temporal and ClickHouse, with a stub agent.

Each test runs one `Worker` on task queues of its own, with the real workflow and the real
activities. The agent service and the browser server are replaced by one local HTTP stub,
so the stream frames are fixed and the rows each case writes are known. Every case uses a
username of its own and deletes its rows at the end.

The worker runs the workflow unsandboxed, so the test can point the module's queue names at
its own queues. The production worker keeps the sandbox.
"""

import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio import workflow
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from database import agent_runs, chat_todos
from database.clickhouse import get_global_client
from tasks.P_agent import activities, stream_writer, workflows
from tasks.run_worker import WORKFLOW_FAILURE_EXCEPTION_TYPES

pytestmark = [pytest.mark.integration, pytest.mark.timeout(240)]

LONG_ID_A = "chatcmpl-tool-a5ca7d0e11f2" * 9
LONG_ID_B = "chatcmpl-tool-b71c3e9d04aa" * 9


def _frame(kind, content, **extra):
    return "data: " + json.dumps({"type": kind, "content": content, **extra}) + "\n\n"


def _answer_frames(base: int, text: str) -> list[str]:
    return [
        _frame("response", text),
        _frame("model_turn", {"index": base, "text": text, "reasoning": "",
                              "tool_calls": [], "usage": {"input_tokens": 5}}),
        _frame("end", text, model="stub-model",
               usage={"prompt_tokens": 11, "completion_tokens": 3,
                      "context_tokens": 11, "peak_context_tokens": 14}),
    ]


def _two_call_frames(base: int) -> list[str]:
    calls = [{"id": LONG_ID_A, "name": "search_collections", "args": {"query": "alpha"}},
             {"id": LONG_ID_B, "name": "search_collections", "args": {"query": "beta"}}]
    frames = [_frame("model_turn", {"index": base, "text": "", "reasoning": "",
                                    "tool_calls": calls, "usage": {}})]
    for i, call in enumerate(calls):
        frames.append(_frame("tool_start", {"index": base + 1 + i, "tool_call_id": call["id"],
                                            "name": call["name"], "args": call["args"]}))
    # The second call ends first.
    for i, call in reversed(list(enumerate(calls))):
        frames.append(_frame("tool_result", {
            "index": base + 1 + i, "tool_call_id": call["id"], "name": call["name"],
            "content": json.dumps({"query": call["args"]["query"], "hits": []}),
            "measure": {"sha256": f"digest-{i}"}, "status": "ok"}))
    return frames + _answer_frames(base + 3, "The answer.")


class _Stub:
    """The agent service and the browser server, as one scripted HTTP server."""

    def __init__(self, script):
        self.script = script
        self.requests: list[dict] = []
        self.released: list[str] = []
        #: Each frame written, with the time it was written.
        self.sent: list[tuple[float, str]] = []
        #: The request numbers whose stream the client closed before the last frame.
        self.closed_early: list[int] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path.startswith("/runs/"):
                    stub.released.append(self.path.split("/")[2])
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                request = json.loads(body)
                stub.requests.append(request)
                frames = stub.script(request, len(stub.requests))
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                try:
                    for frame in frames:
                        self.wfile.write(frame.encode())
                        stub.sent.append((time.monotonic(), frame))
                except OSError:
                    # The attempt closed the stream, for example after a stop.
                    stub.closed_early.append(len(stub.requests))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


class _Case:
    def __init__(self):
        self.username = f"w6-agent-run-{uuid.uuid4().hex[:10]}"
        self.session_id = str(uuid.uuid4())
        self.run_id = str(uuid.uuid4())
        self.turn_uuid = str(uuid.uuid4())
        self.turn_seq = 1
        self.start_seq = 2
        activities._insert_chat_row(self.username, self.session_id, self.turn_seq, "user",
                                    content="What is in the reports?")

    def input(self):
        return activities.AgentRunInput(
            run_id=self.run_id, username=self.username, session_id=self.session_id,
            kind="chat", turn_seq=self.turn_seq, start_seq=self.start_seq,
            turn_uuid=self.turn_uuid, allowed_collections=["testdata"],
        )

    def chat_rows(self):
        with get_global_client() as client:
            return client.query(
                "SELECT seq, role, content, tool_name, tool_input, tool_output "
                "FROM chat_messages FINAL WHERE username = {u:String} "
                "AND session_id = {s:String} ORDER BY seq",
                parameters={"u": self.username, "s": self.session_id},
            ).result_rows

    def run_row(self):
        return agent_runs.read_run(self.username, self.session_id, self.run_id)

    def messages(self):
        return agent_runs.read_messages(self.username, self.session_id, self.run_id)

    def delete(self):
        with get_global_client() as client:
            for table in ("agent_runs", "agent_run_messages", "agent_turn_stops",
                          "chat_messages", "chat_message_stream", "chat_todos"):
                client.command(f"DELETE FROM {table} WHERE username = {{u:String}}",
                               parameters={"u": self.username})


async def _run_case(monkeypatch, script, body, extra_workflows=()):
    """Run `body(client, case, stub, queue)` with a worker for AgentRun on its own queues."""
    stub = _Stub(script)
    case = _Case()
    suffix = uuid.uuid4().hex[:8]
    chat_queue, model_queue = f"w6-chat-{suffix}", f"w6-model-{suffix}"
    monkeypatch.setattr(workflows, "CHAT_TASK_QUEUE", chat_queue)
    monkeypatch.setitem(agent_runs.LEAD_QUEUES, "chat", model_queue)
    monkeypatch.setattr(activities, "INTERNAL_AGENT_URL", stub.url)
    monkeypatch.setattr(stream_writer, "BROWSER_SERVER_URL", stub.url)
    titled = []
    monkeypatch.setattr(activities, "summarize_session", lambda p: titled.append(p) or "")
    client = None
    acts = [activities.open_run, activities.run_agent, activities.append_nag,
            activities.write_ending, activities.summarize_if_first_turn,
            activities.read_chat_todo, activities.fan_in, activities.continue_run]
    try:
        client = await Client.connect("temporal:7233")
        with ThreadPoolExecutor(max_workers=8) as executor:
            async with Worker(
                client, task_queue=chat_queue,
                workflows=[workflows.AgentRun, *extra_workflows],
                activities=acts, activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
                workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES,
            ), Worker(
                client, task_queue=model_queue, activities=[activities.run_agent],
                activity_executor=executor,
            ):
                await body(client, case, stub, chat_queue, titled)
    finally:
        try:
            if client is not None:
                await _end_workflows(client, case)
        finally:
            stub.close()
            case.delete()


async def _end_workflows(client, case):
    """Terminate every workflow of the case that still runs, before its rows go.

    The ids are the top workflow ids a case starts and the `workflow_id` of each of the
    case's run rows, children and continuations included. A child is abandoned by its
    parent, so it keeps running on the case's queue after the test worker stops.
    """
    ids = {f"w6-test-{case.run_id}", f"run-{case.run_id}", f"w7-twice-{case.run_id}"}
    with get_global_client() as ch:
        ids.update(r[0] for r in ch.query(
            "SELECT DISTINCT workflow_id FROM agent_runs FINAL WHERE username = {u:String}",
            parameters={"u": case.username}).result_rows if r[0])
    for workflow_id in sorted(ids):
        handle = client.get_workflow_handle(workflow_id)
        try:
            if (await handle.describe()).status != WorkflowExecutionStatus.RUNNING:
                continue
            await handle.terminate(reason="the test case ended")
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


def _start(client, case, queue, **kwargs):
    return client.start_workflow(
        workflows.AgentRun.run, case.input(), id=f"w6-test-{case.run_id}", task_queue=queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, **kwargs)


def test_a_turn_with_two_parallel_calls_writes_todays_rows(monkeypatch):
    def script(request, n):
        return _two_call_frames(len(request["messages"]))

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        rows = case.chat_rows()
        assert [(r[0], r[1]) for r in rows] == [
            (1, "user"), (2, "tool"), (3, "tool"), (4, "assistant")]
        assert json.loads(rows[1][4]) == {"query": "alpha"}
        assert json.loads(rows[1][5])["query"] == "alpha"
        assert json.loads(rows[2][4]) == {"query": "beta"}
        assert json.loads(rows[2][5])["query"] == "beta"
        assert rows[3][2] == "The answer."
        row = case.run_row()
        assert (row.state, row.result, row.next_seq, row.tool_turns_used) == (
            "completed", "The answer.", 5, 1)
        messages = case.messages()
        assert [(m.idx, m.role) for m in messages] == [
            (0, "human"), (1, "ai"), (2, "tool"), (3, "tool"), (4, "ai")]
        assert messages[2].tool_call_id == LONG_ID_A
        assert json.loads(messages[2].usage_json)["measure"] == {"sha256": "digest-0"}
        assert stub.requests[0]["messages"][0]["content"] == "What is in the reports?"
        assert case.run_id in stub.released
        assert [t.session_id for t in titled] == [case.session_id]

        # A second start with the same id is refused, and the run it names exists.
        with pytest.raises(WorkflowAlreadyStartedError):
            await _start(client, case, queue)

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_stopped_turn_closes_in_open_run(monkeypatch):
    async def body(client, case, stub, queue, titled):
        agent_runs.write_turn_stop(case.username, case.session_id, case.turn_seq)
        handle = await _start(client, case, queue)
        assert await handle.result() == "closed"
        assert stub.requests == []
        assert [(r[0], r[1], r[2]) for r in case.chat_rows()][1:] == [
            (2, "error", "This turn was stopped.")]
        assert case.run_row().state == "cancelled"

    asyncio.run(_run_case(monkeypatch, lambda r, n: [], body))


def test_an_agent_error_ends_the_run_as_failed(monkeypatch):
    def script(request, n):
        return [_frame("error", "Error during streaming: model unavailable")]

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert len(stub.requests) == 2
        row = case.run_row()
        assert row.state == "failed" and "model unavailable" in row.error
        ending = case.chat_rows()[-1]
        assert ending[0] == 2 and ending[1] == "error"
        assert ending[2].startswith("The assistant could not answer: ")

    asyncio.run(_run_case(monkeypatch, script, body))


def test_an_open_todo_nags_twice_then_stops(monkeypatch):
    def script(request, n):
        return _answer_frames(len(request["messages"]), f"Answer {n}.")

    async def body(client, case, stub, queue, titled):
        chat_todos.write_todo(case.username, case.session_id, "read the reports",
                              [{"id": "1", "text": "read report one", "status": "pending"}])
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        roles = [(r[0], r[1]) for r in case.chat_rows()]
        assert roles == [(1, "user"), (2, "assistant"), (3, "nag"), (4, "assistant"),
                         (5, "nag"), (6, "assistant"), (7, "nag")]
        assert len(stub.requests) == 3
        second = stub.requests[1]
        assert (second["tool_turns_used"], second["extra_tool_turns"]) == (0, 6)
        assert [m["role"] for m in second["messages"]] == ["human", "ai", "human"]
        row = case.run_row()
        assert (row.nags_this_turn, row.state, row.next_seq) == (2, "completed", 8)

    asyncio.run(_run_case(monkeypatch, script, body))


# ---------------------------------------------------------------------------- delegation


def _briefing(objective):
    return {"objective": objective, "known": "", "bring_back": "the facts"}


def _delegate_frames(base, calls):
    """One model turn with `run_subagent` calls, and the stop: `tool_start` and `delegate` for
    each call, then `end`. `calls` holds `(call_id, briefings)`."""
    tool_calls = [{"id": c, "name": "run_subagent", "args": {"tasks": b}} for c, b in calls]
    frames = [_frame("model_turn", {"index": base, "text": "", "reasoning": "",
                                    "tool_calls": tool_calls, "usage": {"input_tokens": 7}})]
    for i, (call_id, briefings) in enumerate(calls):
        frames.append(_frame("tool_start", {"index": base + 1 + i, "tool_call_id": call_id,
                                            "name": "run_subagent",
                                            "args": {"tasks": briefings}}))
    for i, (call_id, briefings) in enumerate(calls):
        frames.append(_frame("delegate", {"index": base + 1 + i, "tool_call_id": call_id,
                                          "briefings": briefings}))
    frames.append(_frame("end", "", model="stub-model",
                         usage={"prompt_tokens": 7, "completion_tokens": 2}))
    return frames


def _is_continuation(request):
    last = request["messages"][-1]
    return last["role"] == "tool" and last.get("name") == "run_subagent"


def _objective(request):
    return request["messages"][0]["content"].splitlines()[0].removeprefix("Objective: ")


async def _wait_terminal(case, run_id=None, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = agent_runs.read_run(case.username, case.session_id, run_id or case.run_id)
        if row is not None and agent_runs.is_terminal(row):
            return row
        await asyncio.sleep(0.5)
    raise AssertionError(f"run {run_id or case.run_id} did not end")


def _turn_rows(case):
    return agent_runs.read_turn_runs(case.username, case.session_id, case.turn_seq)


def test_fan_in_once_continues_the_lead_with_every_report(monkeypatch):
    """`fan-in-once`: two children end, and the lead is continued once with both reports."""

    def script(request, n):
        base = len(request["messages"])
        if request["kind"] == "subagent":
            return _answer_frames(base, f"Report on {_objective(request)}.")
        if _is_continuation(request):
            return _answer_frames(base, "The final answer.")
        return _delegate_frames(base, [("d1", [_briefing("alpha"), _briefing("beta")])])

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "delegated"
        lead = await _wait_terminal(case)
        rows = _turn_rows(case)
        continuation = next(r for r in rows if r.continues_run_id == case.run_id)
        await _wait_terminal(case, continuation.run_id)
        lead = case.run_row()
        assert (lead.state, lead.result, lead.delegate_seq) == ("completed", "The final answer.", 2)
        children = [r for r in rows if r.depth == 1]
        assert len(children) == 2 and {r.state for r in _turn_rows(case) if r.depth == 1} == {
            "completed"}
        assert [r.subagent_share for r in children] == [2, 2]

        kinds = [(r["kind"], r["depth"], _is_continuation(r)) for r in stub.requests]
        assert kinds.count(("chat", 0, True)) == 1
        assert kinds.count(("subagent", 1, False)) == 2
        for request in stub.requests:
            assert request["allowed_collections"] == ["testdata"]
            if request["kind"] == "subagent":
                assert request["history"] == [] and request["can_delegate"] is True
        last = next(r for r in stub.requests if _is_continuation(r))["messages"][-1]
        result = json.loads(last["content"])
        assert last["tool_call_id"] == "d1" and result["refused"] == []
        assert sorted(r["report"] for r in result["reports"]) == [
            "Report on alpha.", "Report on beta."]
        chat = [(r[0], r[1], r[2], r[3]) for r in case.chat_rows()]
        assert chat == [(1, "user", "What is in the reports?", ""),
                        (2, "tool", '{"state":"reported"}', "run_subagent"),
                        (3, "assistant", "The final answer.", "")]
        tool_input = json.loads(case.chat_rows()[1][4])
        assert tool_input["tool_call_id"] == "d1"
        assert tool_input["batch_id"] == agent_runs.batch_id_for(case.run_id)
        assert json.loads(case.chat_rows()[1][5])["reports"]

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_depth_1_delegation_continues_through_its_own_continuation(monkeypatch):
    """`depth-limit`: the depth 2 run gets `can_delegate` false and no row goes deeper. The
    depth 1 run reports to the lead through its continuation, and the chain ends both."""

    def script(request, n):
        base = len(request["messages"])
        if request["depth"] == 2:
            return _answer_frames(base, "Deep report.")
        if request["depth"] == 1 and not _is_continuation(request):
            return _delegate_frames(base, [("d2", [_briefing("deeper")])])
        if request["depth"] == 1:
            return _answer_frames(base, "Middle report.")
        if _is_continuation(request):
            return _answer_frames(base, "Lead answer.")
        return _delegate_frames(base, [("d1", [_briefing("middle")])])

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "delegated"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            rows = _turn_rows(case)
            if rows and all(agent_runs.is_terminal(r) for r in rows) and len(rows) >= 5:
                break
            await asyncio.sleep(0.5)
        rows = _turn_rows(case)
        assert max(r.depth for r in rows) == 2
        assert {r.state for r in rows} == {"completed"}
        deep = next(r for r in stub.requests if r["depth"] == 2)
        assert deep["can_delegate"] is False
        middle = next(r for r in rows if r.depth == 1 and not r.continues_run_id)
        assert middle.subagent_share == 4 and middle.result == "Middle report."
        lead_report = json.loads(
            next(r for r in stub.requests if r["depth"] == 0 and _is_continuation(r))
            ["messages"][-1]["content"])
        assert [r["report"] for r in lead_report["reports"]] == ["Middle report."]
        assert case.run_row().result == "Lead answer."

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_run_budget_refuses_the_surplus_by_name(monkeypatch):
    """`run-budget`: seven briefings in one call run five children, and the continuation reads
    the two refusals."""

    def script(request, n):
        base = len(request["messages"])
        if request["kind"] == "subagent":
            return _answer_frames(base, "ok")
        if _is_continuation(request):
            return _answer_frames(base, "Done.")
        return _delegate_frames(base, [("d1", [_briefing(f"b{i}") for i in range(7)])])

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "delegated"
        await _wait_terminal(case)
        rows = _turn_rows(case)
        children = [r for r in rows if r.depth == 1 and not r.continues_run_id]
        by_id = {agent_runs.child_run_id(agent_runs.batch_id_for(case.run_id), i): i
                 for i in range(5)}
        assert sorted(by_id[r.run_id] for r in children) == [0, 1, 2, 3, 4]
        assert [r.subagent_share for r in sorted(children, key=lambda r: by_id[r.run_id])] == [
            1, 0, 0, 0, 0]
        last = next(r for r in stub.requests if _is_continuation(r))["messages"][-1]
        refused = json.loads(last["content"])["refused"]
        assert [(r["objective"], r["reason"]) for r in refused] == [
            ("b5", "too_many_briefings"), ("b6", "too_many_briefings")]
        assert case.run_row().state == "completed"

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_retry_of_the_delegation_writes_the_same_children_and_shares():
    """The budget counts exclude the caller's own batch, so a retry after the child rows
    were written, and before the waiting state, writes the same children and shares."""
    case = _Case()
    try:
        agent_runs.create_run(agent_runs.RunRow(
            run_id=case.run_id, username=case.username, session_id=case.session_id,
            turn_seq=case.turn_seq, thread_id=case.run_id, queue="q", workflow_id="w"))
        # One sub-agent of an earlier batch of the same turn counts against the budget.
        agent_runs.create_run(agent_runs.RunRow(
            run_id=str(uuid.uuid4()), username=case.username, session_id=case.session_id,
            turn_seq=case.turn_seq, thread_id=str(uuid.uuid4()), depth=1, kind="subagent",
            parent_run_id=str(uuid.uuid4()), batch_id=str(uuid.uuid4()), queue="q"))
        row = case.run_row()

        def attempt(writer):
            client = SimpleNamespace(
                delegates=[{"tool_call_id": "d1",
                            "briefings": [_briefing("x"), _briefing("y"), _briefing("z")]}],
                transcript=False, next_seq=0, next_idx=2, tool_turns_used=1, calls={})
            return activities._delegate(row, client, writer, None, 0, 0)

        class Crash(agent_runs.RunRowWriter):
            def write(self, **changes):
                raise RuntimeError("the attempt ends before the waiting state")

        with pytest.raises(RuntimeError):
            attempt(Crash(row))
        first = sorted((r.run_id, r.subagent_share) for r in _turn_rows(case) if r.parent_run_id == case.run_id)
        summary = attempt(agent_runs.RunRowWriter(row))
        second = sorted((r.run_id, r.subagent_share) for r in _turn_rows(case) if r.parent_run_id == case.run_id)
        assert first == second and len(first) == 3
        # Six less the earlier sub-agent leaves five: three children and two to share.
        assert sorted(share for _, share in second) == [0, 1, 1]
        assert summary.children == [agent_runs.child_run_id(summary.batch_id, i) for i in range(3)]
        assert case.run_row().state == "waiting_for_children"
    finally:
        case.delete()


@workflow.defn(sandboxed=False)
class _StartTwice:
    @workflow.run
    async def run(self, child: activities.AgentRunInput) -> list:
        workflow_id = f"run-{child.run_id}"
        return [await workflows.start_run(child, workflow_id),
                await workflows.start_run(child, workflow_id)]


def test_a_duplicate_child_start_is_refused_and_counts_as_started(monkeypatch):
    """`temporalio` 1.16 raises `WorkflowAlreadyStartedError` for a duplicate child id, and
    `start_run` treats it as a start."""

    async def body(client, case, stub, queue, titled):
        agent_runs.create_run(agent_runs.RunRow(
            run_id=case.run_id, username=case.username, session_id=case.session_id,
            turn_seq=case.turn_seq, thread_id=case.run_id, queue="q", workflow_id="w"))
        agent_runs.write_run_terminal(case.run_row(), "completed")
        result = await client.execute_workflow(
            _StartTwice.run, case.input(), id=f"w7-twice-{case.run_id}", task_queue=queue)
        assert result == [True, False]

    asyncio.run(_run_case(monkeypatch, lambda r, n: [], body, extra_workflows=[_StartTwice]))


def test_a_child_that_starts_after_a_stop_continues_its_parent_as_cancelled(monkeypatch):
    """`open_run` of a stopped child writes `cancelled` and runs `fan_in`, so the waiting
    lead ends as `cancelled` too."""

    def script(request, n):
        agent_runs.write_turn_stop(request["username"], request["session_id"], 1)
        return _delegate_frames(len(request["messages"]), [("d1", [_briefing("alpha")])])

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "delegated"
        lead = await _wait_terminal(case)
        assert lead.state == "cancelled"
        rows = _turn_rows(case)
        assert [r.state for r in rows if r.depth == 1] == ["cancelled"]
        assert not [r for r in rows if r.continues_run_id]
        assert len(stub.requests) == 1
        assert case.chat_rows()[-1][1:3] == ("error", "This turn was stopped.")

    asyncio.run(_run_case(monkeypatch, script, body))


def test_the_sweep_fails_a_run_with_no_workflow_and_continues_its_parent(monkeypatch):
    """`collector-sweep`, with rows whose workflows do not exist: the sweep writes `failed`
    for the child, and `fan_in` continues the waiting lead, which then completes."""
    from datetime import timedelta

    from tasks.P_agent import supervise

    def script(request, n):
        return _answer_frames(len(request["messages"]), "Answer after the sweep.")

    async def body(client, case, stub, queue, titled):
        batch = agent_runs.batch_id_for(case.run_id)
        child = agent_runs.child_run_id(batch, 0)
        for idx, role, calls in ((0, "human", "[]"), (1, "ai", json.dumps(
                [{"id": "d1", "name": "run_subagent", "args": {"tasks": [_briefing("x")]}}]))):
            agent_runs.write_message(case.username, case.session_id, case.run_id, case.run_id,
                                     agent_runs.RunMessageRow(idx=idx, role=role, content="q",
                                                              tool_calls_json=calls,
                                                              run_id=case.run_id))
        agent_runs.create_run(agent_runs.RunRow(
            run_id=case.run_id, username=case.username, session_id=case.session_id,
            turn_seq=case.turn_seq, thread_id=case.run_id, queue=agent_runs.LEAD_QUEUES["chat"],
            workflow_id=f"w7-absent-{case.run_id}", state="waiting_for_children",
            delegated_batch_id=batch, delegate_seq=2, start_seq=2, next_seq=3))
        agent_runs.create_run(agent_runs.RunRow(
            run_id=child, username=case.username, session_id=case.session_id,
            turn_seq=case.turn_seq, thread_id=child, parent_run_id=case.run_id, batch_id=batch,
            depth=1, kind="subagent", queue=agent_runs.LEAD_QUEUES["chat"],
            workflow_id=f"run-{child}", tool_call_id="d1",
            briefing=json.dumps(_briefing("x"))))
        later = supervise._now() + timedelta(seconds=300)
        counts = await supervise.sweep(client, later, username=case.username)
        assert counts == {"ended": 1, "continued": 1}
        failed = agent_runs.read_run(case.username, case.session_id, child)
        assert failed.state == "failed" and failed.error == supervise.WORKFLOW_ABSENT
        lead = await _wait_terminal(case)
        assert (lead.state, lead.result) == ("completed", "Answer after the sweep.")
        report = json.loads(stub.requests[0]["messages"][-1]["content"])
        assert [r["state"] for r in report["reports"]] == ["failed"]
        # A second pass finds nothing to do.
        assert await supervise.sweep(client, later, username=case.username) == {
            "ended": 0, "continued": 0}

    asyncio.run(_run_case(monkeypatch, script, body))


# ------------------------------------------------------------------------- stop and orphans

#: A filler frame longer than the 512 bytes that `iter_lines` reads at a time, so each one
#: reaches the attempt as it is written.
_FILLER = "." * 600


def test_a_stop_during_the_stream_writes_nothing_after_the_ending(monkeypatch):
    """A stop cancels `run_agent` and the workflow waits for the attempt to end. The stub
    keeps sending events after the stop and then sends `delegate`. The attempt stops at the
    first event after the cancellation, so no child row exists and the ending row is last.
    """

    def script(request, n):
        def frames():
            yield _frame("response", "Working")
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                time.sleep(0.5)
                yield _frame("response", _FILLER)
            yield from _delegate_frames(len(request["messages"]),
                                        [("d1", [_briefing("alpha")])])
        return frames()

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        deadline = time.monotonic() + 30
        while len(stub.sent) < 4 and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        assert len(stub.sent) >= 4, "the stream did not start"
        agent_runs.write_turn_stop(case.username, case.session_id, case.turn_seq)
        stopped_at = time.monotonic()
        await handle.cancel()
        lead = await _wait_terminal(case, seconds=150)
        latency = time.monotonic() - stopped_at
        print(f"stop latency: {latency:.1f} s from the cancel call to the ending row")
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert lead.state == "cancelled"
        assert [r for r in _turn_rows(case) if r.parent_run_id] == []
        rows = case.chat_rows()
        ending = max(rows, key=lambda r: r[0])
        assert (ending[1], ending[2]) == ("error", "This turn was stopped.")
        assert [r for r in rows if r[1] == "error"] == [ending]
        assert len(stub.requests) == 1

    asyncio.run(_run_case(monkeypatch, script, body))


def test_the_sweep_ends_the_children_of_a_failed_parent(monkeypatch):
    """The first attempt writes the child rows and fails before the waiting state. The
    second attempt gets an agent error, and the lead ends `failed` with its children
    `running`. The sweep ends every child, and the turn holds no open run."""
    from tasks.P_agent import supervise

    def script(request, n):
        if n == 1:
            return _delegate_frames(len(request["messages"]),
                                    [("d1", [_briefing("alpha"), _briefing("beta")])])
        return [_frame("error", "Error during streaming: model unavailable")]

    real_write = agent_runs.RunRowWriter.write

    def write(self, **changes):
        if changes.get("state") == agent_runs.WAITING_FOR_CHILDREN:
            raise RuntimeError("the attempt ends before the waiting state")
        return real_write(self, **changes)

    monkeypatch.setattr(agent_runs.RunRowWriter, "write", write)

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert len(stub.requests) == 2
        lead = case.run_row()
        assert lead.state == "failed" and "model unavailable" in lead.error
        children = [r for r in _turn_rows(case) if r.parent_run_id == case.run_id]
        assert len(children) == 2 and {r.state for r in children} == {"running"}

        counts = await supervise.sweep(client, username=case.username, grace_seconds=0)
        assert counts == {"ended": 2, "continued": 0}
        rows = _turn_rows(case)
        assert {r.state for r in rows if r.parent_run_id} == {"failed"}
        assert [r for r in rows if not agent_runs.is_terminal(r)] == []

    asyncio.run(_run_case(monkeypatch, script, body))
