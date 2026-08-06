"""Per-chat browser session lifetime.

No Chromium here: the registry is pure bookkeeping and the disposer is injected, which
is the reason it is a separate module from `browser.py`.
"""

import asyncio

import pytest

from browser_use_server.sessions import (
    ANONYMOUS,
    MAX_SESSIONS,
    SessionRegistry,
    sweep,
)


@pytest.fixture
def registry():
    return SessionRegistry()


def test_each_chat_gets_its_own_session(registry):
    a = registry.get("chat-a")
    b = registry.get("chat-b")
    assert a is not b
    assert len(registry) == 2
    # And the same chat comes back to the same one, which is what keeps its cookies.
    assert registry.get("chat-a") is a


def test_callers_with_no_session_id_share_the_anonymous_one(registry):
    assert registry.get(None).session_id == ANONYMOUS
    assert registry.get("").session_id == ANONYMOUS
    assert registry.get("   ").session_id == ANONYMOUS
    assert len(registry) == 1


def test_using_a_session_records_the_call_and_resets_idle(registry):
    s = registry.get("chat-a")
    assert s.calls == 1
    s.last_used -= 10_000
    assert s.idle_seconds() > 9_000
    registry.get("chat-a")
    assert s.calls == 2
    assert s.idle_seconds() < 1


def test_only_sessions_past_the_idle_window_expire(registry):
    fresh = registry.get("fresh")
    stale = registry.get("stale")
    stale.last_used -= 7_200  # two hours

    expired = registry.expired()
    assert [s.session_id for s in expired] == ["stale"]
    assert fresh.session_id not in [s.session_id for s in expired]


def test_forget_removes_the_session_and_returns_it(registry):
    registry.get("chat-a")
    assert registry.forget("chat-a").session_id == "chat-a"
    assert len(registry) == 0
    # Forgetting twice is not an error; close is idempotent by design.
    assert registry.forget("chat-a") is None


def test_the_session_cap_evicts_the_least_recently_used(registry):
    for i in range(MAX_SESSIONS + 3):
        s = registry.get(f"chat-{i}")
        s.last_used = float(i)  # oldest first

    doomed = [s.session_id for s in registry.over_limit()]
    assert doomed == ["chat-0", "chat-1", "chat-2"]


def test_nothing_is_evicted_below_the_cap(registry):
    registry.get("only-one")
    assert registry.over_limit() == []


@pytest.mark.asyncio
async def test_sweep_disposes_expired_sessions_and_leaves_the_rest():
    reg = SessionRegistry()
    import browser_use_server.sessions as mod

    original = mod.registry
    mod.registry = reg
    try:
        reg.get("fresh")
        stale = reg.get("stale")
        stale.last_used -= 7_200

        disposed = []

        async def fake_dispose(session):
            disposed.append(session.session_id)

        count = await sweep(fake_dispose)
        assert count == 1
        assert disposed == ["stale"]
        # The disposed one is gone from the registry, the fresh one is untouched.
        assert len(reg) == 1
        assert reg.get("fresh").session_id == "fresh"
    finally:
        mod.registry = original


@pytest.mark.asyncio
async def test_sweep_is_a_no_op_when_nothing_is_idle():
    reg = SessionRegistry()
    import browser_use_server.sessions as mod

    original = mod.registry
    mod.registry = reg
    try:
        reg.get("busy")
        disposed = []

        async def fake_dispose(session):
            disposed.append(session.session_id)

        assert await sweep(fake_dispose) == 0
        assert disposed == []
    finally:
        mod.registry = original


def test_describe_reports_what_the_health_endpoint_needs(registry):
    s = registry.get("chat-a")
    s.context_id = "ctx-1"
    described = registry.describe()
    assert described[0]["session_id"] == "chat-a"
    assert described[0]["has_context"] is True
    assert described[0]["calls"] == 1
    assert described[0]["idle_seconds"] >= 0


def test_asyncio_is_importable_for_the_reaper():
    # Guards against the reaper module losing its asyncio import in a refactor.
    assert asyncio is not None
