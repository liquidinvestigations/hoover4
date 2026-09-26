"""The rewrite of `OR`, `AND` and `NOT` and the `@` of an address in `prepare_match_query`.

The table is the same as the one of `the_boolean_words_are_read_as_operators` in
`website/backend/src/db_utils/manticore_match.rs`, and the two tables change in one patch.
Only the first row differs, because this copy also escapes the `@` of an address.
"""

from __future__ import annotations

import pytest

from collection_search_server.backends import (
    _rewrite_boolean_words, _rewrite_field_operators, prepare_match_query,
)

OR_LINE = "read 1 OR as |, because OR is an ordinary word in a search"
AND_LINE = "dropped 1 AND, because every word of a query must occur anyway"
NOT_LINE = "read 1 NOT x as -x, because NOT is an ordinary word in a search"
STRAY_LINE = "dropped 1 OR or NOT with no word on one side"

REWRITE_TABLE = [
    ('JoeBWilkinson@cs.com OR "Joe B Wilkinson"', 'JoeBWilkinson@cs.com | "Joe B Wilkinson"', [OR_LINE]),
    ("LJM AND Raptor", "LJM Raptor", [AND_LINE]),
    ("water NOT draft", "water -draft", [NOT_LINE]),
    ("(a OR b) AND c", "(a | b) c", [OR_LINE, AND_LINE]),
    ('"cats OR dogs"', '"cats OR dogs"', []),
    ("water or sewage", "water or sewage", []),
    ("OR water", "water", [STRAY_LINE]),
    ("a OR OR b", "a | b", [OR_LINE, STRAY_LINE]),
    ('"a b"~3 OR c', '"a b"~3 | c', [OR_LINE]),
    ('a OR "b', 'a | "b', [OR_LINE]),
]


@pytest.mark.parametrize(("query", "expected", "repairs"), REWRITE_TABLE)
def test_the_boolean_words_are_read_as_operators(query, expected, repairs):
    got, got_repairs = _rewrite_boolean_words(query)
    assert " ".join(got.split()) == expected
    assert got_repairs == repairs


def test_a_lone_not_is_the_error_for_a_query_with_no_searchable_term():
    assert prepare_match_query("NOT").error == "query has no searchable terms"


def test_the_prepared_address_query_keeps_the_address_as_one_term():
    prepared = prepare_match_query('JoeBWilkinson@cs.com OR "Joe B Wilkinson"')
    # The SQL string escape doubles the backslash of `\@`.
    assert prepared.expr == 'JoeBWilkinson\\\\@cs.com | "Joe B Wilkinson"'
    assert prepared.repairs == (OR_LINE,)


def test_an_address_escapes_its_at_sign_and_adds_no_repair():
    assert _rewrite_field_operators("JoeBWilkinson@cs.com") == ("JoeBWilkinson\\@cs.com", [])


def test_a_field_operator_after_whitespace_keeps_the_old_rule():
    rewritten, repairs = _rewrite_field_operators("who paid @acme")
    assert rewritten == "who paid acme"
    assert len(repairs) == 1
    assert _rewrite_field_operators("@page_text water") == ("@page_text water", [])
