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
from temporalio.service import RPCError, RPCStatusCode
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio import workflow
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from database import agent_plans, agent_runs, chat_todos
from database.clickhouse import get_global_client
from tasks.P_agent import activities, plan_runs, steps, stream_writer, workflows
from tasks.run_worker import STEP_HEARTBEAT_THROTTLE, WORKFLOW_FAILURE_EXCEPTION_TYPES

pytestmark = [pytest.mark.integration, pytest.mark.timeout(240)]

LONG_ID_A = "chatcmpl-tool-a5ca7d0e11f2" * 9
LONG_ID_B = "chatcmpl-tool-b71c3e9d04aa" * 9

#: The kinds that the agent service gives, by tool name.
ORDERED = ("append_node", "append_child", "edit_node", "move_node", "remove_node")


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
        kind = ("delegation" if name == "run_subagent"
                else "ordered" if name in ORDERED else "parallel")
        entries.append({
            "id": call_id or f"call-{request['step_no']}-{position}", "name": name,
            "args": args, "kind": kind,
            "briefings": args.get("tasks") if kind == "delegation" else None,
            "page_share": None if kind == "delegation" else 24000,
            "budget_exhausted": False, "retry": not name.startswith("browser_"),
            "args_digest": steps.args_digest(name, args)})
    frames = [_frame("response", content=text)] if text else []
    return frames + [
        _frame("model_turn", text=text, reasoning="", tool_calls=entries,
               bound_names=["search_collections"],
               usage={"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
               summarised=False),
        _frame("end", model="stub-model",
               usage={"prompt_tokens": 11, "completion_tokens": 3, "reasoning_tokens": 0}),
    ]


def _answer_frames(request, text):
    return _reply(request, text)


def _delegate_frames(request, calls):
    """A reply with `run_subagent` calls. `calls` holds `(call_id, briefings)`."""
    return _reply(request, calls=[_call("run_subagent", {"tasks": b}, c) for c, b in calls])


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

    def modes(self):
        return [r["mode"] for r in self.requests]

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

    def messages(self, thread_id=None):
        return agent_runs.read_messages(self.username, self.session_id,
                                        thread_id or self.run_id)

    def delete(self):
        with get_global_client() as client:
            for table in ("agent_runs", "agent_run_messages", "agent_turn_stops",
                          "chat_messages", "chat_message_stream", "chat_todos",
                          "agent_plan_snapshots", "agent_plan_runs", "agent_plan_documents",
                          "agent_plan_decisions"):
                client.command(f"DELETE FROM {table} WHERE username = {{u:String}}",
                               parameters={"u": self.username})


async def _run_case(monkeypatch, script, body, extra_workflows=(), tool=None,
                    model_worker=True):
    """Run `body(client, case, stub, queue, titled)` with a worker on each queue of the
    loop, all of them the case's own."""
    stub = _Stub(script, tool)
    case = _Case()
    suffix = uuid.uuid4().hex[:8]
    chat_queue, model_queue = f"w19-chat-{suffix}", f"w19-model-{suffix}"
    tool_queue = f"w19-tool-{suffix}"
    monkeypatch.setattr(workflows, "CHAT_TASK_QUEUE", chat_queue)
    monkeypatch.setattr(workflows, "AGENT_TOOL_TASK_QUEUE", tool_queue)
    monkeypatch.setitem(agent_runs.LEAD_QUEUES, "chat", model_queue)
    monkeypatch.setitem(agent_runs.LEAD_QUEUES, "planner", model_queue)
    monkeypatch.setitem(agent_runs.LEAD_QUEUES, "organizer", model_queue)
    monkeypatch.setattr(activities, "INTERNAL_AGENT_URL", stub.url)
    monkeypatch.setattr(stream_writer, "BROWSER_SERVER_URL", stub.url)
    titled = []
    monkeypatch.setattr(activities, "title_session", lambda p: titled.append(p) or "")
    client = None
    acts = [activities.open_run, activities.append_nag, activities.write_ending,
            activities.summarize_if_first_turn, activities.read_chat_todo, activities.fan_in,
            activities.continue_run, steps.delegate_step, steps.prepare_continuation,
            steps.record_step_failure, steps.plan_has_sections]
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


def test_plan_tree_calls_keep_their_order_and_a_search_overlaps_them(monkeypatch):
    def script(request, n):
        if n == 1:
            return _reply(request, calls=[_call("append_node", {"text": "A"}),
                                          _call("append_node", {"text": "B"}),
                                          _call("search_collections", {"query": "q"})])
        return _reply(request, "done")

    def tool(request, n):
        time.sleep(1.0)
        return _ok_tool(request, n)

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        log = {(name, json.dumps(args)): (s, e) for name, args, s, e in stub.tool_log}
        a = log[("append_node", '{"text": "A"}')]
        b = log[("append_node", '{"text": "B"}')]
        search = log[("search_collections", '{"query": "q"}')]
        assert a[1] <= b[0], "B started before A ended"
        assert search[0] < a[1] or search[0] < b[1], "the search overlapped neither"

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


def test_the_repeated_call_guard_forces_one_answer(monkeypatch):
    def script(request, n):
        if request["mode"] == "final":
            return _reply(request, "Forced.")
        return _reply(request, calls=[_call("search_collections", {"query": "a"})])

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert stub.modes() == ["tools", "tools", "final"]
        assert len(stub.tool_requests) == 1
        tools = [m for m in case.messages() if m.role == "tool"]
        assert json.loads(tools[-1].content)["error"] == "not_run"
        row = case.run_row()
        assert (row.state, row.end_reason, row.result) == ("completed", "repeated_call", "Forced.")

    asyncio.run(_run_case(monkeypatch, script, body))


def test_read_todo_twice_forces_no_answer(monkeypatch):
    def script(request, n):
        if n <= 2:
            return _reply(request, calls=[_call("read_todo", {})])
        return _reply(request, "done")

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert stub.modes() == ["tools", "tools", "tools"]
        assert case.run_row().end_reason == ""

    asyncio.run(_run_case(monkeypatch, script, body))


def test_the_step_budget_ends_with_one_final_step(monkeypatch):
    monkeypatch.setattr(workflows, "RUN_MODEL_STEPS", 3)

    def script(request, n):
        if request["mode"] == "final":
            return _reply(request, "Budget answer.")
        return _reply(request, calls=[_call("search_collections", {"query": f"q{n}"})])

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        assert stub.modes() == ["tools", "tools", "tools", "final"]
        row = case.run_row()
        assert (row.state, row.end_reason, row.model_steps) == ("completed", "step_budget", 4)
        human = [m.content for m in case.messages() if m.role == "human"]
        assert human[-1] == steps.FINAL_TEXT["step_budget"]

    asyncio.run(_run_case(monkeypatch, script, body))


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


def test_one_forced_answer_with_an_open_todo(monkeypatch):
    monkeypatch.setattr(workflows, "RUN_MODEL_STEPS", 3)

    def script(request, n):
        if request["mode"] == "final":
            return _reply(request, "Forced answer.")
        return _reply(request, calls=[_call("search_collections", {"query": f"q{n}"})])

    async def body(client, case, stub, queue, titled):
        chat_todos.write_todo(case.username, case.session_id, "read the reports",
                              [{"id": "1", "text": "read report one", "status": "pending"},
                               {"id": "2", "text": "read report two", "status": "pending"}])
        assert await (await _start(client, case, queue)).result() == "completed"
        assert stub.modes().count("final") == 1
        roles = [r[1] for r in case.chat_rows()]
        assert "nag" not in roles and roles.count("assistant") == 1
        assert case.run_row().end_reason == "step_budget"

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_retried_final_step_writes_one_human_message(monkeypatch):
    monkeypatch.setattr(workflows, "RUN_MODEL_STEPS", 1)
    finals = []

    def script(request, n):
        if request["mode"] == "final":
            finals.append(n)
            if len(finals) == 1:
                return [_frame("response", content="cut")]
            return _reply(request, "Forced.")
        return _reply(request, calls=[_call("search_collections", {"query": "q"})])

    async def body(client, case, stub, queue, titled):
        assert await (await _start(client, case, queue)).result() == "completed"
        messages = case.messages()
        assert [m.content for m in messages if m.role == "human"].count(
            steps.FINAL_TEXT["step_budget"]) == 1
        assert [m.content for m in messages if m.role == "ai"][-1] == "Forced."
        assert len(finals) == 2

    asyncio.run(_run_case(monkeypatch, script, body))


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


def test_an_open_todo_nags_twice_then_stops(monkeypatch):
    def script(request, n):
        return _reply(request, f"Answer {n}.")

    async def body(client, case, stub, queue, titled):
        chat_todos.write_todo(case.username, case.session_id, "read the reports",
                              [{"id": "1", "text": "read report one", "status": "pending"}])
        handle = await _start(client, case, queue)
        assert await handle.result() == "completed"
        roles = [(r[0], r[1]) for r in case.chat_rows()]
        assert roles == [(1, "user"), (2, "assistant"), (3, "nag"), (4, "assistant"),
                         (5, "nag"), (6, "assistant"), (7, "nag")]
        assert len(stub.requests) == 3
        assert [m["role"] for m in stub.requests[1]["messages"]] == ["human", "ai", "human"]
        row = case.run_row()
        assert (row.nags_this_turn, row.state, row.next_seq) == (2, "completed", 8)

    asyncio.run(_run_case(monkeypatch, script, body))


# ---------------------------------------------------------------------------- delegation


def _briefing(objective):
    return {"objective": objective, "known": "", "bring_back": "the facts"}


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


def test_a_delegation_runs_the_search_first_and_the_continuation_starts_no_child(monkeypatch):
    """`fan-in-once`: a reply with `run_subagent` and a search runs the search, then two
    children. The lead is continued once with both reports, and the continuation's answer
    starts no child."""

    def script(request, n):
        if request["kind"] == "subagent":
            return _reply(request, f"Report on {_objective(request)}.")
        if _is_continuation(request):
            return _reply(request, "The final answer.")
        return _reply(request, calls=[
            _call("run_subagent", {"tasks": [_briefing("alpha"), _briefing("beta")]}, "d1"),
            _call("search_collections", {"query": "first"})])

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        assert await handle.result() == "delegated"
        await _wait_terminal(case)
        rows = _turn_rows(case)
        continuation = next(r for r in rows if r.continues_run_id == case.run_id)
        await _wait_terminal(case, continuation.run_id)
        lead = case.run_row()
        assert (lead.state, lead.result, lead.delegate_seq) == ("completed", "The final answer.", 3)
        rows = _turn_rows(case)
        children = [r for r in rows if r.depth == 1]
        assert len(children) == 2 and {r.state for r in children} == {"completed"}
        assert {r.parent_run_id for r in children} == {case.run_id}
        assert not [r for r in rows if r.parent_run_id == continuation.run_id]
        assert [r.subagent_share for r in children] == [2, 2]
        # The search ended before any child made its model call.
        search_end = stub.tool_log[0][3]
        child_times = [t for t, f in stub.sent if '"model_turn"' in f]
        assert len(stub.tool_log) == 1 and search_end < sorted(child_times)[1]
        kinds = [(r["kind"], r["depth"], _is_continuation(r)) for r in stub.requests]
        assert kinds.count(("chat", 0, True)) == 1
        assert kinds.count(("subagent", 1, False)) == 2
        for request in stub.requests:
            assert request["allowed_collections"] == ["testdata"]
            if request["kind"] == "subagent":
                assert request["earlier"] == [] and request["can_delegate"] is True
        last = next(r for r in stub.requests if _is_continuation(r))["messages"][-1]
        result = json.loads(last["content"])
        assert last["tool_call_id"] == "d1" and result["refused"] == []
        assert sorted(r["report"] for r in result["reports"]) == [
            "Report on alpha.", "Report on beta."]
        chat = [(r[0], r[1], r[2], r[3]) for r in case.chat_rows()]
        assert chat[1][:2] == (2, "tool") and chat[1][3] == "search_collections"
        assert chat[2:] == [(3, "tool", '{"state":"reported"}', "run_subagent"),
                            (4, "assistant", "The final answer.", "")]
        tool_input = json.loads(case.chat_rows()[2][4])
        assert tool_input["tool_call_id"] == "d1"
        assert tool_input["batch_id"] == agent_runs.batch_id_for(case.run_id)
        assert [m.role for m in case.messages()].count("tool") == 2

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_depth_1_delegation_continues_through_its_own_continuation(monkeypatch):
    """`depth-limit`: the depth 2 run gets `can_delegate` false and no row goes deeper. The
    depth 1 run reports to the lead through its continuation, and the chain ends both."""

    def script(request, n):
        if request["depth"] == 2:
            return _reply(request, "Deep report.")
        if request["depth"] == 1 and not _is_continuation(request):
            return _delegate_frames(request, [("d2", [_briefing("deeper")])])
        if request["depth"] == 1:
            return _reply(request, "Middle report.")
        if _is_continuation(request):
            return _reply(request, "Lead answer.")
        return _delegate_frames(request, [("d1", [_briefing("middle")])])

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
        if request["kind"] == "subagent":
            return _reply(request, "ok")
        if _is_continuation(request):
            return _reply(request, "Done.")
        return _delegate_frames(request, [("d1", [_briefing(f"b{i}") for i in range(7)])])

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
        await _wait_terminal(case, next(r for r in _turn_rows(case)
                                        if r.continues_run_id == case.run_id).run_id)
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
        calls = [("d1", [_briefing("x"), _briefing("y"), _briefing("z")])]

        class Crash(agent_runs.RunRowWriter):
            def write(self, **changes):
                raise RuntimeError("the attempt ends before the waiting state")

        with pytest.raises(RuntimeError):
            activities._delegate(row, calls, [2], Crash(row), None)
        first = sorted((r.run_id, r.subagent_share) for r in _turn_rows(case)
                       if r.parent_run_id == case.run_id)
        summary = activities._delegate(row, calls, [2], agent_runs.RunRowWriter(row), None)
        second = sorted((r.run_id, r.subagent_share) for r in _turn_rows(case)
                        if r.parent_run_id == case.run_id)
        assert first == second and len(first) == 3
        # Six less the earlier sub-agent leaves five: three children and two to share.
        assert sorted(share for _, share in second) == [0, 1, 1]
        assert summary.children == [agent_runs.child_run_id(summary.batch_id, i) for i in range(3)]
        assert case.run_row().state == "waiting_for_children"
        # A third attempt finds the waiting state and returns the same children.
        again = activities._delegate(row, calls, [2], agent_runs.RunRowWriter(row), None)
        assert again.children == summary.children
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
        return _delegate_frames(request, [("d1", [_briefing("alpha")])])

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        try:
            await handle.result()
        except WorkflowFailureError:
            pass
        lead = await _wait_terminal(case)
        assert lead.state == "cancelled"
        rows = _turn_rows(case)
        assert {r.state for r in rows if r.depth == 1} <= {"cancelled"}
        assert not [r for r in rows if r.continues_run_id]
        assert len(stub.requests) == 1
        assert case.chat_rows()[-1][1:3] == ("error", "This turn was stopped.")

    asyncio.run(_run_case(monkeypatch, script, body))


def test_the_sweep_fails_a_run_with_no_workflow_and_continues_its_parent(monkeypatch):
    """`collector-sweep`, with rows whose workflows do not exist: the sweep writes `failed`
    for the child, and `fan_in` continues the waiting lead, which then completes."""
    from tasks.P_agent import supervise

    def script(request, n):
        return _reply(request, "Answer after the sweep.")

    async def body(client, case, stub, queue, titled):
        batch = agent_runs.batch_id_for(case.run_id)
        child = agent_runs.child_run_id(batch, 0)
        entry = {"id": "d1", "name": "run_subagent", "args": {"tasks": [_briefing("x")]},
                 "kind": "delegation", "briefings": [_briefing("x")], "position": 0, "seq": 2}
        for idx, role, calls in ((0, "human", "[]"), (1, "ai", json.dumps([entry]))):
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
        assert await supervise.sweep(client, later, username=case.username) == {
            "ended": 0, "continued": 0}

    asyncio.run(_run_case(monkeypatch, script, body))


# ------------------------------------------------------------------------- stop and orphans

#: A filler frame longer than the 512 bytes that `iter_lines` reads at a time, so each one
#: reaches the attempt as it is written.
_FILLER = "." * 600


@pytest.mark.parametrize("stop_after", [3.0, 21.0])
def test_a_stop_during_the_stream_writes_nothing_after_the_ending(monkeypatch, stop_after):
    """A stop cancels `model_step`, and the workflow waits for the attempt to end. The stub
    keeps sending frames after the stop and then a delegation. The attempt stops at the
    first frame after the cancellation, so no child row exists and the ending row is last.
    """

    def script(request, n):
        def frames():
            yield _frame("response", content="Working")
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                time.sleep(0.5)
                yield _frame("response", content=_FILLER)
            yield from _delegate_frames(request, [("d1", [_briefing("alpha")])])
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
        assert [r for r in _turn_rows(case) if r.parent_run_id] == []
        rows = case.chat_rows()
        ending = max(rows, key=lambda r: r[0])
        assert (ending[1], ending[2]) == ("error", "This turn was stopped.")
        assert [r for r in rows if r[1] == "error"] == [ending]
        assert len(stub.requests) == 1

    asyncio.run(_run_case(monkeypatch, script, body))


def test_the_sweep_ends_the_children_of_a_failed_parent(monkeypatch):
    """Every attempt of `delegate_step` writes the child rows and fails before the waiting
    state, and the lead ends `failed` with its children `running`. The sweep ends every
    child, and the turn holds no open run."""
    from tasks.P_agent import supervise

    def script(request, n):
        return _delegate_frames(request, [("d1", [_briefing("alpha"), _briefing("beta")])])

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
        assert len(stub.requests) == 1
        lead = case.run_row()
        assert lead.state == "failed" and "before the waiting state" in lead.error
        children = [r for r in _turn_rows(case) if r.parent_run_id == case.run_id]
        assert len(children) == 2 and {r.state for r in children} == {"running"}

        counts = await supervise.sweep(client, username=case.username, grace_seconds=0)
        assert counts == {"ended": 2, "continued": 0}
        rows = _turn_rows(case)
        assert {r.state for r in rows if r.parent_run_id} == {"failed"}
        assert [r for r in rows if not agent_runs.is_terminal(r)] == []

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_stop_during_the_delegation_ends_every_row_of_the_turn(monkeypatch):
    """The stop lands while `delegate_step` writes the child rows. The lead ends
    `cancelled`, and each child row it wrote ends `cancelled` with it, within
    `STOP_LATENCY_LIMIT_SECONDS` of the stop and with no sweep."""

    def script(request, n):
        return _delegate_frames(request, [("d1", [_briefing("alpha"), _briefing("beta")])])

    real_create = agent_runs.create_run

    def create_run(run_row):
        real_create(run_row)
        if run_row.kind == "subagent":
            # Holds the delegation open, so the stop lands between the child rows.
            time.sleep(2.0)

    monkeypatch.setattr(agent_runs, "create_run", create_run)

    async def body(client, case, stub, queue, titled):
        handle = await _start(client, case, queue)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if [r for r in _turn_rows(case) if r.parent_run_id]:
                break
            await asyncio.sleep(0.1)
        agent_runs.write_turn_stop(case.username, case.session_id, case.turn_seq)
        stopped_at = time.monotonic()
        await handle.cancel()
        deadline = stopped_at + STOP_LATENCY_LIMIT_SECONDS
        rows = _turn_rows(case)
        while time.monotonic() < deadline:
            rows = _turn_rows(case)
            if rows and all(agent_runs.is_terminal(r) for r in rows):
                break
            await asyncio.sleep(0.2)
        latency = time.monotonic() - stopped_at
        print(f"stop latency during the delegation: {latency:.1f} s")
        children = [r for r in rows if r.parent_run_id]
        assert children, "no child row was written"
        assert [(r.run_id, r.state) for r in rows if not agent_runs.is_terminal(r)] == []
        assert latency <= STOP_LATENCY_LIMIT_SECONDS, f"stop latency {latency:.1f} s"
        assert {r.state for r in rows} == {"cancelled"}
        assert [r for r in rows if r.continues_run_id] == []
        assert case.chat_rows()[-1][1:3] == ("error", "This turn was stopped.")
        assert len(stub.requests) == 1

    asyncio.run(_run_case(monkeypatch, script, body))


# ---------------------------------------------------------------------------- the plan layer


def _decide(case, plan_run_id, action, version, comment="", seq=None):
    """Write the decision row and the user row as `decide_plan` does, and return the input
    of the run it starts. The website's checks are tested in `api/chat/plans.rs`."""
    decision_id = str(uuid.uuid4())
    seq = seq or max(r[0] for r in case.chat_rows()) + 1
    activities._insert_chat_row(case.username, case.session_id, seq, "user",
                                content=comment or f"Approved plan version {version}.")
    with get_global_client() as client:
        client.command(
            "INSERT INTO agent_plan_decisions (decision_id, run_id, username, session_id, "
            "action, reviewed_version, comment, outcome, start_seq, turn_uuid, created_at) "
            "VALUES ({d:UUID}, {r:UUID}, {u:String}, {s:String}, {a:String}, {v:UInt64}, "
            "{c:String}, 'accepted', {q:UInt32}, '', now64(3))",
            parameters={"d": decision_id, "r": plan_run_id, "u": case.username,
                        "s": case.session_id, "a": action, "v": version, "c": comment,
                        "q": seq + 1})
    return activities.AgentRunInput(
        run_id=str(uuid.uuid4()), username=case.username, session_id=case.session_id,
        kind="planner" if action == "reject" else "organizer", turn_seq=seq,
        start_seq=seq + 1, turn_uuid=str(uuid.uuid4()), allowed_collections=["testdata"],
        plan_run_id=plan_run_id, decision_id=decision_id)


async def _run_plan(client, queue, inp, workflow_id):
    handle = await client.start_workflow(
        workflows.AgentRun.run, inp, id=workflow_id, task_queue=queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
    return handle, await handle.result()


def _plan_input(case, plan_run_id):
    inp = case.input()
    inp.kind, inp.plan_run_id = "planner", plan_run_id
    return inp


def _verdict(verdict):
    return "Checked.\n```json\n" + json.dumps({"verdict": verdict, "defect_classes": []}) + "\n```"


def test_a_flat_plan_is_reviewed_rejected_approved_and_completed(monkeypatch):
    """`flat-plan`, `unbounded-rejection`, `review-idle` and `terminal-run`.

    Round 0 writes a flat plan and waits for review with no workflow open. A rejection
    starts round 1, which reads the comment. An approval starts the organizer, which
    executes and reviews the root section, and the plan run completes.
    """
    prid = str(uuid.uuid4())
    plan_id = plan_runs.plan_id_for(prid)
    root = agent_plans.root_node_id(plan_id)

    def script(request, n):
        opening = request["messages"][0]["content"]
        if request["kind"] == "planner":
            username, session = request["username"], request["session_id"]
            agent_plans.mutate(username, session, plan_id, "append_node", text=f"Task {n}")
            return _answer_frames(request, f"Orientation {n}.")
        if request["kind"] == "subagent":
            if request.get("purpose") == "review":
                return _answer_frames(request, _verdict("accept"))
            return _answer_frames(request, "Report on the section.")
        if not _is_continuation(request):
            assert opening.startswith("Run the approved plan, version")
            return _delegate_frames(request, [("x1", [dict(_briefing("do the tasks"),
                                                        plan_node_id=root,
                                                        purpose="execute")])])
        if sum(1 for m in request["messages"] if m.get("name") == "run_subagent") == 1:
            return _delegate_frames(request, [("x2", [dict(_briefing("review the tasks"),
                                                        plan_node_id=root,
                                                        purpose="review")])])
        return _answer_frames(request, "Final report.")

    async def body(client, case, stub, queue, titled):
        _, result = await _run_plan(client, queue, _plan_input(case, prid), f"plan-{prid}-r0")
        assert result == "completed"
        plan_run = agent_plans.read_plan_run(case.username, case.session_id, prid)
        assert (plan_run.state, plan_run.reviewed_version) == ("awaiting_review", 2)
        answer = next(r for r in case.chat_rows() if r[1] == "assistant")
        assert answer[2] == "Orientation 1."
        # `review-idle`: no workflow of the session is open while the plan waits.
        for row in agent_runs.read_turn_runs(case.username, case.session_id, case.turn_seq):
            described = await client.get_workflow_handle(row.workflow_id).describe()
            assert described.status != WorkflowExecutionStatus.RUNNING

        inp = _decide(case, prid, "reject", 2, comment="Add a second task.")
        _, result = await _run_plan(client, queue, inp, f"plan-{prid}-r1")
        plan_run = agent_plans.read_plan_run(case.username, case.session_id, prid)
        assert (result, plan_run.state, plan_run.review_round, plan_run.reviewed_version) == (
            "completed", "awaiting_review", 1, 3)
        opening = agent_runs.read_messages(case.username, case.session_id, inp.run_id)[0]
        assert opening.content == "The person rejected plan version 2. Their comment:\n\nAdd a second task."

        inp = _decide(case, prid, "approve", 3)
        await _run_plan(client, queue, inp, f"plan-{prid}-o1")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            plan_run = agent_plans.read_plan_run(case.username, case.session_id, prid)
            if agent_plans.is_terminal(plan_run):
                break
            await asyncio.sleep(0.5)
        assert (plan_run.state, plan_run.approved_version) == ("completed", 3)
        [section] = json.loads(plan_run.sections_json)
        assert (section["node_id"], section["tasks"], section["failed"]) == (root, 2, False)
        kinds = sorted(d.kind for d in agent_plans.read_documents(
            case.username, case.session_id, prid))
        assert kinds == ["final", "prompt", "prompt", "report", "review"]
        rows = agent_runs.read_turn_runs(case.username, case.session_id, inp.turn_seq)
        assert rows and all(agent_runs.is_terminal(r) for r in rows)
        final = [r for r in case.chat_rows() if r[1] == "assistant"][-1]
        assert final[2] == "Final report."
        # Each organizer continuation reads the section states beside the reports.
        steps = [json.loads(r["messages"][-1]["content"]) for r in stub.requests
                 if r["kind"] == "organizer" and _is_continuation(r)]
        assert [[(s["node_id"], s["review"], s["failed"]) for s in step["sections"]]
                for step in steps] == [[(root, "", True)], [(root, "accept", False)]]

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_stop_after_an_approval_closes_the_organizer_in_open_run(monkeypatch):
    """`cancel_plan` in `awaiting_review` after an accepted approval whose run has not opened
    writes the stop row at the decision's turn and no plan state. The organizer then closes
    in `open_run`: it ends `cancelled`, no child row exists, the plan run ends `cancelled`,
    and the transcript ends with the stop row."""
    prid = str(uuid.uuid4())
    plan_id = plan_runs.plan_id_for(prid)

    def script(request, n):
        if request["kind"] == "planner":
            agent_plans.mutate(request["username"], request["session_id"], plan_id,
                               "append_node", text="The only task")
            return _answer_frames(request, "Orientation.")
        raise AssertionError("no agent call after the stop")

    async def body(client, case, stub, queue, titled):
        await _run_plan(client, queue, _plan_input(case, prid), f"plan-{prid}-r0")
        inp = _decide(case, prid, "approve", 2)
        # What `cancel_plan` writes for an accepted decision whose run has not opened.
        agent_runs.write_turn_stop(case.username, case.session_id, inp.start_seq - 1)
        _, result = await _run_plan(client, queue, inp, f"plan-{prid}-o1")
        assert result == "closed"
        organizer = agent_runs.read_run(case.username, case.session_id, inp.run_id)
        assert organizer.state == "cancelled"
        rows = agent_runs.read_turn_runs(case.username, case.session_id, inp.turn_seq)
        assert [r for r in rows if r.parent_run_id] == []
        plan_run = agent_plans.read_plan_run(case.username, case.session_id, prid)
        assert plan_run.state == "cancelled"
        assert len(stub.requests) == 1
        chat = case.chat_rows()
        assert chat[-2][:3] == (inp.turn_seq, "user", "Approved plan version 2.")
        assert chat[-1][:3] == (inp.start_seq, "error", "This turn was stopped.")

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_third_correction_of_one_section_is_refused(monkeypatch):
    """`correction-bound`: the delegation refuses a third correction of one section, and a
    section with no accepting review is listed as failed in the final report."""
    prid = str(uuid.uuid4())
    plan_id = plan_runs.plan_id_for(prid)
    root = agent_plans.root_node_id(plan_id)

    def script(request, n):
        if request["kind"] == "planner":
            agent_plans.mutate(request["username"], request["session_id"], plan_id,
                               "append_node", text="The only task")
            return _answer_frames(request, "Orientation.")
        if request["kind"] == "subagent":
            return _answer_frames(request, "Corrected.")
        if _is_continuation(request):
            return _answer_frames(request, "Final report.")
        fixes = [dict(_briefing(f"fix {i}"), plan_node_id=root, purpose="correct")
                 for i in range(3)]
        return _delegate_frames(request, [("c1", fixes)])

    async def body(client, case, stub, queue, titled):
        await _run_plan(client, queue, _plan_input(case, prid), f"plan-{prid}-r0")
        inp = _decide(case, prid, "approve", 2)
        await _run_plan(client, queue, inp, f"plan-{prid}-o1")
        organizer = await _wait_terminal(case, inp.run_id)
        refused = json.loads(organizer.refused_json)
        assert [(r["objective"], r["reason"]) for r in refused] == [
            ("fix 2", "correction_limit")]
        children = [r for r in agent_runs.read_turn_runs(case.username, case.session_id,
                                                         inp.turn_seq) if r.depth == 1]
        assert sorted((c.purpose, c.plan_node_id) for c in children) == [
            ("correct", root), ("correct", root)]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            plan_run = agent_plans.read_plan_run(case.username, case.session_id, prid)
            if agent_plans.is_terminal(plan_run):
                break
            await asyncio.sleep(0.5)
        assert plan_run.state == "completed"
        final = [r for r in case.chat_rows() if r[1] == "assistant"][-1][2]
        assert final.startswith("Final report.") and "## Failed sections" in final

    asyncio.run(_run_case(monkeypatch, script, body))


def test_a_planner_with_no_section_gets_one_more_round_then_fails(monkeypatch):
    """A planner that answers twice with no tree change gets one nag row with the note, and
    then the run and the plan run fail with the error text."""
    prid = str(uuid.uuid4())

    def script(request, n):
        return _answer_frames(request, "done")

    async def body(client, case, stub, queue, titled):
        handle = await client.start_workflow(
            workflows.AgentRun.run, _plan_input(case, prid), id=f"plan-{prid}-r0",
            task_queue=queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
        with pytest.raises(WorkflowFailureError):
            await handle.result()
        assert len(stub.requests) == 2
        chat = case.chat_rows()
        nags = [r for r in chat if r[1] == "nag"]
        assert [r[2] for r in nags] == [workflows.PLANNER_NO_SECTION_NOTE]
        row = case.run_row()
        assert row.state == "failed" and row.error == workflows.PLANNER_NO_SECTION_ERROR
        assert workflows.PLANNER_NO_SECTION_ERROR in chat[-1][2]
        plan_run = agent_plans.read_plan_run(case.username, case.session_id, prid)
        assert plan_run.state == "failed"

    asyncio.run(_run_case(monkeypatch, script, body))
