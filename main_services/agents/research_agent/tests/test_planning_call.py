"""The first model step accepts the opening human message and the run tools."""

import pytest
from pydantic import ValidationError

from research_agent.steps import ModelStepRequest


def request(**changes):
    body = {
        "run_id": "r", "kind": "chat", "depth": 0, "username": "u", "session_id": "s",
        "step_no": 1, "thinking": True, "messages": [{"role": "human", "content": "q"}],
    }
    body.update(changes)
    return ModelStepRequest(**body)


def test_the_first_step_uses_the_normal_tool_mode():
    assert request().mode == "tools"


def test_the_old_planning_mode_is_refused():
    with pytest.raises(ValidationError):
        request(mode="plan")
