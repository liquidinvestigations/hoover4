"""Tests for the argument normalization (`tool_args`) and the tool wrapper that applies it."""

import json
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool

from research_agent.agent import with_decoded_arguments
from research_agent.execution import validation_error


@pytest.mark.parametrize("validator,value,limit,expected", [
    ("maxItems", ["long source passage " * 30] * 7, 6, "pages: accepts at most 6 items. The call gave 7 items."),
    ("minItems", [], 1, "pages: accepts at least 1 item. The call gave 0 items."),
    ("maxLength", "α" * 400, 200, "pages: accepts at most 200 characters. The call gave 400 characters."),
    ("minLength", "", 1, "pages: accepts at least 1 character. The call gave 0 characters."),
])
def test_size_errors_keep_the_limit_when_input_text_is_long(validator, value, limit, expected):
    kind = "array" if validator.endswith("Items") else "string"
    schema = {"type": "object", "properties": {"pages": {"type": kind, validator: limit}}}
    assert validation_error({"pages": value}, schema) == expected
from research_agent.tool_args import (
    DamagedArguments, decode_string_arguments, model_schema, normalize_arguments,
    rename_aliases, repair_arguments,
)

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


# ------------------------------------------------------------------ the quote token
#
# The argument strings below have the shapes that a model writes when it leaks the quote
# token into a key or a value of a tool call.


def test_the_keys_of_a_todo_step_lose_their_quotes_and_the_values_one_layer():
    args = {"goal": "Identify who Nili Priell Barak is.",
            "steps": [{'id"': '"1"', '"text': "Five Ws: find who she is.",
                       'status"': '"in_progress"'}]}
    fixed, repairs = repair_arguments(args)
    assert fixed == {"goal": "Identify who Nili Priell Barak is.",
                     "steps": [{"id": "1", "text": "Five Ws: find who she is.",
                                "status": "in_progress"}]}
    assert len(repairs) == 5


def test_quoted_keys_and_values_of_a_document_list_are_repaired():
    args = {"documents": [{'"collectionname"': '"textfiles"',
                           '"file_hash"': '"fa098b7d7a24880b2be0e2e595eb1c941808f19888afe576e8facdeb93e315d3"'}]}
    fixed, _ = repair_arguments(args)
    assert fixed == {"documents": [{
        "collectionname": "textfiles",
        "file_hash": "fa098b7d7a24880b2be0e2e595eb1c941808f19888afe576e8facdeb93e315d3"}]}


def test_mark_todo_ids_and_status_lose_one_layer_of_quotes():
    fixed, _ = repair_arguments({"ids": ['"1"', '"2"', '"3"'], "status": '"done"'})
    assert fixed == {"ids": ["1", "2", "3"], "status": "done"}


def test_a_query_keeps_its_phrase_quotes_and_loses_the_quote_token():
    args = {"queries": ['"survey section report",', '"survey results"<|"|>', '"Raptor"'],
            "query": '"LJM"'}
    fixed, repairs = repair_arguments(args)
    assert fixed == {"queries": ['"survey section report",', '"survey results"', '"Raptor"'],
                     "query": '"LJM"'}
    assert repairs == ["value queries[1] lost the quote token"]


def test_a_key_that_holds_the_token_inside_it_is_damage_and_is_not_rebuilt():
    """The parser put an email address and the next key into one key."""
    args = {"citations": [{"collectionname": "tables", "quote": 'a quote<|"|>',
                           'JoeBWilkinson@cs.com<|"|>,why': "his address"}]}
    with pytest.raises(DamagedArguments, match=r"holds a string delimiter at citations\[0\]\."):
        repair_arguments(args)


def test_a_phrase_value_keeps_its_quotes_and_clean_arguments_give_no_repair():
    args = {"note": '"not found in the reports"', "ids": ["1"], "status": "done", "n": 3}
    assert repair_arguments(args) == (args, [])


def test_repaired_keys_with_different_values_are_refused_and_drop_nothing():
    with pytest.raises(DamagedArguments, match="both name the argument id"):
        repair_arguments({"id": "1", 'id"': "2"})


def test_repaired_keys_with_the_same_value_give_one_key():
    fixed, repairs = repair_arguments({"id": "1", 'id"': "1"})
    assert fixed == {"id": "1"}
    assert repairs[-1] == "key 'id\"' repeated 'id' with the same value"


def test_an_alias_key_becomes_the_schema_name():
    schema = {"properties": {"collectionname": {"type": "string"}, "file_hash": {"type": "array"}}}
    fixed, repairs = rename_aliases({"collection": "testdata", "file_hash": ["h"]}, schema)
    assert fixed == {"collectionname": "testdata", "file_hash": ["h"]}
    assert repairs == ["key 'collection' became 'collectionname'"]


def test_an_alias_stays_when_the_schema_has_it():
    schema = {"properties": {"collection": {"type": "string"}, "collectionname": {"type": "string"}}}
    args = {"collection": "a"}
    assert rename_aliases(args, schema) == (args, [])


def test_an_alias_beside_its_name_is_refused_with_another_value_and_removed_with_the_same():
    schema = {"properties": {"collectionname": {"type": "string"}}}
    with pytest.raises(DamagedArguments, match="'collection' and 'collectionname'"):
        rename_aliases({"collection": "a", "collectionname": "b"}, schema)
    assert rename_aliases({"collection": "a", "collectionname": "a"}, schema)[0] == {
        "collectionname": "a"}


# ------------------------------------------------------------------ scalars and lists

IDS_SCHEMA = {
    "type": "object",
    "properties": {
        "ids": {"type": "array", "items": {"type": "integer"}},
        "file_hash": {"type": "string"},
        "citations": {"anyOf": [
            {"type": "array", "items": {"type": "object", "properties": {"file_hash": {"type": "string"}}}},
            {"type": "string"}]},
    },
}


def test_a_scalar_that_is_a_valid_item_becomes_a_one_item_list():
    assert decode_string_arguments({"ids": 3}, IDS_SCHEMA) == {"ids": [3]}
    assert decode_string_arguments({"ids": "3"}, IDS_SCHEMA) == {"ids": [3]}


def test_a_scalar_that_is_not_a_valid_item_stays_for_the_validation_error():
    assert decode_string_arguments({"ids": "three"}, IDS_SCHEMA) == {"ids": "three"}
    assert decode_string_arguments({"ids": True}, IDS_SCHEMA) == {"ids": True}


def test_a_list_for_a_scalar_parameter_stays_a_list_and_the_error_says_so():
    args = {"file_hash": ["a" * 16, "b" * 16]}
    assert normalize_arguments(args, IDS_SCHEMA).args == args
    problem = validation_error(args, IDS_SCHEMA)
    assert problem == ("file_hash: takes one string value, and the call gave a list of 2 "
                       "items. Send one value.")


def test_a_single_object_for_a_list_of_objects_becomes_one_item():
    args = {"citations": {"file_hash": "h"}}
    assert decode_string_arguments(args, IDS_SCHEMA) == {"citations": [{"file_hash": "h"}]}
    schema = {"properties": {"docs": {"type": "array", "items": {"type": "object"}}}}
    assert decode_string_arguments({"docs": {"a": 1}}, schema) == {"docs": [{"a": 1}]}


def test_a_second_normalization_changes_nothing_and_names_no_repair():
    args = {"collection": "testdata", "ids": '"3"', "query": '"LJM"<|"|>',
            "steps": ['a step<|"|>']}
    schema = {"properties": {"collectionname": {"type": "string"}, "query": {"type": "string"},
                             "ids": IDS_SCHEMA["properties"]["ids"],
                             "steps": {"type": "array", "items": {"type": "string"}}}}
    first = normalize_arguments(args, schema)
    assert first.problem == ""
    assert first.args == {"collectionname": "testdata", "ids": [3], "query": '"LJM"',
                          "steps": ["a step"]}
    second = normalize_arguments(first.args, schema)
    assert second == (first.args, [], "")


def test_merged_queries_are_repaired_without_losing_phrase_quotes():
    args = {"queries": ['"LJM"', 'Raptor"<|"|><|"|>"LJM1"']}
    out = normalize_arguments(args, {"properties": {"queries": {"type": "array"}}})
    assert out.args == {"queries": ['"LJM"', '"Raptor"', '"LJM1"']}
    assert out.problem == "" and out.repairs
    assert normalize_arguments(out.args, None) == (out.args, [], "")


# ------------------------------------------------------------------ the served model's calls

FIXTURES = json.loads((Path(__file__).parent / "producer_fixtures" / "gemma4_tool_calls.json")
                      .read_text())
CASES = {entry["case"]: entry for entry in FIXTURES["entries"]}

CITE_SCHEMA = {
    "type": "object",
    "properties": {"citations": {"anyOf": [
        {"type": "array", "items": {
            "type": "object",
            "properties": {"collectionname": {"type": "string"}, "file_hash": {"type": "string"},
                           "quote": {"default": "", "type": "string"},
                           "find": {"default": "", "type": "string"},
                           "why": {"default": "", "type": "string"}},
            "required": ["collectionname", "file_hash"]}},
        {"type": "string"}]}},
    "required": ["citations"],
}


@pytest.mark.parametrize("case", ["objects_written_as_lists"])
def test_each_damaged_parse_of_the_served_model_is_refused_and_not_rebuilt(case):
    parsed = CASES[case]["parser_result"]
    out = normalize_arguments(parsed, {"properties": {}})
    assert out.problem.startswith("The call was not run, because its arguments arrived damaged")
    assert out.args == parsed


def test_a_trailing_delimiter_of_the_served_model_is_removed():
    out = normalize_arguments(CASES["item_with_a_trailing_delimiter"]["parser_result"], None)
    assert out.problem == ""
    assert out.args["steps"][2] == "Summarize findings regarding prime numbers."
    assert all('<|"|>' not in step for step in out.args["steps"])


def test_a_well_formed_search_keeps_every_phrase_quote():
    parsed = CASES["search_queries_with_phrase_quotes"]["parser_result"]
    out = normalize_arguments(parsed, None)
    assert out == (parsed, [], "")
    assert parsed["queries"][0] == '"LJM" "Raptor"'


def test_invented_citation_keys_get_an_error_that_names_the_schema_fields():
    """The served model sent these keys because the template showed `citations` with no
    type. The error names the missing fields and the keys that the schema does not name."""
    parsed = CASES["cite_documents_invented_keys"]["parser_result"]
    out = normalize_arguments(parsed, CITE_SCHEMA)
    assert out.problem == ""
    problem = validation_error(out.args, CITE_SCHEMA)
    assert "citations/0: 'collectionname' is a required property." in problem
    assert "'document_id'" in problem and "'find_phrase'" in problem
    assert "The schema names collectionname, file_hash, quote, find, why." in problem
    assert "not valid under any of the given schemas" not in problem


def test_the_streamed_prefix_of_the_parser_defect_is_not_json_and_its_final_parse_is_damaged():
    """The captured failing input of the external parser defect. The client receives the
    streamed prefix, which is not JSON, and the final parse holds keys with delimiters."""
    case = CASES["streamed_prefix_not_json"]
    assert case["raw"].startswith("<|tool_call>call:cite_documents{")
    with pytest.raises(json.JSONDecodeError):
        json.loads(case["streamed_arguments"])
    out = normalize_arguments(case["parser_result"], None)
    assert out.problem.startswith("The call was not run, because its arguments arrived damaged")


# ------------------------------------------------------------------ the schema shown to the model


def test_the_shown_schema_has_one_type_for_each_parameter():
    shown = model_schema(CITE_SCHEMA)
    citations = shown["properties"]["citations"]
    assert citations["type"] == "array"
    assert citations["items"]["required"] == ["collectionname", "file_hash"]
    assert list(citations["items"]["properties"]) == ["collectionname", "file_hash", "quote",
                                                      "find", "why"]
    shown = model_schema(SEARCH_SCHEMA)
    for name in ("collectionname", "filename_only", "size_min", "sort"):
        assert "anyOf" not in shown["properties"][name], name
    assert shown["properties"]["collectionname"] == {
        "items": {"type": "string"}, "type": "array", "default": None}
    assert shown["properties"]["sort"]["type"] == "object"
    assert shown["properties"]["anything"] == {"default": None}


def test_the_shown_schema_keeps_the_description_and_copies_a_reference_into_place():
    schema = {
        "type": "object",
        "properties": {
            "node_id": {"anyOf": [{"type": "string"}, {"type": "integer"}], "default": "",
                        "description": "The id or number path."},
            "page": {"$ref": "#/$defs/Page"},
            "mixed": {"anyOf": [{"type": "array"}, {"type": "object"}]},
        },
        "$defs": {"Page": {"type": "object", "properties": {"n": {"type": "integer"}}}},
    }
    shown = model_schema(schema)
    assert shown["properties"]["node_id"] == {"type": "string", "default": "",
                                              "description": "The id or number path."}
    assert shown["properties"]["page"] == {"type": "object",
                                           "properties": {"n": {"type": "integer"}}}
    assert "anyOf" in shown["properties"]["mixed"]
    assert "$defs" not in shown
    # The tool's own schema is not changed.
    assert "anyOf" in schema["properties"]["node_id"]


@pytest.mark.parametrize("case", ["queries_merged_by_delimiters", "query_with_a_delimiter_inside"])
def test_captured_query_delimiters_are_repaired(case):
    parsed = CASES[case]["parser_result"]
    out = normalize_arguments(parsed, SEARCH_SCHEMA)
    assert out.problem == "" and out.repairs
    assert all('<|"|>' not in value for value in out.args["queries"])
    assert normalize_arguments(out.args, SEARCH_SCHEMA) == (out.args, [], "")


@pytest.mark.parametrize("raw,expected", [
    ('{children: [], "title": "Keep {children: as text"}', {"children": [], "title": "Keep {children: as text"}),
    ('{"children": [],queries": ["one"]}', {"children": [], "queries": ["one"]}),
])
def test_missing_key_quotes_preserve_quoted_values(raw, expected):
    out = normalize_arguments(raw, None)
    assert out.problem == "" and out.args == expected and out.repairs


def test_unrepairable_json_names_the_damage_position():
    out = normalize_arguments('{children: [}', None)
    assert "position" in out.problem
    assert out.args == {}


def test_captured_collection_list_contains_other_named_arguments():
    args = {"collectionname": ["epstein", "filename_only:true", 'queries:[<|"|>.pdf<|"|>']}
    schema = {**SEARCH_SCHEMA, "properties": {**SEARCH_SCHEMA["properties"], "queries": {"type": "array", "items": {"type": "string"}}}}
    out = normalize_arguments(args, schema)
    assert out.problem == ""
    assert out.args == {"collectionname": ["epstein"], "filename_only": True, "queries": [".pdf"]}


def test_captured_structural_key_prefixes_are_removed():
    args = {"collectionname": "enron", "],queries": ['"franznp"']}
    out = normalize_arguments(args, SEARCH_SCHEMA)
    assert out.problem == "" and out.args["queries"] == ['"franznp"']
    nested = {"children": [{"{children": [{"text": "Read documents"}]}]}
    assert normalize_arguments(nested, None).args == {"children": [{"children": [{"text": "Read documents"}]}]}
