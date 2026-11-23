"""Shared test settings.

Outbound pacing (`agent_common.outbound_pacing`) is off in tests: no interval and no Redis,
so a test neither waits for a permit nor writes to a live store. A pacing test sets its own
interval.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_outbound_pacing(monkeypatch):
    from agent_common import outbound_pacing

    def no_store():
        raise RuntimeError("tests use process state")

    monkeypatch.setenv("OUTBOUND_INTERVAL_SECONDS", "0")
    monkeypatch.setattr(outbound_pacing, "_redis", no_store)
    monkeypatch.setattr(outbound_pacing, "_LOCAL", {})
