"""The first model step accepts the opening human message and the run tools."""

from research_agent.steps import ModelStepRequest


def request(**changes):
    body = {
        "run_id": "r", "kind": "chat", "depth": 0, "username": "u", "session_id": "s",
        "step_no": 1, "thinking": True, "messages": [{"role": "human", "content": "q"}],
    }
    body.update(changes)
    return ModelStepRequest(**body)


def test_a_step_request_has_no_mode():
    """Every model step binds the run's tools. An older worker's `mode` field is ignored."""
    assert "mode" not in ModelStepRequest.model_fields
    assert request(mode="final").step_no == 1
