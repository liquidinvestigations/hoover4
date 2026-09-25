"""Tests for the batch runner of the stage activities.

Each test runs `run_batch` through `temporalio.testing.ActivityEnvironment`, so the
heartbeat details that the server would keep are captured by `on_heartbeat`. The wall
clock of the wait list and the sleep between retries are patched, so no test waits for a
real backoff.
"""

import dataclasses
import json
import time

import pytest
from temporalio.converter import PayloadConverter
from temporalio.exceptions import ApplicationError, CancelledError
from temporalio.testing import ActivityEnvironment

from tasks import heartbeat as hb
from tasks.P3_parse_files import batch_runner as br
from tasks.payload_guard import payload_size
from tasks.task_timing import SkippedOutcome

STAGE = "detect_mime_batch"


class _Clock:
    """A wall clock in seconds that only the patched wait moves."""

    def __init__(self):
        self.now = 1_790_000_000.0
        self.waits = []

    def time(self):
        return self.now

    def wait(self, seconds):
        self.waits.append(seconds)
        self.now += max(0.0, seconds)


@pytest.fixture
def clock(monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(time, "time", fake.time)
    monkeypatch.setattr(br, "_wait", fake.wait)
    return fake


class _Run:
    """One attempt of a stage activity in an ActivityEnvironment."""

    def __init__(self, attempt=1, detail=None):
        self.env = ActivityEnvironment()
        self.env.info = dataclasses.replace(
            self.env.info, attempt=attempt,
            heartbeat_details=[] if detail is None else [detail])
        self.beats = []
        self.env.on_heartbeat = lambda *details: self.beats.append(details)

    def run(self, items, step, stage=STAGE, task_name="detect_mime_all"):
        return self.env.run(lambda: br.run_batch(
            stage, items, key=lambda item: f"h{item}", size=lambda item: 0,
            step=step, task_name=task_name))

    def last_detail(self):
        """The last detail as the server keeps it, after a JSON round trip."""
        return json.loads(json.dumps(self.beats[-1][0]))


def _record(calls, fail=None):
    """A step that records each call and raises `fail(item, count)` when it is set."""
    def step(item):
        calls.append(item)
        error = fail(item, calls.count(item)) if fail else None
        if error is not None:
            raise error
        return {"item": item}
    return step


def _keys(count):
    return [f"h{index}" for index in range(count)]


# Results and heartbeats.

def test_three_items_give_three_ok_results_in_input_order(clock):
    run = _Run()
    result = run.run([0, 1, 2], _record([]))
    assert result.stage == STAGE
    assert [r.item_hash for r in result.results] == ["h0", "h1", "h2"]
    assert [r.status for r in result.results] == ["ok"] * 3
    assert [r.value for r in result.results] == [{"item": 0}, {"item": 1}, {"item": 2}]
    assert all(r.attempts == 1 and r.task_name == "detect_mime_all" for r in result.results)


def test_a_skipped_outcome_gives_skipped_and_the_unwrapped_value(clock):
    result = _Run().run([0], lambda item: SkippedOutcome({"why": "empty"}))
    assert result.results[0].status == "skipped"
    assert result.results[0].value == {"why": "empty"}


def test_each_try_heartbeats_its_run_and_each_finished_file_adds_one_done_row(clock):
    run = _Run()
    run.run([0, 1, 2], _record([]))
    starts = [beat[0] for beat in run.beats if beat[0]["run"] is not None]
    assert [detail["run"][0] for detail in starts] == [0, 1, 2]
    assert [len(detail["done"]) for detail in starts] == [0, 1, 2]
    assert len(run.beats[-1][0]["done"]) == 3
    assert run.beats[-1][0]["run"] is None


def test_zero_items_give_an_empty_result(clock):
    assert _Run().run([], _record([])) == br.BatchResult(stage=STAGE, results=[])


@pytest.mark.parametrize("change", [{"stage": "run_tika_batch"}, {"v": 1}, {"keys": "0" * 16}])
def test_a_detail_of_another_stage_version_or_input_restores_nothing(clock, change):
    first = _Run()
    first.run([0, 1], _record([]))
    detail = {**first.last_detail(), **change}
    calls = []
    _Run(attempt=2, detail=detail).run([0, 1], _record(calls))
    assert calls == [0, 1]


def test_stage_timeout_seconds_is_five_try_budgets_and_the_waits_of_each_file():
    # Each file: 5 tries at 900 + ceil(size / 1250) s, and 1 + 2 + 4 + 8 s of waits.
    assert br.stage_timeout_seconds("detect_mime_batch", [0, 1250, 2500]) == 13560
    assert br.stage_timeout_seconds("run_tika_batch", [0, 1250, 2500]) == 28560
    assert br.stage_timeout_seconds("run_ocr_pdf_batch", [0, 1250, 2500]) == 54045


# The catch rule.

def test_a_non_retryable_error_fails_the_file_after_one_try(clock):
    calls = []
    fail = lambda item, n: (ApplicationError("copy gone", type="TempCopyMissing",
                                             non_retryable=True) if item == 1 else None)
    result = _Run().run([0, 1, 2], _record(calls, fail))
    failed = result.results[1]
    assert (failed.status, failed.error_type, failed.attempts) == ("failed", "TempCopyMissing", 1)
    assert failed.non_retryable is True
    assert calls == [0, 1, 2]
    assert clock.waits == []


def test_a_runtime_error_twice_then_success_is_ok_after_three_tries(clock):
    fail = lambda item, n: RuntimeError("flaky") if n <= 2 else None
    result = _Run().run([0], _record([], fail))
    assert (result.results[0].status, result.results[0].attempts) == ("ok", 3)


def test_a_runtime_error_every_time_fails_after_five_tries(clock):
    calls = []
    result = _Run().run([0], _record(calls, lambda item, n: RuntimeError("always")))
    assert (result.results[0].status, result.results[0].attempts) == ("failed", 5)
    assert result.results[0].error_type == "RuntimeError"
    assert len(calls) == 5
    assert clock.waits == [1, 2, 4, 8]


def test_a_cancelled_error_propagates(clock):
    with pytest.raises(CancelledError):
        _Run().run([0], _record([], lambda item, n: CancelledError("cancelled")))


def test_a_worker_shutdown_between_tries_raises_a_retryable_error(clock):
    run = _Run()

    def step(item):
        run.env.worker_shutdown()
        return item

    with pytest.raises(ApplicationError) as raised:
        run.run([0, 1], step)
    assert raised.value.non_retryable is False
    assert "shutting down" in str(raised.value)


# The wait list.

def test_a_file_that_raises_once_waits_while_the_next_files_run(clock):
    calls = []
    _Run().run([0, 1, 2], _record(calls, lambda item, n: RuntimeError() if (item, n) == (0, 1) else None))
    assert calls == [0, 1, 2, 0]
    assert clock.waits == [1.0]


def test_when_every_file_waits_the_runner_sleeps_once(clock):
    calls = []
    result = _Run().run([0, 1, 2], _record(calls, lambda item, n: RuntimeError() if n == 1 else None))
    assert calls == [0, 1, 2, 0, 1, 2]
    assert clock.waits == [1.0]
    assert [r.attempts for r in result.results] == [2, 2, 2]


def test_a_due_retry_runs_before_the_next_new_file(clock):
    calls = []

    def step(item):
        calls.append(item)
        if item == 0 and calls.count(0) == 1:
            raise RuntimeError("once")
        if item == 1:
            clock.now += 2
        return item

    _Run().run([0, 1, 2], step)
    assert calls == [0, 1, 0, 2]
    assert clock.waits == []


# Resume and lost attempts.

def _die_at(index):
    def fail(item, n):
        return KeyboardInterrupt() if item == index else None
    return fail


def test_a_resumed_attempt_runs_the_suspect_first_and_keeps_the_finished_results(clock):
    items = list(range(100))
    first = _Run()
    with pytest.raises(KeyboardInterrupt):
        first.run(items, _record([], _die_at(57)))
    detail = first.last_detail()
    assert len(detail["done"]) == 57
    assert detail["run"][0] == 57

    calls = []
    second = _Run(attempt=2, detail=detail).run(items, _record(calls))
    assert calls == [57] + list(range(58, 100))
    restored = {row["i"]: row for row in detail["done"]}
    for index in range(57):
        assert second.results[index].value == restored[index]["value"]
        assert second.results[index].status == "ok"
    assert len(second.results) == 100


def test_a_detail_with_every_file_done_runs_nothing(clock):
    first = _Run()
    first.run(list(range(100)), _record([]))
    calls = []
    result = _Run(attempt=2, detail=first.last_detail()).run(list(range(100)), _record(calls))
    assert calls == []
    assert len(result.results) == 100


def test_a_cut_row_runs_again(clock):
    first = _Run()
    first.run([0, 1], lambda item: "x" * 3000 if item == 0 else item)
    detail = first.last_detail()
    assert detail["done"][0] == {"i": 0, "cut": True}
    calls = []
    _Run(attempt=2, detail=detail).run([0, 1], _record(calls))
    assert calls == [0]


def test_a_file_that_ends_two_attempts_gets_stage_attempt_lost(clock):
    items = list(range(100))
    first = _Run()
    with pytest.raises(KeyboardInterrupt):
        first.run(items, _record([], _die_at(57)))
    second = _Run(attempt=2, detail=first.last_detail())
    with pytest.raises(KeyboardInterrupt):
        second.run(items, _record([], _die_at(57)))
    assert second.last_detail()["lost"] == {"57": 1}

    calls = []
    third = _Run(attempt=3, detail=second.last_detail()).run(items, _record(calls))
    lost = third.results[57]
    assert (lost.status, lost.error_type) == ("failed", br.STAGE_ATTEMPT_LOST)
    assert calls == list(range(58, 100))


# The time limit of one try.

def test_a_heartbeat_after_the_try_limit_is_dropped_and_the_try_raises(clock, monkeypatch):
    monkeypatch.setattr(br, "try_budget_seconds", lambda stage, size: 0.2)
    run = _Run()

    def step(item):
        time.sleep(0.3)
        hb.send_heartbeat("inner")
        return item

    with pytest.raises(ApplicationError) as raised:
        run.run([0, 1], step)
    assert raised.value.type == br.FILE_TRY_TIMED_OUT
    assert all(beat[1:] != ("inner",) for beat in run.beats)
    assert run.beats[-1][0]["run"][0] == 0
    # The next attempt counts one lost attempt for that file and runs it first.
    calls = []
    monkeypatch.setattr(br, "try_budget_seconds", lambda stage, size: 60)
    _Run(attempt=2, detail=run.last_detail()).run([0, 1], _record(calls))
    assert calls == [0, 1]


def test_a_step_that_returns_before_the_limit_keeps_its_heartbeats(clock):
    run = _Run()

    def step(item):
        hb.send_heartbeat("inner")
        return item

    result = run.run([0], step)
    assert result.results[0].status == "ok"
    assert [beat[1:] for beat in run.beats if len(beat) > 1] == [("inner",)]


# No progress.

def _detail_with(stage=STAGE, keys=None, **fields):
    detail = {"v": br.BATCH_DETAIL_VERSION, "stage": stage,
              "keys": br.stage_keys_digest(keys or _keys(2)), "att": 1, "prog": 1,
              "done": [], "wait": [], "run": None, "lost": {}}
    detail.update(fields)
    return detail


def test_five_attempts_without_progress_raise_stage_no_progress(clock):
    detail = _detail_with()
    with pytest.raises(ApplicationError) as raised:
        _Run(attempt=7, detail=detail).run([0, 1], _record([]))
    assert raised.value.type == br.STAGE_NO_PROGRESS
    assert raised.value.non_retryable is True
    assert raised.value.details[0]["prog"] == 1


def test_four_attempts_without_progress_still_run(clock):
    calls = []
    _Run(attempt=6, detail=_detail_with()).run([0, 1], _record(calls))
    assert calls == [0, 1]


def test_a_lost_file_counts_as_progress(clock):
    detail = _detail_with(att=6, run=[0, 1, 1_790_000_000_000], lost={"0": 1})
    calls = []
    result = _Run(attempt=7, detail=detail).run([0, 1], _record(calls))
    assert result.results[0].error_type == br.STAGE_ATTEMPT_LOST
    assert calls == [1]


# The size of the detail.

def test_the_detail_of_100_failed_files_stays_under_256_kib(clock):
    message = "ش" * 5000

    def step(item):
        raise ApplicationError(message + "\n" + "ص" * 20000, type="TikaParseFailed",
                               non_retryable=True)

    run = _Run()
    result = run.run(list(range(100)), step)
    assert all(r.status == "failed" for r in result.results)
    detail = run.beats[-1][0]
    assert all("cut" not in row for row in detail["done"])
    assert payload_size(PayloadConverter.default.to_payloads([detail])[0]) < 262_144


def test_stage_failure_results_keep_the_finished_files_of_the_detail(clock):
    first = _Run()
    with pytest.raises(KeyboardInterrupt):
        first.run([0, 1, 2], _record([], _die_at(2)))
    detail = first.last_detail()
    error = ApplicationError("stuck", detail, type=br.STAGE_NO_PROGRESS, non_retryable=True)
    results = br.stage_failure_results(STAGE, _keys(3), error)
    assert [r.status for r in results] == ["ok", "ok", "failed"]
    assert results[2].error_type == br.STAGE_NO_PROGRESS
    assert results[2].error_message.startswith(f"{STAGE} failed: stuck")
    assert results[0].value == {"item": 0}
