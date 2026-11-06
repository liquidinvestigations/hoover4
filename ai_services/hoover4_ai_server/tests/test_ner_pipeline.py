"""Filtered token records give the same groups as one record for each token."""

import numpy as np
import pytest

pytest.importorskip("transformers")

from transformers import TokenClassificationPipeline  # noqa: E402
from transformers.pipelines.token_classification import AggregationStrategy  # noqa: E402

from ner_pipeline import EntityTokenPipeline  # noqa: E402

LABELS = {0: "O", 1: "B-PER", 2: "I-PER", 3: "B-ORG"}


class Tokenizer:
    unk_token_id = 9
    _tokenizer = None

    def convert_ids_to_tokens(self, ids):
        return [f"t{value}" for value in ids] if isinstance(ids, list) else f"t{ids}"

    def convert_tokens_to_string(self, tokens):
        return " ".join(tokens)


class Config:
    id2label = LABELS
    label2id = {label: index for index, label in LABELS.items()}


class Model:
    config = Config


def _pipeline(kind):
    pipe = kind.__new__(kind)
    pipe.tokenizer, pipe.model, pipe.framework = Tokenizer(), Model(), "pt"
    return pipe


def _groups(kind, labels):
    count = len(labels)
    scores = np.zeros((count, len(LABELS)))
    scores[np.arange(count), labels] = 1.0
    ids = np.arange(100, 100 + count)
    ids[-2] = Tokenizer.unk_token_id
    offsets = np.array([[index * 2, index * 2 + 1] for index in range(count)])
    special = np.zeros(count, dtype=int)
    special[[0, -1]] = 1
    pipe = _pipeline(kind)
    records = pipe.gather_pre_entities("x " * count, ids, scores, offsets, special, AggregationStrategy.SIMPLE)
    return [entity for entity in pipe.aggregate(records, AggregationStrategy.SIMPLE)
            if entity["entity_group"] != "O"]


@pytest.mark.parametrize("labels", [
    [0, 1, 2, 0, 2, 0],
    [0, 1, 0, 0, 0, 1, 1, 3, 2, 0],
    [0, 0, 0, 0],
    [1, 2, 2, 3, 3, 0, 2, 0],
    [0, 3, 0, 0, 3, 2, 1, 0],
])
def test_filtered_records_match_the_stock_groups(labels):
    assert _groups(EntityTokenPipeline, labels) == _groups(TokenClassificationPipeline, labels)


def test_an_outside_run_keeps_only_one_record():
    scores = np.zeros((6, len(LABELS)))
    scores[np.arange(6), [1, 0, 0, 0, 0, 1]] = 1.0
    records = _pipeline(EntityTokenPipeline).gather_pre_entities(
        "x" * 12, np.arange(6), scores, np.array([[i, i + 1] for i in range(6)]), np.zeros(6, dtype=int),
        AggregationStrategy.SIMPLE)
    assert [record["index"] for record in records] == [0, 1, 5]
