"""The keepalive lines of `/model_step`.

A model call can wait longer than the worker's read timeout of the step stream. The agent
service therefore sends an SSE comment line while no frame is ready. These tests check that
the comment lines arrive during a wait and that the data frames do not change.
"""

import asyncio

import pytest

from research_agent import steps

TURN = {"type": "model_turn", "text": "done", "tool_calls": []}
END = {"type": "end", "model": "m", "latency_ms": 1, "usage": {}}


async def _frames(delay=0.0, fail=False):
    if delay:
        await asyncio.sleep(delay)
    if fail:
        raise RuntimeError("the model server went away")
    yield TURN
    yield END


def _body(delay=0.0, fail=False) -> list[str]:
    async def collect():
        return [part async for part in steps.stream_frames(_frames(delay, fail))]

    return asyncio.run(collect())


def _data(parts):
    return [part for part in parts if part.startswith("data: ")]


@pytest.fixture(autouse=True)
def _short_keepalive(monkeypatch):
    monkeypatch.setattr(steps, "KEEPALIVE_SECONDS", 0.05)


def test_a_wait_sends_keepalive_lines_before_the_first_frame():
    parts = _body(delay=0.2)
    first_data = next(i for i, part in enumerate(parts) if part.startswith("data: "))
    assert steps.KEEPALIVE_LINE in parts[:first_data]
    assert all(part == steps.KEEPALIVE_LINE for part in parts[:first_data])


def test_the_data_frames_are_those_of_a_stream_that_does_not_wait():
    slow = _body(delay=0.2)
    fast = _body()
    assert fast == _data(fast)
    assert _data(slow) == fast


def test_a_stream_that_raises_sends_one_error_frame():
    parts = _data(_body(fail=True))
    assert len(parts) == 1
    assert '"type": "error"' in parts[0]
    assert "the model server went away" in parts[0]
