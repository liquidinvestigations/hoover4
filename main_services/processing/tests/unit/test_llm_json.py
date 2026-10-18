"""Verify the shared JSON reader of model replies for objects and arrays."""

import pytest

from tasks.llm_json import extract_json


@pytest.mark.parametrize("text, expected", [
    ('{"a": 1}', {"a": 1}),
    ('Answer:\n```json\n{"a": 1}\n```', {"a": 1}),
    ('```json\n"a": 1\n```', {"a": 1}),
    ('<think>{"no": 0}</think>{"a": [1, 2,],}', {"a": [1, 2]}),
    ('```\n{"a": 1}\n```\nlater ```json\n{"b": 2}\n```', {"b": 2}),
])
def test_objects(text, expected):
    assert extract_json(text, "object") == expected


@pytest.mark.parametrize("text, expected", [
    ('["x", "y"]', ["x", "y"]),
    ('```json\n[\n "x",\n "y"\n]\n```', ["x", "y"]),
    ('Here: ["x", "y",]', ["x", "y"]),
])
def test_arrays(text, expected):
    assert extract_json(text, "array") == expected


@pytest.mark.parametrize("text, kind", [
    ("no json", "object"), ('["x"]', "object"), ('{"a": 1}', "array"), ("", "array"),
])
def test_a_reply_without_the_kind_is_refused(text, kind):
    with pytest.raises(ValueError):
        extract_json(text, kind)
