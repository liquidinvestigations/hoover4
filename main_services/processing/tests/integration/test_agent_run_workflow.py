"""The `AgentRun` workflow against the stack's Temporal and ClickHouse, with a stub agent.

Each test runs one `Worker` for each queue of the loop, on task queues of its own, with the
real workflow and the real activities. The agent service and the browser server are
replaced by one local HTTP stub. It answers `/model_step` from a script of replies and
`/tool_call` from a script of tool results, so the rows each case writes are known. Every
case uses a username of its own and deletes its rows at the end.

The worker runs the workflow unsandboxed, so the test can point the module's queue names
and limits at its own values. The production worker keeps the sandbox.
"""

import asyncio
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.workflowservice.v1 import DeleteWorkflowExecutionRequest
from temporalio.service import RPCError, RPCStatusCode
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio import workflow
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from database import agent_runs, chat_todos
from database.clickhouse import get_global_client
from tasks.P_agent import activities, steps, stream_writer, workflows
from tasks.run_worker import STEP_HEARTBEAT_THROTTLE, WORKFLOW_FAILURE_EXCEPTION_TYPES

pytestmark = [pytest.mark.integration, pytest.mark.timeout(240)]

LONG_ID_A = "chatcmpl-tool-a5ca7d0e11f2" * 9
LONG_ID_B = "chatcmpl-tool-b71c3e9d04aa" * 9

#: The tools that the agent service gives the kind `ordered`.
ORDERED = ("write_todo",)


def _frame(kind, **fields):
    return "data: " + json.dumps({"type": kind, **fields}) + "\n\n"


def _call(name, args, call_id=""):
    """One call of a reply: `(name, args, id)`."""
    return (name, args, call_id)


def _reply(request, text="", calls=()):
    """The frames of one model step: the text, the `model_turn` with the call entries as the
    service classifies them, and `end`."""
    entries = []
    for position, (name, args, call_id) in enumerate(calls):
        kind = "ordered" if name in ORDERED else "parallel"
        entries.append({
            "id": call_id or f"call-{request['step_no']}-{position}", "name": name,
            "args": args, "kind": kind, "page_share": 24000,
            "retry": not name.startswith("browser_")})
    frames = [_frame("response", content=text)] if text else []
    return frames + [
        _frame("model_turn", text=text, reasoning="", tool_calls=entries,
               usage={"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
               summarised=False),
        _frame("end", model="stub-model",
               usage={"prompt_tokens": 11, "completion_tokens": 3, "reasoning_tokens": 0}),
    ]


def _answer_frames(request, text):
    return _reply(request, text)


def _ok_tool(request, n):
    call = request["call"]
    return 200, {"tool_call_id": call["id"], "name": call["name"], "status": "ok",
                 "content": json.dumps({"query": call["args"].get("query"), "hits": []}),
                 "measure": {"sha256": f"digest-{call['id'][-6:]}"}, "error_class": ""}


class _Stub:
    """The agent service and the browser server, as one scripted HTTP server."""

    def __init__(self, script, tool=None):
        self.script = script
        self.tool = tool or _ok_tool
        self.requests: list[dict] = []
        self.tool_requests: list[dict] = []
        #: Each tool request as `(name, args, started, ended)`.
        self.tool_log: list[tuple] = []
        self.released: list[str] = []
        #: Each model frame written, with the time it was written.
        self.sent: list[tuple[float, str]] = []
        self.lock = threading.Lock()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if self.path.startswith("/runs/"):
                    stub.released.append(self.path.split("/")[2])
                    self._send(200, {})
                    return
                request = json.loads(body)
                if self.path == "/tool_call":
                    with stub.lock:
                        stub.tool_requests.append(request)
                        n = len(stub.tool_requests)
                    started = time.monotonic()
                    status, answer = stub.tool(request, n)
                    stub.tool_log.append((request["call"]["name"], request["call"]["args"],
                                          started, time.monotonic()))
                    try:
                        self._send(status, answer)
                    except OSError:
                        pass
                    return
                with stub.lock:
                    stub.requests.append(request)
                    n = len(stub.requests)
                frames = stub.script(request, n)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for frame in frames:
                        self.wfile.write(frame.encode())
                        self.wfile.flush()
                        stub.sent.append((time.monotonic(), frame))
                except OSError:
                    pass

            def _send(self, status, answer):
                data = json.dumps(answer).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


class _Case:
    def __init__(self):
        self.username = f"w19-agent-run-{uuid.uuid4().hex[:10]}"
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
            turn_seq=self.turn_seq, start_seq=self.start_seq,
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

    def messages(self, thread_id=None):
        return agent_runs.read_messages(self.username, self.session_id,
                                        thread_id or self.run_id)

    def delete(self):
        with get_global_client() as client:
            for table in ("agent_runs", "agent_run_messages", "agent_turn_stops",
                          "chat_messages", "chat_message_stream", "chat_todos"):
                client.command(f"DELETE FROM {table} WHERE username = {{u:String}}",
                               parameters={"u": self.username})


async def _run_case(monkeypatch, script, body, extra_workflows=(), tool=None,
                    model_worker=True, plan=False):
    """Run `body(client, case, stub, queue, titled)` with a worker on each queue of the
    loop, all of them the case's own."""
    stub = _Stub(script, tool)
    case = _Case()
    suffix = uuid.uuid4().hex[:8]
    chat_queue, model_queue = f"w19-chat-{suffix}", f"w19-model-{suffix}"
    tool_queue = f"w19-tool-{suffix}"
    monkeypatch.setattr(workflows, "CHAT_TASK_QUEUE", chat_queue)
    monkeypatch.setattr(workflows, "AGENT_TOOL_TASK_QUEUE", tool_queue)
    monkeypatch.setattr(workflows, "CHAT_MODEL_TASK_QUEUE", model_queue)
    monkeypatch.setattr(activities, "INTERNAL_AGENT_URL", stub.url)
    monkeypatch.setattr(stream_writer, "BROWSER_SERVER_URL", stub.url)
    titled = []
    monkeypatch.setattr(activities, "title_session", lambda p: titled.append(p) or "")
    client = None
    acts = [activities.open_run, activities.write_ending,
            activities.summarize_if_first_turn,
            steps.record_step_failure, steps.check_citations,
            steps.write_empty_note, steps.write_asked_answer, steps.write_incomplete]
    try:
        client = await Client.connect("temporal:7233")
        with ThreadPoolExecutor(max_workers=32) as executor:
            workers = [
                Worker(client, task_queue=chat_queue,
                       workflows=[workflows.AgentRun, *extra_workflows],
                       activities=acts, activity_executor=executor,
                       workflow_runner=UnsandboxedWorkflowRunner(),
                       workflow_failure_exception_types=WORKFLOW_FAILURE_EXCEPTION_TYPES),
                Worker(client, task_queue=tool_queue, activities=[steps.tool_call],
                       activity_executor=executor,
                       max_heartbeat_throttle_interval=STEP_HEARTBEAT_THROTTLE),
            ]
            if model_worker:
                workers.append(Worker(
                    client, task_queue=model_queue, activities=[steps.model_step],
                    activity_executor=executor,
                    max_heartbeat_throttle_interval=STEP_HEARTBEAT_THROTTLE))
            async with workers[0], workers[1]:
                if model_worker:
                    async with workers[2]:
                        await body(client, case, stub, chat_queue, titled)
                else:
                    await body(client, case, stub, chat_queue, titled)
    finally:
        try:
            if client is not None:
                await _end_workflows(client, case)
        finally:
            stub.close()
            case.delete()


async def _end_workflows(client, case):
    """Terminate and delete each test-owned workflow before its rows go.

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
            description = await handle.describe()
            if description.status == WorkflowExecutionStatus.RUNNING:
                await handle.terminate(reason="the test case ended")
            run_ids = {description.run_id}
            async for execution in client.list_workflows(
                f'WorkflowId = "{workflow_id}"'):
                if execution.id == workflow_id:
                    run_ids.add(execution.run_id)
            for run_id in sorted(run_ids):
                await client.workflow_service.delete_workflow_execution(
                    DeleteWorkflowExecutionRequest(
                        namespace=client.namespace,
                        workflow_execution=WorkflowExecution(
                            workflow_id=workflow_id, run_id=run_id)))
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise


def _start(client, case, queue, **kwargs):
    return client.start_workflow(
        workflows.AgentRun.run, case.input(), id=f"w6-test-{case.run_id}", task_queue=queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE, **kwargs)


def _roles(case, thread_id=None):
    return [(m.idx, m.role) for m in case.messages(thread_id)]


# ------------------------------------------------------------------------------ the loop


def test_one_answer(monkeypatch):
    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        assert (len(stub.requests), len(stub.tool_requests)) == (1, 0)
        row = case.run_row()
        assert (row.state, row.model_steps, row.end_reason) == ("completed", 1, "")
        assert [(r[0], r[1], r[2]) for r in case.chat_rows()] == [
            (1, "user", "What is in the reports?"), (2, "assistant", "done")]
        assert _roles(case) == [(0, "human"), (1, "ai")]

    asyncio.run(_run_case(monkeypatch, lambda r, n: _reply(r, "done"), body))


def test_two_parallel_calls_overlap_and_keep_their_rows(monkeypatch):
    def script(request, n):
        if n == 1:
            return _reply(request, calls=[
                _call("search_collections", {"query": "alpha"}, LONG_ID_A),
                _call("search_collections", {"query": "beta"}, LONG_ID_B)])
        return _reply(request, "The answer.")

    def tool(request, n):
        time.sleep(1.0)
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        (_, _, s1, e1), (_, _, s2, e2) = sorted(stub.tool_log, key=lambda t: t[2])
        assert s2 < e1, "the two tool calls did not overlap"
        rows = case.chat_rows()
        assert [(r[0], r[1]) for r in rows] == [
            (1, "user"), (2, "tool"), (3, "tool"), (4, "assistant")]
        assert json.loads(rows[1][4]) == {"query": "alpha"}
        assert json.loads(rows[1][5])["query"] == "alpha"
        assert json.loads(rows[2][4]) == {"query": "beta"}
        assert rows[3][2] == "The answer."
        row = case.run_row()
        assert (row.state, row.result, row.next_seq, row.model_steps) == (
            "completed", "The answer.", 5, 2)
        messages = case.messages()
        assert [(m.idx, m.role) for m in messages] == [
            (0, "human"), (1, "ai"), (2, "tool"), (3, "tool"), (4, "ai")]
        assert messages[2].tool_call_id == LONG_ID_A
        assert json.loads(messages[2].usage_json)["measure"]["sha256"] == "digest-" + LONG_ID_A[-6:]
        assert stub.requests[0]["messages"][0]["content"] == "What is in the reports?"
        assert case.run_id in stub.released
        assert [t.session_id for t in titled] == [case.session_id]
        with pytest.raises(WorkflowAlreadyStartedError):
            await _start(client, case, queue)

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def test_a_retried_tool_call_sends_one_key_and_writes_one_result(monkeypatch):
    def script(request, n):
        if n == 1:
            return _reply(request, calls=[_call("append_node", {"text": "A"})])
        return _reply(request, "done")

    def tool(request, n):
        if n == 1:
            return 503, {"detail": "busy"}
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        keys = [r["idempotency_key"] for r in stub.tool_requests]
        assert len(keys) == 2 and keys[0] == keys[1]
        assert [m.role for m in case.messages()].count("tool") == 1

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def test_a_browser_action_gets_one_attempt_and_the_loop_goes_on(monkeypatch):
    def script(request, n):
        if n == 1:
            return _reply(request, calls=[_call("browser_click", {"ref": "e1"})])
        return _reply(request, "done")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.tool_requests) == 1 and len(stub.requests) == 2
        [tool] = [m for m in case.messages() if m.role == "tool"]
        assert json.loads(tool.content)["error"] == "tool_unavailable"
        assert stub.requests[1]["messages"][-1]["status"] == "error"

    asyncio.run(_run_case(monkeypatch, script, body, tool=lambda r, n: (503, {})))


def test_a_lost_tool_ends_after_its_limit_with_a_stored_result(monkeypatch):
    from database import agent_step_events

    monkeypatch.setattr(workflows, "TOOL_CALL_TIMEOUT", timedelta(seconds=5))
    recorded = []
    monkeypatch.setattr(agent_step_events, "record", recorded.append)

    def script(request, n):
        if n == 1:
            return _reply(request, calls=[_call("search_collections", {"query": "q"})])
        return _reply(request, "done")

    def tool(request, n):
        time.sleep(20)
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        [tool_message] = [m for m in case.messages() if m.role == "tool"]
        assert json.loads(tool_message.content)["error"] == "tool_unavailable"
        await asyncio.sleep(21)
        # A late attempt writes nothing over the stored result.
        [again] = [m for m in case.messages() if m.role == "tool"]
        assert again.content == tool_message.content
        # Each attempt that passed its limit wrote its own row, and the workflow none.
        rows = sorted((e.attempt, e.ok, e.error_class) for e in recorded if e.step == "tool")
        assert rows == [(n, False, "start_to_close_timeout") for n in (1, 2, 3)], rows

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def _searching(request, n):
    """A model that sends a new search in every step and never answers."""
    return _reply(request, calls=[_call("search_collections", {"query": f"q{n}"})])


def test_identical_searches_of_one_reply_all_run(monkeypatch):
    """The same search three times in one reply, after three earlier runs of it. Every call
    runs, and no result is written in place of a call."""
    def script(request, n):
        if n <= 3:
            return _reply(request, calls=[_call("search_collections", {"query": "a"})])
        if n == 4:
            return _reply(request, calls=[_call("search_collections", {"query": "a"})] * 3)
        return _reply(request, "Answer.")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert [r["call"]["args"] for r in stub.tool_requests] == [{"query": "a"}] * 6
        tools = [m for m in case.messages() if m.role == "tool"]
        assert len(tools) == 6 and all("repeated_call" not in m.content for m in tools)
        row = case.run_row()
        assert (row.end_reason, row.result, row.model_steps) == ("", "Answer.", 5)
        assert "nag" not in [r[1] for r in case.chat_rows()]

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_call_returned_as_text_is_refused_and_is_not_the_answer(monkeypatch):
    """The agent service sends a reply whose text is call syntax as one unreadable call
    with its `argument_error`. The worker passes the error to `/tool_call`, stores the
    refusal, and the next reply is the answer. The call text is never the result."""
    leaked = 'call:read_documents{collectionname:<|"|>testdata<|"|>,page:0}'
    error = "the model server returned this call as text. The model server sent: " + leaked

    def script(request, n):
        if n == 1:
            frames = _reply(request, leaked, calls=[_call("read_documents", {})])
            turn = json.loads(frames[1][len("data: "):])
            turn["tool_calls"][0]["argument_error"] = error
            frames[1] = "data: " + json.dumps(turn) + "\n\n"
            return frames
        return _reply(request, "Answer.")

    def refuse(request, n):
        call = request["call"]
        return 200, {"tool_call_id": call["id"], "name": call["name"], "status": "error",
                     "content": json.dumps({"message": call.get("argument_error", "")}),
                     "measure": {}, "error_class": "invalid_arguments"}

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert [r["call"].get("argument_error") for r in stub.tool_requests] == [error]
        row = case.run_row()
        assert (row.result, row.model_steps) == ("Answer.", 2)
        answers = [r[2] for r in case.chat_rows() if r[1] == "assistant"]
        assert answers == ["Answer."]

    asyncio.run(_run_case(monkeypatch, script, body, tool=refuse))


def test_browser_calls_of_one_reply_run_in_call_order_beside_a_search(monkeypatch):
    def script(request, n):
        if n == 1:
            return _reply(request, calls=[
                _call("browser_navigate", {"url": "https://example.org/"}),
                _call("search_collections", {"query": "q"}),
                _call("browser_click", {"ref": "e1"}),
                _call("read_page", {"urls": ["https://example.org/a"]})])
        return _reply(request, "done")

    def tool(request, n):
        # The first browser call is the slowest, so a parallel run would end it last.
        name = request["call"]["name"]
        time.sleep(1.5 if name == "browser_navigate" else 0.8 if name == "search_collections"
                   else 0.1)
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        spans = {name: (s, e) for name, _, s, e in stub.tool_log}
        chain = [spans[n] for n in ("browser_navigate", "browser_click", "read_page")]
        for (_, end), (start, _) in zip(chain, chain[1:]):
            assert end <= start, chain
        search = spans["search_collections"]
        assert search[0] < chain[0][1], "the search did not overlap the browser chain"
        # A browser action gets one attempt.
        entries = next(m for m in case.messages() if m.role == "ai").tool_calls
        assert [e["retry"] for e in entries] == [False, True, False, True]

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


async def _wait_terminal(case, run_id=None, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = agent_runs.read_run(case.username, case.session_id, run_id or case.run_id)
        if row is not None and agent_runs.is_terminal(row):
            return row
        await asyncio.sleep(0.5)
    raise AssertionError(f"run {run_id or case.run_id} did not end")


# ------------------------------------------------------------------------ the empty reply


def _empty_rows(case, thread_id=None):
    return [m for m in case.messages(thread_id) if steps.is_retry_marker(m)]


def test_an_empty_third_step_gets_one_nudge_and_a_fourth_step(monkeypatch):
    def script(request, n):
        if n <= 2:
            return _reply(request, calls=[_call("search_collections", {"query": f"q{n}"})])
        if n == 3:
            return _reply(request)
        return _reply(request, "The answer after the nudge.")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 4 and len(_empty_rows(case)) == 1
        assert stub.requests[3]["messages"][-1]["content"] == steps.EMPTY_REPLY_TEXT
        rows = [(r[1], r[2]) for r in case.chat_rows()]
        assert rows[-2:] == [("nag", steps.EMPTY_REPLY_TEXT),
                             ("assistant", "The answer after the nudge.")]
        assert "(the assistant returned an empty answer)" not in [r[1] for r in rows]
        row = case.run_row()
        assert (row.result, row.end_reason) == ("The answer after the nudge.", "")
        assert json.loads(_empty_rows(case)[0].usage_json) == {
            steps.RETRY_MARKER_KEY: steps.EMPTY_RETRY_MARKER}

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_second_empty_step_ends_the_turn_incomplete_with_its_evidence(monkeypatch):
    def script(request, n):
        if n <= 2:
            return _reply(request, calls=[_call("search_collections", {"query": f"q{n}"})])
        return _reply(request)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 4 and len(_empty_rows(case)) == 1
        rows = [(r[1], r[2]) for r in case.chat_rows()]
        assert rows[-1][0] == "assistant"
        assert rows[-1][1].startswith("This run stopped before a final answer, because the "
                                      "model returned two replies")
        assert [r[0] for r in rows].count("nag") == 1
        row = case.run_row()
        assert (row.state, row.end_reason, row.result) == (
            "completed", "empty_response", rows[-1][1])

    asyncio.run(_run_case(monkeypatch, script, body))


def test_an_empty_reply_of_a_later_turn_gets_a_new_nudge(monkeypatch):
    def script(request, n):
        if n in (1, 3):
            return _reply(request)
        return _reply(request, f"Answer {n}.")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        first = case.run_id
        case.run_id, case.turn_uuid = str(uuid.uuid4()), str(uuid.uuid4())
        case.turn_seq, case.start_seq = 10, 11
        activities._insert_chat_row(case.username, case.session_id, case.turn_seq, "user",
                                    content="And the second question?")
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 4
        assert len(_empty_rows(case, first)) == 1 and len(_empty_rows(case)) == 1
        assert case.run_row().result == "Answer 4."

    asyncio.run(_run_case(monkeypatch, script, body))


def test_todo_calls_of_one_reply_run_in_the_order_of_the_reply(monkeypatch):
    def script(request, n):
        if n == 1:
            return _reply(request, calls=[_call("mark_todo", {"ids": ["1"], "status": "done"}),
                                          _call("mark_todo", {"ids": ["2"], "status": "done"}),
                                          _call("read_todo", {})])
        return _reply(request, "done")

    def tool(request, n):
        # The first call is the slowest, so a parallel run would end it last.
        time.sleep(1.5 if request["call"]["args"].get("ids") == ["1"] else 0.1)
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        spans = [(name, json.dumps(args), s, e) for name, args, s, e in stub.tool_log]
        assert [(n, a) for n, a, _, _ in spans] == [
            ("mark_todo", '{"ids": ["1"], "status": "done"}'),
            ("mark_todo", '{"ids": ["2"], "status": "done"}'), ("read_todo", "{}")]
        for (_, _, _, end), (_, _, start, _) in zip(spans, spans[1:]):
            assert end <= start, spans

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def test_read_todo_twice_forces_no_answer(monkeypatch):
    def script(request, n):
        if n <= 2:
            return _reply(request, calls=[_call("read_todo", {})])
        return _reply(request, "done")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 3 and len(stub.tool_requests) == 2
        assert case.run_row().end_reason == ""

    asyncio.run(_run_case(monkeypatch, script, body))


def test_the_step_budget_ends_with_no_model_call(monkeypatch):
    """At the step limit, the calls of the last reply run, and the run ends with the result
    that code writes from the thread. No model call follows."""
    monkeypatch.setattr(workflows, "RUN_MODEL_STEPS", 3)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 3 and len(stub.tool_requests) == 3
        assert all("mode" not in r for r in stub.requests)
        row = case.run_row()
        assert (row.state, row.end_reason, row.model_steps) == ("completed", "step_budget", 3)
        assert row.result.startswith("This run stopped before a final answer")
        assert [m.role for m in case.messages()][-2:] == ["ai", "tool"]
        rows = [(r[1], r[2]) for r in case.chat_rows()]
        assert rows[-1] == ("assistant", row.result)
        assert "nag" not in [r[0] for r in rows]

    asyncio.run(_run_case(monkeypatch, _searching, body))


def test_the_step_limit_holds_across_continue_as_new(monkeypatch):
    monkeypatch.setattr(workflows, "CONTINUE_AS_NEW_STEPS", 2)
    monkeypatch.setattr(workflows, "RUN_MODEL_STEPS", 5)

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        assert len(stub.requests) == 5
        row = case.run_row()
        assert (row.end_reason, row.model_steps) == ("step_budget", 5)
        assert [r[1] for r in case.chat_rows()].count("assistant") == 1

    asyncio.run(_run_case(monkeypatch, _searching, body))


def test_continue_as_new_every_two_steps(monkeypatch):
    monkeypatch.setattr(workflows, "CONTINUE_AS_NEW_STEPS", 2)

    def script(request, n):
        if n < 5:
            return _reply(request, calls=[_call("search_collections", {"query": f"q{n}"})])
        return _reply(request, "Answer after five steps.")

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        continued, run_id = 0, handle.first_execution_run_id
        while run_id:
            history = await client.get_workflow_handle(
                handle.id, run_id=run_id).fetch_history()
            last = history.events[-1]
            run_id = ""
            if last.HasField("workflow_execution_continued_as_new_event_attributes"):
                continued += 1
                run_id = (last.workflow_execution_continued_as_new_event_attributes
                          .new_execution_run_id)
        assert continued == 2
        assert case.run_row().model_steps == 5
        assert [r[1] for r in case.chat_rows()].count("assistant") == 1

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_model_queue_wait_fails_the_run_with_a_readable_text(monkeypatch):
    monkeypatch.setattr(workflows, "TIMEOUTS",
                        replace(workflows.TIMEOUTS, queue_wait=timedelta(seconds=3)))

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert case.run_row().state == "failed"
        ending = case.chat_rows()[-1]
        assert ending[1] == "error" and "The model queue wait passed 3 s." in ending[2]

    asyncio.run(_run_case(monkeypatch, lambda r, n: _reply(r, "x"), body, model_worker=False))


#: The longest time from the stop call to the ending row. The step pumps beat every 10 s,
#: and the worker holds back a heartbeat for at most 5 s.
STOP_LATENCY_LIMIT_SECONDS = 15.0


def test_a_stop_during_a_tool_call_cancels_it(monkeypatch):
    def script(request, n):
        return _reply(request, calls=[_call("search_collections", {"query": "slow"})])

    def tool(request, n):
        time.sleep(60)
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        deadline = time.monotonic() + 30
        while not stub.tool_requests and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        assert stub.tool_requests, "the tool call did not start"
        agent_runs.write_turn_stop(case.username, case.session_id, case.turn_seq)
        stopped_at = time.monotonic()
        await handle.cancel()
        lead = await _wait_terminal(case, seconds=60)
        latency = time.monotonic() - stopped_at
        print(f"stop latency during a tool call: {latency:.1f} s")
        assert lead.state == "cancelled"
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert latency <= STOP_LATENCY_LIMIT_SECONDS, f"stop latency {latency:.1f} s"
        assert [m for m in case.messages() if m.role == "tool"] == []
        rows = case.chat_rows()
        assert max(rows)[1:3] == ("error", "This turn was stopped.")

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def test_an_answer_with_open_todo_items_ends_the_turn(monkeypatch):
    """The answer is final. The worker writes no note and marks no item."""
    async def body(client, case, stub, queue, titled):
        chat_todos.write_todo(case.username, case.session_id, "read the reports",
                              [{"id": "1", "text": "read report one", "status": "pending"},
                               {"id": "2", "text": "read report two", "status": "pending"}])
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 1
        roles = [r[1] for r in case.chat_rows()]
        assert "nag" not in roles and roles.count("assistant") == 1
        row = case.run_row()
        assert (row.end_reason, row.result) == ("", "Answer 1.")
        todo = chat_todos.read_todo(case.username, case.session_id)
        assert [i["status"] for i in todo["items"]] == ["pending", "pending"]

    asyncio.run(_run_case(monkeypatch, lambda r, n: _reply(r, f"Answer {n}."), body))


def test_a_model_step_retry_after_its_write_makes_no_second_call(monkeypatch):
    def script(request, n):
        # The stream closes after `model_turn`, with no `end` frame.
        return _reply(request, "Written.")[:-1]

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 1
        assert [m.role for m in case.messages()].count("ai") == 1
        assert case.run_row().result == "Written."

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
        return [_frame("error", error_class="other", retryable=True,
                       content="Error during streaming: model unavailable")]

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert len(stub.requests) == 3
        row = case.run_row()
        assert row.state == "failed" and "model unavailable" in row.error
        ending = case.chat_rows()[-1]
        assert ending[0] == 2 and ending[1] == "error"
        assert ending[2].startswith("The assistant could not answer: ")

    asyncio.run(_run_case(monkeypatch, script, body))


def test_an_uncited_answer_that_names_a_document_gets_one_citation_round(monkeypatch):
    from tasks.P_agent import citations

    def script(request, n):
        if n == 1:
            return _reply(request, "The memo sets the budget [D1].")
        if n == 2:
            return _reply(request, calls=[_call("cite_documents", {"citations": [
                {"collectionname": "testdata", "file_hash": "a" * 64, "quote": "q"}]})])
        return _reply(request, "The memo sets the budget [D1], cited.")

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        assert len(stub.requests) == 3
        note = stub.requests[1]["messages"][-1]["content"]
        assert note.startswith("Your answer uses citation labels") and "[D1]" in note
        rows = [(r[1], r[2], r[3]) for r in case.chat_rows()]
        assert [r[0] for r in rows] == ["user", "assistant", "nag", "tool", "assistant"]
        assert rows[2][1] == note and rows[3][2] == "cite_documents"
        assert rows[4][1] == "The memo sets the budget [D1], cited."
        row = case.run_row()
        assert row.state == "completed"
        assert row.result == "The memo sets the budget [D1], cited."

    def tool(request, n):
        call = request["call"]
        return 200, {"tool_call_id": call["id"], "name": call["name"], "status": "ok",
                     "content": json.dumps({"citations": [{"file_hash": "a" * 16,
                                                        "handle": "[D1]"}]}),
                     "measure": {}, "error_class": ""}

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def _citation_tool(frames):
    """The frames of a reply whose model had `cite_documents`."""
    out = []
    for frame in frames:
        if '"type": "model_turn"' in frame:
            data = json.loads(frame[len("data: "):])
            data["usage"]["citation_tool"] = True
            frame = "data: " + json.dumps(data) + "\n\n"
        out.append(frame)
    return out


def test_a_read_document_answer_without_a_file_name_gets_one_round(monkeypatch):
    """The stored read shape can support an answer that names no path or hash."""
    def script(request, n):
        if n == 1:
            return _citation_tool(_reply(request, calls=[_call("read_documents", {
                "collectionname": "testdata", "file_hashes": ["a" * 64]})]))
        if n == 2:
            return _citation_tool(_reply(request, "The budget is 5."))
        if n == 3:
            return _citation_tool(_reply(request, calls=[_call("cite_documents", {
                "citations": [{"collectionname": "testdata", "file_hash": "a" * 64,
                               "quote": "The budget is 5."}]})]))
        return _citation_tool(_reply(request, "The budget is 5 [D1]."))

    def tool(request, n):
        call = request["call"]
        if call["name"] == "read_documents":
            content = {"items": [{"collectionname": "testdata", "file_hash": "a" * 16,
                                  "path": "/memo.txt", "page": 1,
                                  "text": "The budget is 5.", "more": "next"}]}
        else:
            content = {"citations": [{"collectionname": "testdata",
                                      "file_hash": "a" * 16, "handle": "[D1]"}]}
        return 200, {"tool_call_id": call["id"], "name": call["name"], "status": "ok",
                     "content": json.dumps(content), "measure": {}, "error_class": ""}

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 4
        notes = [m for m in case.messages() if m.usage.get("repair_marker") == "citation"]
        assert len(notes) == 1
        assert case.run_row().result == "The budget is 5 [D1]."
        assert any(m.tool_name == "cite_documents" for m in case.messages())

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


def test_a_failed_citation_call_does_not_stop_the_label_check(monkeypatch):
    """The model calls `cite_documents`, the call fails, and the answer uses the label it
    wanted. The check reads the failed result, finds no successful one, and asks once."""
    def script(request, n):
        if n == 1:
            return _citation_tool(_reply(request, calls=[_call("cite_documents", {
                "citations": [{"source": "memo.txt"}]})]))
        if n == 2:
            return _citation_tool(_reply(request, "The memo sets the budget [D1]."))
        return _citation_tool(_reply(request, "The memo sets the budget."))

    def tool(request, n):
        call = request["call"]
        return 200, {"tool_call_id": call["id"], "name": call["name"], "status": "error",
                     "content": json.dumps({"success": False, "error": "invalid_arguments",
                                            "message": "citations is not valid"}),
                     "measure": None, "error_class": "invalid_arguments"}

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        assert len(stub.requests) == 3
        [cite] = [m for m in case.messages() if m.role == "tool"]
        assert [e["status"] for e in cite.usage["evidence"]] == ["error"]
        notes = [m for m in case.messages() if m.usage.get("repair_marker") == "citation"]
        assert len(notes) == 1
        assert notes[0].usage["citation_check"]["unresolved"] == ["[D1]"]
        assert case.run_row().result == "The memo sets the budget."

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


# ------------------------------------------------------------------------- stop and orphans

#: A filler frame longer than the 512 bytes that `iter_lines` reads at a time, so each one
#: reaches the attempt as it is written.
_FILLER = "." * 600


@pytest.mark.parametrize("stop_after", [3.0, 21.0])
def test_a_stop_during_the_stream_writes_nothing_after_the_ending(monkeypatch, stop_after):
    """A stop cancels `model_step`, and the workflow waits for the attempt to end. The stub
    keeps sending frames after the stop and then a tool call. The attempt stops at the first
    frame after the cancellation, so no tool row exists and the ending row is last.
    """

    def script(request, n):
        def frames():
            yield _frame("response", content="Working")
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                time.sleep(0.5)
                yield _frame("response", content=_FILLER)
            yield from _reply(request, calls=[_call("search_collections", {"query": "late"})])
        return frames()

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        deadline = time.monotonic() + 30
        while len(stub.sent) < 4 and time.monotonic() < deadline:
            await asyncio.sleep(0.2)
        assert len(stub.sent) >= 4, "the stream did not start"
        await asyncio.sleep(stop_after)
        agent_runs.write_turn_stop(case.username, case.session_id, case.turn_seq)
        stopped_at = time.monotonic()
        await handle.cancel()
        lead = await _wait_terminal(case, seconds=150)
        latency = time.monotonic() - stopped_at
        print(f"stop latency: {latency:.1f} s from the cancel call to the ending row, "
              f"stop {stop_after:.0f} s into the stream")
        assert latency <= STOP_LATENCY_LIMIT_SECONDS, f"stop latency {latency:.1f} s"
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert lead.state == "cancelled"
        rows = case.chat_rows()
        ending = max(rows, key=lambda r: r[0])
        assert (ending[1], ending[2]) == ("error", "This turn was stopped.")
        assert [r for r in rows if r[1] == "error"] == [ending]
        assert [r for r in rows if r[1] == "tool"] == []
        assert stub.tool_requests == []
        assert len(stub.requests) == 1

    asyncio.run(_run_case(monkeypatch, script, body))


# ------------------------------------------------------------------- the question

def test_ask_user_ends_after_all_calls_without_a_todo_nag(monkeypatch):
    questions = ["Bigger or smaller than 50?", "Which range?"]

    def script(request, n):
        frames = _reply(request, calls=[
            _call("ask_user", {"question": questions[0], "options": ["bigger", "smaller"]}),
            _call("read_todo", {}),
            _call("ask_user", {"question": questions[1], "options": []}),
        ])
        # The agent service names the model of the reply in `model_turn`.
        turn = json.loads(frames[0][len("data: "):])
        frames[0] = "data: " + json.dumps({**turn, "model": "asking-model"}) + "\n\n"
        return frames

    def tool(request, n):
        call = request["call"]
        content = ({"success": True, "asked": True, **call["args"]}
                   if call["name"] == "ask_user" else {"items": []})
        return 200, {"tool_call_id": call["id"], "name": call["name"],
                     "status": "ok", "content": json.dumps(content),
                     "measure": None, "error_class": ""}

    async def body(client, case, stub, queue, titled):
        chat_todos.write_steps(case.username, case.session_id, "guess", ["one", "two", "three"])
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        assert case.run_row().result == questions[0]
        rows = case.chat_rows()
        assert [r[3] for r in rows if r[1] == "tool"].count("ask_user") == 2
        assert [r[2] for r in rows if r[1] == "assistant"] == [questions[0]]
        assert not [r for r in rows if r[1] == "nag"]
        # The question row names the model of the reply that asked.
        with get_global_client() as ch:
            models = ch.query(
                "SELECT model FROM chat_messages FINAL WHERE username = {u:String} "
                "AND session_id = {s:String} AND role = 'assistant'",
                parameters={"u": case.username, "s": case.session_id}).result_rows
        assert [m[0] for m in models] == ["asking-model"]

    asyncio.run(_run_case(monkeypatch, script, body, tool=tool))


# ------------------------------------------------------------------- the compaction line

#: The version 3 record of a compaction.
COMPACTION_RECORD = {
    "version": 3, "layer": "prefix", "status": "ok", "source": [], "retained_from": None,
    "summary": "The record of the older steps.", "error": "", "tokens_before": 212004,
    "threshold": 209715, "target": 69905, "est_after": 60000, "target_reached": True,
    "steps_summarised": 31, "sizes": {},
}


def _compacted(request, text="", calls=(), end=True, record=None):
    """A model step that compacts first: the `compaction` frame, then the reply, whose
    `model_turn` carries the record."""
    record = COMPACTION_RECORD if record is None else record
    frames = _reply(request, text, calls)
    turn = next(i for i, f in enumerate(frames) if '"type": "model_turn"' in f)
    data = json.loads(frames[turn][len("data: "):])
    data.update(compaction=record, summarised=record["status"] == "ok")
    frames[turn] = "data: " + json.dumps(data) + "\n\n"
    start = _frame("compaction", state="running", tokens_before=212004, target=69905, parts=1)
    return [start] + (frames if end else frames[:-1])


def _line(case):
    rows = [r for r in case.chat_rows() if r[1] == "compaction"]
    return [(r[0], json.loads(r[2])) for r in rows]


def test_a_compaction_line_is_the_first_row_of_its_step(monkeypatch):
    def script(request, n):
        if n == 1:
            return _compacted(request, calls=[_call("search_collections", {"query": "q"})])
        return _answer_frames(request, "Done.")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        [(seq, content)] = _line(case)
        assert seq == case.start_seq
        assert content == {
            "state": "done", "tokens_before": 212004, "target": 69905, "parts": 1,
            "tokens_after": 11, "steps_summarised": 31, "target_reached": True,
            "record": "The record of the older steps.", "part_states": [],
            "summary_state": "ok"}
        rows = [(r[0], r[1]) for r in case.chat_rows() if r[0] >= case.start_seq]
        assert rows == [(case.start_seq, "compaction"), (case.start_seq + 1, "tool"),
                        (case.start_seq + 2, "assistant")]

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_compaction_step_retried_after_its_ai_row_keeps_the_answer_seq(monkeypatch):
    def script(request, n):
        # The stream closes after `model_turn`, with no `end` frame.
        return _compacted(request, "Written.", end=False)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 1
        [(seq, content)] = _line(case)
        assert (seq, content["state"], content["tokens_after"]) == (case.start_seq, "done", 11)
        answers = [r for r in case.chat_rows() if r[1] == "assistant"]
        assert [(r[0], r[2]) for r in answers] == [(case.start_seq + 1, "Written." + steps.SUMMARY_NOTICE)]

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_stream_that_ends_after_the_compaction_frame_writes_the_line_again(monkeypatch):
    def script(request, n):
        frames = _compacted(request, "Written.")
        return frames[:1] if n == 1 else frames

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert len(stub.requests) == 2
        [(seq, content)] = _line(case)
        assert (seq, content["state"]) == (case.start_seq, "done")
        answers = [r[0] for r in case.chat_rows() if r[1] == "assistant"]
        assert answers == [case.start_seq + 1]

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_failed_summary_line_says_so_and_the_answer_gets_no_notice(monkeypatch):
    failed = {**COMPACTION_RECORD, "status": "failed", "summary": "", "steps_summarised": 0,
              "error": "the summary request gave no text"}

    def script(request, n):
        return _compacted(request, "Written.", record=failed)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        [(seq, content)] = _line(case)
        assert (content["summary_state"], content["record"]) == ("failed", "")
        answers = [r[2] for r in case.chat_rows() if r[1] == "assistant"]
        assert answers == ["Written."]
        # The failed record is stored, and it changes no message of a later request.
        stored = [m for m in case.messages() if m.role == "compaction"]
        assert json.loads(stored[0].content)["status"] == "failed"

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_note_warning_field_writes_no_row(monkeypatch):
    def script(request, n):
        if n == 1:
            frames = _reply(request, calls=[_call("search_collections", {"query": "q"})])
            data = json.loads(frames[0][len("data: "):])
            data["note_warning"] = True
            return ["data: " + json.dumps(data) + "\n\n"] + frames[1:]
        return _answer_frames(request, "Done.")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        messages = case.messages()
        assert not [m for m in messages if m.role == "human"
                    and m.content.startswith("Your context is at")]
        assert [m.role for m in messages][:4] == ["human", "ai", "tool", "ai"]
        rows = [(r[0], r[1]) for r in case.chat_rows() if r[0] >= case.start_seq]
        assert rows == [(case.start_seq, "tool"), (case.start_seq + 1, "assistant")]

    asyncio.run(_run_case(monkeypatch, script, body))
