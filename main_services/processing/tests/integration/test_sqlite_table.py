"""Verify the table reader with the stored format samples."""

import os
import pytest
FILE_TYPES = os.path.join(os.environ.get("HOOVER4_TESTDATA", "/testdata"), "file-types")
pytestmark = pytest.mark.skipif(not os.path.isdir(FILE_TYPES), reason="Table samples are not mounted")

import hashlib
import os
import sqlite3
import pytest
from tasks.P3_parse_files.table_sqlite import SqliteLimits, SqliteReport, SqliteTimeLimit, is_sqlite_path, read_sqlite_cells
SQLITE = os.path.join(FILE_TYPES, 'sqlite')

def cells(path, **limits):
    report = SqliteReport()
    out = list(read_sqlite_cells(path, SqliteLimits(**limits), report))
    return (out, report)

def grid(out, sheet):
    return {(c.source_row, c.column_id): c for _sid, name, c in out if name == sheet}

def test_header_is_detected_with_and_without_extension():
    for name in ('contacts-orders.sqlite3', 'many-rows.sqlite3', 'app-data'):
        assert is_sqlite_path(os.path.join(SQLITE, name))
    assert not is_sqlite_path(os.path.join(FILE_TYPES, 'vcard', 'vcard-3.0.vcf'))

def test_tables_then_views_with_header_row_and_blob_marker():
    out, report = cells(os.path.join(SQLITE, 'contacts-orders.sqlite3'))
    assert report.sheets == ['contacts', 'orders', 'order_totals']
    contacts = grid(out, 'contacts')
    assert [contacts[1, c].text for c in range(1, 7)] == ['id', 'name', 'email', 'phone', 'joined', 'photo']
    assert contacts[2, 6].text == '[BLOB 1032 bytes]'
    assert (3, 6) not in contacts
    assert (5, 4) not in contacts
    assert contacts[2, 1].kind == 'int' and contacts[2, 1].int_value == 1
    orders = grid(out, 'orders')
    assert orders[2, 5].kind == 'float' and orders[2, 5].float_value == 2.5
    totals = grid(out, 'order_totals')
    assert totals[1, 3].text == 'total'
    assert sum((1 for r, c in totals if r > 1 and c == 1)) == 10
    assert not any(('PNG' in c.text for _s, _n, c in out))

def test_row_cap_is_reported():
    out, report = cells(os.path.join(SQLITE, 'many-rows.sqlite3'), max_rows=5000)
    rows = {c.source_row for _s, _n, c in out}
    assert max(rows) == 5001
    assert report.truncated_sheets == ['readings']
    out, report = cells(os.path.join(SQLITE, 'many-rows.sqlite3'))
    assert max((c.source_row for _s, _n, c in out)) == 6001
    assert report.truncated_sheets == []

def test_quoted_names_and_empty_tables():
    out, report = cells(os.path.join(SQLITE, 'app-data'))
    assert 'odd name; with quotes' in report.sheets
    odd = grid(out, 'odd name; with quotes')
    assert odd[1, 2].text == 'col"two'
    empty = grid(out, 'empty_table')
    assert list(empty) == [(1, 1)]

def test_open_is_read_only_and_leaves_no_side_files(tmp_path):
    source = os.path.join(SQLITE, 'contacts-orders.sqlite3')
    copy = tmp_path / 'db'
    copy.write_bytes(open(source, 'rb').read())
    before = hashlib.sha256(copy.read_bytes()).hexdigest()
    cells(str(copy))
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before
    assert sorted((p.name for p in tmp_path.iterdir())) == ['db']

def test_time_limit_stops_an_endless_view(tmp_path):
    path = tmp_path / 'loop.sqlite3'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE t (a)')
    db.execute('CREATE VIEW endless AS WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT count(*) FROM c')
    db.commit()
    db.close()
    with pytest.raises(SqliteTimeLimit):
        cells(str(path), time_limit_seconds=0.5)

def test_size_limit_and_wrong_header(tmp_path):
    with pytest.raises(ValueError):
        cells(os.path.join(SQLITE, 'many-rows.sqlite3'), max_bytes=1000)
    other = tmp_path / 'x.sqlite3'
    other.write_bytes(b'not a database' * 100)
    with pytest.raises(ValueError):
        cells(str(other))

def test_virtual_tables_are_skipped(tmp_path):
    path = tmp_path / 'fts.sqlite3'
    db = sqlite3.connect(path)
    try:
        db.execute('CREATE VIRTUAL TABLE notes USING fts5(body)')
    except sqlite3.OperationalError:
        pytest.skip('fts5 not built into this SQLite')
    db.execute("INSERT INTO notes VALUES ('hello')")
    db.commit()
    db.close()
    out, report = cells(str(path))
    assert 'notes' not in report.sheets
    assert any((s.startswith('notes: virtual table') for s in report.skipped))
