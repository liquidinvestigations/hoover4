"""The format table, the reader dispatch, the caps and the truncation record."""

import pytest

from tasks.P3_parse_files.table_formats import (
    BINARY_TABLE_MIMES,
    DELIMITED_TABLE_MIMES,
    LIMIT_COLUMNS_PER_SHEET,
    LIMIT_ROWS_PER_SHEET,
    MAX_CELLS_PER_DOCUMENT,
    MAX_COLUMNS_PER_SHEET,
    MAX_ROWS_PER_SHEET,
    MAX_SHEETS,
    MIN_BINARY_CELLS,
    MIN_DELIMITED_COLUMNS,
    MIN_DELIMITED_ROWS,
    READER_CALAMINE,
    READER_CSV,
    READER_ODS_STREAM,
    READER_XLSX_STREAM,
    TruncationRecord,
    column_index,
    column_letter,
    is_delimited_reader,
    is_table_mime,
    table_format_for,
    table_reader_for,
)


@pytest.mark.parametrize("mime", sorted(BINARY_TABLE_MIMES | DELIMITED_TABLE_MIMES))
def test_every_declared_table_mime_is_a_table(mime):
    assert is_table_mime(mime)


@pytest.mark.parametrize("mime", [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/pdf",
    "text/plain",
    "text/html",
    "application/json",
    "application/vnd.oasis.opendocument.text",
])
def test_things_that_are_not_tables(mime):
    """A `.docx`, a PDF, prose and JSON are all out, and each was a live proposal."""
    assert not is_table_mime(mime)


@pytest.mark.parametrize("name,expected", [
    ("book.xlsx", READER_XLSX_STREAM),
    ("book.xlsm", READER_XLSX_STREAM),
    ("book.xltx", READER_XLSX_STREAM),
    ("book.xls", READER_CALAMINE),
    ("book.xlsb", READER_CALAMINE),
    ("book.ods", READER_ODS_STREAM),
    ("book.ots", READER_ODS_STREAM),
    ("export.csv", READER_CSV),
    ("export.tsv", READER_CSV),
    ("export.tab", READER_CSV),
    ("export.psv", READER_CSV),
    ("readme.md", ""),
])
def test_reader_for_every_fixture_extension(name, expected):
    assert table_reader_for([], name) == expected


def test_the_mime_set_decides_when_the_name_does_not():
    """An extension-less export named only by the sniff still finds its reader."""
    assert table_reader_for(["text/csv"], "/tmp/export") == READER_CSV
    assert table_reader_for(["application/vnd.ms-excel"], "/tmp/blob") == READER_CALAMINE
    assert table_reader_for(
        ["application/vnd.oasis.opendocument.spreadsheet"], "/tmp/blob"
    ) == READER_ODS_STREAM


def test_the_extension_beats_a_disagreeing_mime_set():
    """Five detectors disagree by design and three of them call a `.xlsb` a zip."""
    assert table_reader_for(
        ["application/zip",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
        "/tmp/book.xlsb",
    ) == READER_CALAMINE


def test_table_format_is_the_readers_answer_not_the_detectors():
    assert table_format_for(READER_CSV, "/tmp/export.tsv") == "tsv"
    assert table_format_for(READER_CSV, "/tmp/export") == "csv"
    assert table_format_for(READER_XLSX_STREAM, "/tmp/book.xlsm") == "xlsm"


def test_only_delimited_text_has_to_clear_the_shape_threshold():
    """The whole point of the 2x2 rule: a spreadsheet is a table because it is one."""
    assert is_delimited_reader(READER_CSV)
    assert not is_delimited_reader(READER_XLSX_STREAM)
    assert not is_delimited_reader(READER_CALAMINE)
    assert not is_delimited_reader(READER_ODS_STREAM)
    assert (MIN_DELIMITED_ROWS, MIN_DELIMITED_COLUMNS) == (2, 2)
    assert MIN_BINARY_CELLS == 1


def test_the_caps_are_the_agreed_numbers():
    assert MAX_CELLS_PER_DOCUMENT == 300_000_000
    assert MAX_ROWS_PER_SHEET == 10_000_000
    assert MAX_COLUMNS_PER_SHEET == 300
    assert MAX_SHEETS == 100


@pytest.mark.parametrize("ordinal,letters", [
    (1, "A"), (26, "Z"), (27, "AA"), (28, "AB"), (52, "AZ"), (703, "AAA"),
])
def test_column_letters_round_trip(ordinal, letters):
    assert column_letter(ordinal) == letters
    assert column_index(letters) == ordinal


def test_column_index_reads_a_cell_reference():
    """`<c r="AB7">` is column 28, and the row digits must not leak into the ordinal."""
    assert column_index("AB7") == 28
    assert column_index("A1") == 1


def test_a_truncation_record_names_the_limit_and_its_maximum():
    record = TruncationRecord()
    assert not record.truncated
    record.record(LIMIT_COLUMNS_PER_SHEET, "Sheet1")
    record.record(LIMIT_ROWS_PER_SHEET, "Sheet1")
    assert record.truncated
    assert record.limits == [LIMIT_COLUMNS_PER_SHEET, LIMIT_ROWS_PER_SHEET]
    assert record.maximums == [MAX_COLUMNS_PER_SHEET, MAX_ROWS_PER_SHEET]
    assert record.sheets == ["Sheet1", "Sheet1"]
    assert str(MAX_COLUMNS_PER_SHEET) in record.reason()


def test_the_same_cap_on_the_same_sheet_is_recorded_once():
    """A row cap fires once per row otherwise, and the banner would be unreadable."""
    record = TruncationRecord()
    for _ in range(100):
        record.record(LIMIT_ROWS_PER_SHEET, "Sheet1")
    record.record(LIMIT_ROWS_PER_SHEET, "Sheet2")
    assert record.limits == [LIMIT_ROWS_PER_SHEET, LIMIT_ROWS_PER_SHEET]
    assert record.sheets == ["Sheet1", "Sheet2"]


def test_the_three_truncation_arrays_stay_parallel():
    """Agent-visible contract: index i of each array describes the same cap event."""
    record = TruncationRecord()
    record.record(LIMIT_ROWS_PER_SHEET, "A")
    record.record(LIMIT_COLUMNS_PER_SHEET, "B")
    assert len(record.limits) == len(record.maximums) == len(record.sheets)
