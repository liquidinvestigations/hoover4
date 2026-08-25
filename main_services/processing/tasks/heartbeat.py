"""Activity liveness: the two heartbeat constants and the helpers that use them.

Why this module exists
----------------------
``start_to_close_timeout`` answers "how long may this activity legitimately
run?" -- for ``ffmpeg`` over a 2 GB video, actually hours. ``heartbeat_timeout``
answers a different question: "how long may this activity go without proving it
is alive?" That one has the same answer, ~2 minutes, for every activity in the
tree regardless of how long its real work takes.

The distinction is not academic. An activity task can be lost between the
Temporal matching service and the worker: the server shows ``State: Started``
while a py-spy dump proves every executor thread is idle and the body never ran.
With only ``start_to_close_timeout`` configured, that stall lasts the whole-file
budget -- tens of minutes for a large file. The heartbeat clock starts at
``ActivityTaskStarted``, which is exactly the state such a task is stuck in, so a
``heartbeat_timeout`` turns the same stall into ~2 minutes.
"""

from contextlib import contextmanager
from datetime import timedelta

from temporalio import activity

# NOTE: threading, contextvars and time are imported lazily inside the helpers
# below, never at module scope. Every workflow module imports HEARTBEAT_TIMEOUT
# from here, and the Temporal workflow sandbox restricts exactly those modules --
# a top-level import would make this module unimportable from the one place that
# needs its constant most.

# How often an activity proves it is alive.
HEARTBEAT_INTERVAL = timedelta(seconds=15)

# What the *caller* declares [user requirement: dropped or dead work is caught in
# useful time]. A 15 s beat inside a 30 s deadline is a 2x margin, and it is tight on
# purpose.
#
# **Widening this makes things worse, not safer, and that is not intuitive.** The
# deadline is not only how long until a dead activity is noticed; it is also how long a
# wedged slot stays occupied before the fleet can reuse it. Under a parse burst the box
# is oversubscribed enough that the worker occasionally cannot get a beat out in time,
# and every second of deadline is then a second that slot is held by an activity nobody
# is waiting on -- which starves the remaining slots, which makes the next beat late
# too. It is a feedback loop, and the deadline is its gain.
#
# Measured on the smoke fixture, same code and same fleet, only this number changed:
#
#     30 s deadline   ->  106 s wall,   4 retried activities
#     120 s deadline  ->  220 s wall,  29 retried activities
#
# Four times the retries from a wider deadline. Every activity here is idempotent
# (watermark tables and ReplacingMergeTree dedup), so an early retry costs a little
# repeated work, while a late one costs the whole deadline of wall clock and takes the
# rest of the fleet down with it. If timeouts show up under load, the thing to reduce is
# how much the box is oversubscribed -- `common_workers` x `common_concurrency` -- not
# the sensitivity of the detector.
HEARTBEAT_TIMEOUT = timedelta(seconds=30)

HEARTBEAT_INTERVAL_SECONDS = HEARTBEAT_INTERVAL.total_seconds()

#: Attempts every activity gets before its workflow gives up.
#:
#: Sized for LOSS, not for failure. About one activity in a hundred is dispatched during
#: a parse burst and never heard from again -- the worker completes it, but the box is
#: oversubscribed enough that the completion reaches the server after the deadline above
#: has already expired it. Those losses are correlated, because the process that missed
#: one beat is the process that misses the next, so three attempts is thinner than the
#: one-in-a-million it looks like: it has been observed running out on a 20-millisecond
#: activity and failing that file's whole parse.
#:
#: Raising it is close to free. Every activity here is idempotent on retry (watermark
#: tables and ReplacingMergeTree dedup), and an attempt that is never needed costs
#: nothing at all.
ACTIVITY_MAX_ATTEMPTS = 5


def worker_is_stopping() -> bool:
    """Whether this activity has been asked to stop.

    Two different requests, and a batch loop wants to obey both. The worker sets its
    shutdown event as soon as it is told to drain, which is the early warning;
    cancellation arrives later, through the heartbeat, when the graceful period runs out.
    Outside an activity -- in a unit test, or in the CLI -- neither exists and the answer
    is no.
    """
    if not activity.in_activity():
        return False
    return activity.is_worker_shutdown() or activity.is_cancelled()


def stop_if_worker_is_stopping(*progress) -> None:
    """Abandon a batch at a clean item boundary when the worker is being drained.

    Call this between items of a batch activity, never inside one. Everything completed
    before the call is already durable -- these loops write to ClickHouse as they go and
    skip finished work on the next attempt via a left-anti join or a watermark -- so
    stopping here costs one partial item at most.

    **Why this raises instead of returning a partial result.** A batch activity that
    returned early would report success over work it did not do, and its workflow would
    mark the stage finished: exactly the silent hole this exists to close. Raising a
    RETRYABLE error hands the batch back to Temporal, which redelivers it to a live
    worker, which skips what is already written and finishes the rest.

    **Why raising immediately is cheaper than being killed.** A killed activity is not
    noticed until its heartbeat deadline expires, and that lost time comes out of the
    same budget the retries need -- the reason a restart under load produced timeouts
    rather than exhausted attempts. Failing at once spends an attempt instead of a
    deadline.
    """
    if not worker_is_stopping():
        return
    from temporalio.exceptions import ApplicationError

    detail = " ".join(str(p) for p in progress)
    if activity.in_activity():
        activity.heartbeat(*progress)
    raise ApplicationError(
        "worker is shutting down; stopped at an item boundary"
        + (" after %s" % detail if detail else "")
    )


class HeartbeatClock:
    """Rate-limiter for in-loop heartbeats.

    Class B activities (those with a real loop) heartbeat inside the loop, which
    is strictly better than the pump below: it is evidence of *forward progress*
    rather than evidence of a live thread. But a tight loop over 50k rows must
    not call ``activity.heartbeat()`` 50k times, so gate it on this clock.

        hb = HeartbeatClock()
        for i, row in enumerate(rows):
            hb.beat(f"{i}/{len(rows)}")
            ...
    """

    def __init__(self, interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS):
        self.interval_seconds = interval_seconds
        # Beat once at the start of the loop: an activity that dies on its first
        # iteration should still have proven it got as far as starting.
        self._last = 0.0

    def beat(self, *details) -> bool:
        """Heartbeat if the interval has elapsed. Returns whether it did."""
        import time
        now = time.monotonic()
        if now - self._last < self.interval_seconds:
            return False
        self._last = now
        if activity.in_activity():
            activity.heartbeat(*details)
        return True


def with_heartbeat(fn):
    """Decorate a sync activity so its body always heartbeats while it runs.

    Apply directly under ``@activity.defn``::

        @activity.defn
        @with_heartbeat
        def parse_something(params): ...

    **Why this is a blanket default rather than a per-activity choice.**
    Every one of the 55 call sites declares ``HEARTBEAT_TIMEOUT``, and that
    deadline applies to *every* activity, including the ones whose real work
    legitimately takes minutes -- ffprobe on a large video, a Manticore batch
    write, a dataset purge. An activity that runs past the deadline without
    beating is killed and retried, and since the retry is just as slow, it is
    killed again: a permanent retry loop that looks exactly like a broken
    pipeline.

    Auditing 44 bodies for "can this exceed the deadline?" gets that answer
    wrong eventually, and gets it wrong again the next time someone adds an
    activity.
    Wrapping every body removes the question. The lost-task detection that
    motivated this whole change is untouched: a body that never runs never
    starts a pump, so the server still times it out on the heartbeat clock.

    This does NOT replace in-loop heartbeats. Where a loop exists, a
    ``HeartbeatClock`` inside it reports genuine progress (and shows an
    advancing count in ``temporal workflow describe``), while this only proves
    the worker thread is alive. Both are wanted.
    """
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with heartbeat_pump(fn.__name__):
            return fn(*args, **kwargs)

    return wrapper


@contextmanager
def heartbeat_pump(*details, interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS):
    """Heartbeat every ``interval_seconds`` while the body runs.

    For activities that block in a subprocess (7z, ffmpeg, qpdf, Extractous) and
    cannot heartbeat themselves. Prefer an in-loop ``HeartbeatClock`` when the
    body already has a loop. This is the weaker option: the pump keeps beating
    even if the *child* process wedges, so
    it detects a lost task, a dead worker or a wedged worker process, but not a
    wedged child. That case stays covered by the existing
    ``subprocess.run(..., timeout=...)`` guards, which must never be removed on
    the grounds that "we heartbeat now".
    """
    import contextvars
    import threading

    if not activity.in_activity():   # keeps the helper unit-testable
        yield
        return

    # THE TRAP: activity.heartbeat() resolves a contextvars.ContextVar
    # (temporalio/activity.py, _Context.current().heartbeat). A plain
    # threading.Thread starts with an EMPTY context, so calling it from the pump
    # raises "not in activity context". Copy the context here, in the activity's
    # own thread, and run the call through it.
    ctx = contextvars.copy_context()
    done = threading.Event()

    def pump():
        while not done.wait(interval_seconds):
            try:
                ctx.run(activity.heartbeat, *details)
            except Exception:
                return          # activity finished or was cancelled; stop quietly

    t = threading.Thread(target=pump, name="hb-pump", daemon=True)
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join(timeout=5)
