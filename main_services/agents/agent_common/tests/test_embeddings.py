"""Tests for the query-side embedding contract (agent_common.embeddings)."""

import pytest

from agent_common.embeddings import embedding_input


class TestEmbeddingInput:
    def test_e5_small_prefixes(self):
        assert embedding_input("intfloat/multilingual-e5-small", "passage", "text") == \
            ("passage: text", None)
        assert embedding_input("intfloat/multilingual-e5-small", "query", "text") == \
            ("query: text", None)

    def test_e5_instruct_convention_differs(self):
        assert embedding_input("intfloat/multilingual-e5-large-instruct", "passage", "text") == \
            ("text", None)
        text, task = embedding_input("intfloat/multilingual-e5-large-instruct", "query", "q")
        assert text == "q"
        assert task

    def test_unknown_model_refuses(self):
        with pytest.raises(ValueError):
            embedding_input("sentence-transformers/all-MiniLM-L6-v2", "query", "text")

    def test_unknown_kind_refuses(self):
        with pytest.raises(ValueError):
            embedding_input("intfloat/multilingual-e5-small", "document", "text")

    def test_parity_with_the_processing_half(self):
        # The indexing-side copy lives in
        # main_services/processing/tasks/P5_chunk_embed/embedding_prefix.py and must
        # agree exactly. If you change one, change the other. This test is the
        # check on this side.
        for kind in ("passage", "query"):
            for model in ("intfloat/multilingual-e5-small",
                          "intfloat/multilingual-e5-large-instruct"):
                text, task = embedding_input(model, kind, "x")
                assert isinstance(text, str) and text
                if "instruct" in model and kind == "query":
                    assert task is not None
                else:
                    assert task is None


def test_the_query_and_rerank_calls_send_the_gpu_key(monkeypatch, tmp_path):
    import requests

    from agent_common import embeddings, rerank

    key = tmp_path / "gpu-key"
    key.write_text("k123\n")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(key))
    monkeypatch.setenv("EMBEDDINGS_URL", "http://ai.test/v1")
    monkeypatch.setenv("RERANK_URL", "http://ai.test/v1")
    monkeypatch.setattr(embeddings.telemetry, "record_async", lambda *a, **k: None)
    monkeypatch.setattr(rerank.telemetry, "record_async", lambda *a, **k: None)
    sent = []

    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def post(url, **kwargs):
        sent.append(kwargs.get("headers"))
        if url.endswith("/embeddings"):
            return Response({"data": [{"embedding": [0.0, 1.0]}], "model": "intfloat/multilingual-e5-small"})
        return Response({"results": [{"index": 0, "relevance_score": 0.5}]})

    monkeypatch.setattr(requests, "post", post)
    embeddings.embed_query("q", "intfloat/multilingual-e5-small")
    try:
        rerank.rerank("q", ["d"])
    except rerank.RerankUnavailable:
        pass
    assert sent and all(h == {"Authorization": "Bearer k123"} for h in sent)
    assert len(sent) == 2
    key.write_text("")
    assert embeddings.gpu_headers() == {}
