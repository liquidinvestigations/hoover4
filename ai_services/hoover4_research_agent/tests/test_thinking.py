"""Thinking-budget configuration.

The numbers asserted here are the ones measured against the live vLLM server; see
research_agent/thinking.py for the method.
"""

import pytest

from research_agent.thinking import (
    ANSWER_TOKEN_ALLOWANCE,
    DEFAULT_BUDGET_TOKENS,
    MODE_BUDGETED,
    MODE_OFF,
    MODE_ON,
    describe,
    thinking_budget_tokens,
    thinking_kwargs,
    thinking_mode,
    tool_turn_kwargs,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AGENT_THINKING", raising=False)
    monkeypatch.delenv("AGENT_THINKING_BUDGET_TOKENS", raising=False)


def test_the_default_is_off_which_is_what_the_stack_did_before():
    assert thinking_mode() == MODE_OFF
    assert thinking_kwargs() == {"chat_template_kwargs": {"enable_thinking": False}}


def test_tool_turns_never_think_whatever_the_mode(monkeypatch):
    # Choosing a tool is routing, and letting this model reason about it produces the
    # repeated-call loop the agent has a guard for.
    for mode in (MODE_OFF, MODE_ON, MODE_BUDGETED):
        monkeypatch.setenv("AGENT_THINKING", mode)
        assert tool_turn_kwargs() == {"chat_template_kwargs": {"enable_thinking": False}}


def test_on_enables_unbounded_thinking(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING", "on")
    kwargs = thinking_kwargs()
    assert kwargs["chat_template_kwargs"] == {"enable_thinking": True}
    # No cap: "on" means let it run.
    assert "max_tokens" not in kwargs


def test_budgeted_enables_thinking_and_bounds_the_completion(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING", "budgeted")
    monkeypatch.setenv("AGENT_THINKING_BUDGET_TOKENS", "600")
    kwargs = thinking_kwargs()
    assert kwargs["chat_template_kwargs"] == {"enable_thinking": True}
    assert kwargs["max_tokens"] == 600 + ANSWER_TOKEN_ALLOWANCE


def test_the_default_budget_is_half_an_unbudgeted_thought():
    # An unbudgeted thought measured ~1,300 tokens on Qwen3.5-2B; the default budget is
    # half the round number above that.
    assert DEFAULT_BUDGET_TOKENS == 750
    assert thinking_budget_tokens() == DEFAULT_BUDGET_TOKENS


def test_a_bad_mode_falls_back_to_off_rather_than_guessing(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING", "yes-please")
    assert thinking_mode() == MODE_OFF


def test_mode_is_case_and_whitespace_insensitive(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING", "  Budgeted \n")
    assert thinking_mode() == MODE_BUDGETED


def test_a_nonsense_budget_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING_BUDGET_TOKENS", "lots")
    assert thinking_budget_tokens() == DEFAULT_BUDGET_TOKENS


def test_the_budget_is_clamped_at_both_ends(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING_BUDGET_TOKENS", "1")
    assert thinking_budget_tokens() == 64
    monkeypatch.setenv("AGENT_THINKING_BUDGET_TOKENS", "999999")
    assert thinking_budget_tokens() == 32_768


def test_describe_names_the_budget_only_when_one_applies(monkeypatch):
    monkeypatch.setenv("AGENT_THINKING", "off")
    assert describe() == "thinking=off"
    monkeypatch.setenv("AGENT_THINKING", "budgeted")
    monkeypatch.setenv("AGENT_THINKING_BUDGET_TOKENS", "400")
    assert describe() == "thinking=budgeted budget=400 tokens"
