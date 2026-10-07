"""The `web_search` admission gate, the fetch budget and the fan-out deadline. No network."""

import asyncio

import pytest

from metasearch_server import admission, pipeline, sources as sources_mod
from metasearch_server.engines import SearchResult


def _run_many(gate: admission.Gate, calls: int, hold: float):
    """Start `calls` holders at once. Each keeps its slot for `hold` seconds."""
    peak = {"running": 0}
    outcomes = []

    async def one():
        try:
            async with gate.slot():
                peak["running"] = max(peak["running"], gate.running)
                await asyncio.sleep(hold)
            outcomes.append("ok")
        except admission.Busy as exc:
            outcomes.append(str(exc))

    async def main():
        await asyncio.gather(*(one() for _ in range(calls)))

    asyncio.run(main())
    return peak["running"], outcomes


class TestGate:
    def test_no_more_than_the_limit_run_and_the_rest_wait(self):
        gate = admission.Gate(limit=3, wait_seconds=5)
        peak, outcomes = _run_many(gate, calls=7, hold=0.05)
        assert peak == 3
        assert outcomes == ["ok"] * 7
        state = gate.state()
        assert state["peak_running"] == 3
        assert state["queued"] == 4
        assert state["admitted"] == 7
        assert state["refused_busy"] == 0
        assert state["running"] == 0 and state["waiting"] == 0

    def test_a_call_that_waits_too_long_gets_a_busy_result(self):
        gate = admission.Gate(limit=1, wait_seconds=0.05)
        _, outcomes = _run_many(gate, calls=2, hold=0.3)
        assert outcomes.count("ok") == 1
        busy = [o for o in outcomes if o != "ok"]
        assert len(busy) == 1 and "busy" in busy[0]
        assert gate.state()["refused_busy"] == 1

    def test_a_failing_call_releases_its_slot(self):
        gate = admission.Gate(limit=1, wait_seconds=0.5)

        async def main():
            try:
                async with gate.slot():
                    raise ValueError("boom")
            except ValueError:
                pass
            async with gate.slot():
                return gate.running

        assert asyncio.run(main()) == 1
        assert gate.state()["running"] == 0


class TestFetchBudget:
    def test_queries_past_the_budget_are_skipped_and_named(self, monkeypatch):
        calls = []

        async def fetch_all(query, names, per_source_results=15, timelimit=None,
                            overall_timeout=None):
            calls.append((query, overall_timeout))
            await asyncio.sleep(0.15)
            return ({"ddg": [SearchResult(query, f"https://{query}.example")]}, {"ddg": 1.0}, [],
                    {}, {"ddg": "direct"})

        monkeypatch.setattr(sources_mod, "fetch_all", fetch_all)
        monkeypatch.setattr(sources_mod, "resolve_sources", lambda requested: (["ddg"], []))
        monkeypatch.setattr(pipeline, "FETCH_BUDGET", 1.1)
        monkeypatch.setattr(pipeline, "MIN_QUERY_SECONDS", 1.0)
        outcome = asyncio.run(pipeline.run_search(["a", "b", "c"], max_results=10))
        # The first query starts with 1.1 s left. After it, less than 1 s is left.
        assert [q for q, _ in calls] == ["a"]
        assert calls[0][1] <= 1.1
        assert outcome.skipped_queries == ["b", "c"]


class TestFanOutDeadline:
    def test_a_finished_source_keeps_its_results_when_another_is_cut(self, monkeypatch):
        async def fast(query, max_results, timelimit):
            return [SearchResult("f", "https://fast.example")]

        async def slow(query, max_results, timelimit):
            await asyncio.sleep(5)
            return [SearchResult("s", "https://slow.example")]

        monkeypatch.setitem(
            sources_mod.SOURCES, "fast_test",
            sources_mod.Source(name="fast_test", kind="web", fetch=fast, timeout=10),
        )
        monkeypatch.setitem(
            sources_mod.SOURCES, "slow_test",
            sources_mod.Source(name="slow_test", kind="web", fetch=slow, timeout=10),
        )
        per_source, _, degraded, reasons, _ = asyncio.run(
            sources_mod.fetch_all("q", ["fast_test", "slow_test"], overall_timeout=0.2)
        )
        assert [r.url for r in per_source["fast_test"]] == ["https://fast.example"]
        assert degraded == ["slow_test"]
        assert "overall deadline" in reasons["slow_test"]


@pytest.mark.asyncio
async def test_full_queue_refuses_and_cancelled_waiter_releases_capacity():
    gate = admission.Gate(limit=1, wait_seconds=10, max_waiting=1)
    async with gate.slot():
        async def wait():
            async with gate.slot():
                pytest.fail("The waiting call entered an occupied slot.")
        waiter = asyncio.create_task(wait())
        await asyncio.sleep(0)
        with pytest.raises(admission.Busy, match="queue is full"):
            async with gate.slot():
                pass
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert gate.waiting == 0
    assert gate.running == 0
    async with gate.slot():
        assert gate.running == 1
