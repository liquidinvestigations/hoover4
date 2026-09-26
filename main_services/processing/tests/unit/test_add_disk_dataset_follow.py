"""Unit tests for the one-minute follow of `add-disk-dataset` and its exit codes."""

from datetime import datetime

import pytest
from click.testing import CliRunner

import main
from database import operations
from tasks.P0_scan_disk import submit_job
from tasks.P_ops import cli


class _Clock:
    """A fake `time` module. `sleep` moves the clock instead of waiting."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _row(state: str) -> dict:
    return {
        "op_id": "op", "kind": "add_dataset", "collectionname": "c",
        "collection_dataset": "c__d", "state": state, "progress_done": 0,
        "progress_total": 0, "eta_seconds": 0, "error": "",
        "started_at": datetime(2026, 1, 1), "run_started_at": datetime(1970, 1, 1),
    }


@pytest.fixture
def command(monkeypatch):
    """Run `add-disk-dataset` with the submission, the row and the clock faked.

    `states` maps a clock time to the row state from that time on.
    """
    clock = _Clock()
    fake = {"states": {0: "running"}, "exit": []}

    def get_operation(_op_id):
        state = [value for start, value in sorted(fake["states"].items())
                 if start <= clock.now][-1]
        return _row(state)

    def end_process(code):
        fake["exit"].append(code)
        raise SystemExit(code)

    monkeypatch.setattr(cli, "time", clock)
    monkeypatch.setattr(cli, "end_process", end_process)
    monkeypatch.setattr(cli, "submit_operation", lambda *_args, **_kwargs: "op")
    monkeypatch.setattr(operations, "get_operation", get_operation)
    monkeypatch.setattr(submit_job, "compose_collection_dataset", lambda c, d: f"{c}__{d}")
    monkeypatch.setattr(submit_job, "prepare_disk_dataset", lambda _c, _d, path: path)

    def run(tmp_path, *flags):
        result = CliRunner().invoke(
            main.cli, ["add-disk-dataset", "c", "d", str(tmp_path), *flags],
        )
        return result, clock.now, fake["exit"]

    return fake, run


def test_the_default_follows_for_one_minute_then_exits_0(command, tmp_path):
    fake, run = command
    result, elapsed, exits = run(tmp_path)
    assert exits == [0]
    assert result.exit_code == 0
    assert 60 <= elapsed <= 63
    assert "op is processing. It continues after this command exits." in result.output


def test_a_queued_operation_says_so_at_the_minute(command, tmp_path):
    fake, run = command
    fake["states"] = {0: "queued"}
    result, elapsed, exits = run(tmp_path)
    assert exits == [0]
    assert "op is queued. It starts when a slot for add_dataset is free." in result.output


def test_an_errored_operation_inside_the_minute_exits_1(command, tmp_path):
    fake, run = command
    fake["states"] = {0: "running", 9: "errored"}
    result, elapsed, exits = run(tmp_path)
    assert exits == [1]
    assert result.exit_code == 1
    assert elapsed < 60
    assert "Error: op failed." in result.output


def test_an_operation_that_ends_first_exits_0_at_its_end(command, tmp_path):
    fake, run = command
    fake["states"] = {0: "running", 12: "finished"}
    result, elapsed, exits = run(tmp_path)
    assert exits == [0]
    assert elapsed < 60
    assert "is processing" not in result.output


def test_a_cancelled_operation_inside_the_minute_exits_0(command, tmp_path):
    fake, run = command
    fake["states"] = {0: "cancelled"}
    result, elapsed, exits = run(tmp_path)
    assert exits == [0]


def test_wait_follows_past_the_minute_to_the_end(command, tmp_path):
    fake, run = command
    fake["states"] = {0: "running", 70: "finished"}
    result, elapsed, exits = run(tmp_path, "--wait")
    assert exits == [0]
    assert elapsed >= 70
    assert "is processing" not in result.output


def test_no_wait_returns_after_the_submission(command, tmp_path):
    fake, run = command
    result, elapsed, exits = run(tmp_path, "--no-wait")
    assert exits == [0]
    assert elapsed == 0
    assert "operation op" in result.output


def test_tail_returns_following_at_the_deadline(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(cli, "time", clock)
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: _row("running"))
    assert cli.tail_operation("op", deadline_seconds=10) == "following"
    assert clock.now == 10


def test_the_detach_message_names_the_current_state(monkeypatch, capsys):
    def interrupted(_seconds):
        raise KeyboardInterrupt

    clock = _Clock()
    clock.sleep = interrupted
    monkeypatch.setattr(cli, "time", clock)
    monkeypatch.setattr(operations, "get_operation", lambda _op_id: _row("queued"))
    assert cli.tail_operation("op") == "detached"
    assert "The operation is still queued" in capsys.readouterr().out
