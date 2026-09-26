"""The rows of `agent_step_events`: one for each attempt of an agent model call, tool call
and title call.

The step activities build a `StepEvent` in their `finally` block and hand it to `record`,
which buffers the row on the timing daemon of `tasks/task_timing.py`. Each attempt that
starts writes one row. An attempt that passes its start-to-close limit on a live worker is
cancelled with the reason `timed_out`, and writes its own row with `start_to_close_timeout`.
The workflow writes the row of a step that never started or lost its heartbeat, with
`attempt` 0, because no attempt can write that row. Nothing here raises into an activity:
a lost row costs a report, not a turn.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

#: The columns of `agent_step_events`, in the order of `to_row`.
COLUMNS = [
    "event_time", "username", "session_id", "run_id", "run_kind", "step", "mode", "name",
    "tool_call_id", "task_queue", "attempt", "queue_wait_ms", "duration_ms", "ok",
    "error_class", "error", "prompt_tokens", "completion_tokens", "reasoning_tokens",
]

#: The run id of a row whose run is not known.
NO_RUN_ID = "00000000-0000-0000-0000-000000000000"

#: The characters of the error text that a row keeps.
ERROR_CHARS = 500

#: The largest value of a `UInt32` column.
_UINT32_MAX = 2**32 - 1


@dataclass
class StepEvent:
    """One attempt of one step."""

    username: str
    session_id: str
    run_id: str
    #: `chat`, `subagent`, `planner`, `organizer` or `title`.
    run_kind: str
    #: `model`, `tool` or `title`.
    step: str
    #: The tool name of a tool step, the model id of a model or title step.
    name: str
    task_queue: str
    #: The Temporal attempt, 1 for the first. 0 when the workflow writes the row.
    attempt: int
    ok: bool
    #: `tools`, `final` or `plan` for a model step.
    mode: str = ""
    tool_call_id: str = ""
    queue_wait_ms: int = 0
    duration_ms: int = 0
    error_class: str = ""
    error: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0


def row_username(username: str) -> str:
    """Guests are one bucket, because a guest name is new for each session."""
    name = (username or "").strip()
    if not name or name == "guest" or name.startswith("guest-"):
        return "guest"
    return name


def _uuid_text(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        return NO_RUN_ID


def _uint(value: int, top: int = _UINT32_MAX) -> int:
    try:
        return min(max(int(value), 0), top)
    except (ValueError, TypeError):
        return 0


def to_row(event: StepEvent, now: datetime) -> list:
    """The 19 values of one row, in the order of `COLUMNS`."""
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)
    return [
        now,
        row_username(event.username),
        event.session_id,
        _uuid_text(event.run_id),
        event.run_kind,
        event.step,
        event.mode,
        event.name,
        event.tool_call_id,
        event.task_queue,
        _uint(event.attempt, 65_535),
        _uint(event.queue_wait_ms),
        _uint(event.duration_ms),
        1 if event.ok else 0,
        event.error_class,
        (event.error or "")[:ERROR_CHARS],
        _uint(event.prompt_tokens),
        _uint(event.completion_tokens),
        _uint(event.reasoning_tokens),
    ]


def error_class_of(exc: Optional[BaseException]) -> str:
    """The short class of a step failure, walking the cause chain.

    A Temporal timeout gives `schedule_to_start_timeout`, `heartbeat_timeout` or
    `start_to_close_timeout`. An exception in an attempt that the worker cancelled because
    it timed out also gives `start_to_close_timeout`. The worker keeps beating, so the
    limit that passed is the start-to-close limit. A cancellation gives `cancelled`. An exception with an
    `error_class` attribute, which the agent service's error frame sets, gives that class.
    A refused model request with no class gives `model_request_rejected`. A read timeout
    of the agent service gives `read_timeout`. Anything else gives `other`.
    """
    import asyncio

    import requests
    from temporalio.exceptions import CancelledError, TimeoutError, TimeoutType

    timeouts = {
        TimeoutType.SCHEDULE_TO_START: "schedule_to_start_timeout",
        TimeoutType.HEARTBEAT: "heartbeat_timeout",
        TimeoutType.START_TO_CLOSE: "start_to_close_timeout",
    }
    seen = exc
    while seen is not None:
        if isinstance(seen, TimeoutError) and seen.type in timeouts:
            return timeouts[seen.type]
        if _attempt_timed_out():
            return "start_to_close_timeout"
        if isinstance(seen, (CancelledError, asyncio.CancelledError)):
            return "cancelled"
        named = getattr(seen, "error_class", None)
        if isinstance(named, str) and named:
            return named
        if type(seen).__name__ == "ModelRequestRejected":
            return "model_request_rejected"
        if isinstance(seen, requests.exceptions.ReadTimeout):
            return "read_timeout"
        seen = seen.__cause__
    return "other"


def _attempt_timed_out() -> bool:
    """The running activity attempt was cancelled because it timed out. False outside an
    activity."""
    try:
        from temporalio import activity

        if not activity.in_activity():
            return False
        details = activity.cancellation_details()
        return details is not None and bool(details.timed_out)
    except Exception:  # noqa: BLE001 - a class is never worth a failed step
        return False


def attempt_fields() -> tuple[int, str, int]:
    """`(attempt, task_queue, queue_wait_ms)` of the running activity attempt.

    The queue wait is the start of this attempt minus its schedule, so a retry counts only
    its own wait. Outside an activity the answer is `(1, "", 0)`.
    """
    try:
        from temporalio import activity

        if not activity.in_activity():
            return 1, "", 0
        info = activity.info()
        started = info.started_time
        scheduled = info.current_attempt_scheduled_time
        wait = 0
        if started is not None and scheduled is not None:
            wait = int((started - scheduled).total_seconds() * 1000)
        return int(info.attempt), info.task_queue or "", max(wait, 0)
    except Exception:  # noqa: BLE001 - a row with no attempt fields is still a row
        return 1, "", 0


def record(event: StepEvent) -> None:
    """Buffer the row of one event on the timing daemon. Never raises."""
    try:
        from tasks.task_timing import record_step_event

        record_step_event(to_row(event, datetime.now(timezone.utc)))
    except Exception:  # noqa: BLE001 - a step event is never worth a failed step
        log.debug("agent_step_events: could not buffer a row", exc_info=True)
