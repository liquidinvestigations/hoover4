"""`read_page` in the special session `_reader`: the tab slots, the deadline, the browser.

Every `read_page` call reads in `_reader`, whatever session the caller names. Each URL
takes one tab slot. None of this needs Chromium. The CDP connection is a fake that answers
through the command parsers of `nodriver.cdp`, and the Chromium process is a fake too.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from types import SimpleNamespace

import pytest

from browser_use_server import chat_browser, read_page, router as router_mod, server
from browser_use_server import special_browser
from browser_use_server import reader_client
from browser_use_server.chat_browser import ChatBrowser
from browser_use_server.special_browser import SpecialBrowser, SlotWaitTimeout


def _run_cdp(command, answer: dict):
    """Give `answer` to a `nodriver.cdp` command generator and return its parsed result,
    the way `nodriver.Connection.send` does."""
    try:
        command.send(answer)
    except StopIteration as stop:
        return stop.value
    raise AssertionError("the command did not finish")


def _commit(loader: str) -> SimpleNamespace:
    """A `Page.frameNavigated` event of the main frame."""
    return SimpleNamespace(frame=SimpleNamespace(parent_id=None, loader_id=loader))


class FakeTab:
    """A reader tab. It answers `Page.enable`, `Page.navigate`, `Runtime.evaluate` and
    `Page.handleJavaScriptDialog`, and sends the events of its handlers."""

    def __init__(self, ready_states=(), values=None, error_text=None, download=False,
                 exception=None, dialog=None, hang=False, no_commit=False,
                 probe_hangs=False):
        self.ready_states = list(ready_states)
        self.values = dict(values or {})
        self.error_text = error_text
        self.download = download
        self.exception = exception
        self.dialog = dialog
        self.hang = hang
        self.no_commit = no_commit
        self.probe_hangs = probe_hangs
        self.probes = 0
        self.navigated: list[str] = []
        self.dialogs: list[bool] = []
        self.handlers: dict[type, list] = {}
        self.target = "T"
        self.closed = False

    def add_handler(self, event_type, callback):
        self.handlers.setdefault(event_type, []).append(callback)

    def emit(self, event_type, event):
        for callback in self.handlers.get(event_type, []):
            result = callback(event, self)
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)

    async def send(self, command):
        from nodriver import cdp

        cmd = next(command)
        method, params = cmd["method"], cmd.get("params", {})
        if method == "Page.enable":
            return _run_cdp(command, {})
        if method == "Page.handleJavaScriptDialog":
            self.dialogs.append(params["accept"])
            return _run_cdp(command, {})
        if method == "Page.navigate":
            self.navigated.append(params["url"])
            loader = f"L{len(self.navigated)}"
            answer = {"frameId": "F", "loaderId": loader, "isDownload": self.download}
            if self.error_text:
                answer["errorText"] = self.error_text
            elif not self.no_commit:
                self.emit(cdp.page.FrameNavigated, _commit(loader))
            if self.dialog:
                self.emit(cdp.page.JavascriptDialogOpening,
                          SimpleNamespace(type_=SimpleNamespace(value=self.dialog)))
            return _run_cdp(command, answer)
        assert method == "Runtime.evaluate"
        expression = params["expression"]
        if expression == special_browser.PROBE_EXPRESSION:
            self.probes += 1
            if self.probe_hangs:
                await asyncio.sleep(60)
            return _run_cdp(command, {"result": {"type": "number", "value": 1}})
        if expression == reader_client._READY_JS:
            state = self.ready_states.pop(0) if self.ready_states else "complete"
            return _run_cdp(command, {"result": {"type": "string", "value": state}})
        if self.hang:
            await asyncio.sleep(60)
        if self.exception:
            return _run_cdp(command, {
                "result": {"type": "object"},
                "exceptionDetails": {"exceptionId": 1, "text": "Uncaught", "lineNumber": 0,
                                     "columnNumber": 0,
                                     "exception": {"type": "object",
                                                   "description": self.exception}},
            })
        value = self.values[expression]
        return _run_cdp(command, {"result": {"type": "string", "value": value}})

    async def aclose(self):
        self.closed = True


def _target_info(target_id: str, kind: str = "page") -> dict:
    return {"targetId": target_id, "type": kind, "title": "", "url": "about:blank",
            "attached": False, "canAccessOpener": False}


class FakeBrowser:
    """The browser connection: creates, lists and closes targets.

    `create_gate` holds each creation until it is set. `close_hangs` makes a close never
    answer. `initial` names the page targets that exist before any lease.
    """

    def __init__(self, create_gate=None, close_hangs=False, initial=("START",)):
        self.created: list[str] = []
        self.closed: list[str] = []
        self.targets: dict[str, str] = {t: "page" for t in initial}
        self.open = 0
        self.most_open = 0
        self.create_gate = create_gate
        self.close_hangs = close_hangs

    async def send(self, command):
        cmd = next(command)
        if cmd["method"] == "Target.createTarget":
            assert cmd["params"]["newWindow"] is True
            if self.create_gate is not None:
                await self.create_gate.wait()
            target_id = f"T{len(self.created)}"
            self.created.append(target_id)
            self.targets[target_id] = "page"
            self.open += 1
            self.most_open = max(self.most_open, self.open)
            return _run_cdp(command, {"targetId": target_id})
        if cmd["method"] == "Target.getTargets":
            return _run_cdp(command, {"targetInfos": [
                _target_info(t, kind) for t, kind in self.targets.items()]})
        assert cmd["method"] == "Target.closeTarget"
        target_id = cmd["params"]["targetId"]
        if self.close_hangs:
            await asyncio.sleep(60)
        self.closed.append(target_id)
        if self.targets.pop(target_id, None) is not None and target_id in self.created:
            self.open -= 1
        return _run_cdp(command, {"success": True})


class FakeProc:
    """The Chromium process. `end()` makes it exit."""

    def __init__(self):
        self.returncode = None
        self._ended: asyncio.Event | None = None

    def _event(self) -> asyncio.Event:
        if self._ended is None:
            self._ended = asyncio.Event()
        return self._ended

    async def wait(self):
        await self._event().wait()
        return self.returncode

    def end(self, code: int = -9) -> None:
        self.returncode = code
        self._event().set()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(reader_client, "READY_POLL_S", 0)
    monkeypatch.setattr(reader_client, "SETTLE_S", 0)
    monkeypatch.setattr(read_page, "BOT_CHECK_POLL_S", 0)
    monkeypatch.setattr(read_page, "check_url", lambda url: None)


@pytest.fixture
def fake_tabs(monkeypatch):
    """`nodriver.Tab` replaced by `FakeTab`. Returns the tabs made, in order. A test puts
    the `FakeTab` arguments of the next tabs in `.settings`, or one default in
    `.default`."""
    import nodriver

    class Made(list):
        settings: list[dict]
        default: dict

    made = Made()
    made.settings = []
    made.default = {}

    def make(target, parent):
        settings = made.settings.pop(0) if made.settings else made.default
        tab = FakeTab(**settings)
        tab.target = target
        made.append(tab)
        return tab

    monkeypatch.setattr(nodriver, "Tab", make)
    return made


@pytest.fixture
def browsers(monkeypatch):
    """`chat_browser.start` and `stop` replaced by fakes. Returns the browsers started, in
    order. Set `.fail` to make the next start fail, and `.browser_args` for the
    `FakeBrowser` of the next starts."""

    class Started(list):
        fail = False
        browser_args: dict = {}
        stopped: list = []

    started = Started()
    started.stopped = []

    async def start(session_id, sidecar=True):
        assert sidecar is False
        if started.fail:
            raise chat_browser.BrowserSpawnFailed("no chromium")
        chat = ChatBrowser(session_id=session_id, browser=FakeBrowser(**started.browser_args),
                           chromium=FakeProc())
        started.append(chat)
        return chat

    async def stop(chat):
        started.stopped.append(chat)

    monkeypatch.setattr(chat_browser, "start", start)
    monkeypatch.setattr(chat_browser, "stop", stop)
    return started


_CHECK = f"({read_page._CHECK_JS})()"
_EXTRACT = f"({read_page.extract_script(True)})()"


def _page_values(title: str) -> dict:
    return {
        _CHECK: '{"text": "", "check": false, "url": "u", "title": "", "type": "text/html"}',
        _EXTRACT: '{"title": "%s", "url": "https://a.example/", "text": "%s text"}' % (title, title),
    }


def _later(seconds: float = 30.0) -> float:
    return time.monotonic() + seconds


class TestTabClient:
    def test_navigate_waits_for_the_new_document_to_load(self):
        tab = FakeTab(ready_states=["blank", "loading", "interactive", "interactive", "complete"])
        client = reader_client.TabClient(tab)
        answer = asyncio.run(client.call_tool("browser_navigate", {"url": "https://a.example/"}))
        assert not answer.is_error and tab.navigated == ["https://a.example/"]
        assert tab.ready_states == [] and client.document() == "ours"

    def test_a_page_that_never_fires_load_is_read_after_the_load_wait(self, monkeypatch):
        monkeypatch.setattr(reader_client, "LOAD_WAIT_S", 0.05)
        tab = FakeTab(ready_states=["interactive"] * 100_000)
        answer = asyncio.run(reader_client.TabClient(tab).call_tool(
            "browser_navigate", {"url": "https://a.example/"}))
        assert not answer.is_error

    def test_a_failed_navigation_is_an_error_answer(self):
        tab = FakeTab(error_text="net::ERR_NAME_NOT_RESOLVED")
        answer = asyncio.run(reader_client.TabClient(tab).call_tool(
            "browser_navigate", {"url": "https://a.example/"}))
        assert answer.is_error
        assert answer.content[0].text == "navigation failed: net::ERR_NAME_NOT_RESOLVED"

    def test_a_download_is_an_error_answer(self):
        tab = FakeTab(download=True)
        answer = asyncio.run(reader_client.TabClient(tab).call_tool(
            "browser_navigate", {"url": "https://a.example/file.zip"}))
        assert answer.is_error and "download" in answer.content[0].text

    def test_evaluate_returns_the_string_and_reports_an_exception(self):
        function = "() => JSON.stringify({text: 'x'})"
        tab = FakeTab(values={f"({function})()": '{"text": "x"}'})
        answer = asyncio.run(reader_client.TabClient(tab).call_tool(
            "browser_evaluate", {"function": function}))
        assert not answer.is_error and read_page._decode(answer.content[0].text) == {"text": "x"}
        broken = FakeTab(exception="Error: Execution context was destroyed.")
        answer = asyncio.run(reader_client.TabClient(broken).call_tool(
            "browser_evaluate", {"function": function}))
        assert answer.is_error
        assert answer.content[0].text == "Error: Execution context was destroyed."

    def test_read_one_reads_a_page_through_a_tab(self):
        reader = SimpleNamespace(client=reader_client.TabClient(FakeTab(values=_page_values("Article"))))
        page = asyncio.run(read_page._read_one(reader, "https://a.example/", "", 5000, "user"))
        assert page.title == "Article" and page.full_text == "Article text" and not page.error

    def test_a_document_that_never_committed_is_not_read(self):
        """A navigation that did not commit leaves the earlier document, `about:blank`."""
        reader = SimpleNamespace(client=reader_client.TabClient(FakeTab(
            values=_page_values("blank"), no_commit=True)))
        page = asyncio.run(read_page._read_one(reader, "https://a.example/", "", 5000, "user"))
        assert page.error == "The page did not load." and not page.full_text


class TestSpecialBrowser:
    def test_a_lease_opens_a_tab_in_a_new_window_and_closes_it(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 4)

        async def run():
            async with pool.lease(_later()) as lease:
                assert pool._leased == {lease.target_id} and pool.in_use == 1
                assert not lease.died.is_set()

        asyncio.run(run())
        browser = browsers[0].browser
        assert browser.created == ["T0"] and browser.closed == ["T0"] and fake_tabs[0].closed
        assert pool._leased == set() and pool.in_use == 0

    def test_concurrent_leases_share_one_browser_start(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 4)

        async def one():
            async with pool.lease(_later()):
                await asyncio.sleep(0.01)

        async def run():
            await asyncio.gather(*(one() for _ in range(4)))

        asyncio.run(run())
        assert len(browsers) == 1 and pool.starts == 1

    def test_the_tab_is_closed_when_the_work_fails_or_is_cancelled(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 4)

        async def fail():
            async with pool.lease(_later()):
                raise RuntimeError("boom")

        async def cancel():
            entered = asyncio.Event()

            async def hold():
                async with pool.lease(_later()):
                    entered.set()
                    await asyncio.sleep(60)

            task = asyncio.create_task(hold())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        async def run():
            with pytest.raises(RuntimeError):
                await fail()
            await cancel()

        asyncio.run(run())
        assert browsers[0].browser.closed == ["T0", "T1"]
        assert pool._leased == set() and pool.in_use == 0

    def test_at_most_slots_tabs_are_open_and_the_waits_are_counted(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 16)

        async def one():
            async with pool.lease(_later()):
                await asyncio.sleep(0.02)

        async def run():
            await asyncio.gather(*(one() for _ in range(20)))

        asyncio.run(run())
        assert browsers[0].browser.most_open == 16
        health = pool.health()
        assert health["peak_in_use"] == 16 and health["peak_waiting"] == 4
        assert health["leases"] == 20 and health["in_use"] == 0 and health["waiting"] == 0
        assert health["wait_max_s"] > 0 and health["wait_timeouts"] == 0

    def test_the_slot_wait_does_not_count_the_tab_opening(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 1)

        async def run():
            gate = asyncio.Event()
            asyncio.get_running_loop().call_later(0.2, gate.set)
            await pool._browser(_later())
            browsers[0].browser.create_gate = gate
            async with pool.lease(_later()) as lease:
                return lease.slot_wait_s, lease.tab_open_s

        slot_wait_s, tab_open_s = asyncio.run(run())
        assert slot_wait_s < 0.05 and tab_open_s >= 0.15

    def test_a_wait_past_the_deadline_raises(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 1)

        async def run():
            async with pool.lease(_later()):
                started = time.monotonic()
                with pytest.raises(SlotWaitTimeout):
                    async with pool.lease(time.monotonic() + 0.05):
                        pass
                return time.monotonic() - started

        assert asyncio.run(run()) < 1
        assert pool.health()["wait_timeouts"] == 1 and pool.waiting == 0

    def test_a_failed_start_is_raised_and_counted(self, browsers, fake_tabs):
        browsers.fail = True
        pool = SpecialBrowser("_reader", 2)

        async def run():
            with pytest.raises(chat_browser.BrowserSpawnFailed):
                async with pool.lease(_later()):
                    pass

        asyncio.run(run())
        assert pool.spawn_failures == 1 and pool.in_use == 0

    def test_a_dead_chromium_is_seen_by_its_leases_and_replaced(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 2)

        async def run():
            async with pool.lease(_later()) as lease:
                browsers[0].chromium.end()
                await asyncio.wait_for(lease.died.wait(), 1)
            for _ in range(5):
                await asyncio.sleep(0)
            assert not pool.alive()
            async with pool.lease(_later()) as lease:
                assert not lease.died.is_set()

        asyncio.run(run())
        assert len(browsers) == 2 and pool.deaths == 1 and pool.starts == 2
        # The dead browser's group and profile are cleaned up.
        assert browsers.stopped == [browsers[0]]

    def test_a_tab_made_after_a_cancel_is_closed(self, browsers, fake_tabs):
        async def run():
            gate = asyncio.Event()
            browsers.browser_args = {"create_gate": gate}
            pool = SpecialBrowser("_reader", 1)

            async def open_tab():
                async with pool.lease(_later()):
                    pass

            task = asyncio.create_task(open_tab())
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            gate.set()
            for _ in range(20):
                await asyncio.sleep(0)
            return pool

        pool = asyncio.run(run())
        browser = browsers[0].browser
        assert browser.created == ["T0"] and browser.closed == ["T0"]
        assert pool._leased == set() and pool.in_use == 0

    def test_a_close_that_never_answers_ends_within_the_close_timeout(self, browsers, fake_tabs,
                                                                      monkeypatch):
        monkeypatch.setattr(special_browser, "CLOSE_TIMEOUT_S", 0.05)
        browsers.browser_args = {"close_hangs": True}
        pool = SpecialBrowser("_reader", 1)

        async def run():
            async with pool.lease(_later()):
                pass
            # The slot is free again.
            async with pool.lease(time.monotonic() + 1):
                pass

        asyncio.run(asyncio.wait_for(run(), 5))
        assert pool._leased == set()

    def test_sweep_closes_the_tabs_that_no_lease_holds(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 2)

        async def run():
            async with pool.lease(_later()) as lease:
                browser = browsers[0].browser
                browser.targets["POPUP"] = "page"
                browser.targets["SW"] = "service_worker"
                assert await pool.sweep_tabs() == 1
                assert browser.closed == ["POPUP"]
                assert lease.target_id in browser.targets and "START" in browser.targets

        asyncio.run(run())
        assert pool.health()["tabs_swept"] == 1

    def test_sweep_without_a_browser_does_nothing(self):
        assert asyncio.run(SpecialBrowser("_reader", 2).sweep_tabs()) == 0


class TestWatchdog:
    """A new tab that does not answer fails its lease. `TAB_FAILURES` in a row restart the
    Chromium of the special browser."""

    @pytest.fixture(autouse=True)
    def short(self, monkeypatch):
        monkeypatch.setattr(special_browser, "TAB_ANSWER_S", 0.05)
        monkeypatch.setattr(special_browser, "TAB_FAILURES", 3)

    def test_each_new_tab_runs_the_probe(self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 2)

        async def run():
            async with pool.lease(_later()):
                pass

        asyncio.run(run())
        assert fake_tabs[0].probes == 1 and pool.health()["tabs_not_answering"] == 0

    def test_a_tab_that_does_not_run_the_probe_fails_its_lease_and_is_closed(
            self, browsers, fake_tabs):
        fake_tabs.settings = [{"probe_hangs": True}]
        pool = SpecialBrowser("_reader", 2)

        async def run():
            with pytest.raises(special_browser.TabNotAnswering, match="did not run a script"):
                async with pool.lease(_later()):
                    pass
            # One failure does not restart the browser, and the next tab works.
            async with pool.lease(_later()) as lease:
                assert not lease.died.is_set()

        asyncio.run(run())
        assert browsers[0].browser.closed == ["T0", "T1"] and pool._leased == set()
        health = pool.health()
        assert health["tabs_not_answering"] == 1 and health["watchdog_restarts"] == 0
        assert pool._tabs_not_answering == 0 and len(browsers) == 1

    def test_failures_in_a_row_restart_the_chromium_and_end_its_leases(
            self, browsers, fake_tabs):
        pool = SpecialBrowser("_reader", 8)

        async def run():
            held = asyncio.Event()
            release = asyncio.Event()
            outcome = {}

            async def hold():
                async with pool.lease(_later()) as lease:
                    held.set()
                    await asyncio.wait({asyncio.ensure_future(lease.died.wait()),
                                        asyncio.ensure_future(release.wait())},
                                       return_when=asyncio.FIRST_COMPLETED)
                    outcome["died"] = lease.died.is_set()

            holder = asyncio.create_task(hold())
            await held.wait()
            fake_tabs.default = {"probe_hangs": True}

            async def stuck():
                with pytest.raises(special_browser.TabNotAnswering):
                    async with pool.lease(_later()):
                        pass

            await asyncio.gather(*(stuck() for _ in range(3)))
            await asyncio.wait_for(holder, 1)
            fake_tabs.default = {}
            async with pool.lease(_later()) as lease:
                assert not lease.died.is_set()
            return outcome

        outcome = asyncio.run(run())
        assert outcome == {"died": True}
        assert len(browsers) == 2 and browsers.stopped == [browsers[0]]
        health = pool.health()
        assert health["watchdog_restarts"] == 1 and health["tabs_not_answering"] == 3
        assert health["starts"] == 2 and health["deaths"] == 0

    def test_a_creation_that_does_not_answer_counts_and_its_tab_is_closed_later(
            self, browsers, fake_tabs):
        async def run():
            gate = asyncio.Event()
            browsers.browser_args = {"create_gate": gate}
            pool = SpecialBrowser("_reader", 4)
            for _ in range(3):
                with pytest.raises(special_browser.TabNotAnswering, match="no new tab"):
                    async with pool.lease(_later()):
                        pass
            browsers.browser_args = {}
            gate.set()
            for _ in range(20):
                await asyncio.sleep(0)
            async with pool.lease(_later()):
                pass
            return pool

        pool = asyncio.run(run())
        assert pool.watchdog_restarts == 1 and len(browsers) == 2
        # The three late targets of the old browser are closed when they arrive.
        assert sorted(browsers[0].browser.closed) == ["T0", "T1", "T2"]

    def test_a_failure_after_a_success_starts_the_count_again(self, browsers, fake_tabs):
        fake_tabs.settings = [{"probe_hangs": True}, {"probe_hangs": True}, {},
                              {"probe_hangs": True}, {"probe_hangs": True}]
        pool = SpecialBrowser("_reader", 2)

        async def run():
            for _ in range(5):
                with contextlib.suppress(special_browser.TabNotAnswering):
                    async with pool.lease(_later()):
                        pass

        asyncio.run(run())
        assert pool.watchdog_restarts == 0 and pool.tabs_not_answering == 4



def _pool(slots: int = 16) -> SpecialBrowser:
    return SpecialBrowser("_reader", slots)




def test_shutdown_cancels_pending_browser_start(monkeypatch):
    started = asyncio.Event()
    cancelled = asyncio.Event()
    async def start(*args, **kwargs):
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()
    monkeypatch.setattr(chat_browser, "start", start)
    async def run():
        pool = SpecialBrowser("_reader", 1)
        waiting = asyncio.create_task(pool._browser(time.monotonic() + 60))
        await started.wait()
        await pool.shutdown()
        await asyncio.gather(waiting, return_exceptions=True)
        assert pool._starting.done() and pool._died.is_set()
        assert cancelled.is_set() and pool._chat is None
    asyncio.run(run())
