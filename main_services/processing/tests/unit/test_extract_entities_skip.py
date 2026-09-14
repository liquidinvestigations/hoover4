"""Tests for the P4 empty-NER-endpoint skip."""

from unittest import mock

import pytest

from tasks.P4_extract_entities import activities as nlp_activities
from tasks.P4_extract_entities import extract_ner_from_text as ner_module
from tasks.P4_extract_entities.params import ExtractEntitiesParams


def _params():
    return ExtractEntitiesParams(
        collectionname="coll",
        collection_dataset="coll_ds",
        plan_hash="planhash123",
        hashes=["hash-1"],
    )


@pytest.mark.parametrize("value", [None, "   "])
def test_empty_ner_url_skips_before_clickhouse(monkeypatch, value):
    post_json = mock.Mock()

    def fail_if_client_opens(*args, **kwargs):
        raise AssertionError("empty NER_URL opened ClickHouse")

    monkeypatch.setattr(ner_module, "post_json", post_json)
    monkeypatch.setattr(nlp_activities, "get_collection_client", fail_if_client_opens)
    if value is None:
        monkeypatch.delenv("NER_URL", raising=False)
    else:
        monkeypatch.setenv("NER_URL", value)

    result = nlp_activities.extract_entities_for_hashes(_params())

    assert result.text_segments == 0
    assert result.entity_groups == 0
    post_json.assert_not_called()


def test_non_empty_ner_url_starts_the_existing_path(monkeypatch):
    class QueryStarted(Exception):
        pass

    def mark_query(*args, **kwargs):
        raise QueryStarted

    monkeypatch.setenv("NER_URL", "http://ner.test/v1")
    monkeypatch.setattr(nlp_activities, "get_collection_client", mark_query)

    with pytest.raises(QueryStarted):
        nlp_activities.extract_entities_for_hashes(_params())
