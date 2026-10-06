"""Verify the table reader with the stored format samples."""

import os
import pytest
FILE_TYPES = os.path.join(os.environ.get("HOOVER4_TESTDATA", "/testdata/hoover-testdata/data"), "file-types")
pytestmark = [pytest.mark.integration,
              pytest.mark.skipif(not os.path.isdir(FILE_TYPES), reason="Table samples are not mounted")]

from tasks.P3_parse_files.table_markup import MIME_SPREADSHEETML, read_spreadsheetml_cells, sniff_spreadsheetml, sniff_spreadsheetml_path
SML = os.path.join(FILE_TYPES, 'spreadsheetml')
ONLINE = os.path.join(SML, 'online')

def grid(path):
    return {(sheet, c.source_row, c.column_id): c for _sid, sheet, c in read_spreadsheetml_cells(path)}

def online_samples():
    return sorted(os.listdir(ONLINE)) if os.path.isdir(ONLINE) else []

@pytest.mark.parametrize('name', ['synthetic-workbook.xml', 'synthetic-workbook-saved-as.xls'])
def test_synthetic_workbook_is_detected_by_content(name):
    assert sniff_spreadsheetml_path(os.path.join(SML, name)) == MIME_SPREADSHEETML

def test_html_and_plain_xml_are_not_spreadsheetml():
    assert sniff_spreadsheetml(b'<table border=1><tr><td>1</td></tr></table>') is None
    assert sniff_spreadsheetml(b'<?xml version="1.0"?><root xmlns="urn:example"/>') is None
    assert sniff_spreadsheetml(b'BEGIN:VCARD\r\nVERSION:3.0\r\n') is None

def test_synthetic_workbook_cells():
    cells = grid(os.path.join(SML, 'synthetic-workbook.xml'))
    assert cells['Orders', 1, 1].text == 'Order'
    assert cells['Orders', 2, 1].kind == 'int' and cells['Orders', 2, 1].int_value == 1001
    assert cells['Orders', 2, 2].text == 'Example Trading Ltd'
    assert cells['Orders', 2, 3].kind == 'float'
    assert cells['Orders', 2, 4].kind == 'datetime'
    assert cells['Orders', 2, 5].kind == 'bool'
    assert cells['Orders', 3, 2].text == 'Sample Imports'
    assert cells['Orders', 3, 2].link == 'https://example.org/customer/2'
    assert ('Orders', 3, 3) not in cells
    assert cells['Orders', 3, 4].kind == 'datetime'
    assert cells['Orders', 3, 5].text == '0'
    assert cells['Orders', 6, 1].text == 'Total'
    assert cells['Orders', 6, 3].formula.startswith('=SUM')
    assert cells['Orders', 6, 4].kind == 'error'
    assert cells['Notes', 1, 1].text == 'Second sheet'

def test_a_document_type_declaration_is_refused():
    with pytest.raises(ValueError):
        list(read_spreadsheetml_cells(os.path.join(SML, 'doctype-entities.xml')))

@pytest.mark.parametrize('name', online_samples())
def test_every_public_sample_is_detected_and_read(name):
    path = os.path.join(ONLINE, name)
    assert sniff_spreadsheetml_path(path) == MIME_SPREADSHEETML
    cells = list(read_spreadsheetml_cells(path))
    assert cells, name
    assert all((c.source_row >= 1 and c.column_id >= 1 for _s, _n, c in cells))

def test_merged_cells_sample_keeps_columns():
    cells = grid(os.path.join(ONLINE, 'libreoffice-merged-cells.xml'))
    assert len(cells) > 0
    positions = [(s, c.source_row, c.column_id) for _sid, s, c in read_spreadsheetml_cells(os.path.join(ONLINE, 'libreoffice-merged-cells.xml'))]
    assert len(positions) == len(set(positions))
