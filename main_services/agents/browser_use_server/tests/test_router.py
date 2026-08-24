"""Router lifetime: the LRU cap, the idle reaper, idempotent close.

`chat_browser.start` and `chat_browser.stop` are stubbed, so none of this needs Chromium
or Node. The same approach the retired `test_sessions.py` took with the disposer, moved
up one level now that a session owns two processes instead of a context id.
"""

import asyncio

import pytest

from browser_use_server import chat_browser, router as router_mod
from browser_use_server.chat_browser import ChatBrowser


@pytest.fixture
def fake_browsers(monkeypatch):
    """A router whose browsers are dataclasses, not processes."""
    started, stopped = [], []

    async def fake_start(session_id):
        started.append(session_id)
        return ChatBrowser(session_id=session_id, sidecar_port=1234)

    async def fake_stop(chat):
        stopped.append(chat.session_id)

    monkeypatch.setattr(chat_browser, "start", fake_start)
    monkeypatch.setattr(chat_browser, "stop", fake_stop)
    monkeypatch.setattr(chat_browser, "sidecar_alive", lambda chat: True)
    monkeypatch.setattr(router_mod.chat_browser, "start", fake_start)
    monkeypatch.setattr(router_mod.chat_browser, "stop", fake_stop)
    monkeypatch.setattr(router_mod.chat_browser, "sidecar_alive", lambda chat: True)
    return router_mod.Router(), started, stopped


class TestPerChatIsolation:
    def test_two_chats_get_two_browsers(self, fake_browsers):
        router, started, _ = fake_browsers

        async def run():
            a = await router.get("chat-a")
            b = await router.get("chat-b")
            return a, b

        a, b = asyncio.run(run())
        assert a is not b
        assert started == ["chat-a", "chat-b"]

    def test_the_same_chat_reuses_its_browser(self, fake_browsers):
        router, started, _ = fake_browsers

        async def run():
            return await router.get("chat-a"), await router.get("chat-a")

        a, b = asyncio.run(run())
        assert a is b
        assert started == ["chat-a"]

    def test_no_session_header_shares_one_anonymous_browser(self, fake_browsers):
        router, started, _ = fake_browsers

        async def run():
            return await router.get(None), await router.get("   ")

        a, b = asyncio.run(run())
        assert a is b
        assert started == [router_mod.ANONYMOUS]


class TestEviction:
    def test_the_least_recently_used_chat_is_evicted_at_the_cap(self, fake_browsers, monkeypatch):
        """At the cap, the newest chat evicts the least recently used one, and the evicted
        chat's next call transparently gets a fresh browser rather than an error."""
        router, started, stopped = fake_browsers
        monkeypatch.setattr(router_mod, "MAX_CONTEXTS", 3)

        async def run():
            for i in range(3):
                await router.get(f"chat-{i}")
            await router.get("chat-0")  # make chat-1 the least recently used
            await router.get("chat-3")
            return await router.get("chat-1")

        revived = asyncio.run(run())
        # chat-1 was the least recently used when chat-3 arrived, so it went first.
        # Reviving it then evicts the *next* least recently used, chat-2. The cap is a
        # memory ceiling, so coming back always costs somebody their browser.
        assert stopped == ["chat-1", "chat-2"]
        assert revived.session_id == "chat-1"
        assert started.count("chat-1") == 2

    def test_eviction_tears_the_browser_down(self, fake_browsers, monkeypatch):
        router, _, stopped = fake_browsers
        monkeypatch.setattr(router_mod, "MAX_CONTEXTS", 1)

        async def run():
            await router.get("a")
            await router.get("b")

        asyncio.run(run())
        assert stopped == ["a"]


class TestReaping:
    def test_an_idle_chat_is_reaped(self, fake_browsers):
        router, _, stopped = fake_browsers

        async def run():
            chat = await router.get("idle")
            chat.last_used -= 10_000  # pretend it has been sitting for hours
            await router.get("busy")
            return await router.sweep()

        assert asyncio.run(run()) == 1
        assert stopped == ["idle"]

    def test_a_busy_chat_survives_the_sweep(self, fake_browsers):
        router, _, stopped = fake_browsers

        async def run():
            await router.get("busy")
            return await router.sweep()

        assert asyncio.run(run()) == 0
        assert stopped == []

    def test_health_reflects_a_reaped_session(self, fake_browsers):
        router, _, _ = fake_browsers

        async def run():
            chat = await router.get("idle")
            chat.last_used -= 10_000
            await router.sweep()
            return router.health()

        assert asyncio.run(run())["live_sessions"] == 0


class TestClose:
    def test_close_is_idempotent(self, fake_browsers):
        router, _, stopped = fake_browsers

        async def run():
            await router.get("a")
            return await router.close("a"), await router.close("a")

        first, second = asyncio.run(run())
        assert first is True and second is False
        assert stopped == ["a"]

    def test_closing_an_unknown_session_is_not_an_error(self, fake_browsers):
        router, _, _ = fake_browsers
        assert asyncio.run(router.close("never-existed")) is False


class TestSidecarRecovery:
    def test_a_dead_sidecar_is_restarted_on_the_next_call(self, fake_browsers, monkeypatch):
        """Restarting here rather than failing means the tool call the user is waiting on
        succeeds, instead of failing once just to discover the process was gone."""
        router, _, _ = fake_browsers
        restarts = []

        async def fake_restart(chat):
            restarts.append(chat.session_id)

        alive = {"value": True}
        monkeypatch.setattr(router_mod.chat_browser, "sidecar_alive", lambda chat: alive["value"])
        monkeypatch.setattr(router_mod.chat_browser, "restart_sidecar", fake_restart)

        async def run():
            await router.get("a")
            alive["value"] = False
            await router.get("a")

        asyncio.run(run())
        assert restarts == ["a"]


class TestSpawnDoesNotBlockOtherChats:
    """The map lock must not be held across a spawn.

    A cold Chromium plus its Node sidecar takes 45–90 seconds. Holding the router's single
    lock for that long made every other chat's tool call queue behind one chat's first
    browse. An eight-context router behaving like a one-context one, and the symptom is
    "the site is slow", never "the browser router is serialising".
    """

    def test_a_second_chat_is_served_while_the_first_is_still_spawning(
        self, fake_browsers, monkeypatch
    ):
        router, started, _ = fake_browsers
        release_slow = asyncio.Event()

        async def slow_for_a(session_id):
            started.append(session_id)
            if session_id == "slow":
                await release_slow.wait()
            return ChatBrowser(session_id=session_id, sidecar_port=1234)

        monkeypatch.setattr(router_mod.chat_browser, "start", slow_for_a)

        async def run():
            slow = asyncio.create_task(router.get("slow"))
            await asyncio.sleep(0)  # let it reach the spawn
            # What this asserts: this must complete while `slow` is still in `start`.
            fast = await asyncio.wait_for(router.get("fast"), timeout=1.0)
            release_slow.set()
            return await slow, fast

        slow_chat, fast_chat = asyncio.run(run())
        assert slow_chat.session_id == "slow"
        assert fast_chat.session_id == "fast"

    def test_two_callers_for_one_chat_share_a_single_spawn(self, fake_browsers, monkeypatch):
        """Releasing the lock must not cost the thing the lock was there for: two browsers
        for one chat would double the memory and split the cookies."""
        router, started, _ = fake_browsers
        release = asyncio.Event()

        async def slow_start(session_id):
            started.append(session_id)
            await release.wait()
            return ChatBrowser(session_id=session_id, sidecar_port=1234)

        monkeypatch.setattr(router_mod.chat_browser, "start", slow_start)

        async def run():
            first = asyncio.create_task(router.get("a"))
            second = asyncio.create_task(router.get("a"))
            await asyncio.sleep(0)
            release.set()
            return await first, await second

        one, two = asyncio.run(run())
        assert one is two
        assert started == ["a"], "the second caller started a second browser"

    def test_a_failed_shared_spawn_does_not_wedge_the_chat_forever(
        self, fake_browsers, monkeypatch
    ):
        """The pending entry has to be cleared on failure, or the chat can never start."""
        router, started, _ = fake_browsers
        fail = {"value": True}

        async def maybe_failing(session_id):
            started.append(session_id)
            if fail["value"]:
                raise chat_browser.BrowserSpawnFailed("no chromium")
            return ChatBrowser(session_id=session_id, sidecar_port=1234)

        monkeypatch.setattr(router_mod.chat_browser, "start", maybe_failing)

        async def run():
            with pytest.raises(chat_browser.BrowserSpawnFailed):
                await router.get("a")
            fail["value"] = False
            return await router.get("a")

        assert asyncio.run(run()).session_id == "a"

    def test_eviction_still_happens_and_still_stops_the_browser(
        self, fake_browsers, monkeypatch
    ):
        """Eviction moved outside the lock; it must not have moved out of existence."""
        router, _, stopped = fake_browsers
        monkeypatch.setattr(router_mod, "MAX_CONTEXTS", 2)

        async def run():
            await router.get("a")
            await router.get("b")
            await router.get("c")

        asyncio.run(run())
        assert stopped == ["a"]
        assert len(router.describe()) == 2


class TestHealth:
    def test_spawn_failures_are_counted(self, fake_browsers, monkeypatch):
        router, _, _ = fake_browsers

        async def failing_start(session_id):
            raise chat_browser.BrowserSpawnFailed("no chromium")

        monkeypatch.setattr(router_mod.chat_browser, "start", failing_start)

        async def run():
            with pytest.raises(chat_browser.BrowserSpawnFailed):
                await router.get("a")
            return router.health()

        assert asyncio.run(run())["spawn_failures"] == 1


class TestTabCap:
    """`BROWSER_MAX_TABS_PER_CHAT` was rendered into the environment and read by nothing.
    Exactly the config-that-is-false trap AGENTS.md names. These pin the enforcement."""

    class _Tab:
        def __init__(self, name, kind="page"):
            self.name = name
            self.target = type("T", (), {"type_": kind})()
            self.closed = False

        async def close(self):
            self.closed = True

    class _Browser:
        def __init__(self, tabs):
            self.tabs = tabs

        async def update_targets(self):
            return None

    def _chat(self, tabs):
        chat = ChatBrowser(session_id="a")
        chat.browser = self._Browser(tabs)
        return chat

    def test_the_oldest_tabs_are_closed_past_the_cap(self):
        # The oldest, not the newest: the tab the agent is looking at is the one it just
        # opened.
        tabs = [self._Tab(f"t{i}") for i in range(9)]
        chat = self._chat(tabs)
        closed = asyncio.run(chat_browser.enforce_tab_cap(chat, 6))
        assert closed == 3
        assert [t.name for t in tabs if t.closed] == ["t0", "t1", "t2"]

    def test_a_chat_under_the_cap_is_untouched(self):
        tabs = [self._Tab(f"t{i}") for i in range(3)]
        chat = self._chat(tabs)
        assert asyncio.run(chat_browser.enforce_tab_cap(chat, 6)) == 0
        assert not any(t.closed for t in tabs)

    def test_non_page_targets_do_not_count(self):
        # Service workers and extension backgrounds are targets too, and closing a real
        # tab because an extension has one would be a silent loss of the agent's work.
        tabs = [self._Tab(f"t{i}") for i in range(3)] + [
            self._Tab("sw", kind="service_worker"),
            self._Tab("bg", kind="background_page"),
        ]
        chat = self._chat(tabs)
        assert asyncio.run(chat_browser.enforce_tab_cap(chat, 3)) == 0

    def test_a_chat_with_no_browser_is_not_an_error(self):
        assert asyncio.run(chat_browser.enforce_tab_cap(ChatBrowser(session_id="a"), 6)) == 0

    def test_a_tab_that_will_not_close_does_not_fail_the_call(self):
        class Stubborn(TestTabCap._Tab):
            async def close(self):
                raise RuntimeError("nope")

        tabs = [Stubborn("t0"), self._Tab("t1"), self._Tab("t2")]
        chat = self._chat(tabs)
        # One refuses, the cap is still applied to what it can.
        assert asyncio.run(chat_browser.enforce_tab_cap(chat, 1)) == 1
