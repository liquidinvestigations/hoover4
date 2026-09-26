"""Temporal workflows for AI agent turns.

`AgentRun` owns one agent run. A chat turn is one `AgentRun`, and a deep-research request
is a plan run whose planner and organizer runs are each one `AgentRun`. The state lives in
the `agent_runs` and `agent_run_messages` tables, so the workflow input and results hold
ids only.

`AgentRun` runs on `chat-queue`. Its agent call runs on the queue in its row,
`chat-model-queue` for a chat turn and `research-queue` for a plan run. None of these is
the ingestion queue. An ingestion backlog delaying a person at a screen is the failure a
shared queue guarantees, and these three queues make it impossible.
"""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, CancelledError, WorkflowAlreadyStartedError
from temporalio.workflow import ActivityCancellationType, ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from database import chat_todos
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_agent import nagging
    from tasks.P_agent.model_timeouts import TIMEOUTS
    from tasks.P_agent.activities import (
        AgentRunInput,
        AppendNagParams,
        Continuation,
        OpenedRun,
        ReadTodoParams,
        RunAgentParams,
        RunRef,
        RunSummary,
        WriteEndingParams,
        append_nag,
        continue_run,
        fan_in,
        open_run,
        read_chat_todo,
        run_agent,
        summarize_if_first_turn,
        write_ending,
    )


#: The queue `AgentRun` is dispatched to, and the queue that writes the transcript,
#: reads the todo list and titles the session. Named here so the worker that polls it
#: and the caller that addresses it cannot drift: a workflow addressed to a queue nothing
#: is polling waits for ever with no error anywhere, which presents as chat hanging.
#:
#: **Mirrored in `website/backend/src/api/chat/mod.rs`.** The three names move in the
#: same patch or not at all.
CHAT_TASK_QUEUE = "chat-queue"

#: The queue a chat turn's `run_agent` goes to. One slot is one agent run in flight, and
#: one run makes up to `AGENT_MAX_TOOL_TURNS` model calls in sequence. Each sub-agent runs
#: its own `run_agent` on its parent's queue, so a delegated turn takes one slot for each
#: running sub-agent.
CHAT_MODEL_TASK_QUEUE = "chat-model-queue"

#: The queue of the agent activity of a plan run: its planner and organizer runs and their
#: sub-agents. Its own slots, outside the chat-model slots, so a research run cannot
#: take a chat turn's slot and an ingestion backlog cannot sit in front of it.
RESEARCH_TASK_QUEUE = "research-queue"

#: How long the chat agent activity may go without proving it is alive before Temporal
#: reschedules it on another worker.
#:
#: **This number and the website's `CHAT_STREAM_STALL_SECONDS` are one pair and must be
#: read together.** This one is how long a dead worker goes unnoticed; that one is how
#: long the page waits before telling the user the turn is dead. The page must never give
#: up first, because its advice is "ask again to retry" and a user who follows it while a
#: reschedule is still coming gets the same answer twice, from two workflows. So the
#: stall window is deliberately the larger of the two, by a wide margin: 60 s here
#: against a 180 s default there.
#:
#: `run_agent` carries a heartbeat pump that beats every `RUN_AGENT_HEARTBEAT_SECONDS`
#: (5 s) for as long as the body runs, so the agent's own latency never enters this
#: budget. Lowering it further starts trading
#: against a loaded box missing beats; raising it is worse than it looks, because the
#: deadline is also how long a wedged slot stays occupied (see `tasks.heartbeat`).
CHAT_AGENT_HEARTBEAT_TIMEOUT = timedelta(seconds=60)

def _was_cancelled(exc: BaseException) -> bool:
    """Whether this failure is a cancellation wearing another exception's clothes.

    Temporal wraps a cancelled activity in an `ActivityError` and hands that to the
    workflow, so the cancellation is only visible down the `__cause__` chain. The chain is
    walked rather than the top type inspected, because how deeply it is wrapped is the
    SDK's business and not a thing to depend on.
    """
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, (asyncio.CancelledError, CancelledError)):
            return True
        seen = seen.__cause__
    return False


#: The start-to-close timeout of `run_agent` for a run with no plan, from
#: `chat_run_timeout_seconds` (900 s when the key is empty). It is a budget bound: it follows
#: the measured speed of the model server, so a slow model call that is alive is not failed.
#: A dead worker is found by the heartbeat, which stays fixed.
RUN_AGENT_TIMEOUT = TIMEOUTS.chat_run
#: The start-to-close and heartbeat timeouts of `run_agent` for a run of a plan, of any
#: kind. A research round runs longer than a chat turn and nobody waits at the screen. The
#: start-to-close timeout comes from `plan_run_timeout_seconds` (2,400 s when the key is
#: empty).
PLAN_RUN_AGENT_TIMEOUT = TIMEOUTS.plan_run
PLAN_RUN_AGENT_HEARTBEAT_TIMEOUT = timedelta(minutes=10)

#: Nothing in an `AgentRun` input or result is text. The largest result, a `run_agent`
#: summary with five children, stays under this bound.
AGENT_RUN_PAYLOAD_BYTES = 4096


@workflow.defn
class AgentRun:
    """Own one agent run, from its opening message to its terminal state.

    A chat turn is one `AgentRun`, started by the website on `chat-queue`. The workflow
    input holds ids and settings only. Every activity reads the run row and the thread from
    `agent_runs` and `agent_run_messages`, so a retry reads the same state and no answer,
    tool result or briefing crosses a Temporal payload.

    The run uses no Signal, no Update and no continue-as-new, and it never waits for a
    person. A stop cancels the workflow. The cancellation reaches the workflow as a
    `CancelledError`, or as an `ActivityError` that wraps it, and both write the
    `cancelled` ending. A workflow that starts after a stop closes in `open_run`.

    **The nag loop runs here** for a chat lead, with the rules of `tasks.P_agent.nagging`.
    The two counters are row columns, so they outlive a worker restart.

    The agent activity goes to the queue in the row, `chat-model-queue` for a chat lead.
    The short activities run on `chat-queue`.

    **Delegation.** A run that stops at `run_subagent` ends as `delegated` with its row in
    `waiting_for_children`. It starts one abandoned child `AgentRun` for each accepted
    briefing, and returns. When a run ends, `fan_in` continues its parent once the last
    run of its batch is terminal, and this workflow starts the continuation. A run with no
    accepted briefing is continued at once through `continue_run`. Every start rejects a
    duplicate workflow id, and a refused duplicate counts as started, because the run it
    names exists.
    """

    def __init__(self) -> None:
        #: The todo snapshot taken when the last nag was written, to compare against.
        self._todo_before_nag: dict | None = None

    @workflow.run
    async def run(self, inp: AgentRunInput) -> str:
        opened: OpenedRun = await workflow.execute_activity(
            open_run,
            inp,
            start_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        if opened.state == "closed":
            if opened.continuation_run_id:
                await start_run(self._settings(inp, opened.continuation_run_id),
                                f"run-{opened.continuation_run_id}")
            return "closed"
        try:
            summary = await self._rounds(inp, opened)
        except asyncio.CancelledError:
            await asyncio.shield(self._finish(inp, "cancelled"))
            raise
        except ActivityError as exc:
            # A stop arrives here as well: cancelling a workflow cancels the activity it
            # waits on, and Temporal reports that as an `ActivityError` around the
            # cancellation.
            if _was_cancelled(exc):
                await asyncio.shield(self._finish(inp, "cancelled"))
            else:
                await self._finish(inp, "failed", _cause_text(exc))
            raise
        # Outside the try: a failure below cannot rewrite the state of this run.
        if summary.outcome == "closed":
            return "closed"
        if summary.outcome == "delegated":
            if summary.children:
                # A stop here must not leave a child row with no workflow, so the starts
                # finish before the cancellation goes on. Each started child closes in
                # `open_run`, because the turn has a stop row.
                starts = asyncio.ensure_future(self._start_children(inp, summary.children))
                try:
                    await asyncio.shield(starts)
                except asyncio.CancelledError:
                    await starts
                    raise
            else:
                continuation: Continuation = await workflow.execute_activity(
                    continue_run,
                    RunRef(run_id=inp.run_id, username=inp.username, session_id=inp.session_id),
                    start_to_close_timeout=timedelta(seconds=30),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    task_queue=CHAT_TASK_QUEUE,
                )
                if continuation.run_id:
                    await start_run(self._settings(inp, continuation.run_id),
                                    continuation.workflow_id)
            return "delegated"
        await self._finish(inp, "completed")
        if opened.is_chat_lead:
            await self._summarize_if_first_turn(inp)
        return "completed"

    async def _start_children(self, inp: AgentRunInput, children: list[str]) -> None:
        for child in children:
            await start_run(self._settings(inp, child, "subagent"), f"run-{child}")

    async def _run_agent(self, inp: AgentRunInput, opened: OpenedRun) -> RunSummary:
        """One `run_agent` attempt chain, which is the only writer of the run while it runs.

        A stop waits for the attempt to end (`WAIT_CANCELLATION_COMPLETED`), so
        `write_ending` never runs beside an attempt that still writes rows. An attempt can
        end without an error after the stop arrived. The pending cancellation then raises
        here, so the run still ends as `cancelled`. Children that such an attempt wrote
        have no workflow, and the `cancelled` ending of `write_ending` ends them.
        """
        summary = await workflow.execute_activity(
            run_agent,
            RunAgentParams(
                run_id=inp.run_id,
                username=inp.username,
                session_id=inp.session_id,
                turn_uuid=inp.turn_uuid,
                allowed_collections=list(inp.allowed_collections or []),
                llm_model=inp.llm_model,
                internet_tools=inp.internet_tools,
            ),
            start_to_close_timeout=(PLAN_RUN_AGENT_TIMEOUT if opened.plan
                                    else RUN_AGENT_TIMEOUT),
            heartbeat_timeout=(PLAN_RUN_AGENT_HEARTBEAT_TIMEOUT if opened.plan
                               else CHAT_AGENT_HEARTBEAT_TIMEOUT),
            # The wait for a free slot on the model queue, from `agent_queue_wait_seconds`.
            # None sets no limit. Temporal does not retry this timeout, so a run that waits
            # past it fails and `write_ending` records the failure.
            schedule_to_start_timeout=TIMEOUTS.queue_wait,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=opened.queue,
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError()
        return summary

    async def _rounds(self, inp: AgentRunInput, opened: OpenedRun) -> RunSummary:
        summary = await self._run_agent(inp, opened)
        nags_this_turn = opened.nags_this_turn
        nags_without_progress = opened.nags_without_progress
        while summary.outcome == "answered" and opened.is_chat_lead:
            todo = await self._read_todo(inp)
            # Progress is the store's question, asked of the two snapshots either side of
            # the last nag. A run with no earlier snapshot resets no counter.
            if self._todo_before_nag is not None and chat_todos.is_material_change(
                self._todo_before_nag, todo
            ):
                nags_without_progress = 0
            stop = nagging.stop_reason(todo, nags_without_progress, nags_this_turn)
            if stop:
                if stop != "resolved":
                    await self._append_nag(inp, summary, stop, starts_round=False)
                break
            nags_this_turn += 1
            nags_without_progress += 1
            self._todo_before_nag = todo
            await self._append_nag(
                inp, summary, nagging.nag_message(todo, nags_without_progress),
                starts_round=True,
                nags_this_turn=nags_this_turn,
                nags_without_progress=nags_without_progress,
                # Extended, never reset: five nags on a reset budget would be sixty tool
                # turns, and a nag with no budget left cannot do anything at all.
                extra_tool_turns=nags_this_turn * nagging.NAG_TOOL_TURN_INCREMENT,
            )
            summary = await self._run_agent(inp, opened)
        return summary

    async def _append_nag(self, inp: AgentRunInput, summary: RunSummary, message: str,
                          starts_round: bool, **counters) -> int:
        return await workflow.execute_activity(
            append_nag,
            AppendNagParams(
                run_id=inp.run_id,
                username=inp.username,
                session_id=inp.session_id,
                seq=summary.next_seq,
                idx=summary.next_idx,
                message=message,
                starts_round=starts_round,
                **counters,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )

    async def _read_todo(self, inp: AgentRunInput) -> dict:
        """This session's todo list, as the nag loop's two questions need it."""
        raw = await workflow.execute_activity(
            read_chat_todo,
            ReadTodoParams(username=inp.username, session_id=inp.session_id),
            start_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        return json.loads(raw)

    async def _finish(self, inp: AgentRunInput, state: str, error: str = "") -> None:
        await workflow.execute_activity(
            write_ending,
            WriteEndingParams(
                run_id=inp.run_id,
                username=inp.username,
                session_id=inp.session_id,
                state=state,
                error=error,
                turn_uuid=inp.turn_uuid,
            ),
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        continuation: Continuation = await workflow.execute_activity(
            fan_in,
            RunRef(run_id=inp.run_id, username=inp.username, session_id=inp.session_id),
            start_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        if continuation.run_id:
            await start_run(self._settings(inp, continuation.run_id), continuation.workflow_id)

    @staticmethod
    def _settings(inp: AgentRunInput, run_id: str, kind: str = "") -> AgentRunInput:
        """The input of a child or a continuation: its run id, and the settings that the
        row has no columns for (the collections, the model, the internet switch and the
        turn uuid), copied from this run's input. The row holds the rest."""
        return replace(inp, run_id=run_id, kind=kind or inp.kind, plan_run_id="",
                       decision_id="")

    async def _summarize_if_first_turn(self, inp: AgentRunInput) -> None:
        """Name the conversation after its first turn. It can never fail the run.

        One attempt, a short timeout, and every exception caught here. The answer is
        already written, so a summariser that is down is worth the provisional title and
        nothing else. A cancellation still propagates, because it is a `BaseException`.
        """
        try:
            await workflow.execute_activity(
                summarize_if_first_turn,
                RunRef(run_id=inp.run_id, username=inp.username, session_id=inp.session_id),
                start_to_close_timeout=TIMEOUTS.title_activity,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
                task_queue=CHAT_TASK_QUEUE,
            )
        except Exception:  # noqa: BLE001 - a title is never worth an answer
            workflow.logger.warning(
                "could not title session %s, keeping the provisional title", inp.session_id
            )


async def start_run(child_input: AgentRunInput, workflow_id: str) -> bool:
    """Start an abandoned `AgentRun` child. Returns false when Temporal refused a duplicate
    workflow id, which counts as started, because the run it names exists.

    The child outlives this workflow (`ParentClosePolicy.ABANDON`), so a parent that ends
    right after the start does not cancel it.
    """
    try:
        await workflow.start_child_workflow(
            AgentRun.run,
            child_input,
            id=workflow_id,
            task_queue=CHAT_TASK_QUEUE,
            parent_close_policy=ParentClosePolicy.ABANDON,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        workflow.logger.info("run %s is already started", workflow_id)
        return False
    return True


def _cause_text(exc: BaseException) -> str:
    """The innermost message of a failure, for the ending row a person reads."""
    seen: BaseException | None = exc
    text = str(exc)
    while seen is not None:
        if str(seen):
            text = str(seen)
        seen = seen.__cause__
    return text
