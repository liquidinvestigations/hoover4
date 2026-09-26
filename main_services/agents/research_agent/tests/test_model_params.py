"""The request parameters of the agent's model calls, and the thinking text of a delta.

These tests call the functions that build the parameters. No test reaches into the model
client.
"""

import pytest
from langchain_core.messages import AIMessageChunk

from research_agent import model_params
from research_agent.chat_model import _convert_delta_to_message_chunk


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LLM_SEND_TEMPERATURE", "AGENT_MAX_OUTPUT_TOKENS",
                 "LLM_REQUEST_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("value, expected", [
    (None, {"temperature": 0.3}),
    ("", {"temperature": 0.3}),
    ("true", {"temperature": 0.3}),
    ("false", {}),
])
def test_temperature_follows_the_provider_rule(monkeypatch, value, expected):
    if value is not None:
        monkeypatch.setenv("LLM_SEND_TEMPERATURE", value)
    assert model_params.sampling_params(0.3) == expected


def test_no_output_cap_is_sent_when_the_key_is_unset():
    assert "max_tokens" not in model_params.sampling_params(0.3)
    assert model_params.max_output_tokens() is None


def test_the_output_cap_is_sent_when_set(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_OUTPUT_TOKENS", "32768")
    assert model_params.sampling_params(0.3) == {"temperature": 0.3, "max_tokens": 32768}
    monkeypatch.setenv("LLM_SEND_TEMPERATURE", "false")
    assert model_params.sampling_params(0.3) == {"max_tokens": 32768}


def test_the_request_timeout_is_unset_by_default():
    assert model_params.request_timeout() is None
    assert model_params.client_kwargs() == {}


def test_a_set_request_timeout_turns_off_the_client_retries(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "3600")
    assert model_params.request_timeout() == (10.0, 3600.0)
    kwargs = model_params.client_kwargs()
    assert kwargs["max_retries"] == 0
    assert kwargs["timeout"] == (10.0, 3600.0)


@pytest.mark.parametrize("name", ["AGENT_MAX_OUTPUT_TOKENS", "LLM_REQUEST_TIMEOUT_SECONDS"])
def test_a_value_that_is_not_a_number_names_its_variable(monkeypatch, name):
    monkeypatch.setenv(name, "many")
    with pytest.raises(ValueError, match=name):
        model_params.sampling_params(0.3)
        model_params.client_kwargs()


@pytest.mark.parametrize("field", ["reasoning", "reasoning_content"])
def test_the_thinking_text_reaches_reasoning_content_from_either_field(field):
    chunk = _convert_delta_to_message_chunk(
        {"role": "assistant", "content": "", field: "first I look"}, AIMessageChunk)
    assert chunk.additional_kwargs["reasoning_content"] == "first I look"


def test_a_delta_without_thinking_text_has_no_reasoning_content():
    chunk = _convert_delta_to_message_chunk(
        {"role": "assistant", "content": "answer"}, AIMessageChunk)
    assert "reasoning_content" not in chunk.additional_kwargs
