"""The agent's model client, built with the arguments that `agent.py` gives it.

`test_model_params.py` checks the values that `model_params` returns. These tests give
the values to `ThinkingChatOpenAI` and its HTTP client. A client can refuse a correct value.
"""

import socket
import threading
import time

import openai
import pytest

from research_agent import model_params
from research_agent.chat_model import ThinkingChatOpenAI
from research_agent.thinking import tool_turn_kwargs


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LLM_SEND_TEMPERATURE", "AGENT_MAX_OUTPUT_TOKENS",
                 "LLM_REQUEST_TIMEOUT_SECONDS", "AGENT_TOOL_TURN_THINKING"):
        monkeypatch.delenv(name, raising=False)


def _agent_client(base_url: str) -> ThinkingChatOpenAI:
    """The tool-turn client of `agent.py`, with the same keyword arguments."""
    llm_kwargs = {
        "api_key": "test-key",
        "model": "test-model",
        "streaming": False,
        "disable_streaming": True,
        "stream_usage": True,
    }
    llm_kwargs.update(model_params.sampling_params(0.3))
    llm_kwargs.update(model_params.client_kwargs())
    llm_kwargs["base_url"] = base_url
    return ThinkingChatOpenAI(**llm_kwargs, extra_body=tool_turn_kwargs())


def test_the_client_is_built_with_the_request_timeout(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "3600")
    llm = _agent_client("http://127.0.0.1:9/v1")
    assert llm.max_retries == 0
    assert llm.root_client.max_retries == 0
    assert llm.root_async_client.max_retries == 0
    for client in (llm.root_client, llm.root_async_client):
        assert client._client.timeout.connect == 10.0
        assert client._client.timeout.read == 3600.0


def test_the_client_is_built_without_the_request_timeout():
    llm = _agent_client("http://127.0.0.1:9/v1")
    assert llm.request_timeout is None


class _SilentServer:
    """A TCP server that reads each request and then sends nothing."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.requests = 0
        self._held = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            conn.settimeout(2.0)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            except socket.timeout:
                pass
            if data.count(b"POST ") or data.count(b"GET "):
                self.requests += 1
            self._held.append(conn)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        for conn in self._held:
            conn.close()
        self.sock.close()


def test_one_call_stops_at_the_read_timeout_and_is_not_retried(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "1")
    server = _SilentServer()
    try:
        llm = _agent_client(f"http://127.0.0.1:{server.port}/v1")
        started = time.monotonic()
        with pytest.raises(openai.APITimeoutError):
            llm.invoke("hello")
        elapsed = time.monotonic() - started
        # Let a retry, if the client sent one, reach the server before the count.
        time.sleep(0.5)
        assert elapsed < 5.0
        assert server.requests == 1
    finally:
        server.close()
