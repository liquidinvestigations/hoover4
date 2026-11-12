"""Worker-specific task queues for the stages that read the local folder of a plan.

A plan downloads its files into a folder of the worker that runs the download, and every
stage of the plan then reads those files by path. With workers on several hosts, each
stage must run on the host of that folder. ``HOOVER4_HOST_QUEUE`` names the host of this
process, and is unique for each host (for example the Kubernetes pod name). A process
with a host name polls each of :data:`PINNED_QUEUES` twice: the shared queue, and the
queue ``<queue>@<host>``. A plan claims a host with :func:`claim_plan_host` on the shared
common queue, and then sends its download, its stages and its cleanup to the queues of
that host.

Without ``HOOVER4_HOST_QUEUE``, the claim returns an empty name, and every stage uses
the shared queues, as on one host.

The claim is a new activity in workflows that already run. :func:`plan_host_claimed`
decides whether an execution claims a host. A new execution records the patch marker
:data:`PLAN_HOST_PATCH` and claims a host. An execution that started before the claim
existed has no marker and keeps the shared queues. The earlier ``k3s`` branch claimed a
host without a marker. An installation with histories from that branch sets
``HOOVER4_HISTORY_SOURCE=k3s-branch``, and then an execution without a marker claims a
host as it did there. Each installation has histories of one source only.

A pinned activity waits at most :data:`START_TIMEOUT` for its host. After that,
:func:`host_queue_alive` asks Temporal for the pollers of the host queue. A host that
still polls is busy, and the stage waits again. A host without pollers is lost, and the
plan starts again with a new claim, so another host downloads its files.

The two workers of one queue share one slot count. :class:`SharedSlots` hands out the
activity slots of both, so a process runs no more activities than its configured
concurrency.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import timedelta

from temporalio import activity
from temporalio.worker import (
    CustomSlotSupplier,
    SlotMarkUsedContext,
    SlotPermit,
    SlotReleaseContext,
    SlotReserveContext,
)

from tasks.heartbeat import HEARTBEAT_TIMEOUT, with_heartbeat

SEPARATOR = "@"
START_TIMEOUT = timedelta(minutes=10)
#: The patch marker of the executions that claim a plan host.
PLAN_HOST_PATCH = "plan-host-queue"
#: The history sources that ``HOOVER4_HISTORY_SOURCE`` accepts. ``compose`` is the default.
HISTORY_SOURCES = ("compose", "k3s-branch")
#: A poller that Temporal saw within this many seconds counts as alive.
POLLER_SECONDS = 120

#: The queues whose activities read the local plan folder.
PINNED_QUEUES = frozenset({
    "processing-common-queue",
    "processing-tika-queue",
    "processing-clamav-queue",
    "processing-ocr-queue",
    "processing-ocr-pdf-queue",
    "processing-preview-queue",
})


def host_name() -> str:
    """The host queue name of this process, or an empty string on one host."""
    return os.getenv("HOOVER4_HOST_QUEUE", "").strip()


def history_source() -> str:
    """The source of the workflow histories of this installation.

    A worker reads it at import, so a workflow decision reads one value for the life of
    the process. An unknown value stops the worker at start.
    """
    value = os.getenv("HOOVER4_HISTORY_SOURCE", "").strip() or "compose"
    if value not in HISTORY_SOURCES:
        raise ValueError("HOOVER4_HISTORY_SOURCE must be one of %s." % ", ".join(HISTORY_SOURCES))
    return value


#: Read once, see history_source().
HISTORY_SOURCE = history_source()


def plan_host_claimed() -> bool:
    """Whether this execution claims a plan host. Workflow code only.

    A new execution records :data:`PLAN_HOST_PATCH`. A replayed execution claims a host
    when its history has the marker, or when its history comes from the ``k3s`` branch.
    """
    from temporalio import workflow
    if workflow.patched(PLAN_HOST_PATCH):
        return True
    return HISTORY_SOURCE == "k3s-branch"


def pinned(queue: str, host: str) -> str:
    """The queue of ``host`` for ``queue``, or ``queue`` when ``host`` is empty."""
    if not host or queue not in PINNED_QUEUES:
        return queue
    return f"{queue}{SEPARATOR}{host}"


@activity.defn
@with_heartbeat
async def claim_plan_host() -> str:
    """Return the host of the worker that runs this activity, for the plan that asks."""
    return host_name()


@activity.defn
@with_heartbeat
async def host_queue_alive(queue: str) -> bool:
    """Whether a worker polled the activity queue ``queue`` within :data:`POLLER_SECONDS`."""
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
    client = activity.client()
    response = await client.workflow_service.describe_task_queue(DescribeTaskQueueRequest(
        namespace=client.namespace, task_queue=TaskQueue(name=queue),
        task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY))
    now = time.time()
    return any(now - poller.last_access_time.seconds <= POLLER_SECONDS for poller in response.pollers)


class HostLost(Exception):
    """The host of a plan stopped polling its queues."""


class SharedSlots(CustomSlotSupplier):
    """A fixed number of activity slots for several workers of one process.

    The SDK calls ``release_slot`` from a thread of its core, where no event loop runs, so a
    release cannot notify an ``asyncio.Condition``. Each waiting reservation therefore keeps a
    future of its own loop, and a release sets it through ``call_soon_threadsafe``. A woken
    reservation checks the count again under the lock.
    """

    def __init__(self, slots: int):
        self._free = slots
        self._lock = threading.Lock()
        self._waiters: list[tuple[asyncio.AbstractEventLoop, asyncio.Future]] = []

    async def reserve_slot(self, ctx: SlotReserveContext) -> SlotPermit:
        while True:
            with self._lock:
                if self._free > 0:
                    self._free -= 1
                    return SlotPermit()
                loop = asyncio.get_running_loop()
                waiter = loop.create_future()
                self._waiters.append((loop, waiter))
            try:
                await waiter
            except asyncio.CancelledError:
                with self._lock:
                    self._waiters = [w for w in self._waiters if w[1] is not waiter]
                raise

    def try_reserve_slot(self, ctx: SlotReserveContext) -> SlotPermit | None:
        with self._lock:
            if self._free <= 0:
                return None
            self._free -= 1
            return SlotPermit()

    def mark_slot_used(self, ctx: SlotMarkUsedContext) -> None:
        return None

    def release_slot(self, ctx: SlotReleaseContext) -> None:
        with self._lock:
            self._free += 1
            waiters, self._waiters = self._waiters, []
        for loop, waiter in waiters:
            try:
                loop.call_soon_threadsafe(_wake, waiter)
            except RuntimeError:
                # The loop of this reservation has closed, so nothing waits on it.
                pass


def _wake(waiter: asyncio.Future) -> None:
    if not waiter.done():
        waiter.set_result(None)


def host_lost(exc: BaseException) -> bool:
    """Whether a failure chain holds a lost host: a :class:`HostLost` failure, or a pinned
    activity that no host started in time."""
    from temporalio.exceptions import ApplicationError, TimeoutError, TimeoutType
    seen = exc
    while seen is not None:
        if isinstance(seen, ApplicationError) and seen.type == "HostLost":
            return True
        if isinstance(seen, TimeoutError) and seen.type == TimeoutType.SCHEDULE_TO_START:
            return True
        seen = seen.__cause__
    return False


async def execute_pinned(activity_fn, arg, *, queue: str, host: str, **options):
    """Run an activity on the host queue of ``queue``. Workflow code only.

    Without a host, this is ``workflow.execute_activity`` on ``queue``. With a host, a
    start timeout asks :func:`host_queue_alive`. A busy host gets another wait, and a host
    without pollers raises an ``ApplicationError`` of the type ``HostLost``.
    """
    from temporalio import workflow
    from temporalio.exceptions import ActivityError, ApplicationError
    target = pinned(queue, host)
    heartbeat = options.pop("heartbeat_timeout", HEARTBEAT_TIMEOUT)
    if target == queue:
        return await workflow.execute_activity(activity_fn, arg, task_queue=queue,
                                               heartbeat_timeout=heartbeat, **options)
    while True:
        try:
            return await workflow.execute_activity(activity_fn, arg, task_queue=target,
                                                   schedule_to_start_timeout=START_TIMEOUT,
                                                   heartbeat_timeout=heartbeat, **options)
        except ActivityError as exc:
            if not host_lost(exc):
                raise
            alive = await workflow.execute_activity(
                host_queue_alive, target, task_queue="processing-common-queue",
                start_to_close_timeout=timedelta(minutes=1), heartbeat_timeout=HEARTBEAT_TIMEOUT)
            if not alive:
                raise ApplicationError(f"host {host} stopped polling {target}", type="HostLost",
                                       non_retryable=True) from exc
