"""The agent's endpoint of the model server. Mirrors the worker's tests in
`processing/tests/unit/test_llm_endpoints.py`."""

from research_agent import llm_events
from research_agent.endpoints import PLACEHOLDER_KEY, endpoint


def test_every_call_goes_to_the_one_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu.invalid:21960/v1/")
    monkeypatch.setenv("LLM_API_KEY", "base-key")
    monkeypatch.setenv("LLM_PROVIDER_NAME", "selfhosted")
    found = endpoint()
    assert (found.base_url, found.api_key) == ("http://gpu.invalid:21960/v1", "base-key")
    assert llm_events.provider_from_base_url() == "selfhosted"


def test_a_server_without_a_key_gets_the_placeholder(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu.invalid:21960/v1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY_FILE", raising=False)
    assert endpoint().api_key == PLACEHOLDER_KEY
