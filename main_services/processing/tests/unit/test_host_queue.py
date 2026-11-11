"""The host queues of tasks/host_queue.py and the worker settings of tasks/run_worker.py."""

import pytest

from tasks import host_queue


def test_pinned_names():
    assert host_queue.pinned("processing-tika-queue", "") == "processing-tika-queue"
    assert host_queue.pinned("processing-tika-queue", "w-1") == "processing-tika-queue@w-1"
    # A queue that reads no plan folder stays shared.
    assert host_queue.pinned("processing-indexing-queue", "w-1") == "processing-indexing-queue"


def test_host_lost_reads_the_cause_chain():
    from temporalio.exceptions import ApplicationError, TimeoutError, TimeoutType
    lost = ApplicationError("gone", type="HostLost")
    outer = RuntimeError("child failed")
    outer.__cause__ = lost
    assert host_queue.host_lost(outer)
    assert host_queue.host_lost(TimeoutError("late", type=TimeoutType.SCHEDULE_TO_START, last_heartbeat_details=[]))
    assert not host_queue.host_lost(TimeoutError("slow", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[]))
    assert not host_queue.host_lost(ApplicationError("parse", type="ParseError"))


@pytest.mark.parametrize(("value", "expected"), [("", "compose"), ("compose", "compose"),
                                                  (" k3s-branch ", "k3s-branch")])
def test_the_history_source_defaults_to_compose(monkeypatch, value, expected):
    monkeypatch.setenv("HOOVER4_HISTORY_SOURCE", value)
    assert host_queue.history_source() == expected


def test_an_unknown_history_source_stops_the_worker(monkeypatch):
    monkeypatch.setenv("HOOVER4_HISTORY_SOURCE", "fork")
    with pytest.raises(ValueError, match="HOOVER4_HISTORY_SOURCE"):
        host_queue.history_source()


def test_without_settings_the_workers_stay_as_configured(monkeypatch):
    """Compose sets no host queue and no tuner, so every worker keeps its own slots."""
    from tasks import run_worker
    monkeypatch.delenv("HOOVER4_HOST_QUEUE", raising=False)
    monkeypatch.delenv("HOOVER4_SLOT_TUNER", raising=False)
    workers = [object(), object()]
    assert run_worker.tuned_workers(workers) == workers


def test_shared_slots_hand_out_the_configured_count():
    slots = host_queue.SharedSlots(2)
    assert slots.try_reserve_slot(None) is not None
    assert slots.try_reserve_slot(None) is not None
    assert slots.try_reserve_slot(None) is None
    slots.release_slot(None)
    assert slots.try_reserve_slot(None) is not None


def test_an_async_activity_keeps_its_result_under_the_heartbeat_decorator():
    import asyncio

    from tasks.heartbeat import with_heartbeat

    @with_heartbeat
    async def answer(value: str) -> str:
        await asyncio.sleep(0)
        return value

    assert asyncio.run(answer("pod-a")) == "pod-a"
    assert answer.__name__ == "answer"
