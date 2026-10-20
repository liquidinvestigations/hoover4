"""Row 1 of a delimited sheet: the header, or the first data row (`first_row_is_data`).

Each case writes a small CSV, reads it with the production reader and collector, and
reads the sheet and column rows that the parser would store. Every row stays stored in
both readings. Only `header_row`, the column headers and the column statistics change.
"""

from __future__ import annotations

import pytest

from tasks.P3_parse_files import parse_table
from tasks.P3_parse_files.table_formats import READER_CSV, READER_VERSION
from tasks.P3_parse_files.table_readers import read_csv_cells


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
    assert READER_VERSION == 2
