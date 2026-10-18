"""`BoardCommands`: the serialized command writer of one board.

The workflow id is `board-commands-<board_id>`, so Temporal runs at most one open writer for
a board. The dispatcher starts it on its normal pass for every board with a command that
waits (`board_plan` names them in `PlanOutput.command_boards`). It runs `board_command_step`
until the board has no command left, then completes. A later command starts it again, and
the receipts in ClickHouse carry every decision between runs (`commands.py`).

The workflow makes no model call and takes no board model slot. Its activity reuses the
short limits of the board activities.
"""

from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT, with_heartbeat

#: The prefix of the workflow id of a board's command writer.
COMMANDS_WORKFLOW_PREFIX = "board-commands-"
#: Commands that one activity call handles before it returns.
COMMANDS_PER_STEP = 20
#: Activity calls of one run before it continues as new, which bounds its history.
STEPS_PER_RUN = 100

_SHORT = timedelta(seconds=120)


def commands_workflow_id(board_id: str) -> str:
    return f"{COMMANDS_WORKFLOW_PREFIX}{board_id}"


@dataclass
class CommandStepInput:
    board_id: str


@dataclass
class CommandStepOutput:
    processed: int = 0
    more: bool = False


@activity.defn
@with_heartbeat
def board_command_step(inp: CommandStepInput) -> CommandStepOutput:
    """Handle up to `COMMANDS_PER_STEP` commands of one board, in order."""
    from tasks.P_board.commands import step

    processed = 0
    for _ in range(COMMANDS_PER_STEP):
        if not step(inp.board_id):
            return CommandStepOutput(processed, False)
        processed += 1
    return CommandStepOutput(processed, True)


@workflow.defn
class BoardCommands:
    """Handle the commands of one board until none is left."""

    @workflow.run
    async def run(self, board_id: str) -> int:
        handled = 0
        for _ in range(STEPS_PER_RUN):
            try:
                out: CommandStepOutput = await workflow.execute_activity(
                    board_command_step, CommandStepInput(board_id),
                    start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
                )
            except ActivityError as exc:
                # The commands stay in storage. The dispatcher starts the writer again on a
                # later pass, and a prepared receipt is applied first.
                workflow.logger.warning("board_command_step failed for %s: %s", board_id, exc)
                return handled
            handled += out.processed
            if not out.more:
                return handled
        workflow.continue_as_new(board_id)


__all__ = ["BoardCommands", "COMMANDS_WORKFLOW_PREFIX", "CommandStepInput", "CommandStepOutput",
           "board_command_step", "commands_workflow_id"]
