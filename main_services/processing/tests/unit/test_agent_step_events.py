"""The row builder and the error classes of `agent_step_events`, and its buffer."""

from datetime import datetime, timezone

import pytest
from temporalio.exceptions import (
    ActivityError, CancelledError, RetryState, TimeoutError, TimeoutType,
)

from database import agent_step_events as events
from tasks import task_timing


def _tool_event(**fields) -> events.StepEvent:
    values = dict(username="guest-4f2", session_id="s-1",
                  run_id="7a1f2b3c-0000-4000-8000-000000000001", run_kind="chat",
                  step="tool", name="search_passages", task_queue="agent-tool-queue",
                  attempt=1, ok=True, tool_call_id="call-1", queue_wait_ms=12,
                  duration_ms=340)
    values.update(fields)
    return events.StepEvent(**values)


def test_to_row_of_a_guest_tool_event():
    row = events.to_row(_tool_event(), datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    assert len(row) == 19 == len(events.COLUMNS)
    by_name = dict(zip(events.COLUMNS, row))
    assert by_name["username"] == "guest"
    assert by_name["event_time"] == datetime(2026, 1, 2, 3, 4, 5)
    assert by_name["step"] == "tool"
    assert by_name["tool_call_id"] == "call-1"
    assert by_name["ok"] == 1
    assert by_name["attempt"] == 1


def test_to_row_keeps_a_named_user_and_bounds_the_values():
    row = events.to_row(_tool_event(username="alice", run_id="", error="x" * 900,
                                    duration_ms=-5, ok=False),
                        datetime(2026, 1, 2))
    by_name = dict(zip(events.COLUMNS, row))
    assert by_name["username"] == "alice"
    assert by_name["run_id"] == events.NO_RUN_ID
    assert len(by_name["error"]) == events.ERROR_CHARS
    assert by_name["duration_ms"] == 0
    assert by_name["ok"] == 0


def _wrapped(cause: BaseException) -> ActivityError:
    error = ActivityError("activity failed", scheduled_event_id=1, started_event_id=2,
                          identity="w", activity_type="tool_call", activity_id="1",
                          retry_state=RetryState.TIMEOUT)
    error.__cause__ = cause
    return error


@pytest.mark.parametrize("kind, expected", [
    (TimeoutType.SCHEDULE_TO_START, "schedule_to_start_timeout"),
    (TimeoutType.HEARTBEAT, "heartbeat_timeout"),
    (TimeoutType.START_TO_CLOSE, "start_to_close_timeout"),
])
def test_error_class_of_each_timeout(kind, expected):
    timeout = TimeoutError("timed out", type=kind, last_heartbeat_details=[])
    assert events.error_class_of(timeout) == expected
    assert events.error_class_of(_wrapped(timeout)) == expected


def test_error_class_of_a_cancellation():
    assert events.error_class_of(CancelledError("the run was stopped")) == "cancelled"
    assert events.error_class_of(_wrapped(CancelledError())) == "cancelled"


def _in_an_attempt(monkeypatch, **details):
    from temporalio import activity

    monkeypatch.setattr(activity, "in_activity", lambda: True)
    monkeypatch.setattr(activity, "cancellation_details",
                        lambda: activity.ActivityCancellationDetails(**details))


def test_error_class_of_an_attempt_cancelled_at_its_limit(monkeypatch):
    # The worker cancels an attempt that passed its start-to-close limit.
    _in_an_attempt(monkeypatch, timed_out=True)
    assert events.error_class_of(CancelledError()) == "start_to_close_timeout"
    assert events.error_class_of(ValueError("interrupted")) == "start_to_close_timeout"


def _attempt_info(monkeypatch, elapsed_seconds, limit_seconds):
    from datetime import timedelta
    from types import SimpleNamespace

    from temporalio import activity

    started = datetime.now(timezone.utc) - timedelta(seconds=elapsed_seconds)
    limit = None if limit_seconds is None else timedelta(seconds=limit_seconds)
    monkeypatch.setattr(activity, "info", lambda: SimpleNamespace(
        started_time=started, start_to_close_timeout=limit))


def test_an_attempt_cancelled_at_its_start_to_close_limit_is_that_timeout(monkeypatch):
    _in_an_attempt(monkeypatch, timed_out=True)
    _attempt_info(monkeypatch, elapsed_seconds=600, limit_seconds=600)
    assert events.error_class_of(CancelledError()) == "start_to_close_timeout"
    assert "start_to_close_timeout" not in events.ATTEMPT_WRITES_NO_ROW


def test_an_attempt_cancelled_before_its_limit_lost_its_heartbeat(monkeypatch):
    # The workflow writes the row of this failure, so the attempt writes none.
    _in_an_attempt(monkeypatch, timed_out=True)
    _attempt_info(monkeypatch, elapsed_seconds=45, limit_seconds=600)
    assert events.error_class_of(CancelledError()) == "heartbeat_timeout"
    assert "heartbeat_timeout" in events.ATTEMPT_WRITES_NO_ROW


def test_an_attempt_with_no_start_to_close_limit_lost_its_heartbeat(monkeypatch):
    _in_an_attempt(monkeypatch, timed_out=True)
    _attempt_info(monkeypatch, elapsed_seconds=45, limit_seconds=None)
    assert events.error_class_of(CancelledError()) == "heartbeat_timeout"


def test_error_class_of_an_attempt_cancelled_by_a_stop(monkeypatch):
    _in_an_attempt(monkeypatch, cancel_requested=True)
    assert events.error_class_of(CancelledError()) == "cancelled"


def test_error_class_of_a_service_class_and_the_rest():
    failure = RuntimeError("model server said no")
    failure.error_class = "read_timeout"
    assert events.error_class_of(failure) == "read_timeout"
    assert events.error_class_of(ValueError("boom")) == "other"


def test_attempt_fields_outside_an_activity():
    assert events.attempt_fields() == (1, "", 0)


def test_the_step_buffer_flushes_into_its_table(monkeypatch):
    recorder = task_timing._Recorder()
    monkeypatch.setattr(recorder, "ensure_started", lambda: None)
    inserted = []
    monkeypatch.setattr(recorder, "_insert",
                        lambda db, table, columns, rows: inserted.append((db, table, columns,
                                                                          rows)))
    row = events.to_row(_tool_event(), datetime(2026, 1, 2))
    recorder.record_step(row)
    recorder.flush()
    assert inserted == [("", "agent_step_events", events.COLUMNS, [row])]
    recorder.flush()
    assert len(inserted) == 1


def test_title_usage_tokens():
    from tasks.P_agent.summarize import usage_tokens

    assert usage_tokens({"usage": {"prompt_tokens": 812, "completion_tokens": 31}}) == {
        "prompt_tokens": 812, "completion_tokens": 31}
    assert usage_tokens({}) == {"prompt_tokens": 0, "completion_tokens": 0}
    assert usage_tokens({"usage": {"prompt_tokens": "x"}}) == {
        "prompt_tokens": 0, "completion_tokens": 0}
