"""The endpoint of the model server, and the catalog's view of it."""

from tasks import llm_catalog
from tasks.llm_endpoints import chat_model, endpoint


def configure(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://gpu.invalid:21960/v1/")
    monkeypatch.setenv("LLM_MODEL", "qwen3.8-flash-next")
    monkeypatch.setenv("LLM_API_KEY", "base-key")
    monkeypatch.setenv("LLM_PROVIDER_NAME", "selfhosted")


def test_every_call_goes_to_the_one_endpoint_and_model(monkeypatch):
    configure(monkeypatch)
    assert chat_model() == "qwen3.8-flash-next"
    found = endpoint()
    assert (found.base_url, found.api_key, found.label) == (
        "http://gpu.invalid:21960/v1", "base-key", "selfhosted")


def test_an_endpoint_without_a_name_is_labelled_by_its_host(monkeypatch):
    configure(monkeypatch)
    monkeypatch.delenv("LLM_PROVIDER_NAME")
    assert endpoint().label == "gpu.invalid:21960"


def test_the_catalog_lists_one_provider(monkeypatch):
    configure(monkeypatch)
    monkeypatch.delenv("LLM_API_KEY_FILE", raising=False)
    providers = llm_catalog.providers_from_env()
    assert [(p.name, p.base_url) for p in providers] == [("selfhosted", "http://gpu.invalid:21960/v1")]


def test_disabled_model_servers_give_no_endpoint_and_no_catalog_provider(monkeypatch):
    # deploy.py renders every LLM_* endpoint empty when [ai_services] llm_enabled is false.
    for name in ("LLM_BASE_URL", "LLM_MODEL", "LLM_PROVIDER_NAME"):
        monkeypatch.setenv(name, "")
    assert llm_catalog.providers_from_env() == []
    assert chat_model() == ""
    assert endpoint().base_url == "" and endpoint().label == "unknown"


def test_a_llama_cpp_listing_states_its_window_inside_meta():
    assert llm_catalog._context_window({"id": "m", "meta": {"n_ctx": 262144}}) == 262144
    assert llm_catalog._context_window({"max_model_len": 4096, "meta": {"n_ctx": 8}}) == 4096
    assert llm_catalog._context_window({"id": "m", "meta": None}) == 0
