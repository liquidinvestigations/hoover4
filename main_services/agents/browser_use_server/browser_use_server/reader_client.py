"""Navigate and evaluate one leased reader tab through CDP."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from types import SimpleNamespace

log = logging.getLogger(__name__)

#: How long a page gets to fire its load event after its document is ready to read. The
#: sidecar's `browser_navigate` waits the same time.
LOAD_WAIT_S = 5.0

#: The wait after the load event, for script that renders the page. The sidecar's
#: `browser_navigate` waits the same time.
SETTLE_S = 0.5

#: How often the reader tab is asked for its `document.readyState`.
READY_POLL_S = 0.2

#: How long the probe and the extraction script may run in a reader tab.
SCRIPT_TIMEOUT_S = float(os.getenv("READ_PAGE_SCRIPT_TIMEOUT_S", "15"))

#: How long one PDF slice script may run. The first slice fetches the whole file.
PDF_SLICE_TIMEOUT_S = 60.0

#: Is the committed document ready to read? `about:blank` is the empty tab before the first
#: navigation commits.
_READY_JS = "location.href === 'about:blank' ? 'blank' : document.readyState"

def _answer(text: str, error: bool = False) -> SimpleNamespace:
    """A tool answer in the shape that the sidecar client gives and `_call` reads."""
    return SimpleNamespace(content=[SimpleNamespace(text=text)], is_error=error)


class TabClient:
    """Answers `browser_navigate` and `browser_evaluate` in one tab of the `_reader` session.

    The answers have the shape of the sidecar's answers, so `_read_one` reads a page the
    same way through either. A JavaScript dialog is dismissed, because an open dialog stops
    every script in the page.
    """

    def __init__(self, tab) -> None:
        self.tab = tab
        self._enabled = False
        #: The loader of this client's last navigation, or None.
        self._own = None
        #: The loaders of the main-frame documents that committed since then.
        self._commits: list[str] = []
        #: The URL of the last main-frame document that committed. For an error page of
        #: Chromium it is the URL that could not be reached, for example a redirect target.
        self.seen_url = ""

    async def call_tool(self, tool: str, arguments: dict, raise_on_error: bool = False):
        timeout = float(arguments.get("timeout") or SCRIPT_TIMEOUT_S)
        try:
            await self._enable()
            if tool == "browser_navigate":
                error = await self._navigate(str(arguments["url"]))
                return _answer(error, error=True) if error else _answer("")
            if tool == "browser_evaluate":
                return await asyncio.wait_for(
                    self._evaluate(str(arguments["function"])), timeout=timeout
                )
        except asyncio.TimeoutError:
            return _answer(f"{tool} did not finish within {timeout:g}s", error=True)
        except Exception as exc:  # noqa: BLE001 - CDP raises a protocol error per failure
            return _answer(f"{tool} failed: {exc}", error=True)
        return _answer(f"{tool} is not available in a read_page tab", error=True)

    async def _enable(self) -> None:
        """Receive the navigation and dialog events of the tab. Once per tab."""
        if self._enabled:
            return
        from nodriver import cdp

        self.tab.add_handler(cdp.page.FrameNavigated, self._on_navigated)
        self.tab.add_handler(cdp.page.JavascriptDialogOpening, self._on_dialog)
        await self.tab.send(cdp.page.enable())
        self._enabled = True

    def _on_navigated(self, event, _tab=None) -> None:
        frame = event.frame
        if getattr(frame, "parent_id", None):
            return
        self._commits.append(str(frame.loader_id))
        self.seen_url = str(getattr(frame, "unreachable_url", None)
                            or getattr(frame, "url", None) or "")

    async def _on_dialog(self, event, _tab=None) -> None:
        from nodriver import cdp

        kind = str(getattr(event.type_, "value", event.type_))
        try:
            await self.tab.send(cdp.page.handle_java_script_dialog(
                accept=kind in ("alert", "beforeunload")))
        except Exception as exc:  # noqa: BLE001 - the page can have closed it first
            log.debug("read_page: dialog not dismissed: %s", exc)

    def document(self) -> str:
        """`ours` when the navigation of this client committed. The tab then shows its
        document, or a document that the page itself navigated to from it. `none` while no
        navigation of this client has committed, so the tab still shows an earlier
        document, such as `about:blank`."""
        return "ours" if self._own is not None and self._own in self._commits else "none"

    async def _navigate(self, url: str) -> str:
        """Navigate and wait for the page to load. The error text, or `""`."""
        from nodriver import cdp

        previous = (self._own, self._commits)
        self._own, self._commits = None, []
        self.seen_url = ""
        _frame, loader, error_text, is_download = await self.tab.send(cdp.page.navigate(url))
        if loader is None and not error_text and not is_download:
            # A navigation inside the document keeps the document and its loader.
            self._own = previous[0]
            self._commits = previous[1] + self._commits
        else:
            self._own = str(loader) if loader else None
        if is_download:
            return "the URL starts a download and shows no page"
        if error_text:
            return f"navigation failed: {error_text}"
        while await self._ready_state() in ("blank", "loading", ""):
            await asyncio.sleep(READY_POLL_S)
        deadline = time.monotonic() + LOAD_WAIT_S
        while time.monotonic() < deadline and await self._ready_state() != "complete":
            await asyncio.sleep(READY_POLL_S)
        await asyncio.sleep(SETTLE_S)
        return ""

    async def _ready_state(self) -> str:
        """The document's ready state, `blank`, or `""` while no document answers."""
        from nodriver import cdp

        try:
            remote, exception = await self.tab.send(
                cdp.runtime.evaluate(expression=_READY_JS, return_by_value=True)
            )
        except Exception:  # noqa: BLE001 - the context is replaced during a navigation
            return ""
        return "" if exception else str(getattr(remote, "value", "") or "")

    async def _evaluate(self, function: str):
        from nodriver import cdp

        remote, exception = await self.tab.send(cdp.runtime.evaluate(
            expression=f"({function})()", await_promise=True, return_by_value=True,
        ))
        if exception:
            detail = getattr(getattr(exception, "exception", None), "description", None)
            return _answer(str(detail or exception.text), error=True)
        value = getattr(remote, "value", None)
        return _answer(value if isinstance(value, str) else json.dumps(value))


def _document(chat) -> str:
    """`TabClient.document()` of the client that `chat` reads through. A client without
    navigation tracking, such as a test fake, counts as `ours`."""
    check = getattr(getattr(chat, "client", None), "document", None)
    return check() if callable(check) else "ours"
