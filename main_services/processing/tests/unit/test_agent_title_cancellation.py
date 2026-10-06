"""Verify that cancellation during the title activity stops the agent workflow."""

import asyncio

import pytest
from temporalio.exceptions import CancelledError

from tasks.P_agent.activities import AgentRunInput
from tasks.P_agent import workflows


def test_title_activity_propagates_wrapped_cancellation(monkeypatch):
    failure = RuntimeError("activity failed")
    failure.__cause__ = CancelledError("stopped")

    async def execute(*args, **kwargs):
        raise failure

    monkeypatch.setattr(workflows.workflow, "execute_activity", execute)
    params = AgentRunInput(run_id="run", username="user", session_id="session")
    with pytest.raises(RuntimeError, match="activity failed"):
        asyncio.run(workflows.AgentRun()._summarize_if_first_turn(params))
