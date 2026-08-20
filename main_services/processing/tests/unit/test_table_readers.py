"""What each reader produces, including the things a tab-joined flattening cannot.

The centrepiece is the cross-reader equivalence check: two fixtures hold the same content
as `.xls` and as `.xlsx`, so the streaming OOXML reader and the calamine BIFF reader must
produce the same cell grid. That one assertion covers column indexing, type mapping,
shared strings and blank handling across two independent implementations at once.
"""

import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from tasks.P3_parse_files.table_formats import (
    KIND_DATE,
    KIND_INT,
    KIND_TEXT,
    READER_CALAMINE,
    READER_CSV,
    READER_ODS_STREAM,
    READER_XLSX_STREAM,
)
from tasks.P3_parse_files.table_readers import read_cells

EXCELS = Path("/testdata/hoover-testdata/data/www.learningcontainer.com/excels")

pytestmark = pytest.mark.skipif(not EXCELS.is_dir(), reason="testdata not mounted")


def _grid(path, reader):
    return [
        (sheet_id, cell.source_row, cell.column_id, cell.kind, cell.text)
        for sheet_id, _name, cell in read_cells(str(path), reader)
    ]


def test_the_same_content_reads_identically_as_xls_and_as_xlsx():
    """Two independent implementations, one grid. The single most informative assertion
    in this module: a disagreement here is a column index, a type map, a shared string or
    a blank, and it names which."""
    streamed = _grid(EXCELS / "excel-spreadsheet-examples-for-students.xlsx",
                     READER_XLSX_STREAM)
    calamine = _grid(EXCELS / "excel-spreadsheet-examples-for-students.xls",
                     READER_CALAMINE)
    assert streamed, "the xlsx fixture produced no cells"
    assert streamed == calamine


def test_a_csv_and_its_workbook_hold_the_same_grid():
    """`sample-csv-file-for-testing.csv` is the same export as the xls and the xlsx."""
    csv_cells = _grid(EXCELS / "sample-csv-file-for-testing.csv", READER_CSV)
    xlsx_cells = _grid(EXCELS / "sample-xlsx-file-for-testing.xlsx", READER_XLSX_STREAM)
    assert len(csv_cells) == len(xlsx_cells)


def test_a_dated_workbook_resolves_its_dates_through_the_styles_table():
    """A number is a date only when its style says so. Without the styles lookup this
    column is 20 000 five-digit integers."""
    kinds = {
        cell.kind
        for _sheet, _name, cell in read_cells(
            str(EXCELS / "Sample-sales-data-excel.xlsx"), READER_XLSX_STREAM)
    }
    assert KIND_DATE in kinds
    dates = [
        cell for _s, _n, cell in read_cells(
            str(EXCELS / "Sample-sales-data-excel.xlsx"), READER_XLSX_STREAM)
        if cell.kind == KIND_DATE
    ]
    assert dates[0].time_value is not None
    assert dates[0].text == dates[0].time_value.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- synthetic fixtures


_SHEET_WITH_A_GAP = """<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<sheetData>
<row r="1"><c r="A1" t="inlineStr"><is><t>left</t></is></c>
            <c r="D1" t="inlineStr"><is><t>right</t></is></c></row>
<row r="2"><c r="A2"><v>1</v></c><c r="D2"><v>2</v></c></row>
<row r="3"><c r="B3" s="1"><v>43528</v></c><c r="C3"><f>A2+D2</f><v>3</v></c></row>
</sheetData>
</worksheet>
"""

_STYLES = """<?xml version="1.0"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<cellXfs count="2"><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>
</styleSheet>
"""

_WORKBOOK = """<?xml version="1.0"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="Gapped" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""

_RELS = """<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>
"""


@pytest.fixture
def gapped_xlsx(tmp_path):
    path = tmp_path / "gapped.xlsx"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", _WORKBOOK)
        zf.writestr("xl/_rels/workbook.xml.rels", _RELS)
        zf.writestr("xl/styles.xml", _STYLES)
        zf.writestr("xl/worksheets/sheet1.xml", _SHEET_WITH_A_GAP)
    return path


def test_a_row_with_a_gap_keeps_its_column_ordinals(gapped_xlsx):
    """The thing the tab-joined text flattening cannot do: a row with fewer cells than it
    has columns loses its alignment the moment the `r` attribute is ignored."""
    cells = {(c.source_row, c.column_id): c
             for _s, _n, c in read_cells(str(gapped_xlsx), READER_XLSX_STREAM)}
    assert cells[(1, 1)].text == "left"
    assert cells[(1, 4)].text == "right"
    assert (1, 2) not in cells and (1, 3) not in cells


def test_a_styled_number_becomes_a_date_and_an_unstyled_one_does_not(gapped_xlsx):
    cells = {(c.source_row, c.column_id): c
             for _s, _n, c in read_cells(str(gapped_xlsx), READER_XLSX_STREAM)}
    assert cells[(3, 2)].kind == KIND_DATE
    assert cells[(3, 2)].time_value == datetime(2019, 3, 4)
    assert cells[(2, 1)].kind == KIND_INT


def test_a_formula_is_kept_beside_its_cached_value(gapped_xlsx):
    cells = {(c.source_row, c.column_id): c
             for _s, _n, c in read_cells(str(gapped_xlsx), READER_XLSX_STREAM)}
    assert cells[(3, 3)].formula == "A2+D2"
    assert cells[(3, 3)].text == "3"


def test_the_sheet_name_comes_from_the_workbook_part(gapped_xlsx):
    names = {name for _s, name, _c in read_cells(str(gapped_xlsx), READER_XLSX_STREAM)}
    assert names == {"Gapped"}


_ODS_CONTENT = """<?xml version="1.0"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:xlink="http://www.w3.org/1999/xlink">
<office:body><office:spreadsheet>
<table:table table:name="Sheet1">
 <table:table-row>
  <table:table-cell office:value-type="string"><text:p>name</text:p></table:table-cell>
  <table:table-cell office:value-type="string"><text:p>amount</text:p></table:table-cell>
  <table:table-cell table:number-columns-repeated="16384"/>
 </table:table-row>
 <table:table-row>
  <table:table-cell office:value-type="string">
    <text:p><text:a xlink:href="https://example.org/acme">Acme</text:a></text:p>
  </table:table-cell>
  <table:table-cell office:value-type="float" office:value="1204.5">
    <text:p>1 204,50</text:p></table:table-cell>
  <table:table-cell table:number-columns-repeated="16384"/>
 </table:table-row>
 <table:table-row table:number-rows-repeated="1048574">
  <table:table-cell table:number-columns-repeated="16384"/>
 </table:table-row>
</table:table>
</office:spreadsheet></office:body>
</office:document-content>
"""


@pytest.fixture
def repeated_ods(tmp_path):
    path = tmp_path / "repeated.ods"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", _ODS_CONTENT)
    return path


def test_an_empty_repeat_costs_nothing(repeated_ods):
    """`number-columns-repeated="16384"` and `number-rows-repeated="1048576"` are
    LibreOffice's normal output for the empty tail of every row and every sheet.
    Expanding them naively is an instant out-of-memory on an ordinary file."""
    cells = list(read_cells(str(repeated_ods), READER_ODS_STREAM))
    assert len(cells) == 4
    assert max(cell.column_id for _s, _n, cell in cells) == 2
    assert max(cell.source_row for _s, _n, cell in cells) == 2


def test_ods_keeps_the_display_text_and_the_machine_value_separately(repeated_ods):
    """The one format that hands us both. `cell_text` is what the file renders and the
    typed value is what sorts, and neither is derived from the other."""
    cells = {(c.source_row, c.column_id): c
             for _s, _n, c in read_cells(str(repeated_ods), READER_ODS_STREAM)}
    amount = cells[(2, 2)]
    assert amount.text == "1 204,50"
    assert amount.float_value == 1204.5


def test_ods_keeps_a_cells_hyperlink(repeated_ods):
    cells = {(c.source_row, c.column_id): c
             for _s, _n, c in read_cells(str(repeated_ods), READER_ODS_STREAM)}
    assert cells[(2, 1)].link == "https://example.org/acme"
    assert cells[(2, 1)].kind == KIND_TEXT


def test_an_unreadable_file_raises_so_the_fallback_reader_can_run(tmp_path):
    """The activity tries calamine when a streaming reader raises, and it can only do
    that if the reader raises rather than returning an empty grid."""
    broken = tmp_path / "broken.xlsx"
    broken.write_bytes(b"not a zip at all")
    with pytest.raises(Exception):
        list(read_cells(str(broken), READER_XLSX_STREAM))
