"""`recurse_json_decode` must carry a broker result page through unchanged.

The transcript stores the exact string the tool returns. Decoding a page's nested string into a dict here,
the way every other JSON-shaped string is decoded, would leave `trajectory.py` a dict
that a later `_dumps` call re-serializes into different bytes than the broker built.
"""

import json

from research_agent.agent import recurse_json_decode


PAGE_TEXT = json.dumps(
    {"kind": "result_page", "tool_name": "search_collections", "items": []},
    sort_keys=True,
    separators=(",", ":"),
)


class TestRecurseJsonDecode:
    def test_a_result_page_string_is_returned_unchanged(self):
        event = {"output": PAGE_TEXT}
        decoded = recurse_json_decode(event)
        assert decoded["output"] == PAGE_TEXT
        assert isinstance(decoded["output"], str)

    def test_a_nested_result_page_string_is_returned_unchanged(self):
        event = {"content": [{"type": "text", "text": PAGE_TEXT}]}
        decoded = recurse_json_decode(event)
        assert decoded["content"][0]["text"] == PAGE_TEXT

    def test_a_non_page_json_string_still_decodes(self):
        # Every other JSON-shaped string keeps today's behaviour: decoded into an
        # object, recursively.
        text = json.dumps({"kind": "something_else", "nested": json.dumps({"a": 1})})
        decoded = recurse_json_decode(text)
        assert decoded == {"kind": "something_else", "nested": {"a": 1}}

    def test_an_object_whose_kind_is_result_page_but_is_not_json_nested_is_unaffected(self):
        # A plain dict already, not a string: the guard only applies at the string
        # -> json.loads step, so a dict input is walked exactly as before.
        value = {"kind": "result_page", "inner": json.dumps({"a": 1})}
        decoded = recurse_json_decode(value)
        assert decoded == {"kind": "result_page", "inner": {"a": 1}}

    def test_a_plain_string_that_is_not_json_is_unaffected(self):
        assert recurse_json_decode("not json") == "not json"
