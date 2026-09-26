"""The worker's timeouts of an agent run that the model's speed decides.

`workflows.py` reads no environment itself, because workflow code must be deterministic. It
imports `TIMEOUTS` from here, inside `workflow.unsafe.imports_passed_through()`. This module
reads the environment once, at import.

Each variable is rendered by `deploy.py` from a `[main_services]` key. An empty or unset
variable keeps the value the worker used before the key existed.

| variable | key | empty means |
|---|---|---|
| `HOOVER4_AGENT_QUEUE_WAIT_SECONDS` | `agent_queue_wait_seconds` | no schedule-to-start timeout |
| `HOOVER4_CHAT_RUN_TIMEOUT_SECONDS` | `chat_run_timeout_seconds` | 900 s |
| `HOOVER4_PLAN_RUN_TIMEOUT_SECONDS` | `plan_run_timeout_seconds` | 2,400 s |
| `HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS` | `title_request_timeout_seconds` | 30 s |

These are budget bounds, and they follow the measured speed of the model server. The
liveness bounds (the heartbeats, the run-row keepalive, the worker's 300 s read of the agent
stream) stay fixed in their own modules, because a liveness bound that grows with the budget
leaves a dead turn on the screen for hours.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

QUEUE_WAIT_ENV = "HOOVER4_AGENT_QUEUE_WAIT_SECONDS"
CHAT_RUN_ENV = "HOOVER4_CHAT_RUN_TIMEOUT_SECONDS"
PLAN_RUN_ENV = "HOOVER4_PLAN_RUN_TIMEOUT_SECONDS"
TITLE_REQUEST_ENV = "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS"

DEFAULT_CHAT_RUN_SECONDS = 900
DEFAULT_PLAN_RUN_SECONDS = 2400
DEFAULT_TITLE_REQUEST_SECONDS = 30.0


@dataclass(frozen=True)
class ModelTimeouts:
    """The timeouts of one worker process."""

    #: The schedule-to-start timeout of `run_agent`. None sets no limit on the wait for a slot.
    queue_wait: timedelta | None
    #: The start-to-close timeout of `run_agent` for a chat turn.
    chat_run: timedelta
    #: The start-to-close timeout of `run_agent` for a run of a plan.
    plan_run: timedelta
    #: The read timeout of the title request, in seconds.
    title_request_seconds: float

    @property
    def title_activity(self) -> timedelta:
        """The start-to-close timeout of the title activity.

        A 4xx answer makes the title call send a second request, so the activity allows two
        requests and 30 s more: 90 s at a 30 s request, 270 s at 120 s.
        """
        return timedelta(seconds=2 * self.title_request_seconds + 30)


def _seconds(environ: Mapping[str, str], name: str) -> float | None:
    """The number of seconds in `name`, or None when it is unset or empty.

    Raises `ValueError` naming the variable when the value is not a positive number.
    """
    raw = (environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be above 0, got {raw!r}")
    return value


def load(environ: Mapping[str, str] = os.environ) -> ModelTimeouts:
    """Read the timeouts from `environ`. An unset or empty variable keeps its default."""
    queue_wait = _seconds(environ, QUEUE_WAIT_ENV)
    chat_run = _seconds(environ, CHAT_RUN_ENV)
    plan_run = _seconds(environ, PLAN_RUN_ENV)
    title = _seconds(environ, TITLE_REQUEST_ENV)
    return ModelTimeouts(
        queue_wait=timedelta(seconds=queue_wait) if queue_wait is not None else None,
        chat_run=timedelta(seconds=chat_run if chat_run is not None
                           else DEFAULT_CHAT_RUN_SECONDS),
        plan_run=timedelta(seconds=plan_run if plan_run is not None
                           else DEFAULT_PLAN_RUN_SECONDS),
        title_request_seconds=title if title is not None else DEFAULT_TITLE_REQUEST_SECONDS,
    )


TIMEOUTS = load()
