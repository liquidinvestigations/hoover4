"""Temporal workflows for AI agent turns.

`AgentRun` owns one agent run. A chat turn is one `AgentRun`, and a deep-research request
is a plan run whose planner and organizer runs are each one `AgentRun`. The state lives in
the `agent_runs` and `agent_run_messages` tables, so the workflow input and results hold
ids only.

`AgentRun` runs the agent loop on `chat-queue`. Each model call is one `model_step`
activity on the queue in its row, `chat-model-queue` for a chat turn and `research-queue`
for a plan run. Each tool call is one `tool_call` activity on `agent-tool-queue`. None of
these is the ingestion queue, so an ingestion backlog cannot delay a person at a screen.

**A change to `AgentRun` needs the drain.** A running `AgentRun` replays its history on
new code, and a history that does not match the new code fails as nondeterministic. No
workflow versioning exists, so a deploy that changes this workflow first stops every open
agent turn and cancels every running `AgentRun` (`tasks/Readme.md`).
"""

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import (
    ActivityError, ApplicationError, CancelledError, TimeoutError as TemporalTimeoutError,
    TimeoutType, WorkflowAlreadyStartedError,
)
from temporalio.workflow import ActivityCancellationType, ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from database import chat_todos
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_agent import nagging
    from tasks.P_agent.model_timeouts import (
        CONTINUE_AS_NEW_STEPS, HISTORY_EVENTS_PER_RUN, RUN_MODEL_STEPS,
        STEP_HEARTBEAT_TIMEOUT, TIMEOUTS, TOOL_CALL_TIMEOUT,
    )
    from tasks.P_agent.activities import (
        AgentRunInput,
        AppendNagParams,
        CallRef,
        Continuation,
        OpenedRun,
        ReadTodoParams,
        RunRef,
        RunSummary,
        WriteEndingParams,
        append_nag,
        continue_run,
        fan_in,
        open_run,
        read_chat_todo,
        summarize_if_first_turn,
        write_ending,
    )
    from tasks.P_agent.preload import PRELOAD_TIMEOUT, PreloadParams, preload_reads
    from tasks.P_agent.steps import (
        FoundDocumentsParams,
        ModelStepParams,
        ModelStepResult,
        RepeatNoteParams,
        StepFailure,
        StepRef,
        REPEAT_STEP_LIMIT,
        ToolCallParams,
        AskedAnswerParams,
        delegate_step,
        model_step,
        needs_citations,
        plan_has_sections,
        prepare_continuation,
        record_step_failure,
        runs_in_order,
        tool_call,
        write_asked_answer,
        write_found_documents,
        write_repeat_note,
    )


#: The queue `AgentRun` is dispatched to, and the queue of its short activities: open, nag,
#: ending, fan-in, delegation, todo read and title. Named here so the worker that polls it
#: and the caller that addresses it cannot drift: a workflow addressed to a queue nothing
#: is polling waits for ever with no error anywhere, which presents as chat hanging.
#:
#: **Mirrored in `website/backend/src/api/chat/mod.rs`.** The queue names move in the
#: same patch or not at all.
CHAT_TASK_QUEUE = "chat-queue"

#: The queue of the `model_step` activities of a chat turn and its sub-agents. One slot is
#: one model call in flight.
CHAT_MODEL_TASK_QUEUE = "chat-model-queue"

#: The queue of the `model_step` activities of a plan run: its planner and organizer runs
#: and their sub-agents. Its own slots, outside the chat model slots, so a research run
#: cannot take a chat turn's slot.
RESEARCH_TASK_QUEUE = "research-queue"

#: The queue of every `tool_call` activity, of chat turns and plan runs alike. One slot is
#: one tool call in flight. A delegation takes no tool slot.
AGENT_TOOL_TASK_QUEUE = "agent-tool-queue"

#: Nothing in an `AgentRun` input or result is text. A `RunSummary` with five children
#: stays under this bound. A `ModelStepResult` carries one `CallRef` for each call, so a
#: reply with more than about 12 calls passes it, and the payload guard limits still hold.
AGENT_RUN_PAYLOAD_BYTES = 4096

#: The note of the extra planner round, when the planner answered with no plan section.
PLANNER_NO_SECTION_NOTE = (
    "The plan has no section yet. A section is a node with at least one task under it, "
    "and the root counts. Read the tree with read_plan. Add each section with append_node "
    "and each of its tasks with append_child. Then answer with the orientation."
)

#: The error of a planner run that wrote no plan section after its extra round.
PLANNER_NO_SECTION_ERROR = ("The planner wrote no plan section, so the plan cannot run. Ask "
                            "for the research again.")

#: The limits of the short activities on `chat-queue`, except the ending and the title.
_SHORT_TIMEOUT = timedelta(seconds=30)


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


_TIMEOUT_CLASSES = {
    TimeoutType.SCHEDULE_TO_START: "schedule_to_start_timeout",
    TimeoutType.HEARTBEAT: "heartbeat_timeout",
    TimeoutType.START_TO_CLOSE: "start_to_close_timeout",
}


def _error_class(exc: BaseException) -> str:
    """The class of a step failure, from the `TimeoutError` type in its cause chain."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, TemporalTimeoutError):
            return _TIMEOUT_CLASSES.get(seen.type, "activity_error")
        seen = seen.__cause__
    return "activity_error"


def _failure_text(exc: BaseException) -> str:
    """The text of the `failed` ending. A model step that waited in its queue past the
    limit gets a sentence a person can read, in place of the Temporal timeout text."""
    if (isinstance(exc, ActivityError) and exc.activity_type == "model_step"
            and _error_class(exc) == "schedule_to_start_timeout"):
        seconds = int(TIMEOUTS.queue_wait.total_seconds()) if TIMEOUTS.queue_wait else 0
        return f"The model queue wait passed {seconds:,} s."
    return _cause_text(exc)


@workflow.defn
class AgentRun:
    """Own one agent run, from its opening message to its terminal state.

    A chat turn is one `AgentRun`, started by the website on `chat-queue`. The workflow
    input holds ids and settings only. Every activity reads the run row and the thread from
    `agent_runs` and `agent_run_messages`, so a retry reads the same state and no answer,
    tool result or briefing crosses a Temporal payload.

    **The loop.** A round runs the unanswered calls of the thread, then one `model_step`.
    A reply with calls gives the next calls. A reply with no call ends the round. The
    `ordered` calls and the calls to the plan tree and todo tools (`steps.runs_in_order`)
    run one after the other in the order of the reply, the other calls run at once beside
    them, and a `delegation` runs after both. After `RUN_MODEL_STEPS` model steps, one
    `final` step binds no tool and the run ends. A call that repeats earlier calls
    (`steps.repeat_sources`) gets a stored result and does not run, and the other calls of
    its reply run. When `REPEAT_STEP_LIMIT` model steps in a row hold only repeated calls
    and exempt reads, the exempt reads run and the run gets one repeat note, which counts
    as a nag. The second time, the run gets one `final` step. A sub-agent whose answer is
    empty gets one more `final` step (`steps.EMPTY_ANSWER_TEXT`), and when that answer is
    empty too, `write_found_documents` writes its result. The first `tools` reply of a
    thread with no text and no call gets `steps.EMPTY_REPLY_TEXT` as a nag, and one more
    model step. The workflow continues as new every
    `CONTINUE_AS_NEW_STEPS` model steps, or when its history passes
    `HISTORY_EVENTS_PER_RUN` events, and the new run resumes from the thread.

    **The run-start reads.** A run that starts a thread (`OpenedRun.preload`) writes its
    role and general skill reads as synthetic calls before its first model step
    (`preload.preload_reads`). The first turn of a chat also classifies
    its request and reads the picked skills. The
    step gets one attempt, and a failure leaves the turn going on without the reads.

    The run uses no Signal and no Update, and it never waits for a person. A stop cancels
    the workflow. The cancellation reaches the workflow as a `CancelledError`, or as an
    `ActivityError` that wraps it, and both write the `cancelled` ending. A workflow that
    starts after a stop closes in `open_run`.

    **The nag loop runs here** for a chat lead, with the rules of `tasks.P_agent.nagging`.
    The two counters are row columns, so they outlive a worker restart. A nag asks only for
    the todo marks, so the reply of a nag round does not replace the answer row
    (`steps.keeps_answer`). A stop of the nag loop writes no transcript row. Before the
    first nag, a chat answer that names a document in a turn with no `cite_documents`
    call gets one citation round (`steps.needs_citations`), whose reply replaces the
    answer. **A planner that
    answers with no plan section** gets one extra round with `PLANNER_NO_SECTION_NOTE`, and
    then fails.

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
        #: The model steps of the run thread.
        self._steps = 0
        #: The model steps of this workflow run, across its nag rounds.
        self._steps_here = 0
        self._planner_retry_done = False
        #: The nag counters of the turn. `run` sets them from the row, and every note and
        #: nag writes them back into the row.
        self._nags_this_turn = 0
        self._nags_without_progress = 0

    @workflow.run
    async def run(self, inp: AgentRunInput) -> str:
        self._todo_before_nag = json.loads(inp.todo_before_nag) if inp.todo_before_nag else None
        self._planner_retry_done = inp.planner_retry_done
        opened: OpenedRun = await workflow.execute_activity(
            open_run,
            inp,
            start_to_close_timeout=_SHORT_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        if opened.state == "closed":
            if opened.continuation_run_id:
                await start_run(self._settings(inp, opened.continuation_run_id),
                                f"run-{opened.continuation_run_id}")
            return "closed"
        self._steps = opened.model_steps
        self._nags_this_turn = opened.nags_this_turn
        self._nags_without_progress = opened.nags_without_progress
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
                await self._finish(inp, "failed", _failure_text(exc))
            raise
        except ApplicationError as exc:
            await self._finish(inp, "failed", exc.message)
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
                    start_to_close_timeout=_SHORT_TIMEOUT,
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

    @staticmethod
    def _ref_fields(inp: AgentRunInput) -> dict:
        return dict(run_id=inp.run_id, username=inp.username, session_id=inp.session_id,
                    turn_uuid=inp.turn_uuid,
                    allowed_collections=list(inp.allowed_collections or []),
                    llm_model=inp.llm_model, internet_tools=inp.internet_tools)

    def _ref(self, inp: AgentRunInput) -> StepRef:
        return StepRef(**self._ref_fields(inp))

    # ------------------------------------------------------------------------ the loop

    async def _agent_loop(self, inp: AgentRunInput, opened: OpenedRun,
                          first: bool) -> RunSummary:
        """One round: run the unanswered calls, then model steps until a reply has no call.

        The first round of a workflow run adds the children's reports of a continuation
        and starts with the unanswered calls that `open_run` found. A later round starts
        after a nag, with no call left.
        """
        pending: list[CallRef] = []
        if first and opened.preload:
            await self._preload(inp, opened)
        if first:
            if opened.continues:
                await workflow.execute_activity(
                    prepare_continuation, self._ref(inp),
                    start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    task_queue=CHAT_TASK_QUEUE,
                )
            pending = list(opened.pending)
        while True:
            if pending:
                delegated = await self._run_calls(inp, pending)
                if delegated is not None:
                    return delegated
                pending = []
            if (self._steps_here >= CONTINUE_AS_NEW_STEPS
                    or workflow.info().get_current_history_length() > HISTORY_EVENTS_PER_RUN):
                workflow.continue_as_new(replace(
                    inp,
                    todo_before_nag=(json.dumps(self._todo_before_nag)
                                     if self._todo_before_nag is not None else ""),
                    planner_retry_done=self._planner_retry_done,
                ))
            if self._steps >= RUN_MODEL_STEPS:
                return await self._forced_answer(inp, opened, "step_budget")
            result = await self._model_step(inp, opened, "tools", "")
            if result.outcome == "closed":
                return RunSummary(outcome="closed", next_seq=result.next_seq)
            if result.outcome == "empty":
                # The first reply of the thread with no text and no call gets one more step.
                await self._write_note(inp, result, empty_reply=True)
                continue
            if result.outcome == "answered":
                if result.empty_answer and opened.kind == "subagent":
                    return await self._empty_retry(inp, opened, "")
                return RunSummary(outcome="answered", next_seq=result.next_seq,
                                  next_idx=result.next_idx)
            if result.repeat_streak >= REPEAT_STEP_LIMIT:
                if result.repeat_notes == 0:
                    # The calls that are not repeats are exempt reads. They run first, so
                    # each call of the step has its result before the note.
                    if result.calls:
                        delegated = await self._run_calls(inp, result.calls)
                        if delegated is not None:
                            return delegated
                    await self._write_note(inp, result)
                    continue
                return await self._forced_answer(inp, opened, "repeated_call")
            pending = result.calls

    async def _forced_answer(self, inp: AgentRunInput, opened: OpenedRun,
                             reason: str) -> RunSummary:
        """Run one `final` step for `reason`. A sub-agent whose answer is empty gets
        `_empty_retry`."""
        result = await self._model_step(inp, opened, "final", reason)
        if result.outcome == "closed":
            return RunSummary(outcome="closed", next_seq=result.next_seq)
        if result.empty_answer and opened.kind == "subagent":
            return await self._empty_retry(inp, opened, reason)
        return RunSummary(outcome="answered", next_seq=result.next_seq,
                          next_idx=result.next_idx, end_reason=reason)

    async def _empty_retry(self, inp: AgentRunInput, opened: OpenedRun,
                           reason: str) -> RunSummary:
        """One more `final` step of a sub-agent whose answer was empty. When that answer is
        empty too, `write_found_documents` writes the run's result from its thread."""
        result = await self._model_step(inp, opened, "final", reason, empty_retry=True)
        if result.outcome == "closed":
            return RunSummary(outcome="closed", next_seq=result.next_seq)
        if result.empty_answer:
            await workflow.execute_activity(
                write_found_documents,
                FoundDocumentsParams(**self._ref_fields(inp), reason=reason),
                start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                task_queue=CHAT_TASK_QUEUE,
            )
            self._raise_if_stopped()
        return RunSummary(outcome="answered", next_seq=result.next_seq,
                          next_idx=result.next_idx, end_reason=reason)

    async def _write_note(self, inp: AgentRunInput, result: ModelStepResult,
                          empty_reply: bool = False) -> None:
        """The repeat note, or EMPTY_REPLY_TEXT, at the index and seq after the reply. It
        counts as a nag."""
        self._nags_this_turn += 1
        self._nags_without_progress += 1
        await workflow.execute_activity(
            write_repeat_note,
            RepeatNoteParams(**self._ref_fields(inp), seq=result.next_seq, idx=result.next_idx,
                             nags_this_turn=self._nags_this_turn,
                             nags_without_progress=self._nags_without_progress,
                             empty_reply=empty_reply),
            start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        self._raise_if_stopped()

    async def _preload(self, inp: AgentRunInput, opened: OpenedRun) -> None:
        """The run-start reads of a run that starts a thread. One attempt. A failure has
        its `agent_step_events` row with step `preload`, and the turn goes on without the
        reads. Only a stop ends the run here."""
        try:
            await workflow.execute_activity(
                preload_reads,
                PreloadParams(**self._ref_fields(inp), classify=opened.preload_classify),
                start_to_close_timeout=PRELOAD_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
                task_queue=CHAT_TASK_QUEUE,
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except ActivityError as exc:
            if _was_cancelled(exc):
                raise
            await self._record_failure(inp, "preload", CHAT_TASK_QUEUE, exc, name="systemone")
        self._raise_if_stopped()

    async def _model_step(self, inp: AgentRunInput, opened: OpenedRun, mode: str,
                          reason: str, empty_retry: bool = False) -> ModelStepResult:
        self._steps += 1
        self._steps_here += 1
        try:
            result = await workflow.execute_activity(
                model_step,
                ModelStepParams(**self._ref_fields(inp), step_no=self._steps, mode=mode,
                                final_reason=reason, empty_retry=empty_retry),
                start_to_close_timeout=TIMEOUTS.model_call,
                heartbeat_timeout=STEP_HEARTBEAT_TIMEOUT,
                # The wait for a free model slot. None sets no limit. Temporal does not
                # retry this timeout, so a step that waits past it fails the run.
                schedule_to_start_timeout=TIMEOUTS.queue_wait,
                retry_policy=RetryPolicy(maximum_attempts=3,
                                         initial_interval=timedelta(seconds=5),
                                         backoff_coefficient=2.0,
                                         maximum_interval=timedelta(seconds=60),
                                         non_retryable_error_types=["ModelRequestRejected"]),
                task_queue=opened.queue,
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except ActivityError as exc:
            if not _was_cancelled(exc):
                await self._record_failure(inp, "model", opened.queue, exc,
                                           name=inp.llm_model, mode=mode)
            raise
        self._raise_if_stopped()
        return result

    async def _run_calls(self, inp: AgentRunInput, pending: list[CallRef]) -> RunSummary | None:
        """Run the calls of one reply. Returns the delegation summary, or None."""
        ordered = sorted((c for c in pending if runs_in_order(c)), key=lambda c: c.position)
        parallel = [c for c in pending if c.kind != "delegation" and not runs_in_order(c)]
        delegations = [c for c in pending if c.kind == "delegation"]

        async def in_order() -> list[tuple[CallRef, str]]:
            # The plan tree and todo calls keep the order of the reply.
            statuses = []
            for call in ordered:
                statuses.append((call, await self._tool_call(inp, call)))
            return statuses

        results = await asyncio.gather(in_order(), *(self._tool_call(inp, c) for c in parallel))
        if delegations:
            # A delegation takes no tool slot. A stop waits for it to end, so the
            # `cancelled` ending sees every child row it wrote, and ends each of them.
            summary = await workflow.execute_activity(
                delegate_step, self._ref(inp),
                start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                task_queue=CHAT_TASK_QUEUE,
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            self._raise_if_stopped()
            return summary
        statuses = results[0] + list(zip(parallel, results[1:]))
        asked = next((call for call, status in sorted(statuses, key=lambda pair: pair[0].position)
                      if call.name == "ask_user" and status == "ok"), None)
        if asked is not None:
            next_seq = await workflow.execute_activity(
                write_asked_answer,
                AskedAnswerParams(**self._ref_fields(inp), call=asked),
                start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                task_queue=CHAT_TASK_QUEUE,
            )
            return RunSummary(outcome="answered", next_seq=next_seq, asked=True)
        return None

    async def _tool_call(self, inp: AgentRunInput, call: CallRef) -> str:
        """One tool call, and the status of its result. A failure after the last attempt
        stores a `tool_unavailable` result, gives `error`, and the loop goes on. Only a stop
        ends the run here."""
        status = "error"
        try:
            result = await workflow.execute_activity(
                tool_call,
                ToolCallParams(**self._ref_fields(inp), call=call),
                start_to_close_timeout=TOOL_CALL_TIMEOUT,
                heartbeat_timeout=STEP_HEARTBEAT_TIMEOUT,
                schedule_to_start_timeout=TIMEOUTS.queue_wait,
                retry_policy=RetryPolicy(maximum_attempts=3 if call.retry else 1,
                                         initial_interval=timedelta(seconds=2),
                                         backoff_coefficient=2.0),
                task_queue=AGENT_TOOL_TASK_QUEUE,
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            status = result.status
        except ActivityError as exc:
            if _was_cancelled(exc):
                raise
            await self._record_failure(inp, "tool", AGENT_TOOL_TASK_QUEUE, exc, call=call,
                                       name=call.name)
        self._raise_if_stopped()
        return status

    async def _record_failure(self, inp: AgentRunInput, step: str, queue: str,
                              exc: BaseException, call: CallRef | None = None,
                              name: str = "", mode: str = "") -> None:
        await workflow.execute_activity(
            record_step_failure,
            StepFailure(**self._ref_fields(inp), step=step, mode=mode, name=name,
                        error_class=_error_class(exc), task_queue=queue, call=call),
            start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )

    @staticmethod
    def _raise_if_stopped() -> None:
        """A step can end without an error after the stop arrived, because the workflow
        waits for it (`WAIT_CANCELLATION_COMPLETED`). The pending cancellation then raises
        here, so the run still ends as `cancelled`."""
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError()

    # ------------------------------------------------------------------------ the rounds

    async def _rounds(self, inp: AgentRunInput, opened: OpenedRun) -> RunSummary:
        summary = await self._agent_loop(inp, opened, first=True)
        while summary.outcome == "answered":
            if summary.asked:
                break
            if opened.kind == "planner":
                has_sections = await workflow.execute_activity(
                    plan_has_sections, self._ref(inp),
                    start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                    task_queue=CHAT_TASK_QUEUE,
                )
                if not has_sections:
                    # A planner at the step budget gets no extra round.
                    if self._planner_retry_done or summary.end_reason == "step_budget":
                        raise ApplicationError(PLANNER_NO_SECTION_ERROR, non_retryable=True)
                    self._planner_retry_done = True
                    await self._append_nag(inp, summary, PLANNER_NO_SECTION_NOTE,
                                           starts_round=True)
                    summary = await self._agent_loop(inp, opened, first=False)
                    continue
            # A forced answer has no tool, so a nag after it cannot change the todo. The
            # repeat note before a `repeated_call` answer was the nag.
            if summary.end_reason in ("step_budget", "repeated_call"):
                break
            # An answer that names a document in a turn with no citation gets one round
            # that asks for the citations and the answer again, before any todo nag.
            if opened.is_chat_lead and not summary.end_reason and await workflow.execute_activity(
                needs_citations, self._ref(inp),
                start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                task_queue=CHAT_TASK_QUEUE,
            ):
                await self._append_nag(inp, summary, nagging.CITATION_NOTE, starts_round=True)
                summary = await self._agent_loop(inp, opened, first=False)
                continue
            todo = await self._read_todo(inp)
            # Progress is the store's question, asked of the two snapshots either side of
            # the last nag. A run with no earlier snapshot resets no counter.
            if self._todo_before_nag is not None and chat_todos.is_material_change(
                self._todo_before_nag, todo
            ):
                self._nags_without_progress = 0
            stop = nagging.stop_reason(todo, self._nags_without_progress, self._nags_this_turn)
            if stop:
                # The stop reason goes to the log only. A transcript row after the answer
                # would take the place of the answer as the last row of the turn.
                if stop != "resolved":
                    workflow.logger.info("run %s ends its nag rounds: %s", inp.run_id, stop)
                break
            self._nags_this_turn += 1
            self._nags_without_progress += 1
            self._todo_before_nag = todo
            await self._append_nag(
                inp, summary, nagging.nag_message(todo, self._nags_without_progress),
                starts_round=True,
            )
            summary = await self._agent_loop(inp, opened, first=False)
        return summary

    async def _append_nag(self, inp: AgentRunInput, summary: RunSummary, message: str,
                          starts_round: bool) -> int:
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
                nags_this_turn=self._nags_this_turn,
                nags_without_progress=self._nags_without_progress,
            ),
            start_to_close_timeout=_SHORT_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )

    async def _read_todo(self, inp: AgentRunInput) -> dict:
        """The todo list owned by this run, as the nag loop needs it."""
        raw = await workflow.execute_activity(
            read_chat_todo,
            ReadTodoParams(username=inp.username, session_id=inp.session_id,
                           run_id=inp.run_id),
            start_to_close_timeout=_SHORT_TIMEOUT,
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
            start_to_close_timeout=_SHORT_TIMEOUT,
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
                       decision_id="", todo_before_nag="", planner_retry_done=False)

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
