"""Temporal workflows for AI agent turns.

`AgentRun` owns one agent run. A chat turn is one `AgentRun`, and its state lives in the
`agent_runs` and `agent_run_messages` tables, so the workflow input and results hold ids
only. `ResearchTask` owns a deep research run and keeps the older shape: one agent call
and a payload that it writes into the transcript.

`AgentRun` runs on `chat-queue`. Its agent call runs on the queue in its row,
`chat-model-queue` for a chat turn. Deep research runs on `research-queue`. None of these is the ingestion queue. An ingestion backlog
delaying a person at a screen is the failure a shared queue guarantees, and these three
queues make it impossible.
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
    from tasks.P_agent.activities import (
        AgentRunInput,
        AppendNagParams,
        Continuation,
        OpenedRun,
        ReadTodoParams,
        ResearchTaskParams,
        RunAgentParams,
        RunRef,
        RunSummary,
        WriteEndingParams,
        WriteResultParams,
        append_nag,
        continue_run,
        fan_in,
        open_run,
        read_chat_todo,
        run_agent,
        run_research_agent,
        summarize_if_first_turn,
        write_chat_message,
        write_ending,
    )
    from tasks.P_agent.trajectory import pair_tool_calls


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

#: The queue `ResearchTask` is dispatched to. Four slots, outside the twelve chat-model
#: slots, so a research run cannot take a chat turn's slot and an ingestion backlog
#: cannot sit in front of it.
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
#: 60 s is four missed beats -- `run_agent` carries `@with_heartbeat`, whose
#: pump beats every `HEARTBEAT_INTERVAL` (15 s) for as long as the body runs, so the
#: agent's own latency never enters this budget. Lowering it further starts trading
#: against a loaded box missing beats; raising it is worse than it looks, because the
#: deadline is also how long a wedged slot stays occupied (see `tasks.heartbeat`).
CHAT_AGENT_HEARTBEAT_TIMEOUT = timedelta(seconds=60)

async def _write_row(params, seq: int, role: str, content: str, **extra) -> None:
    """Append one finished transcript row.

    Short and retryable: the insert is keyed on `(username, session_id, seq)`, so a retry
    replaces the row rather than appending a second one.

    The timeout arguments and `task_queue` are spelled out rather than unpacked from a
    shared dict. `test_every_execute_activity_declares_a_heartbeat_timeout` and
    `test_agent_activities_declare_their_task_queue` read the call sites as source, so a
    dict would hide both from the checks that exist to find a wedged activity or a
    queue nobody polls.
    """
    await workflow.execute_activity(
        write_chat_message,
        WriteResultParams(
            username=params.username,
            session_id=params.session_id,
            seq=seq,
            role=role,
            content=content,
            **extra,
        ),
        start_to_close_timeout=timedelta(minutes=2),
        heartbeat_timeout=HEARTBEAT_TIMEOUT,
        retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        task_queue=CHAT_TASK_QUEUE,
    )


async def _write_payload(
    params, payload: dict, empty_answer: str, start_seq: int
) -> tuple[str, int, int]:
    """Write a finished research payload into the transcript. Return the answer, the next
    free `seq`, and the peak context of the run.

    Only `ResearchTask` calls it. It writes the same row shapes that `run_agent` writes for
    a chat turn, so the page renders a research transcript and a chat transcript the same
    way.
    """
    seq = start_seq

    # Pair start/end events into one row each, with the arguments, the result and any
    # documents surfaced, so every tool call renders as one card.
    for call in pair_tool_calls(payload.get("tool_calls", [])):
        await _write_row(
            params, seq, "tool", call.summary,
            tool_name=call.tool_name,
            tool_input=call.tool_input,
            tool_output=call.tool_output,
            doc_refs=call.doc_refs,
        )
        seq += 1

    # Token counts as the provider billed them. A missing key is 0, which every reader
    # renders as unknown -- an agent that reported no usage must not look free.
    usage = payload.get("usage") or {}
    peak = int(usage.get("peak_context_tokens") or 0)
    answer = payload.get("answer") or empty_answer
    await _write_row(
        params, seq, "assistant", answer,
        # The agent separates its narration from its answer; carrying the narration
        # through as `reasoning` is what keeps the disclosure working.
        reasoning=payload.get("reasoning") or "",
        model=payload.get("model") or "",
        context_tokens=int(usage.get("context_tokens") or 0),
        peak_context_tokens=peak,
        context_window=int(usage.get("context_window") or 0),
    )
    return answer, seq + 1, peak


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


#: The start-to-close timeout of `run_agent` for a run with no plan. A chat turn a person is
#: watching that has produced nothing for a quarter of an hour is wedged, and failing it
#: returns the answer slot to them.
RUN_AGENT_TIMEOUT = timedelta(seconds=900)

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
                for child in summary.children:
                    await start_run(self._settings(inp, child, "subagent"), f"run-{child}")
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

    async def _run_agent(self, inp: AgentRunInput, opened: OpenedRun) -> RunSummary:
        """One `run_agent` attempt chain, which is the only writer of the run while it runs.

        A stop waits for the attempt to end (`WAIT_CANCELLATION_COMPLETED`), so
        `write_ending` never runs beside an attempt that still writes rows. An attempt can
        end without an error after the stop arrived. The pending cancellation then raises
        here, so the run still ends as `cancelled`. Children that such an attempt wrote
        have no workflow, and the agent run sweep ends them.
        """
        summary = await workflow.execute_activity(
            run_agent,
            RunAgentParams(
                run_id=inp.run_id,
                username=inp.username,
                session_id=inp.session_id,
                turn_uuid=inp.turn_uuid,
                allowed_collections=list(inp.allowed_collections),
                llm_model=inp.llm_model,
                internet_tools=inp.internet_tools,
            ),
            start_to_close_timeout=RUN_AGENT_TIMEOUT,
            heartbeat_timeout=CHAT_AGENT_HEARTBEAT_TIMEOUT,
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
                start_to_close_timeout=timedelta(seconds=90),
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


@workflow.defn
class ResearchTask:
    """Run the full research agent for one question and write the result into the chat.

    Split into two activities on purpose: the agent call is slow and retryable, while
    the write is fast and keyed, so a retried agent call cannot leave a half-written
    transcript behind.

    A failure is written into the transcript as an `error` row rather than left as a
    silently failed workflow. The user is looking at a chat window waiting for an
    answer, and "nothing ever appeared" is the one outcome that gives them nothing to
    act on.

    It runs on `research-queue` so an ingestion backlog cannot sit in front of it, and
    so its four slots sit outside the twelve chat-model slots.
    """

    @workflow.run
    async def run(self, params: "ResearchTaskParams") -> str:
        seq = params.start_seq
        try:
            raw = await workflow.execute_activity(
                run_research_agent,
                params,
                start_to_close_timeout=timedelta(seconds=2400),
                heartbeat_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
                task_queue=RESEARCH_TASK_QUEUE,
            )
        except Exception as e:  # noqa: BLE001 - recorded for the user, then re-raised
            await _write_row(
                params, seq, "error", f"The research task failed: {e}",
            )
            raise

        answer, _, _ = await _write_payload(
            params, json.loads(raw), "(the research agent returned an empty answer)", seq
        )
        return answer
