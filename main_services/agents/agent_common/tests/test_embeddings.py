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
