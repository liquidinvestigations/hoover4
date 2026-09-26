"""The request body of the thinking switch. See research_agent/thinking.py."""

from research_agent.thinking import thinking_body


def test_on_enables_thinking_in_the_template():
    assert thinking_body(True) == {"chat_template_kwargs": {"enable_thinking": True}}


def test_off_disables_thinking_in_the_template():
    assert thinking_body(False) == {"chat_template_kwargs": {"enable_thinking": False}}


def test_the_body_sends_no_token_budget():
    assert set(thinking_body(True)) == {"chat_template_kwargs"}
