"""The readiness gate that runs before each CLI workflow start.

A clock and a sleep driven by hand replace the real ones, so no test here sleeps. A
stand-in client answers the four probe calls.
"""

import asyncio
import os
import pathlib
import re

import pytest
from temporalio.service import RPCError, RPCStatusCode

from tasks import temporal_readiness as gate


class Clock:
    """A monotonic clock that moves only when the gate sleeps."""

    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class StandInClient:
    """Answers the four probe calls. `describe_error(now)` picks the describe result."""

    def __init__(self, clock, *, namespace_bad=lambda now: False,
                 describe_error=lambda now: None):
        self.clock = clock
        self.namespace_bad = namespace_bad
        self.describe_error = describe_error
        self.service_client = self
        self.workflow_service = self
        self.described = []

    async def check_health(self, timeout=None):
        return True

    async def describe_namespace(self, request, timeout=None):
        if self.namespace_bad(self.clock()):
            raise RPCError("shard status unknown", RPCStatusCode.UNAVAILABLE, b"")
        return object()

    async def list_workflow_executions(self, request, timeout=None):
        assert request.page_size == 1
        return object()

    def get_workflow_handle(self, workflow_id):
        self.described.append(workflow_id)
        client = self

        class Handle:
            async def describe(self, rpc_timeout=None):
                error = client.describe_error(client.clock())
                if error is not None:
                    raise error
                return object()

        return Handle()


def run_gate(client, clock):
    asyncio.run(gate.wait_for_temporal(client, clock=clock, sleep=clock.sleep))


def test_ready_after_five_seconds_of_good_probes():
    clock = Clock()
    client = StandInClient(clock)
    run_gate(client, clock)
    assert clock.now == gate.READY_STABLE_SECONDS
    assert set(client.described) == {gate.COLLECTOR_WORKFLOW_ID}


def test_a_bad_probe_resets_the_good_run():
    # Good at 0 to 4 s, bad at 5 s, good again from 6 s: the new run is 5 s old at 11 s.
    clock = Clock()
    client = StandInClient(clock, namespace_bad=lambda now: now == 5)
    run_gate(client, clock)
    assert clock.now == 11


def test_the_deadline_raises_with_the_text_and_the_last_error():
    clock = Clock()
    client = StandInClient(clock, namespace_bad=lambda now: True)
    with pytest.raises(gate.TemporalNotReady) as raised:
        run_gate(client, clock)
    assert clock.now == gate.READY_DEADLINE_SECONDS
    assert str(raised.value) == gate.READY_ERROR_TEXT.format(
        last_error="RPCError: shard status unknown")
    assert str(raised.value).startswith(
        "Temporal did not stay ready for 5 s within 60 s, so the workflow was not started.")


def test_an_absent_collector_counts_as_good():
    clock = Clock()
    client = StandInClient(
        clock,
        describe_error=lambda now: RPCError("not found", RPCStatusCode.NOT_FOUND, b""),
    )
    run_gate(client, clock)
    assert clock.now == gate.READY_STABLE_SECONDS


def test_another_describe_error_resets_the_good_run():
    clock = Clock()
    client = StandInClient(
        clock,
        describe_error=lambda now: (
            RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"") if now == 3 else None
        ),
    )
    run_gate(client, clock)
    assert clock.now == 9


def test_a_refused_submit_writes_the_row_errored(monkeypatch):
    import temporalio.client

    import database.operations as operations
    from tasks.P_ops import cli

    finished = []

    async def connect(_target):
        return object()

    async def refuse(_client):
        raise gate.TemporalNotReady(gate.READY_ERROR_TEXT.format(last_error="x"))

    async def no_attribute_wait(_client):
        pytest.fail("the search-attribute wait ran after a refusal")

    monkeypatch.setattr(temporalio.client.Client, "connect", staticmethod(connect))
    monkeypatch.setattr(gate, "wait_for_temporal", refuse)
    monkeypatch.setattr("tasks.visibility.ensure_search_attributes_ready", no_attribute_wait)
    monkeypatch.setattr(operations, "create_operation",
                        lambda *_args, **_kwargs: {"op_id": "op"})
    monkeypatch.setattr(operations, "finish_operation",
                        lambda op_id, state, error: finished.append((op_id, state, error)))
    with pytest.raises(gate.TemporalNotReady):
        cli.submit_operation("reindex_collection", collectionname="c")
    assert finished == [(
        "op", "errored", "TemporalNotReady: " + gate.READY_ERROR_TEXT.format(last_error="x"),
    )]


def _rust_gate_source() -> str | None:
    """`website/backend/src/temporal_ready.rs`, or None when it is not reachable.

    The worker container mounts only `main_services/processing`. Set
    `HOOVER4_TEMPORAL_READY_RS` to a copy of the file to run the comparison there.
    """
    override = os.environ.get("HOOVER4_TEMPORAL_READY_RS")
    if override:
        return pathlib.Path(override).read_text()
    for parent in pathlib.Path(__file__).resolve().parents:
        candidate = parent / "website" / "backend" / "src" / "temporal_ready.rs"
        if candidate.is_file():
            return candidate.read_text()
    return None


def test_the_constants_match_the_rust_gate():
    source = _rust_gate_source()
    if source is None:
        pytest.skip("website/backend/src/temporal_ready.rs is not mounted here")

    def rust_const(name: str) -> str:
        match = re.search(rf"pub const {name}: [^=]+= (.+?);\n", source)
        assert match, f"{name} not found in temporal_ready.rs"
        return match.group(1)

    for name in ("READY_STABLE_SECONDS", "READY_DEADLINE_SECONDS",
                 "PROBE_INTERVAL_SECONDS", "PROBE_TIMEOUT_SECONDS"):
        assert int(rust_const(name)) == getattr(gate, name), name
    assert rust_const("COLLECTOR_WORKFLOW_ID") == f'"{gate.COLLECTOR_WORKFLOW_ID}"'
    assert rust_const("READY_ERROR_TEXT") == f'"{gate.READY_ERROR_TEXT}"'
