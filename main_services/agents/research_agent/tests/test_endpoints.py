"""The agent's endpoint of each model name. Mirrors the worker's tests in
`processing/tests/unit/test_llm_endpoints.py`."""

from research_agent import llm_events
from research_agent.endpoints import endpoint_for


def test_only_the_quality_model_goes_to_the_quality_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu.invalid:21960/v1")
    monkeypatch.setenv("LLM_API_KEY", "base-key")
    monkeypatch.setenv("LLM_PROVIDER_NAME", "selfhosted")
    monkeypatch.setenv("LLM_QUALITY_BASE_URL", "http://10.0.0.8:12008/v1/")
    monkeypatch.setenv("LLM_QUALITY_MODEL", "lan/coder-35b")
    quality = endpoint_for("lan/coder-35b")
    assert (quality.base_url, quality.api_key, quality.is_quality) == (
        "http://10.0.0.8:12008/v1", "base-key", True)
    base = endpoint_for("dgemma")
    assert (base.base_url, base.api_key, base.is_quality) == ("http://gpu.invalid:21960/v1", "base-key", False)
    assert llm_events.provider_from_base_url() == "selfhosted"
    assert llm_events.provider_from_base_url(quality.base_url) == "10.0.0.8"


def test_without_a_quality_endpoint_every_model_uses_the_base(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu.invalid:21960/v1")
    monkeypatch.delenv("LLM_QUALITY_BASE_URL", raising=False)
    monkeypatch.setenv("LLM_QUALITY_MODEL", "lan/coder-35b")
    assert not endpoint_for("lan/coder-35b").is_quality
