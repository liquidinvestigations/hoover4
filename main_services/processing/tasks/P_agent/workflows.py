"""Temporal workflows for AI agent turns.

`AgentRun` owns one agent run. A chat turn is one `AgentRun`. The state lives in
the `agent_runs` and `agent_run_messages` tables, so the workflow input and results hold
ids only.

`AgentRun` runs the agent loop on `chat-queue`. Each model call is one `model_step`
activity on `chat-model-queue`. Each tool call is one `tool_call` activity on `agent-tool-queue`. None of
these is the ingestion queue, so an ingestion backlog cannot delay a person at a screen.

**A change to `AgentRun` needs the drain.** A running `AgentRun` replays its history on
new code, and a history that does not match the new code fails as nondeterministic. No
workflow versioning exists, so a deploy that changes this workflow first stops every open
agent turn and cancels every running `AgentRun` (`tasks/Readme.md`).
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import (
    ActivityError, ApplicationError, CancelledError, TimeoutError as TemporalTimeoutError,
    TimeoutType,
)
from temporalio.workflow import ActivityCancellationType

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_agent.model_timeouts import (
        CONTINUE_AS_NEW_STEPS, HISTORY_EVENTS_PER_RUN, RUN_MODEL_STEPS,
        STEP_HEARTBEAT_TIMEOUT, TIMEOUTS, TOOL_CALL_TIMEOUT,
    )
    from tasks.P_agent.followups import write_followups
    from tasks.P_agent.steps import MODEL_STEP_MODE
    from tasks.P_agent.activities import (
        AgentRunInput,
        CallRef,
        OpenedRun,
        RunRef,
        RunSummary,
        WriteEndingParams,
        open_run,
        summarize_if_first_turn,
        write_ending,
    )
    from tasks.P_agent.control_steps import (
        CONTROL_HEARTBEAT_SECONDS,
        HOOK_MARGIN_SECONDS,
        HOOK_SECONDS,
        ControlOutcome,
        ControlParams,
        control_event,
    )
    from tasks.P_agent.steps import (
        EMPTY_RESPONSE,
        STEP_BUDGET,
        AskedAnswerParams,
        EmptyNoteParams,
        IncompleteParams,
        ModelStepParams,
        ModelStepResult,
        StepFailure,
        StepRef,
        ToolCallParams,
        model_step,
        record_step_failure,
        runs_in_browser,
        runs_in_order,
        tool_call,
        write_asked_answer,
        write_empty_note,
        write_incomplete,
    )


#: The queue `AgentRun` is dispatched to, and the queue of its short activities: open, note,
#: ending, fan-in, section dispatch and title. Named here so the worker that polls it
#: and the caller that addresses it cannot drift: a workflow addressed to a queue nothing
#: is polling waits for ever with no error anywhere, which presents as chat hanging.
#:
#: **Mirrored in `website/backend/src/api/chat/mod.rs`.** The queue names move in the
#: same patch or not at all.
CHAT_TASK_QUEUE = "chat-queue"

#: The queue of model steps and follow-up generation. One slot is one model call.
CHAT_MODEL_TASK_QUEUE = "chat-model-queue"

#: The queue of every `tool_call` activity. One slot is one tool call in flight.
AGENT_TOOL_TASK_QUEUE = "agent-tool-queue"

#: Nothing in an `AgentRun` input or result is text. A `ModelStepResult` carries one `CallRef` for each call, so a
#: reply with more than about 12 calls passes it, and the payload guard limits still hold.
AGENT_RUN_PAYLOAD_BYTES = 4096

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
    Every call of a reply runs: the length of the conversation and an earlier identical call
    refuse none. The `ordered` calls and the calls to todo tools
    (`steps.runs_in_order`) run one after the other in the order of the reply. The calls to
    the browser server (`steps.runs_in_browser`) run one after the other in a second chain,
    because they drive one browser. The other calls run at once beside both chains. A reply
    with calls gives the next calls. A reply with no call ends the round.

    **The limits.** When the model steps of the thread reach `RUN_MODEL_STEPS`, across
    continue-as-new and continuations, the run makes no further model call.
    `write_incomplete` writes a result from the stored thread, with `end_reason`
    `step_budget`. The first reply of a thread with no text and no call gets
    `steps.EMPTY_REPLY_TEXT`, which is the stored retry marker, and one more model step. A
    second such reply ends the run the same way, with `end_reason` `empty_response`. The
    workflow continues as new every `CONTINUE_AS_NEW_STEPS` model steps, or when its
    history passes `HISTORY_EVENTS_PER_RUN` events, and the new run resumes from the thread.

    The run uses no Signal and no Update, and it never waits for a person. A stop cancels
    the workflow. The cancellation reaches the workflow as a `CancelledError`, or as an
    `ActivityError` that wraps it, and both write the `cancelled` ending. A workflow that
    starts after a stop closes in `open_run`.

    **The policy hooks.** `control_event` runs at three points of the loop
    (`control_steps.py`). `turn_started` follows `open_run`, and its skill loads run as a
    policy batch before the first model step. `tool_batch_completed` follows every batch,
    and its follow-on calls run as one more batch before the next model step. Automatic
    reads follow a model batch only, so after a policy batch the hook can load skills and
    no more.
    `answer_drafted` follows an answer or a question. It writes one combined note when
    the draft has a finding that asks for a round, and the loop runs one more round. A turn
    gets at most two repair rounds after its first draft, counted from the stored notes, and
    a discovery note counts separately. A run that ended at a limit gets no review, and a
    run at the step limit gets no further round. The reply of a round after a question is
    the question that the person reads.

    **Shared calls.** Two parallel calls of one batch with the same `share_key` share one
    execution: the later call waits for the first, and `tool_call` stores a pointer to the
    first result when that result is complete. Otherwise the later call runs. Two
    `read_page` calls of the browser chain share a result the same way, unless the batch
    holds a browser call that can change the page.
    """

    def __init__(self) -> None:
        #: The model steps of the run thread.
        self._steps = 0
        #: The model steps of this workflow run, across its rounds.
        self._steps_here = 0

    @workflow.run
    async def run(self, inp: AgentRunInput) -> str:
        opened: OpenedRun = await workflow.execute_activity(
            open_run,
            inp,
            start_to_close_timeout=_SHORT_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        if opened.state == "closed":
            return "closed"
        self._steps = opened.model_steps
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
        if not summary.end_reason:
            try:
                await workflow.execute_activity(
                    write_followups,
                    RunRef(run_id=inp.run_id, username=inp.username, session_id=inp.session_id),
                    start_to_close_timeout=TIMEOUTS.title_activity,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    task_queue=CHAT_MODEL_TASK_QUEUE,
                )
            except asyncio.CancelledError:
                await asyncio.shield(self._finish(inp, "cancelled"))
                raise
            except Exception as exc:
                if _was_cancelled(exc):
                    await asyncio.shield(self._finish(inp, "cancelled"))
                    raise
                workflow.logger.warning("could not generate follow-up suggestions for %s", inp.session_id)
        await self._finish(inp, "completed")
        await self._summarize_if_first_turn(inp)
        return "completed"

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
                          pending: list[CallRef]) -> RunSummary:
        """One round: run the unanswered calls, then model steps until a reply has no call.

        The first round of a workflow run starts with the unanswered calls that `open_run`
        found and the calls of the turn's preparation. A later round starts after a note.
        After each batch, `tool_batch_completed` can give a policy batch, which runs before
        the next model step.
        """
        while True:
            if pending:
                asked = await self._run_calls(inp, pending)
                if asked is not None:
                    return asked
                after = await self._control(inp, "tool_batch_completed",
                                            anchor_idx=pending[0].ai_idx)
                if after.closed:
                    return RunSummary(outcome="closed", next_seq=after.next_seq)
                if after.end_turn:
                    return await self._incomplete(inp, "no_progress")
                pending = after.calls
                if pending:
                    continue
            if (self._steps_here >= CONTINUE_AS_NEW_STEPS
                    or workflow.info().get_current_history_length() > HISTORY_EVENTS_PER_RUN):
                workflow.continue_as_new(inp)
            if self._steps >= RUN_MODEL_STEPS:
                # The stored results of the last calls stay. No model call follows.
                return await self._incomplete(inp, STEP_BUDGET)
            result = await self._model_step(inp, opened)
            if result.outcome == "closed":
                return RunSummary(outcome="closed", next_seq=result.next_seq)
            if result.outcome == "empty":
                # The first reply of the thread with no text and no call gets one more step.
                await self._write_empty_note(inp, result)
                continue
            if result.outcome == "empty_again":
                return await self._incomplete(inp, EMPTY_RESPONSE)
            if result.outcome == "answered":
                return RunSummary(outcome="answered", next_seq=result.next_seq,
                                  next_idx=result.next_idx)
            pending = result.calls

    async def _control(self, inp: AgentRunInput, hook: str, anchor_idx: int = -1,
                       draft_kind: str = "") -> ControlOutcome:
        """One policy hook (`control_steps.control_event`). The activity timeout comes from
        the hook deadline. A failed hook raises like any short activity."""
        seconds = HOOK_SECONDS[hook]
        outcome: ControlOutcome = await workflow.execute_activity(
            control_event,
            ControlParams(**self._ref_fields(inp), hook=hook, anchor_idx=anchor_idx,
                          deadline_seconds=seconds, draft_kind=draft_kind,
                          model_limit_reached=self._steps >= RUN_MODEL_STEPS),
            start_to_close_timeout=timedelta(seconds=seconds + HOOK_MARGIN_SECONDS),
            heartbeat_timeout=timedelta(seconds=CONTROL_HEARTBEAT_SECONDS * 5),
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
            cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        self._raise_if_stopped()
        return outcome

    async def _incomplete(self, inp: AgentRunInput, reason: str) -> RunSummary:
        """End the model steps of a run that stopped before an answer, with the result that
        `write_incomplete` writes from the stored thread, and no model call."""
        next_seq = await workflow.execute_activity(
            write_incomplete,
            IncompleteParams(**self._ref_fields(inp), reason=reason, limit=RUN_MODEL_STEPS),
            start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        self._raise_if_stopped()
        return RunSummary(outcome="answered", next_seq=next_seq, end_reason=reason)

    async def _write_empty_note(self, inp: AgentRunInput, result: ModelStepResult) -> None:
        """EMPTY_REPLY_TEXT at the index and seq after the reply. It is the retry marker of
        the thread, and it writes no counter."""
        await workflow.execute_activity(
            write_empty_note,
            EmptyNoteParams(**self._ref_fields(inp), seq=result.next_seq, idx=result.next_idx),
            start_to_close_timeout=_SHORT_TIMEOUT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=CHAT_TASK_QUEUE,
        )
        self._raise_if_stopped()

    async def _model_step(self, inp: AgentRunInput, opened: OpenedRun) -> ModelStepResult:
        self._steps += 1
        self._steps_here += 1
        try:
            result = await workflow.execute_activity(
                model_step,
                ModelStepParams(**self._ref_fields(inp), step_no=self._steps),
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
                task_queue=CHAT_MODEL_TASK_QUEUE,
                cancellation_type=ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
        except ActivityError as exc:
            if not _was_cancelled(exc):
                await self._record_failure(inp, "model", CHAT_MODEL_TASK_QUEUE, exc,
                                           name=inp.llm_model, mode=MODEL_STEP_MODE)
            raise
        self._raise_if_stopped()
        return result

    async def _run_calls(self, inp: AgentRunInput, pending: list[CallRef]) -> RunSummary | None:
        """Run the calls of one reply. Returns the summary of a successful question, or
        None."""
        ordered = sorted((c for c in pending if runs_in_order(c)), key=lambda c: c.position)
        browser = sorted((c for c in pending if runs_in_browser(c)), key=lambda c: c.position)
        parallel = sorted((c for c in pending if not runs_in_order(c) and not runs_in_browser(c)),
                          key=lambda c: c.position)
        # A browser call with one attempt only can change the page, so no read shares.
        page_changes = any(not c.retry for c in browser)

        async def in_order(chain: list[CallRef], share: bool) -> list[tuple[CallRef, str]]:
            # The todo calls, and the browser calls, keep the order of the reply within
            # their chain.
            statuses = []
            first: dict[str, CallRef] = {}
            for call in chain:
                leader = first.get(call.share_key) if share and call.share_key else None
                statuses.append((call, await self._tool_call(inp, call, leader)))
                if share and call.share_key:
                    first.setdefault(call.share_key, call)
            return statuses

        leaders: dict[str, CallRef] = {}
        tasks: dict[str, asyncio.Task] = {}

        async def shared(call: CallRef, leader: CallRef) -> str:
            await tasks[leader.call_id]
            return await self._tool_call(inp, call, leader)

        for call in parallel:
            leader = leaders.get(call.share_key) if call.share_key else None
            if leader is None:
                if call.share_key:
                    leaders[call.share_key] = call
                tasks[call.call_id] = asyncio.ensure_future(self._tool_call(inp, call))
            else:
                tasks[call.call_id] = asyncio.ensure_future(shared(call, leader))
        results = await asyncio.gather(in_order(ordered, False),
                                       in_order(browser, not page_changes),
                                       *(tasks[c.call_id] for c in parallel))
        statuses = results[0] + results[1] + list(zip(parallel, results[2:]))
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

    async def _tool_call(self, inp: AgentRunInput, call: CallRef,
                         shared_from: CallRef | None = None) -> str:
        """One tool call, and the status of its result. A failure after the last attempt
        stores a `tool_unavailable` result, gives `error`, and the loop goes on. Only a stop
        ends the run here. `shared_from` is the earlier call of the batch with the same
        `share_key`, whose complete result the call can share."""
        status = "error"
        try:
            result = await workflow.execute_activity(
                tool_call,
                ToolCallParams(**self._ref_fields(inp), call=call, shared_from=shared_from),
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
        prepared = await self._control(inp, "turn_started", anchor_idx=0)
        if prepared.closed:
            return RunSummary(outcome="closed", next_seq=prepared.next_seq)
        pending = list(prepared.calls) + [c for c in opened.pending
                                          if c.call_id not in {p.call_id for p in prepared.calls}]
        summary = await self._agent_loop(inp, opened, pending)
        # True when a round follows a question, so the reply of that round is the question
        # the person reads.
        after_question = False
        while summary.outcome == "answered" and not summary.end_reason:
            kind = "question" if summary.asked or after_question else "answer"
            review = await self._control(inp, "answer_drafted", draft_kind=kind)
            if review.closed or not review.round:
                break
            after_question = kind == "question"
            summary = await self._agent_loop(inp, opened, [])
        return summary

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

    async def _summarize_if_first_turn(self, inp: AgentRunInput) -> None:
        """Name the conversation after its first turn. Propagate cancellation."""
        try:
            await workflow.execute_activity(
                summarize_if_first_turn,
                RunRef(run_id=inp.run_id, username=inp.username, session_id=inp.session_id),
                start_to_close_timeout=TIMEOUTS.title_activity,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
                task_queue=CHAT_TASK_QUEUE,
            )
        except Exception as exc:
            if _was_cancelled(exc):
                raise
            workflow.logger.warning(
                "could not title session %s, keeping the provisional title", inp.session_id
            )


def _cause_text(exc: BaseException) -> str:
    """The innermost message of a failure, for the ending row a person reads."""
    seen: BaseException | None = exc
    text = str(exc)
    while seen is not None:
        if str(seen):
            text = str(seen)
        seen = seen.__cause__
    return text
