"""Temporal workflows of investigation boards.

`BoardDispatcher` is a singleton with the fixed id `board-dispatcher`. The chat worker
asserts it at start, as `collect-eta-samples` is asserted. Each pass runs `board_plan`,
starts the command writer `BoardCommands` (`command_workflows.py`) of every board that
`board_plan` names, starts the reasons and explores whose start commands are committed,
cancels the explores of paused boards, and sleeps for `POLL_SECONDS`. All state is in
ClickHouse, so no person action needs a signal: the next pass reads it. The dispatcher waits
for no person, only for its own timer and reasons.

`board_plan` submits a start command for each reason and explore it returns, and the task
carries the request id. The dispatcher keeps the task until a later pass reports the command
committed or refused, and carries the waiting tasks into the next run. A task without a
request id comes from a history written before the command writer and starts at once, so
such a history replays with the same commands.

Each pass also starts `label_board` for the board that `board_plan` names in `labels`, when
no label task is in flight (`labels.labels_to_start`). It runs on `chat-model-queue` as a
reason does and uses no board model slot.

`BoardExplore` runs one intent: one explore turn, an ordinary `AgentRun` child on
`chat-queue` that writes a workspace report, then `conclude_explore`, and for a report
`convert_explore_report` on `chat-model-queue`. The conversion is one model request with two
attempts. After its last attempt, `record_explore_end` records `explore_failed` with the
report version. A cancellation records `explore_cancelled`.

**A change that schedules a different command for an existing history event needs the drain
of `tasks/Readme.md`.** Terminate `board-dispatcher`, cancel every `board-explore-*` workflow,
deploy, and let the worker start the dispatcher again. The next pass reopens the interrupted
intents. A new step that an old history decodes as empty, such as `PlanOutput.labels`, needs
no drain. A `temporalio.worker.Replayer` run of the new code over a fetched history is the
evidence for that.
"""

import asyncio
from datetime import timedelta

from temporalio import workflow
from dataclasses import dataclass, field

from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError, is_cancelled_exception
from temporalio.workflow import ChildWorkflowCancellationType, ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_board import model as m
    from tasks.P_board.activities import (
        Concluded,
        EndRequest,
        ExploreTask,
        FinalFailure,
        PlanInput,
        PlanOutput,
        ReasonFailure,
        ReasonTask,
        TurnRequest,
        board_plan,
        board_reason,
        conclude_explore,
        convert_explore_report,
        open_explore_turn,
        record_explore_end,
        record_final_failure,
        record_reason_failure,
    )
    from tasks.P_agent.model_timeouts import TIMEOUTS
    from tasks.P_board.command_workflows import BoardCommands, commands_workflow_id
    from tasks.P_board.labels import LabelTask, label_board, labels_to_start

#: Seconds between two passes of the dispatcher.
POLL_SECONDS = 5
#: Passes before the dispatcher continues as new, which bounds its history.
PASSES_PER_RUN = 200
#: The queue of `AgentRun`. Mirrored from `tasks/P_agent/workflows.py`.
CHAT_TASK_QUEUE = "chat-queue"
#: The queue of model calls. Mirrored from `tasks/P_agent/workflows.py`.
CHAT_MODEL_TASK_QUEUE = "chat-model-queue"

_SHORT = timedelta(seconds=120)

#: The retry of an activity that reads and writes ClickHouse only. Its writes have fixed
#: keys, so a repeat is harmless (`tasks/Readme.md`, retries).
STORAGE_RETRY = RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS)
#: The retry of an activity that sends one external model request: one more attempt after
#: one second.
EXTERNAL_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=1))


@dataclass
class DispatcherState:
    """The start commands that wait for their commit when the dispatcher continues as new."""
    reasons: list[ReasonTask] = field(default_factory=list)
    explores: list[ExploreTask] = field(default_factory=list)


def _key(board_id: str, request_id: str) -> str:
    return f"{board_id} {request_id}"


@workflow.defn
class BoardDispatcher:
    """Plan and start the work of every live board."""

    def __init__(self) -> None:
        self._reasons: dict[str, asyncio.Task] = {}
        self._labels: dict[str, asyncio.Task] = {}
        self._commands: dict[str, asyncio.Task] = {}
        self._awaiting: dict[str, ReasonTask | ExploreTask] = {}
        self._woken = False

    @workflow.run
    async def run(self, state: DispatcherState | None = None) -> None:
        for task in (state.reasons + state.explores) if state else []:
            self._awaiting[_key(task.board_id, task.request_id)] = task
        for _ in range(PASSES_PER_RUN):
            waiting_reasons = {t.board_id for t in self._awaiting.values() if isinstance(t, ReasonTask)}
            try:
                output: PlanOutput = await workflow.execute_activity(
                    board_plan, PlanInput(in_flight_reasons=sorted(set(self._reasons) | waiting_reasons),
                                          awaiting=sorted(self._awaiting)),
                    start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STORAGE_RETRY,
                )
            except ActivityError as exc:
                workflow.logger.warning("board_plan failed: %s", exc)
                output = PlanOutput()
            for board_id in output.command_boards:
                await self._start_commands(board_id)
            for key in output.rejected:
                self._awaiting.pop(key, None)
            for key in output.committed:
                task = self._awaiting.pop(key, None)
                if isinstance(task, ReasonTask):
                    self._start_reason(task)
                elif isinstance(task, ExploreTask):
                    await self._start_explore(task)
            for reason in output.reasons:
                if reason.request_id:
                    self._awaiting[_key(reason.board_id, reason.request_id)] = reason
                else:
                    self._start_reason(reason)
            for explore in output.explores:
                if explore.request_id:
                    self._awaiting[_key(explore.board_id, explore.request_id)] = explore
                else:
                    await self._start_explore(explore)
            for board_id in labels_to_start(set(self._labels), output.labels):
                self._labels[board_id] = asyncio.ensure_future(self._label(board_id))
            for workflow_id in output.cancels:
                try:
                    await workflow.get_external_workflow_handle(workflow_id).cancel()
                except Exception as exc:  # noqa: BLE001 - a closed explore needs no cancel
                    workflow.logger.info("could not cancel %s: %s", workflow_id, exc)
            self._woken = False
            try:
                await workflow.wait_condition(lambda: self._woken, timeout=timedelta(seconds=POLL_SECONDS))
            except asyncio.TimeoutError:
                pass
        # No continue-as-new with a reason or a label task in flight: the new run would not
        # know about it and could start a second one for the same board.
        if self._reasons or self._labels:
            await asyncio.gather(*self._reasons.values(), *self._labels.values(),
                                 return_exceptions=True)
        if self._awaiting:
            waiting = list(self._awaiting.values())
            workflow.continue_as_new(DispatcherState(
                [t for t in waiting if isinstance(t, ReasonTask)],
                [t for t in waiting if isinstance(t, ExploreTask)]))
        workflow.continue_as_new()

    def _start_reason(self, reason: ReasonTask) -> None:
        if reason.board_id not in self._reasons:
            self._reasons[reason.board_id] = asyncio.ensure_future(self._reason(reason))

    async def _start_commands(self, board_id: str) -> None:
        """Start the command writer of a board unless this run already waits for it."""
        if board_id in self._commands:
            return
        try:
            handle = await workflow.start_child_workflow(
                BoardCommands.run, board_id, id=commands_workflow_id(board_id),
                task_queue=m.BOARD_TASK_QUEUE, parent_close_policy=ParentClosePolicy.ABANDON,
                cancellation_type=ChildWorkflowCancellationType.ABANDON,
            )
        except Exception as exc:  # noqa: BLE001 - a writer that is already open keeps running
            workflow.logger.info("could not start the command writer of %s: %s", board_id, exc)
            return
        self._commands[board_id] = asyncio.ensure_future(self._command_end(board_id, handle))

    async def _command_end(self, board_id: str, handle) -> None:
        try:
            await handle
        except Exception as exc:  # noqa: BLE001 - the next pass starts the writer again
            workflow.logger.warning("the command writer of %s ended with %s", board_id, exc)
        finally:
            self._commands.pop(board_id, None)
            self._woken = True

    async def _start_explore(self, explore: ExploreTask) -> None:
        try:
            await workflow.start_child_workflow(
                BoardExplore.run, explore,
                id=m.explore_workflow_id(explore.board_id, explore.intent_id),
                task_queue=m.BOARD_TASK_QUEUE,
                parent_close_policy=ParentClosePolicy.ABANDON,
            )
        except Exception as exc:  # noqa: BLE001 - an explore that is already open keeps running
            workflow.logger.warning("could not start the explore of %s %s: %s",
                                    explore.board_id, explore.intent_id, exc)

    async def _label(self, board_id: str) -> None:
        try:
            await workflow.execute_activity(
                label_board, LabelTask(board_id), task_queue=CHAT_MODEL_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=15), heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=EXTERNAL_RETRY,
            )
        except ActivityError as exc:
            workflow.logger.warning("label_board failed for %s: %s", board_id, exc)
        finally:
            self._labels.pop(board_id, None)
            self._woken = True

    async def _reason(self, reason: ReasonTask) -> None:
        try:
            await workflow.execute_activity(
                board_reason, reason, task_queue=CHAT_MODEL_TASK_QUEUE,
                start_to_close_timeout=TIMEOUTS.board_reason_activity,
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=EXTERNAL_RETRY,
            )
        except ActivityError as exc:
            workflow.logger.warning("board_reason failed for %s: %s", reason.board_id, exc)
            if reason.final:
                await self._final_failure(reason, str(exc))
            else:
                await self._reason_failure(reason, str(exc.cause or exc))
        finally:
            self._reasons.pop(reason.board_id, None)
            self._woken = True

    async def _reason_failure(self, reason: ReasonTask, error: str) -> None:
        """Record `model_failure` for an assessment whose call failed in every attempt."""
        try:
            await workflow.execute_activity(
                record_reason_failure,
                ReasonFailure(reason.board_id, reason.reason_no, reason.stalled, error),
                start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=STORAGE_RETRY,
            )
        except ActivityError as exc:
            # A later pass plans from the fold without a result of this assessment.
            workflow.logger.warning("record_reason_failure failed for %s: %s", reason.board_id, exc)

    async def _final_failure(self, reason: ReasonTask, error: str) -> None:
        """Record the end of a final assessment whose call failed, so it ends its operation."""
        try:
            await workflow.execute_activity(
                record_final_failure, FinalFailure(reason.board_id, reason.assessed_budget, error),
                start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=STORAGE_RETRY,
            )
        except ActivityError as exc:
            # The next pass sees the running operation without a reason in flight and ends it.
            workflow.logger.warning("record_final_failure failed for %s: %s", reason.board_id, exc)


@workflow.defn
class BoardExplore:
    """Run one intent as one explore turn, and convert its report into the fact."""

    @workflow.run
    async def run(self, task: ExploreTask) -> str:
        try:
            return await self._explore(task)
        except asyncio.CancelledError:
            await asyncio.shield(self._record(task, m.EXPLORE_CANCELLED, "the explore was cancelled"))
            raise

    async def _record(self, task: ExploreTask, kind: str, error: str, report: dict | None = None) -> None:
        await workflow.execute_activity(
            record_explore_end,
            EndRequest(task.board_id, task.intent_id, task.attempt, kind, error, report or {}),
            start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=STORAGE_RETRY,
        )

    async def _explore(self, task: ExploreTask) -> str:
        request = TurnRequest(task.board_id, task.intent_id, task.attempt)
        opened = await workflow.execute_activity(
            open_explore_turn, request, start_to_close_timeout=_SHORT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=STORAGE_RETRY,
        )
        if opened.skip_kind:
            await self._record(task, opened.skip_kind, opened.skip_reason)
            return "skipped"
        try:
            await workflow.execute_child_workflow(
                "AgentRun", opened.run_input, id=opened.workflow_id, task_queue=CHAT_TASK_QUEUE,
            )
        except ChildWorkflowError as exc:
            if is_cancelled_exception(exc):
                raise asyncio.CancelledError() from exc
            # The files of a failed turn stay in its workspace. The explore fails.
            workflow.logger.warning("the explore turn of %s ended with %s", task.intent_id, exc)
            request.turn_error = str(exc.cause or exc)[:500]
        concluded: Concluded = await workflow.execute_activity(
            conclude_explore, request, start_to_close_timeout=_SHORT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=STORAGE_RETRY,
        )
        if concluded.outcome != "convert":
            return concluded.outcome
        try:
            return await workflow.execute_activity(
                convert_explore_report, request, task_queue=CHAT_MODEL_TASK_QUEUE,
                start_to_close_timeout=TIMEOUTS.board_reason_activity,
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=EXTERNAL_RETRY,
            )
        except ActivityError as exc:
            if is_cancelled_exception(exc):
                raise asyncio.CancelledError() from exc
            workflow.logger.warning("the conversion of %s failed: %s", task.intent_id, exc)
            await self._record(task, m.EXPLORE_FAILED,
                               f"the report conversion failed: {exc.cause or exc}"[:2000],
                               concluded.report)
            return "failed"
