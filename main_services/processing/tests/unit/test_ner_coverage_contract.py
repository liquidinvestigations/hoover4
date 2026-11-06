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

def test_cpu_keeps_its_supported_usage_contract_and_identity(monkeypatch):
    monkeypatch.setattr(client,"post_json",lambda *_args,**_kwargs:SimpleNamespace(provider="spacy",data={"data":[],"usage":{"texts":2}}))
    results,model=client.extract_ner_from_texts(["first","second"])
    assert len(results)==2
    assert model=="ner-spacy-xx"
