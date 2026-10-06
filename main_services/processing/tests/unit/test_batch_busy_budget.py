"""Verify busy delays, scheduling, restart persistence, and bounded attempts."""

import dataclasses
from datetime import datetime, timedelta, timezone
import json
import time

import pytest
from temporalio.testing import ActivityEnvironment

from tasks.P3_parse_files import batch_runner as br
from tasks.remote import RemoteBusy


class Ended(BaseException):
    pass


class Clock:
    now = 1_000_000.0
    deadline = None
    kill = None

    def advance(self, seconds):
        target = self.now + max(0, seconds)
        for limit in (self.deadline, self.kill):
            if limit is not None and self.now < limit <= target:
                self.now = limit
                raise Ended()
        self.now = target


def simulate(monkeypatch, scripts, kills=()):
    clock = Clock()
    monkeypatch.setattr(time, "time", lambda: clock.now)
    monkeypatch.setattr(time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(br, "_wait", clock.advance)
    files = list(scripts)
    timeout = br.stage_timeout_seconds("tika_text_batch", [0] * len(files))
    detail, calls, success_times, endings = None, {}, {}, []
    kills = list(kills)
    start = clock.now

    def step(name):
        index = calls.get(name, 0)
        calls[name] = index + 1
        event = scripts[name][min(index, len(scripts[name]) - 1)]
        clock.advance(event[1])
        if event[0] == "busy":
            raise RemoteBusy(event[2])
        if event[0] == "fail":
            raise RuntimeError("Service failed.")
        success_times[name] = clock.now - start
        return name

    for attempt in range(1, 13):
        env = ActivityEnvironment()
        env.info = dataclasses.replace(env.info, attempt=attempt,
            started_time=datetime.fromtimestamp(clock.now, timezone.utc),
            start_to_close_timeout=timedelta(seconds=timeout),
            heartbeat_details=[detail] if detail else [])
        def beat(*details):
            nonlocal detail
            detail = json.loads(json.dumps(details[0]))
        env.on_heartbeat = beat
        clock.deadline = clock.now + timeout
        clock.kill = start + kills.pop(0) if kills else None
        try:
            result = env.run(lambda: br.run_batch("tika_text_batch", files,
                key=lambda name: name, size=lambda _name: 0, task_name="parse", step=step))
        except Ended:
            endings.append(clock.now - start)
            clock.kill = clock.deadline = None
            clock.advance(30)
            continue
        return result, success_times, clock.now - start, endings, timeout
    raise AssertionError("The activity exceeded the simulation attempt limit.")


SLOW = {
    "A": [("busy", 300, 120)],
    "B": [("busy", 300, 120)],
    "C": [("busy", 300, 120), ("busy", 300, 120), ("ok", 300)],
}


@pytest.mark.parametrize("kills", [(), (5000,), (5000, 10000)])
def test_shared_budget_survives_restarts_and_starts_new_files(monkeypatch, kills):
    result, times, elapsed, endings, timeout = simulate(monkeypatch, SLOW, kills)
    assert times["C"] < 3000
    assert elapsed < timeout
    assert elapsed <= 15100
    assert endings == list(kills)
    assert [(r.item_hash, r.status, r.error_type, r.attempts) for r in result.results] == [
        ("A", "failed", "ServiceStayedBusy", 0),
        ("B", "failed", "ServiceStayedBusy", 0),
        ("C", "ok", "", 1),
    ]


def test_busy_wait_reserves_time_after_ordinary_failures(monkeypatch):
    scripts = {"A": [("ok", 60)],
               "B": [("fail", 1890)] * 4 + [("busy", 60, 120)],
               "C": [("fail", 1890)] * 4 + [("busy", 60, 120)]}
    result, _, elapsed, endings, timeout = simulate(monkeypatch, scripts)
    assert not endings
    assert elapsed < timeout
    assert result.results[0].status == "ok"
    assert all(row.error_type == "ServiceStayedBusy" and row.attempts == 4 for row in result.results[1:])


def test_busy_twice_then_success_uses_one_try(monkeypatch):
    result, _, elapsed, endings, _ = simulate(monkeypatch, {
        "A": [("busy", 1, 30), ("busy", 1, 30), ("ok", 1)],
    })
    assert not endings
    assert elapsed == 63
    assert result.results[0].status == "ok"
    assert result.results[0].attempts == 1


def test_a_lost_busy_retry_does_not_consume_the_lost_attempt_limit(monkeypatch):
    now = 1_000_100.0
    monkeypatch.setattr(time, "time", lambda: now)
    detail = {"v": br.BATCH_DETAIL_VERSION, "stage": "tika_text_batch",
              "keys": br.stage_keys_digest(["A"]), "att": 1, "prog": 1,
              "done": [], "wait": [], "busy0": 1_000_000_000,
              "run": [0, 1, 1_000_000_000, True, 1_000_000_000], "lost": {}}
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, attempt=10, heartbeat_details=[detail],
        started_time=datetime.fromtimestamp(now, timezone.utc),
        start_to_close_timeout=timedelta(seconds=br.stage_timeout_seconds("tika_text_batch", [0])))
    result = env.run(lambda: br.run_batch("tika_text_batch", ["A"],
        key=lambda name: name, size=lambda _name: 0, task_name="parse", step=lambda name: name))
    assert result.results[0].status == "ok"
    assert result.results[0].attempts == 1
