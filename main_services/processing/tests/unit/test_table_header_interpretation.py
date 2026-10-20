"""Row 1 of a delimited sheet: the header, or the first data row.

Each case writes a small CSV, reads it with the production reader and collector, and
reads the sheet and column rows that the parser would store. Every row stays stored in
both readings. `header_row`, the column headers and the column statistics follow the
display choice (`first_row_is_data`). `header_state`, `header_basis` and
`header_candidates` record every plausible reading (`header_reading`).
"""

from __future__ import annotations

import pytest

from tasks.P3_parse_files import parse_table
from tasks.P3_parse_files.table_formats import READER_CSV, READER_VERSION, READER_XLSX_STREAM
from tasks.P3_parse_files.table_readers import RawCell, read_csv_cells


def _parse(tmp_path, text: str, name: str = "table.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    params = parse_table.ParseTableParams(collectionname="c", collection_dataset="c_d",
                                          file_hash="h" * 64, file_path=str(path), timeout_seconds=60)
    collector = parse_table._Collector(params, READER_CSV)
    for sheet_id, sheet_name, cell in read_csv_cells(str(path), delimiter=","):
        assert collector._accept(sheet_id, sheet_name, cell, None)
    collector.settle_headers()
    sheets = parse_table._sheet_rows(params, collector).to_pylist()
    columns = parse_table._column_rows(params, collector).to_pylist()
    return sheets, columns


def _events(count: int) -> str:
    """Rows shaped like a headerless event export: a seven-digit id and a title."""
    return "".join(f"{4000000 + 137 * i},Reception number {i} (Invitation)\n" for i in range(count))


def test_a_headered_file_keeps_its_header_and_its_count(tmp_path):
    sheets, columns = _parse(tmp_path, "id,title\n1001,Alpha\n1002,Beta\n1003,Gamma\n")
    assert sheets[0]["header_row"] == 1 and sheets[0]["row_count"] == 4
    assert [c["header"] for c in columns] == ["id", "title"]
    assert columns[0]["non_empty"] == 3 and columns[0]["min_value"] == "1001"


def test_a_headerless_file_reads_its_first_row_as_data(tmp_path):
    sheets, columns = _parse(tmp_path, _events(20))
    assert sheets[0]["header_row"] == 0 and sheets[0]["row_count"] == 20
    assert [c["header"] for c in columns] == ["", ""]
    assert [c["non_empty"] for c in columns] == [20, 20]
    assert columns[0]["samples"][0] == "4000000" and columns[0]["min_value"] == "4000000"
    assert columns[1]["samples"][0] == "Reception number 0 (Invitation)"


def test_a_quoted_title_with_commas_stays_one_cell(tmp_path):
    text = '6935631,"A Conversation with Mr. Example, Ministry of Justice (Invitation)"\n' + _events(5)
    sheets, columns = _parse(tmp_path, text)
    assert sheets[0]["header_row"] == 0 and sheets[0]["column_count"] == 2
    assert columns[1]["samples"][0].startswith("A Conversation with Mr. Example, Ministry")


def test_dates_in_the_first_row_are_data(tmp_path):
    sheets, _ = _parse(tmp_path, "2021-01-05,Opening\n2021-02-07,Briefing\n2021-03-09,Reception\n")
    assert sheets[0]["header_row"] == 0


@pytest.mark.parametrize("text", [
    # Text labels above numbers.
    "region,2019,2020\nNorth,15,20\nSouth,17,22\n",
    # Years above numbers with the same digit count: consecutive periods are a header.
    "region,2019,2020,2021\nNorth,1500,2000,2100\nSouth,1700,2200,2300\n",
    # A text label above a numeric column decides, whatever the other columns hold.
    "id,value\n1,abc\n2,3.5\n3,x\n",
])
def test_a_numeric_or_mixed_file_with_labels_keeps_its_header(tmp_path, text):
    sheets, columns = _parse(tmp_path, text)
    assert sheets[0]["header_row"] == 1
    assert columns[0]["header"] in ("region", "id")


def test_a_mixed_headerless_file_reads_its_first_row_as_data(tmp_path):
    sheets, columns = _parse(tmp_path, "1,abc\n2,3.5\n3,x\n4,y\n")
    assert sheets[0]["header_row"] == 0 and columns[0]["non_empty"] == 4


def test_a_text_only_file_keeps_row_one_as_its_header(tmp_path):
    """Text cells cannot show whether row 1 is a header, so the earlier reading stays."""
    sheets, columns = _parse(tmp_path, "Alice,Paris\nBob,Rome\nCarol,Oslo\n")
    assert sheets[0]["header_row"] == 1 and columns[0]["header"] == "Alice"
    assert sheets[0]["row_count"] == 3


def test_an_empty_file_has_no_sheet(tmp_path):
    sheets, columns = _parse(tmp_path, "")
    assert sheets == [] and columns == []


def test_a_new_reading_has_a_new_reader_version():
    """A parse of the earlier version is not reused for another dataset (`_existing_parse`)."""
    assert READER_VERSION == 3


def _reading(sheet):
    return sheet["header_state"], sheet["header_basis"], sheet["header_candidates"], sheet["header_row"]


@pytest.mark.parametrize("text,display", [
    # Text-only records: the cells cannot show whether row 1 is a header.
    ("Alice,Paris\nBob,Rome\nCarol,Oslo\n", 1),
    # Identifiers whose digit count changes below row 1.
    ("9,alpha\n10,beta\n11,gamma\n", 1),
    # Consecutive numeric data reads like a header of periods.
    ("1,2\n3,4\n5,6\n", 1),
    # A header of years that are not consecutive, above numbers with as many digits.
    ("region,2018,2020\nNorth,1500,2000\nSouth,1700,2200\n", 0),
    # Years above numbers with another digit count.
    ("region,2019,2020\nNorth,15,20\nSouth,17,22\n", 1),
    # A headerless export with seven-digit identifiers.
    (_events(20), 0),
    # Text labels above text columns.
    ("name,city\nAlice,Paris\nBob,Rome\n", 1),
])
def test_a_delimited_row_one_that_can_be_either_keeps_both_readings(tmp_path, text, display):
    sheets, _ = _parse(tmp_path, text)
    assert _reading(sheets[0]) == ("ambiguous", "heuristic", [0, 1], display)


@pytest.mark.parametrize("text", [
    "id,title\n1001,Alpha\n1002,Beta\n1003,Gamma\n",
    "id,value\n1,abc\n2,3.5\n3,x\n",
    # A label above a column of integers and decimals.
    "amount,label\n1,a\n2.5,b\n3,c\n",
    # A label above dates, with a quoted comma and a blank cell in the data.
    'opened,title\n2021-01-05,"Opening, North"\n2021-02-07,\n2021-03-09,Reception\n',
])
def test_a_text_label_above_typed_data_is_an_established_header(tmp_path, text):
    sheets, columns = _parse(tmp_path, text)
    assert _reading(sheets[0]) == ("established", "heuristic", [1], 1)
    assert columns[0]["header"] in ("id", "amount", "opened")


def test_a_number_in_row_one_never_establishes_a_header(tmp_path):
    """One numeric cell in row 1 can be data, so the header label beside it does not decide."""
    sheets, _ = _parse(tmp_path, "N/A,3\n5,4\n6,7\n")
    assert _reading(sheets[0])[:3] == ("ambiguous", "heuristic", [0, 1])


def test_a_blank_cell_in_row_one_leaves_the_other_labels_to_decide(tmp_path):
    sheets, columns = _parse(tmp_path, ",amount\nNorth,10\nSouth,20\n")
    assert _reading(sheets[0]) == ("established", "heuristic", [1], 1)
    assert [c["header"] for c in columns] == ["", "amount"]


def test_the_final_row_and_the_first_row_value_stay_stored(tmp_path):
    """The first row value occurs again in a later row. Both readings keep every stored row,
    so neither the final row nor the repeated value is lost."""
    sheets, _ = _parse(tmp_path, "Paris,x\nRome,y\nParis,z\nOslo,w\n")
    assert _reading(sheets[0])[:3] == ("ambiguous", "heuristic", [0, 1])
    assert sheets[0]["row_count"] == 4 and sheets[0]["max_source_row"] == 4


def test_a_workbook_sheet_reads_row_one_as_its_header_by_format(tmp_path):
    params = parse_table.ParseTableParams(collectionname="c", collection_dataset="c_d",
                                          file_hash="h" * 64, file_path=str(tmp_path / "book.xlsx"), timeout_seconds=60)
    collector = parse_table._Collector(params, READER_XLSX_STREAM)
    for row in range(1, 4):
        for column in (1, 2):
            text = f"r{row}c{column}"
            assert collector._accept(0, "Sheet1", RawCell(row, column, "text", text), None)
    collector.settle_headers()
    sheets = parse_table._sheet_rows(params, collector).to_pylist()
    assert _reading(sheets[0]) == ("established", "format", [1], 1)
