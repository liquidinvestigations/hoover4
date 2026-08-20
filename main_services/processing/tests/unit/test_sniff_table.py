"""The strict rules of the delimited-text sniff, one at a time.

Every one of these is a rule whose relaxation is a false positive against prose, so each
test names the rule rather than the input.
"""

import pytest

from tasks.P3_parse_files.sniff_table import (
    CANDIDATE_DELIMITERS,
    MIME_CSV,
    MIME_TSV,
    MIN_SNIFF_LINES,
    should_check_table,
    sniff_table,
)


def _bytes(*lines: str) -> bytes:
    # Every sample ends with a newline: the sniff drops the trailing partial line,
    # because a truncated read cuts the last line mid-field.
    return ("\n".join(lines) + "\n").encode("utf-8")


CSV = _bytes(
    "id,name,amount",
    "1,Acme Ltd,1204.50",
    "2,Bohm GmbH,88.00",
    "3,Ceres SA,4.25",
    "4,Delta BV,900.00",
    "5,Epsilon Oy,12.00",
)


def test_a_plain_csv_is_accepted():
    result = sniff_table(CSV)
    assert result is not None
    assert result.mime_type == MIME_CSV
    assert result.delimiter == ","
    assert result.field_count == 3


def test_a_tsv_is_named_as_a_tsv():
    result = sniff_table(CSV.replace(b",", b"\t"))
    assert result is not None
    assert result.mime_type == MIME_TSV
    assert result.delimiter == "\t"


def test_a_european_semicolon_csv_is_accepted():
    """The decimal comma also parses as a two-field comma table; the semicolon wins on
    field count, which is the tie-break rule."""
    result = sniff_table(_bytes(
        "id;name;amount",
        "1;Acme Ltd;1204,50",
        "2;Bohm GmbH;88,00",
        "3;Ceres SA;4,25",
        "4;Delta BV;900,00",
        "5;Epsilon Oy;12,00",
    ))
    assert result is not None
    assert result.delimiter == ";"
    assert result.field_count == 3


def test_a_four_line_file_is_refused():
    """Four lines of anything can be rectangular by accident."""
    short = _bytes(*[f"a,b,c" for _ in range(MIN_SNIFF_LINES - 1)])
    assert sniff_table(short) is None


def test_a_ragged_file_is_refused():
    """Exactly constant, not modal and not within one: prose averages commas."""
    assert sniff_table(_bytes(
        "a,b,c", "d,e,f", "g,h", "i,j,k", "l,m,n", "o,p,q",
    )) is None


def test_a_single_column_list_is_refused():
    """Two columns minimum. A list of names is a text file."""
    assert sniff_table(_bytes("alpha", "beta", "gamma", "delta", "epsilon", "zeta")) is None


def test_a_colon_separated_file_is_refused():
    """The rule this whole module exists for: an RFC 822 header block is a rectangular
    two-column colon-delimited table, and there are 21 291 of them on this box."""
    assert ":" not in CANDIDATE_DELIMITERS
    assert sniff_table(_bytes(
        "Message-ID: <1234@example.com>",
        "Date: Mon, 1 Jan 2001 00:00:00 -0800",
        "From: someone@example.com",
        "To: another@example.com",
        "Subject: quarterly numbers",
        "Mime-Version: 1.0",
    )) is None


def test_a_space_separated_file_is_refused():
    assert " " not in CANDIDATE_DELIMITERS
    assert sniff_table(_bytes(
        "the quick brown fox",
        "jumps over the dog",
        "and then runs away",
        "while nobody is watching",
        "which is the whole point",
        "of a lazy afternoon",
    )) is None


def test_a_quoted_field_containing_the_delimiter_counts_as_one_field():
    result = sniff_table(_bytes(
        'id,name,amount',
        '1,"Acme, Ltd",1204.50',
        '2,"Bohm, GmbH",88.00',
        '3,"Ceres, SA",4.25',
        '4,"Delta, BV",900.00',
        '5,"Epsilon, Oy",12.00',
    ))
    assert result is not None
    assert result.field_count == 3


def test_prose_with_a_blank_line_is_refused():
    """A blank line inside the sample is a paragraph break, not an empty record."""
    assert sniff_table(_bytes(
        "a,b,c", "d,e,f", "", "g,h,i", "j,k,l", "m,n,o",
    )) is None


def test_the_gate_never_offers_the_sniff_an_email():
    """The single most important line in the module: the email sniff answers first."""
    assert not should_check_table(["text/plain"], is_email=True)
    assert should_check_table(["text/plain"], is_email=False)


def test_the_gate_skips_bytes_no_amount_of_reading_makes_a_table():
    assert not should_check_table(["application/pdf"])
    assert not should_check_table(["image/jpeg"])
    assert should_check_table([])
    assert should_check_table(["application/octet-stream"])


@pytest.mark.parametrize("delimiter", CANDIDATE_DELIMITERS)
def test_every_candidate_delimiter_is_reachable(delimiter):
    rows = [delimiter.join(("a", "b", "c"))] * 6
    assert sniff_table(_bytes(*rows)) is not None
