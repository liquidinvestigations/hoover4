"""Verify encoded data limits at the embedding request boundary."""

from contextlib import nullcontext
import inspect
from types import SimpleNamespace

import pytest

from database.manticore import limit_encoded_runs
from tasks.P5_chunk_embed import activities
from tasks.P5_chunk_embed.params import ChunkEmbedParams


@pytest.mark.parametrize("encoded", [
    "A" * 201,
    "A" * 76 + "\r\n" + "B" * 76,
    "PHOTO;ENCODING=b:\n " + "A" * 76 + "\n " + "B" * 76,
])
def test_mixed_text_limits_model_input_and_preserves_source(monkeypatch, encoded):
    text = "Evidence about the contract and the parties. " * 18 + "\n" + encoded + "\nConclusion."
    sent, stored = run_embedding(monkeypatch, text)
    assert len(sent) == 1
    assert sent[0] == "passage: " + limit_encoded_runs(text)
    assert len(sent[0]) < len("passage: " + text)
    chunk = stored["text_chunks"][0]
    assert chunk[7] == text
    assert text.encode()[chunk[5]:chunk[6]].decode() == chunk[7]


def test_prose_and_a_quoted_checksum_reach_embedding_unchanged(monkeypatch):
    text = ("The release checksum is " + "a" * 64 + ". Recipients can verify the archive. " * 5).rstrip()
    sent, _ = run_embedding(monkeypatch, text)
    assert sent == ["passage: " + text]


def test_encoded_attachment_has_no_embedding_request(monkeypatch):
    text = ("A" * 76 + "\n") * 8
    sent, stored = run_embedding(monkeypatch, text)
    assert sent == []
    assert stored == {}


def run_embedding(monkeypatch, text):
    sent, stored = [], {}
    rows = [{"collection_dataset": "sample", "file_hash": "a" * 64,
             "extracted_by": "text", "page_id": 1, "text": text}]

    class Client:
        def query_arrow(self, _sql, params):
            page = rows if not params["after_hash"] else []
            return SimpleNamespace(to_pylist=lambda: page)

        def query(self, *_args):
            return SimpleNamespace(result_rows=[])

        def insert(self, table, values, **_kwargs):
            stored.setdefault(table, []).extend(values)

    def post(_endpoints, payload, **_kwargs):
        sent.extend(payload["input"])
        return SimpleNamespace(data={"model": "intfloat/multilingual-e5-small",
            "data": [{"index": i, "embedding": [0.5, 0.5]}
                     for i in range(len(payload["input"]))]})

    monkeypatch.setenv("EMBEDDINGS_URL", "http://embeddings.example/v1")
    monkeypatch.setattr(activities, "get_collection_client", lambda _name: nullcontext(Client()))
    monkeypatch.setattr(activities, "_probed_serving", lambda: ("intfloat/multilingual-e5-small", 2))
    monkeypatch.setattr(activities, "HeartbeatClock", lambda: SimpleNamespace(beat=lambda *_args: None))
    monkeypatch.setattr(activities, "stop_if_worker_is_stopping", lambda *_args: None)
    monkeypatch.setattr(activities, "post_json", post)
    inspect.unwrap(activities.chunk_embed_for_hashes)(ChunkEmbedParams(
        collectionname="sample", collection_dataset="sample", plan_hash="plan", hashes=["a" * 64],
    ))
    return sent, stored
