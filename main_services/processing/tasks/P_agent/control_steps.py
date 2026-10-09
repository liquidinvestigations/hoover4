"""The `control_event` activity: the policy hooks of `AgentRun`.

`AgentRun` calls it at three points: `turn_started` after `open_run`, `tool_batch_completed`
after every call of a batch has its result, and `answer_drafted` after an answer or a
question. The coordinator (`control.coordinator`) stores one decision for each event and
writes its rows. The activity returns ids and small values only: the policy calls that the
workflow runs through `tool_call`, whether a draft gets another round, and the next seq.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P_agent.activities import CallRef
from tasks.P_agent.steps import StepRef

#: The deadline of each hook, in seconds. The workflow sets the activity timeout from the
#: same value, and the activity applies the lower of it and the definition's limit. D7 sets
#: the preparation deadline. The other two are experiment parameters.
HOOK_SECONDS = {"turn_started": 15.0, "tool_batch_completed": 10.0, "answer_drafted": 60.0}

#: The time an activity may take beyond its hook deadline: the reads and writes of the
#: stored thread, and the agent's snapshot and call normalization.
HOOK_MARGIN_SECONDS = 60.0

#: The heartbeat of the activity. A stop reaches it with the next beat.
CONTROL_HEARTBEAT_SECONDS = 2.0


@dataclass
class ControlParams(StepRef):
    #: `turn_started`, `tool_batch_completed` or `answer_drafted`.
    hook: str = ""
    #: The `ai` message of the batch. -1 for the newest model reply, the draft's.
    anchor_idx: int = -1
    deadline_seconds: float = 15.0
    #: True when the run has used its model steps, so no repair round can follow.
    model_limit_reached: bool = False
    #: `answer` or `question` for `answer_drafted`.
    draft_kind: str = ""


@dataclass
class ControlOutcome:
    #: The unanswered calls of the event's policy batch.
    calls: list[CallRef] = field(default_factory=list)
    #: True when a draft note asks for another round.
    round: bool = False
    next_seq: int = 0
    closed: bool = False
    end_turn: bool = False


@activity.defn
@with_heartbeat(interval_seconds=CONTROL_HEARTBEAT_SECONDS)
def control_event(params: ControlParams) -> ControlOutcome:
    """Decide one event and write its rows (`control.coordinator.run_hook`)."""
    from tasks.P_agent.control.coordinator import run_hook

    return run_hook(params)


__all__ = ["CONTROL_HEARTBEAT_SECONDS", "ControlOutcome", "ControlParams", "HOOK_MARGIN_SECONDS",
           "HOOK_SECONDS", "control_event"]
