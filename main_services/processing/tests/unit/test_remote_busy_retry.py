"""Verify busy retry persistence and ordinary activity failure limits."""

import dataclasses
from datetime import timedelta
import json
import time

import pytest
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import ActivityEnvironment

from tasks.remote import RemoteBusy
from tasks.remote_busy_retry import with_remote_busy_retry


def run_attempt(function, attempt, detail, seconds=1000):
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=attempt,
        heartbeat_details=[detail] if detail else [],
        start_to_close_timeout=timedelta(seconds=seconds))
    beats = []
    env.on_heartbeat = lambda *values: beats.append(json.loads(json.dumps(values[0])))
    try:
        return env.run(with_remote_busy_retry(function)), beats, None
    except Exception as exc:
        return None, beats, exc


def test_busy_retries_exceed_five_attempts_and_then_succeed(monkeypatch):
    now, detail, calls = [1000.0], None, []
    monkeypatch.setattr(time, "time", lambda: now[0])
    def request():
        calls.append(1)
        if len(calls) <= 6:
            raise RemoteBusy(5)
        return "done"
    for attempt in range(1, 8):
        result, beats, error = run_attempt(request, attempt, detail)
        if attempt <= 6:
            assert isinstance(error, ApplicationError)
            assert error.type == "RemoteBusy"
            assert error.next_retry_delay == timedelta(seconds=5)
            detail = beats[-1]
            assert detail["first_busy"] == 1000
            assert detail["failures"] == 0
            now[0] += 5
        else:
            assert error is None
            assert result == "done"


def test_busy_budget_expires_across_a_restart(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    def request():
        raise RemoteBusy(5)
    _, beats, _ = run_attempt(request, 1, None, seconds=100)
    now[0] = 1051
    _, _, error = run_attempt(lambda: pytest.fail("The expired request ran."), 2, beats[-1], seconds=100)
    assert error.type == "ServiceStayedBusy"
    assert error.non_retryable


def test_ordinary_failures_stop_after_five_attempts(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    detail = None
    def request():
        raise ValueError("Request failed.")
    for attempt in range(1, 6):
        _, beats, error = run_attempt(request, attempt, detail)
        detail = beats[-1]
        assert detail["failures"] == attempt
        if attempt < 5:
            assert isinstance(error, ValueError)
        else:
            assert error.type == "ValueError"
            assert error.non_retryable


def test_cancellation_remains_cancellation():
    def request():
        raise CancelledError("Cancelled.")
    _, beats, error = run_attempt(request, 1, None)
    assert isinstance(error, CancelledError)
    assert beats[-1]["failures"] == 0


def test_a_prior_busy_response_does_not_end_an_ordinary_retry(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 2000.0)
    detail = {"remote_retry": 1, "first_busy": 1000.0, "busy_retry": False,
              "failures": 1, "attempt": 2, "running": False}
    result, _, error = run_attempt(lambda: "done", 3, detail, seconds=100)
    assert result == "done"
    assert error is None


def test_a_timed_out_attempt_that_saved_progress_is_not_a_failure(monkeypatch):
    """A long NER plan saves batches and reaches its timeout. Its retries continue the work."""
    from tasks.heartbeat import send_heartbeat
    from tasks.remote_busy_retry import record_saved_progress
    monkeypatch.setattr(time, "time", lambda: 1000.0)

    def saves_then_times_out():
        record_saved_progress()
        send_heartbeat("NER saved")
        raise CancelledError("Cancelled.")

    detail = None
    for attempt in range(1, 9):
        _, beats, error = run_attempt(saves_then_times_out, attempt, detail)
        assert isinstance(error, CancelledError)
        detail = beats[-1]
        assert detail["saved"] is True and detail["running"] is True
    result, beats, error = run_attempt(lambda: "done", 9, detail)
    assert error is None and result == "done"
    assert beats[-1]["failures"] == 0


def test_timed_out_attempts_without_saved_progress_use_the_limit_and_name_the_cause(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    detail = {"remote_retry": 1, "failures": 4, "attempt": 5, "running": True, "saved": False}
    _, _, error = run_attempt(lambda: pytest.fail("The used limit ran the request."), 6, detail)
    assert error.non_retryable and error.type == "FailureLimit"
    assert str(error).endswith("The last failure: an attempt ended without a result")


def test_the_failure_limit_names_the_last_exception(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    detail = None
    for attempt in range(1, 5):
        def fails():
            raise ValueError("NER service returned incomplete text results")
        _, beats, _ = run_attempt(fails, attempt, detail)
        detail = beats[-1]
    # The fifth attempt reaches its timeout after it saved nothing.
    detail = dict(detail, running=True, attempt=5)
    _, _, error = run_attempt(lambda: pytest.fail("The used limit ran the request."), 6, detail)
    assert "an attempt ended without a result" in str(error)
    detail = dict(detail, running=False, failures=5)
    _, _, error = run_attempt(lambda: pytest.fail("The used limit ran the request."), 6, detail)
    assert "ValueError: NER service returned incomplete text results" in str(error)
