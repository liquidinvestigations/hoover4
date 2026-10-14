"""Temporal workflows of investigation boards.

`BoardDispatcher` is a singleton with the fixed id `board-dispatcher`. The chat worker
asserts it at start, as `collect-eta-samples` is asserted. Each pass runs `board_plan`,
starts the reasons and explores it returns, cancels the explores of paused boards, and sleeps
for `POLL_SECONDS`. All state is in ClickHouse, so no person action needs a signal: the next
pass reads it. The dispatcher waits for no person, only for its own timer and reasons.

Each pass also starts `label_board` for the board that `board_plan` names in `labels`, when
no label task is in flight (`labels.labels_to_start`). It runs on `chat-model-queue` as a
reason does and uses no board model slot.

`BoardExplore` runs one intent: an explore turn, and when its answer has no valid block, one
conclude turn in the same chat session. Each turn is an ordinary `AgentRun` child on
`chat-queue`.

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
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import HEARTBEAT_TIMEOUT
    from tasks.P_board import model as m
    from tasks.P_board.activities import (
        EndRequest,
        ExploreTask,
        PlanInput,
        PlanOutput,
        ReasonTask,
        TurnRequest,
        board_plan,
        board_reason,
        conclude_explore,
        open_explore_turn,
        record_explore_end,
    )
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


@workflow.defn
class BoardDispatcher:
    """Plan and start the work of every live board."""

    def __init__(self) -> None:
        self._reasons: dict[str, asyncio.Task] = {}
        self._labels: dict[str, asyncio.Task] = {}
        self._woken = False

    @workflow.run
    async def run(self) -> None:
        for _ in range(PASSES_PER_RUN):
            try:
                output: PlanOutput = await workflow.execute_activity(
                    board_plan, PlanInput(in_flight_reasons=sorted(self._reasons)),
                    start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
            except ActivityError as exc:
                workflow.logger.warning("board_plan failed: %s", exc)
                output = PlanOutput()
            for reason in output.reasons:
                if reason.board_id not in self._reasons:
                    self._reasons[reason.board_id] = asyncio.ensure_future(self._reason(reason))
            for explore in output.explores:
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
        workflow.continue_as_new()

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
                retry_policy=RetryPolicy(maximum_attempts=2),
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
                start_to_close_timeout=timedelta(minutes=15), heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except ActivityError as exc:
            workflow.logger.warning("board_reason failed for %s: %s", reason.board_id, exc)
        finally:
            self._reasons.pop(reason.board_id, None)
            self._woken = True


@workflow.defn
class BoardExplore:
    """Run one intent as an explore turn, and a conclude turn when the answer needs one."""

    @workflow.run
    async def run(self, task: ExploreTask) -> str:
        try:
            outcome = await self._turn(task, "explore")
            if outcome == "needs_conclude":
                outcome = await self._turn(task, "conclude")
            return outcome
        except asyncio.CancelledError:
            await asyncio.shield(self._record(task, m.EXPLORE_CANCELLED, "the explore was cancelled"))
            raise

    async def _record(self, task: ExploreTask, kind: str, error: str) -> None:
        await workflow.execute_activity(
            record_explore_end, EndRequest(task.board_id, task.intent_id, task.attempt, kind, error),
            start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

    async def _turn(self, task: ExploreTask, phase: str) -> str:
        request = TurnRequest(task.board_id, task.intent_id, task.attempt, phase)
        opened = await workflow.execute_activity(
            open_explore_turn, request, start_to_close_timeout=_SHORT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if opened.skip_kind:
            await self._record(task, opened.skip_kind, opened.skip_reason)
            return "skipped"
        try:
            await workflow.execute_child_workflow(
                "AgentRun", opened.run_input, id=opened.workflow_id, task_queue=CHAT_TASK_QUEUE,
            )
        except ChildWorkflowError as exc:
            # A failed or killed turn still leaves its rows. Conclude reads what it wrote.
            workflow.logger.warning("the %s turn of %s ended with %s", phase, task.intent_id, exc)
        return await workflow.execute_activity(
            conclude_explore, request, start_to_close_timeout=_SHORT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=3),
        )
