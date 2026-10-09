"""`AgentRun` with its policy hooks, on Temporal's time-skipping test server.

The activities are fakes with the real names and queues, so these tests read the order in
which the workflow schedules them, the stop of a hook, and the replay of a recorded history.
They need the test server, which the SDK downloads on first use.
"""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from tasks.P_agent.activities import AgentRunInput, CallRef, OpenedRun, RunRef, WriteEndingParams
from tasks.P_agent.control_steps import ControlOutcome, ControlParams
from tasks.P_agent.steps import (
    AskedAnswerParams, EmptyNoteParams, IncompleteParams, ModelStepParams, ModelStepResult,
    StepFailure, ToolCallParams, ToolCallResult,
)
from tasks.P_agent.workflows import (
    AGENT_TOOL_TASK_QUEUE, CHAT_MODEL_TASK_QUEUE, CHAT_TASK_QUEUE, AgentRun,
)

pytestmark = pytest.mark.integration

LOG: list[str] = []
SCRIPT: dict[str, list] = {}


def _call(ai_idx, position, call_id, name, share_key="", kind="parallel", retry=True):
    return CallRef(ai_idx=ai_idx, position=position, call_id=call_id, name=name, kind=kind,
                   seq=10 + position, retry=retry, share_key=share_key)


@activity.defn(name="open_run")
async def open_run(inp: AgentRunInput) -> OpenedRun:
    LOG.append("open_run")
    return OpenedRun(state="running", model_steps=0)


@activity.defn(name="control_event")
async def control_event(params: ControlParams) -> ControlOutcome:
    LOG.append(f"control:{params.hook}:{params.anchor_idx}:{params.draft_kind}")
    outcome = SCRIPT["control"].pop(0)
    if outcome == "block":
        while True:
            activity.heartbeat()
            await asyncio.sleep(0.2)
    return outcome


@activity.defn(name="model_step")
async def model_step(params: ModelStepParams) -> ModelStepResult:
    LOG.append(f"model:{params.step_no}")
    return SCRIPT["model"].pop(0)


@activity.defn(name="tool_call")
async def tool_call(params: ToolCallParams) -> ToolCallResult:
    shared = f"<{params.shared_from.call_id}" if params.shared_from else ""
    LOG.append(f"tool:{params.call.call_id}{shared}")
    await asyncio.sleep(0.05 if params.call.position == 0 else 0)
    return ToolCallResult(status="ok")


@activity.defn(name="write_followups")
async def write_followups(ref: RunRef) -> None:
    LOG.append("followups")


@activity.defn(name="write_ending")
async def write_ending(params: WriteEndingParams) -> None:
    LOG.append(f"ending:{params.state}")


@activity.defn(name="summarize_if_first_turn")
async def summarize_if_first_turn(ref: RunRef) -> str:
    LOG.append("title")
    return ""


@activity.defn(name="record_step_failure")
async def record_step_failure(params: StepFailure) -> None:
    LOG.append("failure")


@activity.defn(name="write_asked_answer")
async def write_asked_answer(params: AskedAnswerParams) -> int:
    return 0


@activity.defn(name="write_empty_note")
async def write_empty_note(params: EmptyNoteParams) -> int:
    return 0


@activity.defn(name="write_incomplete")
async def write_incomplete(params: IncompleteParams) -> int:
    return 0


def _workers(client, executor):
    return [
        Worker(client, task_queue=CHAT_TASK_QUEUE, workflows=[AgentRun],
               activities=[open_run, control_event, write_ending, summarize_if_first_turn,
                           record_step_failure, write_asked_answer, write_empty_note,
                           write_incomplete], activity_executor=executor),
        Worker(client, task_queue=CHAT_MODEL_TASK_QUEUE, activities=[model_step, write_followups],
               activity_executor=executor),
        Worker(client, task_queue=AGENT_TOOL_TASK_QUEUE, activities=[tool_call],
               activity_executor=executor),
    ]


def _input():
    return AgentRunInput(run_id=str(uuid.uuid4()), username="u", session_id="s", turn_seq=1,
                         start_seq=2, internet_tools=True)


async def _run_with(env, scenario):
    with ThreadPoolExecutor(max_workers=8) as executor:
        workers = _workers(env.client, executor)
        for w in workers:
            asyncio.ensure_future(w.run())
        try:
            return await scenario()
        finally:
            await asyncio.gather(*(w.shutdown() for w in workers), return_exceptions=True)


def test_hooks_run_policy_batches_before_the_next_model_step_and_replay():
    LOG.clear()
    SCRIPT.update(
        control=[
            ControlOutcome(calls=[_call(1, 0, "ctl-a-0", "read_skill")]),     # turn_started
            ControlOutcome(),                                                 # after the skill batch
            ControlOutcome(calls=[_call(5, 0, "ctl-b-0", "read_page")]),      # after the search batch
            ControlOutcome(),                                                 # after the policy reads
            ControlOutcome(round=True),                                       # first draft
            ControlOutcome(),                                                 # repaired draft
        ],
        model=[
            ModelStepResult(outcome="calls", calls=[
                _call(3, 0, "m-0", "web_search", share_key="k1"),
                _call(3, 1, "m-1", "web_search", share_key="k1"),
                _call(3, 2, "m-2", "search_collections", share_key="k2")]),
            ModelStepResult(outcome="answered", next_seq=20, next_idx=9),
            ModelStepResult(outcome="answered", next_seq=22, next_idx=11),
        ])

    async def main():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async def scenario():
                inp = _input()
                handle = await env.client.start_workflow(AgentRun.run, inp, id=inp.run_id,
                                                         task_queue=CHAT_TASK_QUEUE)
                assert await handle.result() == "completed"
                return await handle.fetch_history()
            history = await _run_with(env, scenario)
            await Replayer(workflows=[AgentRun]).replay_workflow(history)

    asyncio.run(main())
    assert LOG[:4] == ["open_run", "control:turn_started:0:", "tool:ctl-a-0",
                       "control:tool_batch_completed:1:"]
    assert LOG[4] == "model:1"
    batch = LOG[5:8]
    assert set(batch) == {"tool:m-0", "tool:m-1<m-0", "tool:m-2"}
    assert batch.index("tool:m-0") < batch.index("tool:m-1<m-0")
    assert LOG[8:] == ["control:tool_batch_completed:3:", "tool:ctl-b-0",
                       "control:tool_batch_completed:5:", "model:2",
                       "control:answer_drafted:-1:answer", "model:3",
                       "control:answer_drafted:-1:answer", "followups", "ending:completed",
                       "title"]


def test_a_stop_during_a_hook_ends_the_run_with_no_model_step():
    LOG.clear()
    SCRIPT.update(control=[ControlOutcome(), "block"],
                  model=[ModelStepResult(outcome="answered", next_seq=9, next_idx=3)])

    async def main():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async def scenario():
                inp = _input()
                handle = await env.client.start_workflow(AgentRun.run, inp, id=inp.run_id,
                                                         task_queue=CHAT_TASK_QUEUE)
                for _ in range(200):
                    if LOG and LOG[-1].startswith("control:answer_drafted"):
                        break
                    await asyncio.sleep(0.05)
                await handle.cancel()
                with pytest.raises(WorkflowFailureError):
                    await handle.result()
            await _run_with(env, scenario)

    asyncio.run(main())
    assert LOG[-2:] == ["control:answer_drafted:-1:answer", "ending:cancelled"]
    assert LOG.count("model:1") == 1 and "model:2" not in LOG and "followups" not in LOG


def test_a_restarted_worker_resumes_after_the_completed_hooks():
    LOG.clear()
    SCRIPT.update(control=[ControlOutcome(), ControlOutcome()],
                  model=[ModelStepResult(outcome="answered", next_seq=9, next_idx=3)])

    async def main():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            inp = _input()
            with ThreadPoolExecutor(max_workers=8) as executor:
                # The first worker serves no model queue, so the run waits at its first
                # model step with no activity in flight. It keeps no workflow in its cache,
                # so the next workflow task goes to the shared queue.
                first = Worker(env.client, task_queue=CHAT_TASK_QUEUE, workflows=[AgentRun],
                               activities=[open_run, control_event], activity_executor=executor,
                               max_cached_workflows=0)
                task = asyncio.ensure_future(first.run())
                handle = await env.client.start_workflow(AgentRun.run, inp, id=inp.run_id,
                                                         task_queue=CHAT_TASK_QUEUE)
                for _ in range(200):
                    if "control:turn_started:0:" in LOG:
                        break
                    await asyncio.sleep(0.05)
                await asyncio.sleep(0.5)
                await first.shutdown()
                await task

            async def second():
                return await handle.result()
            # New workers replay the history and resume at the model step.
            assert await _run_with(env, second) == "completed"

    asyncio.run(main())
    assert LOG.count("control:turn_started:0:") == 1
    assert LOG.count("open_run") == 1
    assert LOG == ["open_run", "control:turn_started:0:", "model:1",
                   "control:answer_drafted:-1:answer", "followups", "ending:completed", "title"]


def test_progress_ends_through_the_incomplete_activity_without_another_model_step():
    LOG.clear()
    SCRIPT.update(control=[ControlOutcome(), ControlOutcome(end_turn=True)],
                  model=[ModelStepResult(outcome="tools", calls=[_call(1, 0, "search", "search_collections")], next_seq=9, next_idx=3)])
    async def main():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async def scenario():
                inp = _input()
                return await env.client.execute_workflow(AgentRun.run, inp, id=inp.run_id, task_queue=CHAT_TASK_QUEUE)
            assert await _run_with(env, scenario) == "completed"
    asyncio.run(main())
    assert LOG.count("model:1") == 1 and "model:2" not in LOG
    assert LOG[-2:] == ["ending:completed", "title"]
