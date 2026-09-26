"""The limits of the steps of an agent run.

`workflows.py` reads no environment itself, because workflow code must be deterministic. It
imports `TIMEOUTS` and the constants from here, inside `workflow.unsafe.imports_passed_through()`.
This module reads the environment once, at import.

Each variable is rendered by `deploy.py` from a `[main_services]` key.

| variable | key | what it bounds | empty means |
|---|---|---|---|
| `HOOVER4_AGENT_QUEUE_WAIT_SECONDS` | `agent_queue_wait_seconds` | the schedule-to-start limit of each `model_step` and `tool_call` | no limit |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `llm_request_timeout_seconds` | the start-to-close limit of one `model_step` | 3,600 s |
| `HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS` | `title_request_timeout_seconds` | the read timeout of the title request | 30 s |

The agent services read `LLM_REQUEST_TIMEOUT_SECONDS` as the read timeout of their model
client, so one model call and the step that waits for it have the same limit.

The constants below have no key. A person fixed each value, and each comment names what the
value bounds. The run has no time budget: `RUN_MODEL_STEPS` bounds its length.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

QUEUE_WAIT_ENV = "HOOVER4_AGENT_QUEUE_WAIT_SECONDS"
MODEL_CALL_ENV = "LLM_REQUEST_TIMEOUT_SECONDS"
TITLE_REQUEST_ENV = "HOOVER4_TITLE_REQUEST_TIMEOUT_SECONDS"

DEFAULT_MODEL_CALL_SECONDS = 3600
DEFAULT_TITLE_REQUEST_SECONDS = 30.0

#: The start-to-close limit of one `tool_call` attempt. A tool that runs longer gets a
#: `tool_unavailable` result after its last attempt, and the model reads it.
TOOL_CALL_TIMEOUT = timedelta(seconds=300)

#: The heartbeat limit of `model_step` and `tool_call`. It is how long a dead worker holds
#: a slot before Temporal retries the step. It stays under the website's stall window
#: `CHAT_STREAM_STALL_SECONDS` (180 s), so the page never gives up on a turn first.
STEP_HEARTBEAT_TIMEOUT = timedelta(seconds=30)

#: The timer of the heartbeat pump of `model_step` and `tool_call`, in seconds. Three beats
#: fit in `STEP_HEARTBEAT_TIMEOUT`, and a stop reaches a running step with the next beat.
STEP_HEARTBEAT_SECONDS = 10.0

#: The model steps of one run thread. The step after the last one is a `final` step that
#: binds no tool, and the run ends `completed` with `end_reason` `step_budget`.
RUN_MODEL_STEPS = 600

#: The model steps of one workflow run. The loop then continues as new, which keeps the
#: workflow history short. The stored thread holds the state, so nothing is lost.
CONTINUE_AS_NEW_STEPS = 250

#: The second continue-as-new trigger: the history length at a step boundary. The shortest
#: measured call of the served model is 13 output tokens, so one step adds at most about
#: 14,800 events, and the history stays under the server limit of 51,200.
HISTORY_EVENTS_PER_RUN = 30_000


@dataclass(frozen=True)
class ModelTimeouts:
    """The timeouts of one worker process."""

    #: The schedule-to-start limit of `model_step` and `tool_call`. None sets no limit.
    queue_wait: timedelta | None
    #: The start-to-close limit of one `model_step`.
    model_call: timedelta
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
    model_call = _seconds(environ, MODEL_CALL_ENV)
    title = _seconds(environ, TITLE_REQUEST_ENV)
    return ModelTimeouts(
        queue_wait=timedelta(seconds=queue_wait) if queue_wait is not None else None,
        model_call=timedelta(seconds=model_call if model_call is not None
                             else DEFAULT_MODEL_CALL_SECONDS),
        title_request_seconds=title if title is not None else DEFAULT_TITLE_REQUEST_SECONDS,
    )


TIMEOUTS = load()
