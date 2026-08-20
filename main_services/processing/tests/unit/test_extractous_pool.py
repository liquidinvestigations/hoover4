"""Extractous helper pool: timeout kills the child and the next extract works."""

import os
import sys

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files.parse_tika import ExtractousHelperPool


_SLEEP_HELPER = [
    sys.executable,
    "-u",
    "-c",
    "import sys, time\n"
    "for line in sys.stdin:\n"
    "    time.sleep(30)\n",
]

_ECHO_HELPER = [
    sys.executable,
    "-u",
    "-c",
    "import json, sys\n"
    "for line in sys.stdin:\n"
    "    json.loads(line)\n"
    "    sys.stdout.write(json.dumps({'ok': True, 'text': 'ok', 'metadata': {}}))\n"
    "    sys.stdout.write('\\n')\n"
    "    sys.stdout.flush()\n",
]


def test_timeout_kills_the_helper_and_the_next_extract_succeeds():
    pool = ExtractousHelperPool(size=1, helper_cmd=_SLEEP_HELPER, timeout_s=0.3)
    try:
        with pytest.raises(ApplicationError) as excinfo:
            pool.extract("/does/not/matter")
        assert excinfo.value.non_retryable is True
        killed = pool.last_killed_pid
        assert killed is not None
        with pytest.raises(ProcessLookupError):
            os.kill(killed, 0)
        assert pool._live == 0

        pool._helper_cmd = _ECHO_HELPER
        text, meta = pool.extract("/does/not/matter")
        assert text == "ok"
        assert meta == {}
    finally:
        pool.close()


def test_warm_helper_reuses_the_same_process():
    pool = ExtractousHelperPool(size=1, helper_cmd=_ECHO_HELPER, timeout_s=5)
    try:
        pool.extract("/a")
        helper = pool._idle.get_nowait()
        first_pid = helper.pid
        pool._idle.put(helper)
        pool.extract("/b")
        helper = pool._idle.get_nowait()
        assert helper.pid == first_pid
        pool._idle.put(helper)
    finally:
        pool.close()


def test_a_checkout_recovers_after_every_helper_is_killed():
    """A killed helper never checks back in.

    Two threads, one slot: the second parks on the idle queue while the first
    holds the only helper. The timeout kills that helper, so nothing is ever put
    back. A checkout that waited on the queue without a bound would still be
    parked here; instead it re-checks and spawns.
    """
    import threading

    pool = ExtractousHelperPool(size=1, helper_cmd=_SLEEP_HELPER, timeout_s=0.3)
    result: list = []

    def waiter():
        pool._helper_cmd = _ECHO_HELPER
        try:
            result.append(pool.extract("/second"))
        except Exception as exc:  # noqa: BLE001 - the assertion is below
            result.append(exc)

    try:
        # Hold the only slot, then start the waiter so it parks on the idle queue.
        held = pool._checkout()
        thread = threading.Thread(target=waiter, daemon=True)
        thread.start()
        pool._kill(held)
        thread.join(timeout=15)
        assert not thread.is_alive(), "checkout never returned after the helper was killed"
        assert result == [("ok", {})]
    finally:
        pool.close()
