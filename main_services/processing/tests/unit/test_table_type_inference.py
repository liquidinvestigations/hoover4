"""Typing rules, which are where eagerness costs correctness.

A CSV carries no types at all, so every one of these rules exists to keep a column from
being filterable on a silently wrong reading of its values.
"""

from datetime import datetime

import pytest

from tasks.P3_parse_files.table_formats import (
    KIND_DATE,
    KIND_DATETIME,
    KIND_FLOAT,
    KIND_INT,
    KIND_TEXT,
)
from tasks.P3_parse_files.table_readers import (
    excel_serial_to_datetime,
    format_code_is_date,
    infer_delimited_kind,
    parse_iso_datetime,
    resolve_text_encoding,
)


@pytest.mark.parametrize("text", ["007", "01", "0123456789"])
def test_a_leading_zero_makes_it_an_identifier_not_a_number(text):
    """`007` is an agent and `01` is a month. Typing either loses the leading zero."""
    kind, _int, _float, _time = infer_delimited_kind(text)
    assert kind == KIND_TEXT


@pytest.mark.parametrize("text", ["1,234.00", "$99.00", "12%", "1 234", "1.2.3"])
def test_formatted_numbers_stay_text(text):
    kind, _int, _float, _time = infer_delimited_kind(text)
    assert kind == KIND_TEXT


def test_a_plain_integer_gets_both_typed_columns():
    kind, int_value, float_value, _time = infer_delimited_kind("1204")
    assert (kind, int_value, float_value) == (KIND_INT, 1204, 1204.0)


def test_an_int64_above_two_to_the_53_keeps_cell_int_exact():
    """Float64 cannot represent it, and a 19-digit account number is an ordinary cell."""
    text = "9007199254740993"
    kind, int_value, float_value, _time = infer_delimited_kind(text)
    assert kind == KIND_INT
    assert int_value == 9007199254740993
    assert int_value != int(float_value)


def test_an_integer_past_int64_stays_text():
    kind, _int, _float, _time = infer_delimited_kind("9" * 25)
    assert kind == KIND_TEXT


def test_a_decimal_is_a_float():
    kind, int_value, float_value, _time = infer_delimited_kind("-1204.50")
    assert (kind, int_value, float_value) == (KIND_FLOAT, None, -1204.50)


def test_an_ambiguous_date_stays_text():
    """Nothing in the file says whether `03/04/2020` is 3 April or 4 March, and a corpus
    filtered on a silently wrong reading of it is worse than one that cannot be."""
    kind, _int, _float, _time = infer_delimited_kind("03/04/2020")
    assert kind == KIND_TEXT


def test_an_iso_date_is_a_date():
    kind, _int, _float, time_value = infer_delimited_kind("2019-03-04")
    assert kind == KIND_DATE
    assert time_value == datetime(2019, 3, 4)


def test_an_iso_datetime_with_an_offset_normalises_to_utc():
    kind, _int, _float, time_value = infer_delimited_kind("2019-03-04T10:00:00+02:00")
    assert kind == KIND_DATETIME
    assert time_value == datetime(2019, 3, 4, 8, 0, 0)


def test_true_and_false_stay_text():
    """A CSV has no booleans, only words."""
    for text in ("TRUE", "false", "Yes"):
        kind, _int, _float, _time = infer_delimited_kind(text)
        assert kind == KIND_TEXT


def test_an_impossible_iso_date_is_not_a_date():
    assert parse_iso_datetime("2019-02-30") is None
    assert parse_iso_datetime("2019-13-01") is None


def test_serial_sixty_is_the_lotus_leap_year_bug():
    """The 1900 system counts a 29th of February 1900 that never existed. Serial 60 is
    that day, so it has no answer, and every serial above it is one greater than a naive
    epoch calculation would give."""
    assert excel_serial_to_datetime(59) == datetime(1900, 2, 28)
    assert excel_serial_to_datetime(60) is None
    assert excel_serial_to_datetime(61) == datetime(1900, 3, 1)


def test_the_1900_and_1904_epochs_disagree_by_four_years_and_a_day():
    assert excel_serial_to_datetime(43528) == datetime(2019, 3, 4)
    assert excel_serial_to_datetime(42066, date1904=True) == datetime(2019, 3, 4)


@pytest.mark.parametrize("code,is_date", [
    ("yyyy-mm-dd", True),
    ("dd/mm/yyyy hh:mm", True),
    ("h:mm:ss", True),
    ('"$"#,##0.00', False),
    ("#,##0", False),
    ("[Red]#,##0", False),
    ('0.00" kg"', False),
])
def test_a_custom_format_code_is_read_past_its_literals(code, is_date):
    """`"$"#,##0.00` contains a `d` in nobody's calendar, and a currency column reported
    as dates is the classic naive-reader failure."""
    assert format_code_is_date(code) is is_date


def test_the_recorded_encoding_is_preferred_over_a_guess():
    assert resolve_text_encoding(["iso-8859-1"]) == "iso-8859-1"
    assert resolve_text_encoding(["utf-8"]) == "utf-8"


def test_a_non_answer_encoding_is_skipped():
    """`unknown-8bit` and `binary` name the absence of an answer, not an encoding."""
    assert resolve_text_encoding(["unknown-8bit", "binary"]) == "utf-8"
    assert resolve_text_encoding(["not-a-codec"]) == "utf-8"
    assert resolve_text_encoding([]) == "utf-8"
