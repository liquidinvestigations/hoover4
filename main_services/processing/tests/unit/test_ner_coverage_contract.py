"""Only complete provider responses can create current NER completion."""
from types import SimpleNamespace
import pytest
from tasks.P4_extract_entities import extract_ner_from_text as client

@pytest.mark.parametrize("body", [
    {"data":[]},
    {"data":[],"coverage_version":1,"processed_inputs":2},
    {"data":[],"coverage_version":2,"processed_inputs":1},
])
def test_old_or_partial_gpu_response_is_not_current(monkeypatch,body):
    monkeypatch.setattr(client,"post_json",lambda *_args,**_kwargs:SimpleNamespace(provider="gpu",data=body))
    with pytest.raises(RuntimeError,match="coverage"):
        client.extract_ner_from_texts(["first","second"])

def test_ner_has_only_the_gpu_endpoint(monkeypatch):
    monkeypatch.setenv("NER_URL","http://gpu/v1/")
    assert client._endpoints()==[("gpu","http://gpu/v1/extract-entities")]

def test_ner_has_no_url_without_a_gpu_endpoint(monkeypatch):
    monkeypatch.setenv("NER_URL","")
    assert client._endpoints()==[("gpu","")]
