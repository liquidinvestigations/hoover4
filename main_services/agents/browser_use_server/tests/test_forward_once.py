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
