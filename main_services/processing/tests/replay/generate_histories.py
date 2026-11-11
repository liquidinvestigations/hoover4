"""Generate the host queue histories of the replay suite.

Run it in the worker container. It starts a local Temporal development server, so it
never touches the queues of the running stack:

    docker exec hoover4-worker sh -lc 'cd /app && uv run python tests/replay/generate_histories.py'

The activities return the results of a recorded Compose plan
(``fixtures/compose_histories.json.gz``), so each generated history is the history of that
plan under another worker placement. The script writes ``fixtures/host_queue_histories.json.gz``.

Scenarios:

- ``k3s-branch``: the commands of the earlier ``k3s`` branch on the host ``pod-a``. The
  branch ran the same claim without a patch marker, so the script removes the marker from
  the recorded plan history (:func:`without_patch`).
- ``current-shared``: the current code without ``HOOVER4_HOST_QUEUE``. The claim returns an
  empty host, and every stage uses the shared queues.
- ``current-host``: the current code on the host ``pod-a``.
- ``current-lost-host``: the host ``pod-a`` stops polling before the download. The plan
  claims ``pod-b`` and runs there.
- ``current-cancelled``: the operator cancels the plan while its group runs on ``pod-a``.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import sys
import uuid
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from typing import Any, Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from temporalio import activity, workflow  # noqa: E402
from temporalio.client import WorkflowExecutionStatus  # noqa: E402
from temporalio.common import RawValue  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

import tasks.host_queue as host_queue  # noqa: E402
from tasks.run_worker import sandboxed_runner  # noqa: E402

FIXTURES = HERE / "fixtures"
#: The recorded plan and its group workflow.
SOURCE_PLAN = "compose-ExecuteSinglePlan-88"
SOURCE_GROUP = "compose-ProcessItemsBatched-46"
SHARED_QUEUES = sorted(host_queue.PINNED_QUEUES | {"processing-indexing-queue"})
#: The wait for a pinned activity in the generated lost-host history. The workflow
#: records the value, and replay does not compare it.
START_TIMEOUT = timedelta(seconds=3)


def load(name: str) -> dict:
    with gzip.open(FIXTURES / name, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _decoded(payloads: dict | None) -> Any:
    if not payloads or not payloads.get("payloads"):
        return None
    payload = payloads["payloads"][0]
    data = base64.b64decode(payload.get("data", ""))
    return json.loads(data) if data else None


def recorded_results(*histories: dict) -> dict[str, deque]:
    """The completed result of each activity type, in the order of the histories."""
    results: dict[str, deque] = defaultdict(deque)
    for entry in histories:
        scheduled = {}
        for event in entry["history"]["events"]:
            kind = event["eventType"]
            if kind == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
                attributes = event["activityTaskScheduledEventAttributes"]
                scheduled[event["eventId"]] = attributes["activityType"]["name"]
            elif kind == "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":
                attributes = event["activityTaskCompletedEventAttributes"]
                results[scheduled[attributes["scheduledEventId"]]].append(
                    _decoded(attributes.get("result")))
    return results


def recorded_child_results(entry: dict) -> dict[str, Any]:
    initiated = {}
    out = {}
    for event in entry["history"]["events"]:
        kind = event["eventType"]
        if kind == "EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED":
            attributes = event["startChildWorkflowExecutionInitiatedEventAttributes"]
            initiated[event["eventId"]] = attributes["workflowType"]["name"]
        elif kind == "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED":
            attributes = event["childWorkflowExecutionCompletedEventAttributes"]
            out[initiated[attributes["initiatedEventId"]]] = _decoded(attributes.get("result"))
    return out


class Scenario:
    def __init__(self, name: str, hosts: list[str], *, branch: bool = False,
                 lost: frozenset = frozenset(), cancel: bool = False):
        self.name = name
        self.hosts = deque(hosts)
        self.branch = branch
        self.lost = lost
        self.cancel = cancel
        self.calls: list[tuple[str, str]] = []


def _patch_id(event: dict) -> str | None:
    if event["eventType"] != "EVENT_TYPE_MARKER_RECORDED":
        return None
    payloads = event["markerRecordedEventAttributes"].get("details", {}).get("patch-data", {})
    value = _decoded(payloads)
    return value.get("id") if isinstance(value, dict) else None


def without_patch(history: dict, patch: str) -> dict:
    """The history that the same commands give without the marker of ``patch``.

    The earlier ``k3s`` branch claimed a host without a marker. Its history is this
    history without the marker event and without the search attribute update that records
    the patch, with every later event id moved down.
    """
    events = history["events"]
    removed = set()
    for index, event in enumerate(events):
        if _patch_id(event) == patch:
            removed.add(int(event["eventId"]))
            following = events[index + 1]
            if following["eventType"] == "EVENT_TYPE_UPSERT_WORKFLOW_SEARCH_ATTRIBUTES":
                removed.add(int(following["eventId"]))
    if not removed:
        raise RuntimeError(f"the history has no marker of {patch}")

    def moved(value: str) -> str:
        number = int(value)
        return str(number - sum(1 for gone in removed if gone < number))

    def renumber(node):
        if isinstance(node, dict):
            return {key: (moved(value) if (key == "eventId" or key.endswith("EventId"))
                          and isinstance(value, str) and value.isdigit() else renumber(value))
                    for key, value in node.items()}
        if isinstance(node, list):
            return [renumber(item) for item in node]
        return node

    kept = [event for event in events if int(event["eventId"]) not in removed]
    return {**history, "events": renumber(kept)}


#: The recorded result of each stage child workflow of the plan. run_scenario sets it.
CHILD_RESULTS: dict[str, Any] = {}


@workflow.defn(dynamic=True, sandboxed=False)
class RecordedChild:
    """Every stage child workflow of the plan other than its group workflow."""

    @workflow.run
    async def run(self, args: Sequence[RawValue]) -> Any:
        return CHILD_RESULTS.get(workflow.info().workflow_type)


async def run_scenario(env: WorkflowEnvironment, scenario: Scenario, plan: dict, group: dict) -> dict:
    from tasks.P2_execute_plan.workflows import ExecuteSinglePlan, ExecuteSinglePlanParams, ProcessItemsBatched
    from tasks.visibility import ensure_search_attributes_ready

    client = env.client
    await ensure_search_attributes_ready(client, 30)
    results = recorded_results(plan, group)
    children = recorded_child_results(plan)
    group_started = asyncio.Event()

    @activity.defn(dynamic=True)
    async def recorded(args: Sequence[RawValue]) -> Any:
        info = activity.info()
        name = info.activity_type
        scenario.calls.append((name, info.task_queue))
        if name == "claim_plan_host":
            return scenario.hosts.popleft()
        if name == "host_queue_alive":
            queue = activity.payload_converter().from_payload(args[0].payload, str)
            return queue.rsplit(host_queue.SEPARATOR, 1)[-1] not in scenario.lost
        if info.task_queue.startswith("processing-clamav-queue"):
            group_started.set()
            if scenario.cancel:
                await asyncio.sleep(3600)
        queue = results.get(name)
        if not queue:
            raise RuntimeError(f"no recorded result for {name}")
        return queue.popleft()

    original_timeout = host_queue.START_TIMEOUT
    host_queue.START_TIMEOUT = START_TIMEOUT
    CHILD_RESULTS.clear()
    CHILD_RESULTS.update(children)
    queues = list(SHARED_QUEUES)
    for host in {"pod-a", "pod-b"} - set(scenario.lost):
        queues += [host_queue.pinned(queue, host) for queue in host_queue.PINNED_QUEUES]
    workers = [Worker(client, task_queue="processing-common-queue",
                      workflows=[ExecuteSinglePlan, ProcessItemsBatched, RecordedChild],
                      activities=[recorded], workflow_runner=sandboxed_runner())]
    workers += [Worker(client, task_queue=queue, activities=[recorded])
                for queue in queues if queue != "processing-common-queue"]
    params_payload = _decoded(plan["history"]["events"][0]["workflowExecutionStartedEventAttributes"]["input"])
    params = ExecuteSinglePlanParams(**params_payload)
    workflow_id = f"execute-plan-{scenario.name}-{uuid.uuid4().hex[:8]}"
    try:
        tasks = [asyncio.create_task(w.run()) for w in workers]
        handle = await client.start_workflow(
            ExecuteSinglePlan.run, params, id=workflow_id, task_queue="processing-common-queue",
            execution_timeout=timedelta(minutes=5))
        if scenario.cancel:
            await asyncio.wait_for(group_started.wait(), 60)
            await handle.cancel()
        try:
            await handle.result()
        except Exception as exc:  # noqa: BLE001 - the cancelled scenario ends in a failure
            if not scenario.cancel:
                raise
            print(f"{scenario.name}: {type(exc).__name__}")
        history = json.loads((await handle.fetch_history()).to_json())
        if scenario.branch:
            history = without_patch(history, host_queue.PLAN_HOST_PATCH)
        out = {f"{scenario.name}-ExecuteSinglePlan": dict(
            workflow_id=workflow_id, workflow_type="ExecuteSinglePlan", history=history)}
        group_id = f"process-batches-{params.collection_dataset}-{params.plan_hash}-0"
        group_handle = client.get_workflow_handle(group_id)
        for _ in range(300):
            # The cancellation reaches the group after the plan has closed.
            if (await group_handle.describe()).status != WorkflowExecutionStatus.RUNNING:
                break
            await asyncio.sleep(0.1)
        group_history = await group_handle.fetch_history()
        out[f"{scenario.name}-ProcessItemsBatched"] = dict(
            workflow_id=group_id, workflow_type="ProcessItemsBatched",
            history=json.loads(group_history.to_json()))
        return out
    finally:
        for w in workers:
            await w.shutdown()
        host_queue.START_TIMEOUT = original_timeout


async def main() -> None:
    compose = load("compose_histories.json.gz")
    plan, group = compose[SOURCE_PLAN], compose[SOURCE_GROUP]
    scenarios = [
        Scenario("k3s-branch", ["pod-a"], branch=True),
        Scenario("current-shared", [""]),
        Scenario("current-host", ["pod-a"]),
        Scenario("current-lost-host", ["pod-a", "pod-b"], lost=frozenset({"pod-a"})),
        Scenario("current-cancelled", ["pod-a"], cancel=True),
    ]
    out = {}
    async with await WorkflowEnvironment.start_local() as env:
        for scenario in scenarios:
            out.update(await run_scenario(env, scenario, plan, group))
            pinned = sorted({queue for _, queue in scenario.calls if host_queue.SEPARATOR in queue})
            print(f"{scenario.name}: {len(scenario.calls)} activities, pinned queues {pinned}")
    with gzip.open(FIXTURES / "host_queue_histories.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)


if __name__ == "__main__":
    asyncio.run(main())
