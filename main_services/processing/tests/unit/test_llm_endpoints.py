"""The endpoint of each model name, and the catalog's view of the quality endpoint."""

from tasks import llm_catalog
from tasks.llm_endpoints import QUALITY_PLACEHOLDER_KEY, endpoint_for

QUALITY = "lan/coder-35b"


def configure(monkeypatch, quality=True):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu.invalid:21960/v1/")
    monkeypatch.setenv("LLM_MODEL", "dgemma")
    monkeypatch.setenv("LLM_API_KEY", "base-key")
    monkeypatch.setenv("LLM_PROVIDER_NAME", "selfhosted")
    if quality:
        monkeypatch.setenv("LLM_QUALITY_BASE_URL", "http://10.0.0.8:12008/v1")
        monkeypatch.setenv("LLM_QUALITY_MODEL", QUALITY)
    else:
        monkeypatch.delenv("LLM_QUALITY_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_QUALITY_MODEL", raising=False)


def test_the_quality_model_goes_to_the_quality_endpoint(monkeypatch):
    configure(monkeypatch)
    endpoint = endpoint_for(QUALITY)
    assert endpoint.base_url == "http://10.0.0.8:12008/v1"
    assert endpoint.api_key == QUALITY_PLACEHOLDER_KEY
    assert endpoint.label == "10.0.0.8:12008"


def test_every_other_model_goes_to_the_base_endpoint(monkeypatch):
    configure(monkeypatch)
    for model in ("dgemma", "", "other"):
        endpoint = endpoint_for(model)
        assert endpoint.base_url == "http://gpu.invalid:21960/v1"
        assert endpoint.api_key == "base-key"
        assert endpoint.label == "selfhosted"


def test_without_a_quality_endpoint_the_quality_name_is_an_ordinary_model(monkeypatch):
    configure(monkeypatch, quality=False)
    assert endpoint_for(QUALITY).base_url == "http://gpu.invalid:21960/v1"


def test_the_catalog_lists_the_quality_endpoint_as_a_provider(monkeypatch):
    configure(monkeypatch)
    monkeypatch.delenv("LLM_API_KEY_FILE", raising=False)
    providers = llm_catalog.providers_from_env()
    assert [p.base_url for p in providers] == ["http://gpu.invalid:21960/v1", "http://10.0.0.8:12008/v1"]
    assert providers[1].name == "10.0.0.8:12008"


def test_a_llama_cpp_listing_states_its_window_inside_meta():
    assert llm_catalog._context_window({"id": "m", "meta": {"n_ctx": 262144}}) == 262144
    assert llm_catalog._context_window({"max_model_len": 4096, "meta": {"n_ctx": 8}}) == 4096
    assert llm_catalog._context_window({"id": "m", "meta": None}) == 0
