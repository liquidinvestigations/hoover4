"""Tests for tasks.P4_extract_entities.activities.extract_entities_for_hashes.

Covers the NER-request batching (NLP_BATCH_TEXTS), the re-assembly of results
in input order, the nlp_processed watermark (text_bytes), and the failure
policy: NER errors must propagate, never be swallowed into empty results.
"""

import contextlib
import math

import pytest
import requests

from tasks.P4_extract_entities import activities as nlp_activities
from tasks.P4_extract_entities import extract_ner_from_text as ner_module
from tasks.P4_extract_entities.activities import NLP_BATCH_TEXTS
from tasks.P4_extract_entities.params import ExtractEntitiesParams


class _FakeQueryResult:
    def __init__(self, rows):
        self._rows = rows

    def to_pylist(self):
        return self._rows


class _FakeCHClient:
    """Stands in for the collection ClickHouse client: serves the canned
    text_content rows and records every insert_arrow call."""

    def __init__(self, text_rows):
        self._text_rows = text_rows
        self.inserts = {}

    def query_arrow(self, query, parameters=None):
        return _FakeQueryResult(self._text_rows)

    def insert_arrow(self, table, tbl):
        self.inserts.setdefault(table, []).append(tbl)


class _FakeResponse:
    def __init__(self, payload, error=None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


def _text_rows(n):
    return [
        {
            "collection_dataset": "coll_ds",
            "file_hash": f"hash-{i}",
            "extracted_by": "tika",
            "page_id": 0,
            # trailing whitespace: text_bytes must be of the *cleaned* text
            "text": f"text-{i}  ",
        }
        for i in range(n)
    ]


def _params(n):
    return ExtractEntitiesParams(
        collectionname="coll",
        collection_dataset="coll_ds",
        plan_hash="planhash123",
        hashes=[f"hash-{i}" for i in range(n)],
    )


def _install_fakes(monkeypatch, text_rows, post):
    fake_client = _FakeCHClient(text_rows)

    @contextlib.contextmanager
    def fake_client_ctx(collectionname):
        yield fake_client

    monkeypatch.setattr(nlp_activities, "get_collection_client", fake_client_ctx)
    monkeypatch.setattr(nlp_activities, "get_string_term_ids", lambda *a, **kw: {})
    # The endpoint list is now built from the environment per call, so the
    # stub server is injected the same way deploy.py injects the real one.
    monkeypatch.setenv("NER_URL", "http://ner.test/v1")
    monkeypatch.setenv("NER_PROVIDER", "gpu")
    monkeypatch.delenv("NER_URL_FALLBACK", raising=False)
    monkeypatch.setattr(requests, "post", post)
    return fake_client


@pytest.mark.parametrize("n", [1, 63, 64, 65, 130])
def test_ner_requests_are_batched_and_reassembled_in_order(monkeypatch, n):
    batches = []

    def fake_post(url, json=None, **kwargs):
        batch = list(json["input"])
        batches.append(batch)
        entities = [
            {"text_index": j, "label": "PER", "text": f"ent:{text}"}
            for j, text in enumerate(batch)
        ]
        return _FakeResponse({"data": entities})

    fake_client = _install_fakes(monkeypatch, _text_rows(n), fake_post)

    result = nlp_activities.extract_entities_for_hashes(_params(n))

    # ceil(n / NLP_BATCH_TEXTS) calls, each bounded by NLP_BATCH_TEXTS
    assert len(batches) == math.ceil(n / NLP_BATCH_TEXTS)
    assert all(len(batch) <= NLP_BATCH_TEXTS for batch in batches)
    # requests cover the cleaned texts in input order
    assert [t for batch in batches for t in batch] == [f"text-{i}" for i in range(n)]

    assert result.text_segments == n
    assert result.entity_groups == 4 * n  # PER/ORG/LOC/MISC row per segment

    # results re-assembled in input order: each segment's PER hit names its own text
    entity_hit_rows = fake_client.inserts["entity_hit"][0].to_pylist()
    per_rows = [r for r in entity_hit_rows if r["entity_type"] == "PER"]
    assert len(per_rows) == n
    for row in per_rows:
        i = int(row["file_hash"].split("-")[1])
        assert row["entity_values"] == [f"ent:text-{i}"]

    # watermark rows: one per segment, text_bytes of the cleaned text
    processed_rows = fake_client.inserts["nlp_processed"][0].to_pylist()
    assert len(processed_rows) == n
    for row in processed_rows:
        i = int(row["file_hash"].split("-")[1])
        assert row["text_bytes"] == len(f"text-{i}".encode("utf-8"))
        # NER_PROVIDER=gpu is set by _install_fakes, so every row must be
        # attributed to the GPU model -- not to the configured default.
        assert row["nlp_model"] == ner_module.NLP_MODEL_BY_PROVIDER["gpu"]


def test_ner_failure_propagates_and_writes_nothing(monkeypatch):
    """Failure policy: the activity must fail (so Temporal retries it), never
    swallow the error into empty entity lists."""

    def fake_post(url, json=None, **kwargs):
        return _FakeResponse({}, error=requests.HTTPError("ner service down"))

    fake_client = _install_fakes(monkeypatch, _text_rows(3), fake_post)

    with pytest.raises(requests.HTTPError):
        nlp_activities.extract_entities_for_hashes(_params(3))

    assert fake_client.inserts == {}


class TestBatchCharacterBudget:
    """A batch bounded only by COUNT is not bounded at all.

    Each text may be as long as the NER service's per-text ceiling, so 64 of them is
    tens of megabytes in one request — and the service holds a parsed document for every
    text in the batch simultaneously. On a corpus of large plain-text files that walked
    the spaCy container through a 4 GB memory limit and then a 12 GB one, and each time
    the cgroup killed the server process rather than the container, so every in-flight
    activity failed with `Connection refused` against something that looked healthy
    afterwards. These pin the character budget that makes the peak a property of the
    constant instead of a property of the corpus.
    """

    def test_the_count_cap_still_applies(self):
        batches = list(nlp_activities.batch_texts_by_chars(["x"] * 200))
        assert all(len(b) <= NLP_BATCH_TEXTS for b in batches)
        assert sum(len(b) for b in batches) == 200

    def test_a_few_large_texts_are_split_where_a_count_cap_would_not(self):
        # Eight texts is well under NLP_BATCH_TEXTS, so a count-based batcher sends all
        # eight at once. Each is a quarter of the budget, so this must become 2+ batches.
        texts = ["y" * (nlp_activities.NLP_BATCH_CHARS // 4) for _ in range(8)]
        batches = list(nlp_activities.batch_texts_by_chars(texts))
        assert len(texts) < NLP_BATCH_TEXTS
        assert len(batches) > 1
        for b in batches:
            assert sum(len(t) for t in b) <= nlp_activities.NLP_BATCH_CHARS

    def test_an_oversized_text_travels_alone_and_is_not_dropped(self):
        huge = "z" * (nlp_activities.NLP_BATCH_CHARS * 2)
        batches = list(nlp_activities.batch_texts_by_chars(["a", huge, "b"]))
        assert [t for b in batches for t in b] == ["a", huge, "b"]
        assert [huge] in batches

    def test_order_is_preserved_exactly(self):
        texts = [f"t{i}" for i in range(150)]
        assert [t for b in nlp_activities.batch_texts_by_chars(texts) for t in b] == texts

    def test_no_texts_means_no_requests(self):
        assert list(nlp_activities.batch_texts_by_chars([])) == []
