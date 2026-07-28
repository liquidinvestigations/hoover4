"""Tests for tasks.P4_extract_entities.extract_ner_from_text._group_entities_by_text."""

from tasks.P4_extract_entities.extract_ner_from_text import _group_entities_by_text


def _entity(label, text, text_index=None):
    e = {"label": label, "text": text}
    if text_index is not None:
        e["text_index"] = text_index
    return e


def test_empty_input_no_texts():
    assert _group_entities_by_text([], 0) == []


def test_empty_entities_multiple_texts():
    result = _group_entities_by_text([], 3)
    assert result == [{"PER": [], "ORG": [], "LOC": [], "MISC": []}] * 3


def test_single_text_forces_text_index_zero():
    """With num_texts == 1 the service's text_index is ignored: everything
    lands in the single result slot, even if the service claims index 7."""
    result = _group_entities_by_text([_entity("PER", "Ada", text_index=7)], 1)
    assert result == [{"PER": ["Ada"], "ORG": [], "LOC": [], "MISC": []}]


def test_single_text_missing_text_index_defaults_to_zero():
    result = _group_entities_by_text([_entity("ORG", "ACME")], 1)
    assert result[0]["ORG"] == ["ACME"]


def test_multiple_texts_grouped_by_text_index():
    entities = [
        _entity("PER", "Ada", text_index=1),
        _entity("ORG", "ACME", text_index=0),
        _entity("PER", "Bob", text_index=1),
    ]
    result = _group_entities_by_text(entities, 2)
    assert result[0] == {"PER": [], "ORG": ["ACME"], "LOC": [], "MISC": []}
    assert result[1] == {"PER": ["Ada", "Bob"], "ORG": [], "LOC": [], "MISC": []}


def test_unknown_labels_are_dropped():
    result = _group_entities_by_text([_entity("DATE", "yesterday", text_index=0)], 1)
    assert result == [{"PER": [], "ORG": [], "LOC": [], "MISC": []}]


def test_gpe_maps_to_loc():
    result = _group_entities_by_text(
        [_entity("GPE", "Berlin", text_index=0), _entity("LOC", "Alps", text_index=0)], 1
    )
    assert result[0]["LOC"] == ["Berlin", "Alps"]


def test_out_of_range_text_index_is_dropped():
    result = _group_entities_by_text([_entity("PER", "Ada", text_index=2)], 2)
    assert result == [{"PER": [], "ORG": [], "LOC": [], "MISC": []}] * 2


def test_negative_text_index_is_dropped():
    """Latent bug, pinned: with num_texts > 1 the old bounds check was only
    `text_index < len(result)`, so text_index = -1 passed and silently wrote
    the entity into the LAST text's slot."""
    result = _group_entities_by_text([_entity("PER", "Ada", text_index=-1)], 2)
    assert result == [{"PER": [], "ORG": [], "LOC": [], "MISC": []}] * 2
