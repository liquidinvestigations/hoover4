"""Where processing time goes: one row per activity execution, batched, best-effort.

The hook is a **Temporal activity inbound interceptor** (:class:`TaskTimingInterceptor`),
installed on every worker in ``run_worker.py``. That is the one place in this codebase
that wraps every activity without exception:

* ``@with_heartbeat`` (``tasks/heartbeat.py``) also wraps almost every body, but only the
  *sync* ones, and it is applied by hand at each definition -- an activity that forgets
  it is a silent hole, which is exactly the failure mode instrumentation must not have.
* Touching the ~55 call sites would have to be repeated for every activity added later.
* The interceptor sits above the activity body, so it sees the same execution Temporal
  sees: it gets the attempt number, the task queue, and the failure case for free,
  because an activity that raises passes through here on its way out.

Temporal sets the activity context (``temporalio/worker/_activity.py``, ``_Context.set``)
*before* it invokes the interceptor chain, for sync and async activities alike, so
``activity.info()`` is available here and is where ``task_name``/``attempt``/``task_queue``
come from, and also ``scheduled_time`` / ``started_time`` (queue wait) and the parent
workflow identity.

**What is measured.** Wall time from the moment this worker accepts the task to the
moment the body returns or raises. For a sync activity that includes the hand-off to the
thread-pool executor -- see the note in ``00035_processing_task_runs.sql``. It is not CPU
time and does not claim to be. ``schedule_to_start_ms`` is the complementary number:
``started_time - scheduled_time``, the time the task was eligible on its queue before
this worker accepted it. ``retry_backoff_ms`` is ``current_attempt_scheduled_time -
scheduled_time``. When ``activity.info()`` is missing (unit tests, a broken context)
those three are 0 / the Unix epoch and the workflow identity columns are empty -- the
activity still runs.

**Routing.** Per-collection rows go to that collection's own database. The collection
is read off the activity's parameter dataclass (virtually all of them carry
``collectionname`` and ``collection_dataset``). An activity whose parameters name no
collection -- ``ensure_temp_dir_exists``, ``cleanup_temp_dir``, ``collect_eta_samples``,
the P_agent chat activities -- is recorded in the global ``Hoover4_Processing`` copy of
``processing_task_runs`` with an empty ``collection_dataset``. The INFO log names that
table the first time a given task type takes this path.

**Best-effort, but never silent.** Nothing in here may fail an ingest, so every write is
wrapped. Every drop -- a failed insert, an overflowing buffer -- is logged with a count.
A bare ``except: pass`` losing error rows is the failure mode this exists to close.

**Batched.** 200k files is single-digit millions of executions. One insert per execution
would add a ClickHouse round trip to every activity and distort the very measurement it
is taking, so rows land in an in-process buffer that a single daemon thread drains every
few seconds (or as soon as it is full) -- the same shape as the website's `telemetry.rs`
buffer and `ai_telemetry.py`'s fire-and-forget writes.

The same thread samples what is *running* into ``processing_task_inflight``: a finished-row
table cannot show a task that has been stuck for twenty minutes, and that is the one the
live view most needs to name. Inflight is busy slots. Queue *waiters* are a different
table, ``Hoover4_Processing.processing_queue_backlog``, filled from Temporal
``DescribeTaskQueue`` on the same cadence: levels, nothing written while every queue's
backlog is 0. DescribeTaskQueue is async and must not run on the activity path -- the
common worker hands this recorder its client and event loop at startup, and the daemon
schedules the RPCs onto that loop.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from temporalio import activity
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)

log = logging.getLogger(__name__)

#: How often the buffer is drained and the in-flight snapshot written.
FLUSH_INTERVAL_SECONDS = 5.0

#: Drain early once this many rows are waiting, so a burst does not sit for the full
#: interval.
FLUSH_AT_ROWS = 500

#: Hard cap on the buffer. Reached only when ClickHouse is unreachable for minutes; at
#: that point the oldest rows are dropped (loudly) rather than growing the worker's RSS
#: without bound.
MAX_BUFFERED_ROWS = 100_000

#: Not more than one overflow/insert-failure warning per this many seconds, per worker.
#: The count is carried in the message, so nothing is hidden by the rate limit.
WARN_EVERY_SECONDS = 30.0

#: Queue-backlog sampling is coarser than inflight: DescribeTaskQueue is an RPC per
#: queue, and 10 s is inside the 10-15 s window the table is designed for.
BACKLOG_INTERVAL_SECONDS = 10.0

#: Unix epoch as a naive datetime, matching DateTime64(3) DEFAULT toDateTime64(0, 3).
_EPOCH = datetime(1970, 1, 1)

#: Every queue a worker in ``run_worker.py`` polls. Sampled as a set so a dead worker
#: still shows up as waiters-without-pollers rather than as a missing row.
KNOWN_TASK_QUEUES: Tuple[str, ...] = (
    "processing-common-queue",
    "processing-tika-queue",
    "processing-ocr-queue",
    "processing-nlp-queue",
    "processing-embed-queue",
    "processing-indexing-queue",
    "processing-index-planner-queue",
)

#: Parameter attributes that identify the artifact an execution worked on, most specific
#: first. ``plan_hash`` is last and is a deliberate fallback: the P4/P5/P6 activities
#: operate on a whole plan and have no document of their own, and an empty column there
#: would lose the only handle those rows have.
_HASH_FIELDS: Tuple[str, ...] = (
    "file_hash",
    "item_hash",
    "hash",
    "pdf_hash",
    "email_hash",
    "archive_hash",
    "video_hash",
    "blob_hash",
    "plan_hash",
)

_RUNS_COLUMNS = [
    "collection_dataset",
    "task_name",
    "hash",
    "outcome",
    "run_time_ms",
    "started_at",
    "attempt",
    "task_queue",
    "worker_id",
    "scheduled_at",
    "schedule_to_start_ms",
    "retry_backoff_ms",
    "workflow_id",
    "workflow_run_id",
    "workflow_type",
]

_INFLIGHT_COLUMNS = [
    "collection_dataset",
    "task_name",
    "worker_id",
    "sampled_at",
    "in_flight",
    "oldest_age_ms",
]

_BACKLOG_COLUMNS = [
    "task_queue",
    "sampled_at",
    "backlog_count",
    "backlog_age_ms",
    "add_rate",
    "dispatch_rate",
    "pollers",
]

_AI_COLUMNS = [
    "service",
    "provider",
    "username",
    "session_id",
    "latency_ms",
    "ok",
    "detail",
]


def _worker_id() -> str:
    """``host-pid``. Low cardinality by construction: one value per worker process."""
    host = os.environ.get("HOSTNAME") or socket.gethostname()
    return f"{host[:40]}-{os.getpid()}"


WORKER_ID = _worker_id()


def _first_attr(args: Sequence[Any], names: Sequence[str]) -> str:
    """First non-empty string attribute found on any argument, in ``names`` order.

    Activities here take exactly one parameter dataclass, but the loop over ``args``
    costs nothing and keeps this correct if one ever takes two.
    """
    for name in names:
        for arg in args:
            value = getattr(arg, name, None)
            if isinstance(value, str) and value:
                return value
    return ""


def identify(args: Sequence[Any]) -> Tuple[str, str, str]:
    """``(collectionname, collection_dataset, hash)`` read off the activity parameters."""
    return (
        _first_attr(args, ("collectionname",)),
        _first_attr(args, ("collection_dataset",)),
        _first_attr(args, _HASH_FIELDS),
    )


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Temporal timestamps are timezone-aware UTC; ClickHouse columns are naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _delta_ms(later: datetime | None, earlier: datetime | None) -> int:
    """``later - earlier`` in milliseconds, 0 if either side is missing, never negative."""
    if later is None or earlier is None:
        return 0
    a = _naive_utc(later)
    b = _naive_utc(earlier)
    if a is None or b is None:
        return 0
    ms = int((a - b).total_seconds() * 1000)
    return min(max(ms, 0), 4_294_967_295)


@dataclass(frozen=True)
class _ActivityFields:
    task_name: str
    attempt: int
    task_queue: str
    scheduled_at: datetime
    schedule_to_start_ms: int
    retry_backoff_ms: int
    workflow_id: str
    workflow_run_id: str
    workflow_type: str


def _activity_fields(input: ExecuteActivityInput) -> _ActivityFields:
    """Identity plus queue-wait fields. Empty/0 when ``activity.info()`` is missing."""
    fallback_name = getattr(input.fn, "__name__", "unknown_task")
    try:
        info = activity.info()
    except Exception:  # noqa: BLE001 - not in an activity context
        return _ActivityFields(
            task_name=fallback_name,
            attempt=1,
            task_queue="",
            scheduled_at=_EPOCH,
            schedule_to_start_ms=0,
            retry_backoff_ms=0,
            workflow_id="",
            workflow_run_id="",
            workflow_type="",
        )
    scheduled = _naive_utc(getattr(info, "scheduled_time", None))
    started = _naive_utc(getattr(info, "started_time", None))
    retry_at = _naive_utc(getattr(info, "current_attempt_scheduled_time", None))
    return _ActivityFields(
        task_name=info.activity_type,
        attempt=int(info.attempt),
        task_queue=info.task_queue or "",
        scheduled_at=scheduled or _EPOCH,
        schedule_to_start_ms=_delta_ms(started, scheduled),
        retry_backoff_ms=_delta_ms(retry_at, scheduled),
        workflow_id=getattr(info, "workflow_id", None) or "",
        workflow_run_id=getattr(info, "workflow_run_id", None) or "",
        workflow_type=getattr(info, "workflow_type", None) or "",
    )


def _duration_ms(age: Any) -> int:
    """Protobuf Duration to milliseconds; 0 when the field is missing or zero."""
    if age is None:
        return 0
    seconds = int(getattr(age, "seconds", 0) or 0)
    nanos = int(getattr(age, "nanos", 0) or 0)
    return min(max(seconds * 1000 + nanos // 1_000_000, 0), 4_294_967_295)


def row_from_describe(queue: str, resp: Any, sampled_at: datetime) -> list:
    """One ``processing_queue_backlog`` row from a DescribeTaskQueue response.

    Prefers the enhanced ``stats`` block when the server fills it, falls back to
    ``task_queue_status.backlog_count_hint`` (Temporal 1.23 reports the hint and
    pollers, and leaves add/dispatch rates and backlog age at 0).
    """
    stats = getattr(resp, "stats", None)
    status = getattr(resp, "task_queue_status", None)
    backlog = 0
    age_ms = 0
    add_rate = 0.0
    dispatch_rate = 0.0
    if stats is not None:
        backlog = int(getattr(stats, "approximate_backlog_count", 0) or 0)
        age_ms = _duration_ms(getattr(stats, "approximate_backlog_age", None))
        add_rate = float(getattr(stats, "tasks_add_rate", 0.0) or 0.0)
        dispatch_rate = float(getattr(stats, "tasks_dispatch_rate", 0.0) or 0.0)
    if backlog == 0 and status is not None:
        backlog = int(getattr(status, "backlog_count_hint", 0) or 0)
    pollers = len(list(getattr(resp, "pollers", None) or ()))
    return [
        queue,
        sampled_at,
        min(max(backlog, 0), 4_294_967_295),
        age_ms,
        add_rate,
        dispatch_rate,
        min(max(pollers, 0), 65535),
    ]


def backlog_rows_to_write(rows: Sequence[list]) -> list[list]:
    """Keep the sample when any queue reports a backlog OR has a poller attached.

    A backlog of 0 does not mean the queue is idle. Servers that leave the enhanced
    ``stats`` block empty fall back to ``backlog_count_hint``, which reads 0 for a task
    that is sync-matched or about to be -- so a fleet stalled on dispatch reports zeros
    on every queue while activities wait seconds to start. Keying the sample on pollers
    instead means a worker that is attached is always on the record, and the table's TTL
    is what bounds it. Only a stack with no workers at all costs zero rows.
    """
    if not rows:
        return []
    if not any(int(row[2] or 0) or int(row[6] or 0) for row in rows):
        return []
    return list(rows)


class _Recorder:
    """The buffer, its flusher thread, and the in-flight registry.

    One instance per worker process (:data:`_recorder`). All public methods are safe to
    call from any thread and none of them raise.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: Dict[str, List[list]] = {}
        self._row_count = 0
        self._overflow_dropped = 0
        self._insert_dropped = 0
        self._last_warn = 0.0

        self._inflight: Dict[int, Tuple[str, str, str, float]] = {}
        self._next_token = 0

        self._unroutable: Dict[str, int] = {}
        self._ai_rows: List[list] = []

        self._temporal_client: Any = None
        self._loop: Any = None
        self._last_backlog_at = 0.0
        self._backlog_logged = False

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

    def attach_client(self, client: Any, loop: Any) -> None:
        """Hand the Temporal client to the backlog sampler. Never raises."""
        with self._lock:
            self._temporal_client = client
            self._loop = loop

    def ensure_started(self) -> None:
        if self._thread is not None:
            return
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._run, name="task-timing", daemon=True
            )
            self._thread.start()
            atexit.register(self.flush)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(FLUSH_INTERVAL_SECONDS)
            self._wake.clear()
            self.flush()
            self._sample_inflight()
            self._sample_backlog()

    # -- recording ---------------------------------------------------------

    def begin(self, collectionname: str, dataset: str, task_name: str) -> int:
        """Register a running execution. Returns the token to pass to :meth:`end`."""
        self.ensure_started()
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._inflight[token] = (collectionname, dataset, task_name, time.monotonic())
        return token

    def end(self, token: int) -> None:
        with self._lock:
            self._inflight.pop(token, None)

    def record(self, collectionname: str, row: list) -> None:
        # Unroutable activities never call begin(), so this is what starts the
        # flusher thread for them. Without it the buffer sits until a collection-scoped
        # activity happens, and collect_eta_samples would be invisible again.
        self.ensure_started()
        flush_now = False
        with self._lock:
            rows = self._rows.setdefault(collectionname, [])
            if self._row_count >= MAX_BUFFERED_ROWS:
                # Drop the OLDEST row of the largest bucket: the newest rows describe
                # what the pipeline is doing now, which is the more useful half to keep.
                victim = max(self._rows.values(), key=len)
                if victim:
                    victim.pop(0)
                    self._row_count -= 1
                    self._overflow_dropped += 1
            rows.append(row)
            self._row_count += 1
            if self._row_count >= FLUSH_AT_ROWS:
                flush_now = True
        if flush_now:
            self._wake.set()

    def record_ai(self, row: list) -> None:
        """Buffer one ``ai_service_telemetry`` row. Same process, same daemon, never raises."""
        self.ensure_started()
        with self._lock:
            self._ai_rows.append(row)

    def note_unroutable(self, task_name: str) -> None:
        """An activity whose parameters name no collection: recorded in the global table."""
        with self._lock:
            seen = self._unroutable.get(task_name, 0)
            self._unroutable[task_name] = seen + 1
            first = seen == 0
        if first:
            log.info(
                "task_timing: %s names no collectionname in its parameters, so its "
                "executions are recorded in Hoover4_Processing.processing_task_runs",
                task_name,
            )

    # -- writing -----------------------------------------------------------

    def _warn(self, message: str, *args: Any) -> None:
        now = time.monotonic()
        if now - self._last_warn < WARN_EVERY_SECONDS:
            return
        self._last_warn = now
        log.warning(message, *args)

    def flush(self) -> None:
        """Drain the buffer into ClickHouse. Never raises."""
        with self._lock:
            pending = {name: rows for name, rows in self._rows.items() if rows}
            self._rows = {}
            self._row_count = 0
            overflow, self._overflow_dropped = self._overflow_dropped, 0
            ai_rows, self._ai_rows = self._ai_rows, []

        if overflow:
            self._warn(
                "task_timing: buffer full, dropped %d processing_task_runs rows "
                "(ClickHouse slow or unreachable)",
                overflow,
            )

        for collectionname, rows in pending.items():
            self._insert(collectionname, "processing_task_runs", _RUNS_COLUMNS, rows)
        if ai_rows:
            self._insert("", "ai_service_telemetry", _AI_COLUMNS, ai_rows)

    def _insert(
        self, collectionname: str, table: str, columns: List[str], rows: List[list]
    ) -> None:
        if not rows:
            return
        try:
            if not collectionname:
                from database.clickhouse import get_global_client, insert_idempotent

                with get_global_client() as client:
                    insert_idempotent(client, table, rows, column_names=columns)
            else:
                from database.clickhouse import get_collection_client, insert_idempotent

                with get_collection_client(collectionname) as client:
                    insert_idempotent(client, table, rows, column_names=columns)
        except Exception as exc:  # noqa: BLE001 - never fail an ingest over telemetry
            self._insert_dropped += len(rows)
            self._warn(
                "task_timing: insert into %s.%s failed, %d rows dropped "
                "(%d total this process): %s",
                collectionname or "Hoover4_Processing",
                table,
                len(rows),
                self._insert_dropped,
                exc,
            )

    def _sample_inflight(self) -> None:
        """Write one level sample per (collection, dataset, task) that is running.

        Nothing is written when the process is idle, which is what lets a reader treat
        "no fresh samples" as "nothing running" rather than as a gap in the data.
        """
        now_monotonic = time.monotonic()
        with self._lock:
            snapshot = list(self._inflight.values())
        if not snapshot:
            return

        sampled_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        buckets: Dict[Tuple[str, str, str], Tuple[int, float]] = {}
        for collectionname, dataset, task_name, started in snapshot:
            key = (collectionname, dataset, task_name)
            count, oldest = buckets.get(key, (0, 0.0))
            buckets[key] = (count + 1, max(oldest, now_monotonic - started))

        per_collection: Dict[str, List[list]] = {}
        for (collectionname, dataset, task_name), (count, oldest) in buckets.items():
            per_collection.setdefault(collectionname, []).append(
                [
                    dataset,
                    task_name,
                    WORKER_ID,
                    sampled_at,
                    min(count, 65535),
                    min(int(oldest * 1000), 4_294_967_295),
                ]
            )

        for collectionname, rows in per_collection.items():
            self._insert(
                collectionname, "processing_task_inflight", _INFLIGHT_COLUMNS, rows
            )

    def _sample_backlog(self) -> None:
        """Describe every known queue. Never raises, never runs on the activity path."""
        now = time.monotonic()
        with self._lock:
            client = self._temporal_client
            loop = self._loop
            last = self._last_backlog_at
        if client is None or loop is None:
            return
        if last and (now - last) < BACKLOG_INTERVAL_SECONDS:
            return
        with self._lock:
            self._last_backlog_at = now
        try:
            future = asyncio.run_coroutine_threadsafe(_describe_all_queues(client), loop)
            samples = future.result(timeout=8)
        except Exception as exc:  # noqa: BLE001 - telemetry never fails an ingest
            if not self._backlog_logged:
                self._backlog_logged = True
                log.warning(
                    "task_timing: DescribeTaskQueue failed, queue backlog not sampled: %s",
                    exc,
                )
            return
        rows = backlog_rows_to_write(samples)
        if rows:
            self._insert("", "processing_queue_backlog", _BACKLOG_COLUMNS, rows)


_recorder = _Recorder()


async def _describe_all_queues(client: Any) -> list[list]:
    """One DescribeTaskQueue RPC per known queue. Failures of a single queue are skipped."""
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

    sampled_at = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    namespace = getattr(client, "namespace", None) or "default"
    rows: list[list] = []
    for name in KNOWN_TASK_QUEUES:
        try:
            resp = await client.workflow_service.describe_task_queue(
                DescribeTaskQueueRequest(
                    namespace=namespace,
                    task_queue=TaskQueue(name=name),
                    task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,
                    include_task_queue_status=True,
                    report_stats=True,
                    report_pollers=True,
                )
            )
            rows.append(row_from_describe(name, resp, sampled_at))
        except Exception as exc:  # noqa: BLE001 - one dead queue must not drop the rest
            if not _recorder._backlog_logged:
                _recorder._backlog_logged = True
                log.warning(
                    "task_timing: DescribeTaskQueue(%s) failed, queue backlog not sampled: %s",
                    name,
                    exc,
                )
    return rows


def attach_temporal_client(client: Any) -> None:
    """Give the recorder the common worker's Temporal client for queue-backlog samples.

    Other workers leave this unset: DescribeTaskQueue is cluster-wide, so the two
    common-worker processes sampling every queue is enough (a reader takes the newest
    row per task_queue). Starts the daemon so an idle fleet still records waiters.
    Never raises.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        _recorder.attach_client(client, loop)
        _recorder.ensure_started()
    except Exception:  # noqa: BLE001 - attaching telemetry must not fail a worker boot
        log.warning("task_timing: failed to attach Temporal client for queue backlog", exc_info=True)


class _TimingActivityInbound(ActivityInboundInterceptor):
    """Times one activity execution and hands the row to the buffer."""

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        fields = _activity_fields(input)
        collectionname, dataset, item_hash = identify(input.args)

        unroutable = not collectionname
        if unroutable:
            _recorder.note_unroutable(fields.task_name)

        token = None if unroutable else _recorder.begin(
            collectionname, dataset, fields.task_name
        )
        started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        start = time.monotonic()
        outcome = "ok"
        try:
            return await self.next.execute_activity(input)
        except BaseException:
            # Cancellation counts as a failed execution too: it consumed the time.
            outcome = "error"
            raise
        finally:
            run_time_ms = max(0, int((time.monotonic() - start) * 1000))
            if token is not None:
                _recorder.end(token)
            _recorder.record(
                collectionname,
                [
                    dataset,
                    fields.task_name,
                    item_hash,
                    outcome,
                    min(run_time_ms, 4_294_967_295),
                    started_at,
                    min(max(fields.attempt, 0), 65535),
                    fields.task_queue,
                    WORKER_ID,
                    fields.scheduled_at,
                    fields.schedule_to_start_ms,
                    fields.retry_backoff_ms,
                    fields.workflow_id,
                    fields.workflow_run_id,
                    fields.workflow_type,
                ],
            )


class TaskTimingInterceptor(Interceptor):
    """Install on every ``Worker`` to get a ``processing_task_runs`` row per execution."""

    def intercept_activity(
        self, next: ActivityInboundInterceptor
    ) -> ActivityInboundInterceptor:
        return _TimingActivityInbound(next)


def flush_now() -> None:
    """Drain the buffer synchronously. For tests and for shutdown paths."""
    _recorder.flush()


def record_ai_service(row: list) -> None:
    """Enqueue one ``ai_service_telemetry`` row onto the timing daemon. Never raises."""
    try:
        _recorder.record_ai(row)
    except Exception:  # noqa: BLE001 - telemetry is never worth a failed activity
        log.debug("task_timing: ai_service_telemetry buffer failed", exc_info=True)
