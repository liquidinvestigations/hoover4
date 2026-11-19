"""Preserve busy budgets, outage budgets and ordinary failure limits across activity retries.

The state of each budget is in the heartbeat details. Temporal gives those details to the
next attempt of the activity, also after a worker restart, so the budgets continue.

`with_remote_busy_retry` waits for a busy answer (`RemoteBusy`). `with_remote_outage_retry`
also waits for a service that refuses connections (`RemoteOutage`), for at most
`OUTAGE_BUDGET_SECONDS` from the first refused attempt. The delay between those attempts
grows from `OUTAGE_FIRST_DELAY_SECONDS` to `OUTAGE_MAX_DELAY_SECONDS`. Temporal schedules
the next attempt, so a waiting activity holds no worker slot. Neither wait uses the ordinary
failure limit `ACTIVITY_MAX_ATTEMPTS`. The workflow must schedule the activity with
unlimited Temporal attempts, because this wrapper enforces both limits.
"""

import functools
import time
from datetime import timedelta

from temporalio import activity
from temporalio.exceptions import ApplicationError

from tasks.failure_chain import is_cancellation
from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, batch_progress, send_heartbeat, worker_is_stopping
from tasks.remote import RemoteBusy, RemoteOutage

#: How long a NER or embedding activity waits for a service that refuses connections.
OUTAGE_BUDGET_SECONDS = 12 * 3600
#: The delay before the first attempt after a refused connection. It doubles each time.
OUTAGE_FIRST_DELAY_SECONDS = 5
#: The longest delay between two attempts during an outage.
OUTAGE_MAX_DELAY_SECONDS = 120


class _RetryState:
    def __init__(self, info):
        details = info.heartbeat_details
        previous = details[0] if details and isinstance(details[0], dict) else {}
        if previous.get("remote_retry") != 1:
            previous = {}
        self.detail = dict(previous)
        failures = int(previous.get("failures", info.attempt - 1))
        if previous.get("running") and not previous.get("busy_retry") and not previous.get("saved"):
            # The attempt ended without a result, for example at its timeout or with its
            # worker. An attempt that saved progress first is not a failure: its retry
            # continues after the saved work, and the remaining work becomes smaller.
            failures += max(1, info.attempt - int(previous.get("attempt", info.attempt - 1)))
            self.detail["last_error"] = "an attempt ended without a result"
        self.detail.update(remote_retry=1, failures=failures, attempt=info.attempt, running=True,
                           saved=False)
        timeout = info.start_to_close_timeout
        self.busy_budget = timeout.total_seconds() / 2 if timeout else 900.0

    def heartbeat_detail(self):
        return dict(self.detail)

    def failure_limit_error(self) -> ApplicationError:
        """The non-retryable error of a used failure limit. It names the last failure."""
        cause = self.detail.get("last_error") or "an attempt ended without a result"
        return ApplicationError(f"The activity failure limit is used. The last failure: {cause}",
                                type="FailureLimit", non_retryable=True)

    def busy_expired(self, delay=0):
        first = self.detail.get("first_busy")
        return first is not None and time.time() + delay - first >= self.busy_budget

    def fail_busy(self):
        raise ApplicationError("The activity busy budget is used.",
                               type="ServiceStayedBusy", non_retryable=True)

    def outage_expired(self, delay=0):
        first = self.detail.get("first_outage")
        return first is not None and time.time() + delay - first >= OUTAGE_BUDGET_SECONDS

    def outage_delay(self) -> float:
        retries = int(self.detail.get("outage_retries", 0))
        return float(min(OUTAGE_MAX_DELAY_SECONDS, OUTAGE_FIRST_DELAY_SECONDS * 2 ** min(retries, 10)))

    def fail_outage(self):
        cause = self.detail.get("last_outage") or "the service refused the connection"
        raise ApplicationError(
            f"The service stayed unavailable for {OUTAGE_BUDGET_SECONDS // 3600} hours. "
            f"The last failure: {cause}", type="ServiceOutage", non_retryable=True)


def with_remote_busy_retry(fn, *, outage: bool = False):
    """Retry busy answers without consuming the ordinary failure budget.

    With `outage`, also retry `RemoteOutage` within the outage budget. See the module docstring.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not activity.in_activity():
            return fn(*args, **kwargs)
        state = _RetryState(activity.info())
        with batch_progress(state):
            if state.detail.get("busy_retry") and state.busy_expired():
                state.fail_busy()
            if outage and state.detail.get("outage_retry") and state.outage_expired():
                state.fail_outage()
            if state.detail["failures"] >= ACTIVITY_MAX_ATTEMPTS:
                raise state.failure_limit_error()
            send_heartbeat()
            try:
                result = fn(*args, **kwargs)
                if state.detail.pop("first_outage", None) is not None:
                    state.detail.update(outage_retry=False, outage_retries=0)
                return result
            except RemoteOutage as exc:
                if not outage:
                    return _ordinary_failure(state, exc)
                if is_cancellation(exc) or worker_is_stopping():
                    raise
                state.detail.setdefault("first_outage", time.time())
                delay = state.outage_delay()
                state.detail.update(running=False, busy_retry=False, outage_retry=True,
                                    outage_retries=int(state.detail.get("outage_retries", 0)) + 1,
                                    last_outage=f"{type(exc).__name__}: {exc}"[:300])
                send_heartbeat()
                if state.outage_expired(delay):
                    state.fail_outage()
                raise ApplicationError(str(exc)[:1000], type="RemoteOutage",
                    next_retry_delay=timedelta(seconds=delay)) from exc
            except RemoteBusy as exc:
                state.detail.setdefault("first_busy", time.time())
                state.detail.update(running=False, busy_retry=True)
                send_heartbeat()
                if state.busy_expired(exc.retry_after_seconds):
                    state.fail_busy()
                raise ApplicationError(str(exc), type="RemoteBusy",
                    next_retry_delay=timedelta(seconds=exc.retry_after_seconds)) from exc
            except Exception as exc:
                if is_cancellation(exc) or worker_is_stopping():
                    raise
                return _ordinary_failure(state, exc)
    return wrapper


def _ordinary_failure(state: _RetryState, exc: BaseException):
    """Count one ordinary failure and raise. The last allowed failure is non-retryable."""
    state.detail.update(running=False, busy_retry=False, outage_retry=False,
                        failures=state.detail["failures"] + 1,
                        last_error=f"{type(exc).__name__}: {exc}"[:300])
    send_heartbeat()
    if state.detail["failures"] >= ACTIVITY_MAX_ATTEMPTS:
        raise ApplicationError(str(exc), type=getattr(exc, "type", "") or type(exc).__name__,
                               non_retryable=True) from exc
    raise exc


def with_remote_outage_retry(fn):
    """`with_remote_busy_retry` that also waits for a refused NER or embedding service."""
    return with_remote_busy_retry(fn, outage=True)


def record_saved_progress() -> None:
    """Record that this attempt saved durable work that its retry skips.

    `with_remote_busy_retry` then does not count the attempt as a failure when it ends
    without a result. Outside such an attempt nothing is recorded.
    """
    from tasks.heartbeat import _BATCH_PROGRESS, _attempt_key
    if not activity.in_activity():
        return
    state = _BATCH_PROGRESS.get(_attempt_key())
    if isinstance(state, _RetryState):
        state.detail["saved"] = True
