"""Tests for tasks.heartbeat: the pump's contextvars trap and the loop clock.

The pump exists because class C activities block in a subprocess and cannot
heartbeat themselves. Its one unexpected failure mode -- a plain
threading.Thread starts with an EMPTY contextvars context, so calling
activity.heartbeat() from it raises "not in activity context" -- is what
test_pump_fires_from_a_blocked_thread covers.
"""

import time

import pytest
from temporalio import activity

from tasks import heartbeat as hb


class _FakeActivityContext:
    """Minimal stand-in for temporalio's activity context.

    The real one is resolved through a contextvars.ContextVar, which is exactly
    what the pump has to copy; monkeypatching activity.heartbeat and
    activity.in_activity reproduces the call path without a Temporal worker.
    """

    def __init__(self):
        self.beats = []

    def install(self, monkeypatch):
        monkeypatch.setattr(activity, "in_activity", lambda: True)
        monkeypatch.setattr(activity, "heartbeat", lambda *d: self.beats.append(d))
        return self


def test_the_two_constants_hold_the_agreed_relationship():
    # 15 s beat inside a 30 s deadline. The interval must divide into the timeout at
    # least twice or a single missed beat times the activity out; the UPPER bound is the
    # one that is commonly got wrong, because the deadline is also how long a wedged slot
    # is held before the fleet can reuse it. Widening it measurably multiplies retries
    # rather than preventing them -- see the comment on HEARTBEAT_TIMEOUT.
    assert hb.HEARTBEAT_INTERVAL.total_seconds() == 15
    assert hb.HEARTBEAT_TIMEOUT.total_seconds() == 30
    assert 2 * hb.HEARTBEAT_INTERVAL <= hb.HEARTBEAT_TIMEOUT <= 3 * hb.HEARTBEAT_INTERVAL


def test_pump_fires_from_a_blocked_thread(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)
    with hb.heartbeat_pump("extracting", interval_seconds=0.02):
        time.sleep(0.2)          # stands in for a blocking subprocess.run
    assert len(ctx.beats) >= 3, f"pump did not fire while blocked: {ctx.beats}"
    assert all(beat == ("extracting",) for beat in ctx.beats)


def test_pump_stops_when_the_body_exits(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)
    with hb.heartbeat_pump(interval_seconds=0.02):
        time.sleep(0.1)
    settled = len(ctx.beats)
    time.sleep(0.15)
    assert len(ctx.beats) == settled, "pump kept beating after the body finished"


def test_pump_is_inert_outside_an_activity(monkeypatch):
    """Keeps every class C activity unit-testable without a Temporal worker."""
    monkeypatch.setattr(activity, "in_activity", lambda: False)
    with hb.heartbeat_pump("x", interval_seconds=0.01):
        time.sleep(0.05)        # must not raise


def test_pump_survives_a_heartbeat_that_raises(monkeypatch):
    """A cancelled or completed activity makes heartbeat() raise; the pump must
    stop quietly rather than report a spurious error from a daemon thread."""
    monkeypatch.setattr(activity, "in_activity", lambda: True)

    def boom(*_details):
        raise RuntimeError("activity is no longer running")

    monkeypatch.setattr(activity, "heartbeat", boom)
    with hb.heartbeat_pump(interval_seconds=0.01):
        time.sleep(0.08)


def test_clock_rate_limits_in_loop_heartbeats(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)
    clock = hb.HeartbeatClock(interval_seconds=0.05)

    assert clock.beat("0/100") is True, "first iteration must always beat"
    assert clock.beat("1/100") is False, "a tight loop must not beat every pass"
    time.sleep(0.06)
    assert clock.beat("2/100") is True

    assert [d[0] for d in ctx.beats] == ["0/100", "2/100"]


@pytest.mark.parametrize("in_activity", [True, False])
def test_clock_never_raises_outside_an_activity(monkeypatch, in_activity):
    monkeypatch.setattr(activity, "in_activity", lambda: in_activity)
    monkeypatch.setattr(activity, "heartbeat", lambda *d: None)
    assert hb.HeartbeatClock(interval_seconds=0).beat("x") is True


# send_heartbeat and batch_progress: the batch detail goes first on every send.

class _Progress:
    def __init__(self, detail):
        self.detail = detail

    def heartbeat_detail(self):
        return self.detail


def _install_attempt(monkeypatch, attempt=1):
    info = type("Info", (), {"workflow_run_id": "run", "activity_id": "1", "attempt": attempt})
    monkeypatch.setattr(activity, "info", lambda: info)


def test_every_send_of_the_module_puts_the_batch_detail_first(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)
    _install_attempt(monkeypatch)
    detail = {"v": 2}
    with hb.batch_progress(_Progress(detail)):
        hb.HeartbeatClock(interval_seconds=0).beat("clock")
        with hb.heartbeat_pump("pump", interval_seconds=0.02):
            time.sleep(0.1)
        monkeypatch.setattr(hb, "worker_is_stopping", lambda: True)
        with pytest.raises(Exception):
            hb.stop_if_worker_is_stopping("stop")
    assert ctx.beats[0] == (detail, "clock")
    assert (detail, "pump") in ctx.beats
    assert ctx.beats[-1] == (detail, "stop")
    assert hb._BATCH_PROGRESS == {}


def test_with_nothing_registered_the_details_pass_unchanged_without_info(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)

    def no_info():
        raise AssertionError("activity.info() was called")

    monkeypatch.setattr(activity, "info", no_info)
    hb.send_heartbeat("a", 1)
    assert ctx.beats == [("a", 1)]


def test_a_progress_that_returns_none_drops_the_heartbeat(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)
    _install_attempt(monkeypatch)
    with hb.batch_progress(_Progress(None)):
        hb.send_heartbeat("dropped")
    assert ctx.beats == []


def test_two_attempts_keep_their_own_registrations(monkeypatch):
    ctx = _FakeActivityContext().install(monkeypatch)
    _install_attempt(monkeypatch, attempt=1)
    with hb.batch_progress(_Progress({"att": 1})):
        _install_attempt(monkeypatch, attempt=2)
        with hb.batch_progress(_Progress({"att": 2})):
            assert len(hb._BATCH_PROGRESS) == 2
            hb.send_heartbeat()
        _install_attempt(monkeypatch, attempt=1)
        hb.send_heartbeat()
    assert ctx.beats == [({"att": 2},), ({"att": 1},)]
