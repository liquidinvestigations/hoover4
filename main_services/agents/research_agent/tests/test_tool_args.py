"""Tests for `decode_string_arguments` and the tool wrapper that applies it."""

from langchain_core.tools import StructuredTool

from research_agent.agent import with_decoded_arguments
from research_agent.tool_args import decode_string_arguments

# Parameters in the shape the MCP server publishes, taken from the `search_collections`
# input schema, with `anything` added for a parameter that accepts any type.
SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "collectionname": {
            "anyOf": [{"items": {"type": "string"}, "type": "array"}, {"type": "null"}],
            "default": None,
        },
        "query": {"default": "", "type": "string"},
        "filename_only": {"anyOf": [{"type": "boolean"}, {"type": "null"}], "default": None},
        "size_min": {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": None},
        "sort": {
            "anyOf": [
                {
                    "properties": {
                        "field": {"type": "string"},
                        "direction": {"enum": ["asc", "desc"], "type": "string"},
                    },
                    "required": ["field", "direction"],
                    "type": "object",
                },
                {"type": "null"},
            ],
            "default": None,
        },
        "anything": {"anyOf": [{}, {"type": "null"}], "default": None},
    },
}


def test_list_sent_as_json_string_is_decoded():
    out = decode_string_arguments({"collectionname": '["testdata"]'}, SEARCH_SCHEMA)
    assert out == {"collectionname": ["testdata"]}


def test_bare_string_for_array_of_strings_is_wrapped():
    out = decode_string_arguments({"collectionname": "testdata"}, SEARCH_SCHEMA)
    assert out == {"collectionname": ["testdata"]}


def test_number_text_for_array_of_strings_is_wrapped():
    out = decode_string_arguments({"collectionname": "2024"}, SEARCH_SCHEMA)
    assert out == {"collectionname": ["2024"]}


def test_boolean_text_for_array_of_strings_is_wrapped():
    out = decode_string_arguments({"collectionname": "true"}, SEARCH_SCHEMA)
    assert out == {"collectionname": ["true"]}


def test_boolean_words_are_decoded_in_any_case():
    for word, expected in (("True", True), ("false", False), ("TRUE", True), ("False", False)):
        out = decode_string_arguments({"filename_only": word}, SEARCH_SCHEMA)
        assert out == {"filename_only": expected}


def test_integer_sent_as_string_is_decoded():
    out = decode_string_arguments({"size_min": "5"}, SEARCH_SCHEMA)
    assert out == {"size_min": 5}
    assert type(out["size_min"]) is int


def test_boolean_is_not_accepted_for_an_integer():
    out = decode_string_arguments({"size_min": "true"}, SEARCH_SCHEMA)
    assert out == {"size_min": "true"}


def test_object_sent_as_json_string_is_decoded():
    sort = '{"field": "date", "direction": "desc"}'
    out = decode_string_arguments({"sort": sort}, SEARCH_SCHEMA)
    assert out == {"sort": {"field": "date", "direction": "desc"}}


def test_string_parameter_holding_json_text_stays_a_string():
    out = decode_string_arguments({"query": '["testdata"]'}, SEARCH_SCHEMA)
    assert out == {"query": '["testdata"]'}


def test_unconstrained_parameter_stays_a_string():
    out = decode_string_arguments({"anything": "[1, 2]"}, SEARCH_SCHEMA)
    assert out == {"anything": "[1, 2]"}


def test_nested_any_of_with_null_is_followed():
    schema = {
        "properties": {
            "ids": {
                "anyOf": [
                    {"anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "null"}]},
                    {"type": "null"},
                ]
            }
        }
    }
    assert decode_string_arguments({"ids": "[1, 2]"}, schema) == {"ids": [1, 2]}
    # `null` is never a decode target.
    assert decode_string_arguments({"ids": "null"}, schema) == {"ids": "null"}


def test_value_that_does_not_decode_stays_unchanged():
    assert decode_string_arguments({"size_min": "five"}, SEARCH_SCHEMA) == {"size_min": "five"}
    assert decode_string_arguments({"sort": "[1]"}, SEARCH_SCHEMA) == {"sort": "[1]"}
    assert decode_string_arguments({"sort": "{broken"}, SEARCH_SCHEMA) == {"sort": "{broken"}


def test_unknown_parameter_and_non_string_values_stay_unchanged():
    args = {"other": "[1]", "collectionname": ["a"], "size_min": 3}
    assert decode_string_arguments(args, SEARCH_SCHEMA) == args


def test_type_list_and_ref_are_followed():
    schema = {
        "properties": {
            "limit": {"type": ["integer", "null"]},
            "page": {"$ref": "#/$defs/Page"},
        },
        "$defs": {"Page": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    }
    out = decode_string_arguments({"limit": "7", "page": '{"n": 2}'}, schema)
    assert out == {"limit": 7, "page": {"n": 2}}


async def test_wrapped_tool_receives_decoded_live_model_arguments():
    received = {}

    async def call_tool(**arguments):
        received.update(arguments)
        return "ok"

    tool = StructuredTool(
        name="search_collections",
        description="Search the collections.",
        args_schema=SEARCH_SCHEMA,
        coroutine=call_tool,
    )
    wrapped = with_decoded_arguments(tool)

    # The exact argument dict the live model sent.
    live = {"collectionname": "testdata", "query": "stanley.ec02.pdf", "filename_only": "True"}
    assert await wrapped.ainvoke(live) == "ok"
    assert received == {
        "collectionname": ["testdata"],
        "query": "stanley.ec02.pdf",
        "filename_only": True,
    }
    # The original tool is not changed.
    assert tool.coroutine is call_tool
    assert wrapped.name == tool.name and wrapped.args_schema is tool.args_schema
