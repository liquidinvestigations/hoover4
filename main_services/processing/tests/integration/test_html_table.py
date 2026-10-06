"""Verify the table reader with the stored format samples."""

import os
import pytest
FILE_TYPES = os.path.join(os.environ.get("HOOVER4_TESTDATA", "/testdata/hoover-testdata/data"), "file-types")
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.path.isdir(FILE_TYPES), reason="Table samples are not mounted")]

from tasks.P3_parse_files.table_markup import MIME_HTML_TABLE, MIME_SPREADSHEETML, read_html_table_cells, sniff_html_table, sniff_html_table_path
HTML_XLS = os.path.join(FILE_TYPES, 'html-xls')

def sample(name):
    return os.path.join(HTML_XLS, name)

def grid(path):
    return {(sheet, c.source_row, c.column_id): c for sid, sheet, c in read_html_table_cells(path)}

def html_xls_samples():
    if not os.path.isdir(HTML_XLS):
        return []
    return sorted((n for n in os.listdir(HTML_XLS) if n.lower().endswith(('.xls', '.xlsx'))))

@pytest.mark.parametrize('name', html_xls_samples())
def test_every_sample_is_detected(name):
    sniff = sniff_html_table_path(sample(name))
    assert sniff is not None
    assert sniff.mime_type in (MIME_HTML_TABLE, MIME_SPREADSHEETML)

@pytest.mark.parametrize('name', html_xls_samples())
def test_calamine_cannot_read_them(name):
    calamine = pytest.importorskip('python_calamine')
    with pytest.raises(Exception):
        calamine.CalamineWorkbook.from_path(sample(name))

def test_rules():
    table = b'<table border=1>\r\n<tr><td>a</td><td>b</td></tr></table>'
    assert sniff_html_table(table, 'x.xls').rule == 'leading_table'
    assert sniff_html_table(b'\xef\xbb\xbf  ' + table, 'X.XLS').rule == 'leading_table'
    assert sniff_html_table(b'<html><head><title>t</title></head><body>' + table, 'x.xlsx').rule == 'leading_table'
    office = b'<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel"><body><p>x</p>' + table
    assert sniff_html_table(office, 'x.xls').rule == 'office_namespace'
    assert sniff_html_table(table, 'x.html') is None
    assert sniff_html_table(table, 'x') is None
    assert sniff_html_table(b'<html><body><p>Report</p>' + table, 'x.xls') is None
    assert sniff_html_table(bytes.fromhex('d0cf11e0a1b11ae1') + b'\x00' * 504, 'x.xls') is None
    assert sniff_html_table(b'PK\x03\x04' + b'\x00' * 100, 'x.xlsx') is None
    assert sniff_html_table(b"<?xml version='1.0'?><svg/>", 'x.xls') is None

def test_report_fragment_grid():
    cells = grid(sample('report-fragment.xls'))
    assert cells['Sheet1', 1, 1].text == 'Monthly case list'
    assert ('Sheet1', 1, 2) not in cells
    assert [cells['Sheet1', 2, c].text for c in range(1, 6)] == ['Case', 'Date', 'Officer', 'Amount', 'Closed']
    assert cells['Sheet1', 3, 2].kind == 'date'
    assert cells['Sheet1', 3, 4].kind == 'float'
    assert cells['Sheet1', 4, 4].kind == 'int'
    assert cells['Sheet1', 5, 4].kind == 'text'
    assert cells['Sheet1', 6, 3].text == 'D. Dale & E. Eden'
    assert cells['Sheet1', 7, 2].text == 'first line\nsecond line'
    assert ('Sheet1', 6, 2) not in cells

def test_office_export_sheet_names_and_encoding():
    cells = grid(sample('excel-web-page.xls'))
    assert {sheet for sheet, _r, _c in cells} == {'Cases'}
    assert cells['Cases', 6, 2].text == 'Ünïcode — test'
    cells = grid(sample('web-export-two-tables.xlsx'))
    assert {sheet for sheet, _r, _c in cells} == {'Cases', 'Sheet2'}

def test_spans_and_nested_tables(tmp_path):
    path = tmp_path / 't.xls'
    path.write_bytes(b'<table><tr><td rowspan=2>A</td><td>B</td><td>C</td></tr><tr><td>D</td><td>E<table><tr><td>inner</td></tr></table></td></tr><tr><td x:str>007</td><td x:num="1234.5">1,234.50</td></tr></table>')
    cells = grid(str(path))
    assert cells['Sheet1', 2, 2].text == 'D'
    assert cells['Sheet1', 2, 3].text == 'E\ninner'
    assert cells['Sheet1', 3, 1].kind == 'text'
    assert cells['Sheet1', 3, 2].float_value == 1234.5

def test_online_samples_when_present():
    online = os.path.join(HTML_XLS, 'online')
    if not os.path.isdir(online):
        pytest.skip('no online samples')
    for name in os.listdir(online):
        path = os.path.join(online, name)
        sniff = sniff_html_table_path(path)
        assert sniff is not None, name
        if sniff.mime_type == MIME_HTML_TABLE:
            assert len(grid(path)) >= 2, name

def test_excel_single_file_web_page():
    from tasks.P3_parse_files.table_markup import MIME_MHTML_WORKBOOK, read_mhtml_workbook_cells
    path = os.path.join(HTML_XLS, 'online', 'xls2xlsx-Dates.xls')
    if not os.path.exists(path):
        pytest.skip('no online samples')
    assert sniff_html_table_path(path).mime_type == MIME_MHTML_WORKBOOK
    cells = list(read_mhtml_workbook_cells(path))
    assert {name for _sid, name, _c in cells} == {'Sheet1'}
    first = {(c.source_row, c.column_id): c.text for _s, _n, c in cells}
    assert first[1, 1] == 'Date\nformats: General'
    assert len(cells) > 50

def test_online_office_export_reads_as_a_grid():
    path = os.path.join(HTML_XLS, 'online', 'xls2xlsx-report.xls')
    if not os.path.exists(path):
        pytest.skip('no online samples')
    cells = grid(path)
    assert len(cells) > 2000
    assert cells['NORMAL005', 1, 1].text.startswith('Date Report Generated')
