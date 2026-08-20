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
come from.

**What is measured.** Wall time from the moment this worker accepts the task to the
moment the body returns or raises. For a sync activity that includes the hand-off to the
thread-pool executor -- see the note in ``00035_processing_task_runs.sql``. It is not CPU
time and does not claim to be.

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
live view most needs to name.
"""

from __future__ import annotations

import atexit
import logging
import os
import socket
import threading
import time
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
]

_INFLIGHT_COLUMNS = [
    "collection_dataset",
    "task_name",
    "worker_id",
    "sampled_at",
    "in_flight",
    "oldest_age_ms",
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

        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------

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

        if overflow:
            self._warn(
                "task_timing: buffer full, dropped %d processing_task_runs rows "
                "(ClickHouse slow or unreachable)",
                overflow,
            )

        for collectionname, rows in pending.items():
            self._insert(collectionname, "processing_task_runs", _RUNS_COLUMNS, rows)

    def _insert(
        self, collectionname: str, table: str, columns: List[str], rows: List[list]
    ) -> None:
        if not rows:
            return
        try:
            if not collectionname:
                from database.clickhouse import get_global_client

                with get_global_client() as client:
                    client.insert(table, rows, column_names=columns)
            else:
                from database.clickhouse import get_collection_client

                with get_collection_client(collectionname) as client:
                    client.insert(table, rows, column_names=columns)
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


_recorder = _Recorder()


def _activity_identity(input: ExecuteActivityInput) -> Tuple[str, int, str]:
    """``(task_name, attempt, task_queue)``.

    ``activity.info()`` is the authority -- it carries the *registered* activity type,
    which may differ from the Python function name. The function name is the fallback
    for the unit tests, which call the interceptor outside an activity context.
    """
    try:
        info = activity.info()
        return (info.activity_type, int(info.attempt), info.task_queue)
    except Exception:  # noqa: BLE001 - not in an activity context
        return (getattr(input.fn, "__name__", "unknown_task"), 1, "")


class _TimingActivityInbound(ActivityInboundInterceptor):
    """Times one activity execution and hands the row to the buffer."""

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        task_name, attempt, task_queue = _activity_identity(input)
        collectionname, dataset, item_hash = identify(input.args)

        unroutable = not collectionname
        if unroutable:
            _recorder.note_unroutable(task_name)

        token = None if unroutable else _recorder.begin(collectionname, dataset, task_name)
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
                    task_name,
                    item_hash,
                    outcome,
                    min(run_time_ms, 4_294_967_295),
                    started_at,
                    min(max(attempt, 0), 65535),
                    task_queue,
                    WORKER_ID,
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
