"""Replay the plan workflows of both existing history sources on the current code.

`fixtures/compose_histories.json.gz` holds plans and groups that the local Compose stack
recorded before the host claim existed. `fixtures/host_queue_histories.json.gz` holds the
histories of `generate_histories.py`: the claim of the earlier `k3s` branch without a patch
marker, and the current claim on the shared queues, on one host, after a lost host and
after a cancellation. The Temporal `Replayer` fails on a command that a history does not
hold, so each passing case proves that the current code reproduces the recorded commands.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import gzip
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with gzip.open(FIXTURES / name, "rt", encoding="utf-8") as fh:
        return json.load(fh)


COMPOSE = _load("compose_histories.json.gz")
GENERATED = _load("host_queue_histories.json.gz")
CURRENT = {key: entry for key, entry in GENERATED.items() if key.startswith("current-")}
BRANCH = {key: entry for key, entry in GENERATED.items() if key.startswith("k3s-branch-")}


@pytest.fixture
def history_source(monkeypatch):
    """Set `HOOVER4_HISTORY_SOURCE` as a worker reads it at import."""
    import tasks.host_queue as host_queue

    def choose(value: str) -> None:
        assert value in host_queue.HISTORY_SOURCES
        monkeypatch.setattr(host_queue, "HISTORY_SOURCE", value)

    return choose


def _replay(*entries: dict) -> list:
    """The replay failure of each history, or None for a history that replays."""
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tasks.P2_execute_plan.workflows import ExecuteSinglePlan, ProcessItemsBatched
    from tasks.P3_parse_files.pdf_cursor import PdfPartGroup
    from tasks.P_admin.workflows import OcrRunPlan
    from tasks.run_worker import sandboxed_runner

    replayer = Replayer(workflows=[ExecuteSinglePlan, ProcessItemsBatched, PdfPartGroup, OcrRunPlan],
                        workflow_runner=sandboxed_runner())

    async def run() -> list:
        out = []
        for entry in entries:
            history = WorkflowHistory.from_json(entry["workflow_id"], entry["history"])
            result = await replayer.replay_workflow(history, raise_on_replay_failure=False)
            out.append(result.replay_failure)
        return out

    return asyncio.run(run())


def _params(cases: dict):
    return [pytest.param(entry, id=key) for key, entry in sorted(cases.items())]


def _events(entry: dict) -> list:
    return entry["history"]["events"]


def _activities(entry: dict) -> list[tuple[str, str]]:
    """(activity type, task queue) of each scheduled activity, in order."""
    out = []
    for event in _events(entry):
        if event["eventType"] == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
            attributes = event["activityTaskScheduledEventAttributes"]
            out.append((attributes["activityType"]["name"], attributes["taskQueue"]["name"]))
    return out


def _patches(entry: dict) -> set[str]:
    found = set()
    for event in _events(entry):
        if event["eventType"] != "EVENT_TYPE_MARKER_RECORDED":
            continue
        details = event["markerRecordedEventAttributes"].get("details", {})
        for payload in details.get("patch-data", {}).get("payloads", []):
            data = json.loads(base64.b64decode(payload.get("data", "")) or "null")
            if isinstance(data, dict) and data.get("id"):
                found.add(data["id"])
    return found


def _prefixes(entry: dict) -> list[dict]:
    """The history of the execution at each point where an activity or a child runs.

    A worker that restarts at that point replays exactly this prefix.
    """
    out = []
    events = _events(entry)
    for index, event in enumerate(events[:-1]):
        if event["eventType"] in ("EVENT_TYPE_ACTIVITY_TASK_STARTED",
                                  "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED"):
            prefix = copy.deepcopy(entry)
            prefix["history"]["events"] = events[:index + 1]
            out.append(prefix)
    return out


@pytest.mark.parametrize("entry", _params(COMPOSE))
def test_a_compose_history_replays(entry, history_source):
    history_source("compose")
    assert _replay(entry) == [None]


@pytest.mark.parametrize("source", ["compose", "k3s-branch"])
@pytest.mark.parametrize("entry", _params(CURRENT))
def test_a_current_history_replays_with_either_history_source(entry, source, history_source):
    history_source(source)
    assert _replay(entry) == [None]


@pytest.mark.parametrize("entry", _params(BRANCH))
def test_a_k3s_branch_history_replays_with_its_history_source(entry, history_source):
    history_source("k3s-branch")
    assert _replay(entry) == [None]


def test_a_k3s_branch_plan_needs_its_history_source(history_source):
    """Without the setting, the branch claim has no marker and replay fails."""
    history_source("compose")
    failure, = _replay(BRANCH["k3s-branch-ExecuteSinglePlan"])
    assert failure is not None
    assert "claim_plan_host" in str(failure) or "download_plan_files" in str(failure)


def test_a_k3s_branch_group_replays_with_either_history_source(history_source):
    """A group workflow reads its host from its input, so it needs no marker."""
    for source in ("compose", "k3s-branch"):
        history_source(source)
        assert _replay(BRANCH["k3s-branch-ProcessItemsBatched"]) == [None]


def test_a_compose_plan_fails_with_the_k3s_branch_history_source(history_source):
    """The setting must match the source of the histories of the installation."""
    history_source("k3s-branch")
    failures = _replay(*[entry for key, entry in COMPOSE.items() if "ExecuteSinglePlan" in key])
    assert all(failure is not None for failure in failures)


@pytest.mark.parametrize("entry", _params({**COMPOSE, **CURRENT}))
def test_every_in_flight_prefix_replays(entry, history_source):
    """A worker restart at any activity or child of a plan replays the history so far."""
    history_source("compose")
    prefixes = _prefixes(entry)
    assert _replay(*prefixes) == [None] * len(prefixes)


def test_the_plan_histories_have_in_flight_prefixes():
    for key, entry in {**COMPOSE, **GENERATED}.items():
        if "cancelled" not in key:
            assert len(_prefixes(entry)) >= 3, key


@pytest.mark.parametrize("entry", _params(BRANCH))
def test_every_in_flight_k3s_branch_prefix_replays(entry, history_source):
    history_source("k3s-branch")
    prefixes = _prefixes(entry)
    assert _replay(*prefixes) == [None] * len(prefixes)


def test_old_and_new_histories_replay_on_one_worker(history_source):
    """A Compose installation holds plans from before and after the claim at one time."""
    history_source("compose")
    entries = [*COMPOSE.values(), *CURRENT.values()]
    assert _replay(*entries) == [None] * len(entries)


def test_the_generated_histories_hold_the_expected_placement():
    plan = "ExecuteSinglePlan"
    shared = _activities(GENERATED[f"current-shared-{plan}"])
    assert "plan-host-queue" in _patches(GENERATED[f"current-shared-{plan}"])
    assert shared[1] == ("claim_plan_host", "processing-common-queue")
    assert all("@" not in queue for _, queue in shared)

    branch = GENERATED[f"k3s-branch-{plan}"]
    assert "plan-host-queue" not in _patches(branch)
    assert ("download_plan_files", "processing-common-queue@pod-a") in _activities(branch)

    host = _activities(GENERATED[f"current-host-{plan}"])
    assert ("download_plan_files", "processing-common-queue@pod-a") in host
    assert ("cleanup_plan_dir", "processing-common-queue@pod-a") in host
    group = _activities(GENERATED["current-host-ProcessItemsBatched"])
    assert ("clamav_scan_batch", "processing-clamav-queue@pod-a") in group
    assert ("tika_text_batch", "processing-tika-queue@pod-a") in group

    lost = _activities(GENERATED[f"current-lost-host-{plan}"])
    names = [name for name, _ in lost]
    assert names.count("claim_plan_host") == 2
    assert ("host_queue_alive", "processing-common-queue") in lost
    assert ("download_plan_files", "processing-common-queue@pod-a") in lost
    assert ("download_plan_files", "processing-common-queue@pod-b") in lost
    assert ("cleanup_plan_dir", "processing-common-queue@pod-b") in lost

    cancelled = GENERATED[f"current-cancelled-{plan}"]
    names = [name for name, _ in _activities(cancelled)]
    assert names.count("claim_plan_host") == 1
    assert "cleanup_plan_dir" not in names
    assert _events(cancelled)[-1]["eventType"] == "EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED"
    # The plan starts its groups with the default parent close policy, so the server
    # terminates the running group when the cancelled plan closes.
    group = _events(GENERATED["current-cancelled-ProcessItemsBatched"])
    assert group[-1]["eventType"] == "EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED"
