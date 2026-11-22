"""The router sends each forwarded call to the sidecar once.

The worker's `tool_call` activity is the only retry of a tool request. A failed read tool
returns an error marked retryable, so Temporal runs it once more. A failed action tool
returns a plain error, because its first call can have changed the page.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from browser_use_server import server


class _Client:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments, raise_on_error=False):
        self.calls.append(name)
        raise ConnectionError("the sidecar closed the connection")


@pytest.mark.parametrize("tool, retryable", [("browser_snapshot", True), ("browser_click", False)])
def test_a_failed_sidecar_call_is_sent_once(monkeypatch, tool, retryable):
    client = _Client()
    chat = SimpleNamespace(client=client, session_id="chat")
    restarts = []

    async def restart(c):
        restarts.append(c)

    monkeypatch.setattr(server.chat_browser, "sidecar_alive", lambda c: True)
    monkeypatch.setattr(server.chat_browser, "restart_sidecar", restart)
    monkeypatch.setattr(server.telemetry, "record_async", lambda *a, **k: None)
    routed = SimpleNamespace(name=tool)
    result, failed = asyncio.run(server.RoutedTool._forward(routed, chat, tool, {}))
    assert failed is True
    assert client.calls == [tool]
    assert len(restarts) == 1
    assert result.structured_content.get("retryable", False) is retryable
    # The research service reads `retryable` from the text that the model client gets.
    assert json.loads(result.content[0].text).get("retryable", False) is retryable


@pytest.mark.parametrize("key", ["F5", "Control+r", "Meta+r"])
def test_reload_shortcut_reloads_the_tab(monkeypatch, key):
    from nodriver import cdp

    class Tab:
        def __init__(self):
            self.handlers = {}
            self.reloads = []

        def add_handler(self, event, handler):
            self.handlers[event] = handler

        def remove_handler(self, event, handler):
            assert self.handlers.pop(event) is handler

        async def send(self, command):
            assert next(command)["method"] == "Page.enable"

        async def reload(self, *, ignore_cache):
            self.reloads.append(ignore_cache)
            self.handlers[cdp.page.DomContentEventFired](None)

    tab = Tab()
    client = _Client()
    chat = SimpleNamespace(client=client, session_id="chat")

    async def active_tab(_chat):
        return tab

    monkeypatch.setattr(server.capture_mod, "active_tab", active_tab)
    monkeypatch.setattr(server.chat_browser, "sidecar_alive", lambda c: True)
    monkeypatch.setattr(server.telemetry, "record_async", lambda *a, **k: None)

    result, failed = asyncio.run(server.RoutedTool._forward(
        SimpleNamespace(name="browser_press_key"), chat, "browser_press_key", {"key": key}))

    assert not failed
    assert result.content[0].text == "Reloaded the current page."
    assert tab.reloads == [True]
    assert not tab.handlers
    assert not client.calls
