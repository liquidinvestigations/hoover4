"""The keepalive lines of `/run/stream`.

A model call can wait longer than the worker's read timeout of the run stream. The agent
service therefore sends an SSE comment line while no event is ready. These tests check that
the comment lines arrive during a wait and that the data frames do not change.
"""

import asyncio

import pytest

from research_agent import api

END = {"type": "end", "content": "done", "is_task_complete": True}
TURN = {"type": "model_turn", "content": {"index": 1, "text": "done"}}


class _Agent:
    def __init__(self, delay=0.0, fail=False):
        self.delay = delay
        self.fail = fail

    async def stream(self, **_kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("the model server went away")
        yield TURN
        yield END


def _request():
    return api.RunRequest(
        run_id="r", kind="chat", depth=0, username="u", session_id="s",
        messages=[{"role": "human", "content": "question"}],
    )


def _body(monkeypatch, agent) -> list[str]:
    monkeypatch.setattr(api.app.state, "agent", agent, raising=False)

    async def collect():
        response = await api.run_stream(_request())
        return [part async for part in response.body_iterator]

    return asyncio.run(collect())


def _data(parts):
    return [part for part in parts if part.startswith("data: ")]


@pytest.fixture(autouse=True)
def _short_keepalive(monkeypatch):
    monkeypatch.setattr(api, "KEEPALIVE_SECONDS", 0.05)


def test_a_wait_sends_keepalive_lines_before_the_first_frame(monkeypatch):
    parts = _body(monkeypatch, _Agent(delay=0.2))
    first_data = next(i for i, part in enumerate(parts) if part.startswith("data: "))
    assert api.KEEPALIVE_LINE in parts[:first_data]
    assert all(part == api.KEEPALIVE_LINE for part in parts[:first_data])


def test_the_data_frames_are_those_of_a_stream_that_does_not_wait(monkeypatch):
    slow = _body(monkeypatch, _Agent(delay=0.2))
    fast = _body(monkeypatch, _Agent())
    assert fast == _data(fast)
    assert _data(slow) == fast


def test_a_stream_that_raises_sends_the_error_frame(monkeypatch):
    parts = _data(_body(monkeypatch, _Agent(fail=True)))
    assert len(parts) == 1
    assert '"type": "error"' in parts[0]
    assert "Error during streaming: the model server went away" in parts[0]
