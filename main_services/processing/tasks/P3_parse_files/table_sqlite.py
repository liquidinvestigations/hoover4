"""Read SQLite tables and views without changing the input file."""

from __future__ import annotations

import os
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Iterator
from tasks.P3_parse_files.table_formats import KIND_FLOAT, KIND_INT, KIND_TEXT
from tasks.P3_parse_files.table_readers import RawCell
SQLITE_MAGIC = b'SQLite format 3\x00'
MIME_SQLITE = 'application/vnd.sqlite3'
SQLITE_MIMES = frozenset({MIME_SQLITE, 'application/x-sqlite3'})
READER_SQLITE = 'sqlite'
MAX_CELL_BYTES = 64 * 1024

def is_sqlite(data: bytes) -> bool:
    return data[:16] == SQLITE_MAGIC

def is_sqlite_path(path: str) -> bool:
    with open(path, 'rb') as handle:
        return is_sqlite(handle.read(16))

@dataclass
class SqliteLimits:
    max_bytes: int = 2 * 1024 ** 3
    max_rows: int = 1000000
    max_sheets: int = 100
    time_limit_seconds: float = 300.0

@dataclass
class SqliteReport:
    sheets: list[str] = field(default_factory=list)
    truncated_sheets: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

class SqliteTimeLimit(Exception):
    pass
_ALLOWED_PRAGMAS = {'table_xinfo', 'table_info'}

def _authorizer(action, arg1, arg2, db_name, trigger):
    if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or '').lower() in _ALLOWED_PRAGMAS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY

def open_readonly(path: str, limits: SqliteLimits) -> sqlite3.Connection:
    size = os.path.getsize(path)
    if size > limits.max_bytes:
        raise ValueError(f'SQLite file of {size} bytes is larger than {limits.max_bytes}')
    if not is_sqlite_path(path):
        raise ValueError('not a SQLite 3 file')
    uri = 'file:' + urllib.parse.quote(os.path.abspath(path)) + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True, check_same_thread=False, isolation_level=None)
    connection.enable_load_extension(False)
    connection.execute('PRAGMA trusted_schema = OFF')
    connection.execute('PRAGMA query_only = ON')
    connection.text_factory = lambda b: b.decode('utf-8', errors='replace')
    connection.set_authorizer(_authorizer)
    return connection

def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'

def _cell(value) -> RawCell | None:
    if value is None:
        return None
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        return RawCell(0, 0, KIND_INT, str(value), int_value=value, float_value=float(value))
    if isinstance(value, float):
        text = repr(value)
        return RawCell(0, 0, KIND_FLOAT, text, float_value=value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return RawCell(0, 0, KIND_TEXT, f'[BLOB {len(value)} bytes]', is_blob=True)
    text = str(value)
    if not text:
        return None
    encoded = text.encode('utf-8')
    if len(encoded) > MAX_CELL_BYTES:
        text = encoded[:MAX_CELL_BYTES].decode('utf-8', errors='ignore')
    return RawCell(0, 0, KIND_TEXT, text)

def read_sqlite_cells(path: str, limits: SqliteLimits | None=None, report: SqliteReport | None=None, *, on_progress=None) -> Iterator[tuple[int, str, RawCell]]:
    from tasks.P3_parse_files.table_formats import MAX_ROWS_PER_SHEET, MAX_SHEETS
    limits = limits or SqliteLimits(max_rows=MAX_ROWS_PER_SHEET + 1, max_sheets=MAX_SHEETS + 1)
    report = report if report is not None else SqliteReport()
    connection = open_readonly(path, limits)
    deadline = time.monotonic() + limits.time_limit_seconds

    def progress() -> int:
        return 1 if time.monotonic() > deadline else 0
    connection.set_progress_handler(progress, 10000)
    try:
        try:
            objects = connection.execute("SELECT type, name, sql FROM sqlite_schema WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' ORDER BY type = 'view', rowid").fetchall()
        except sqlite3.OperationalError as error:
            if 'interrupted' in str(error):
                raise SqliteTimeLimit('time limit while reading the schema') from error
            raise
        sheet_id = -1
        for kind, name, sql in objects:
            if kind == 'table' and (sql or '').lstrip().upper().startswith('CREATE VIRTUAL'):
                report.skipped.append(f'{name}: virtual table')
                continue
            if sheet_id + 1 >= limits.max_sheets:
                report.skipped.append(f'{name}: sheet limit')
                continue
            try:
                columns = [row[1] for row in connection.execute(f'PRAGMA table_xinfo({_quote(name)})') if len(row) < 7 or row[6] in (0, 2, 3)]
                cursor = connection.execute(f'SELECT * FROM {_quote(name)}')
            except sqlite3.OperationalError as error:
                if 'interrupted' in str(error):
                    raise SqliteTimeLimit(f'time limit in {name}') from error
                report.skipped.append(f'{name}: {error}')
                continue
            sheet_id += 1
            report.sheets.append(name)
            if not columns and cursor.description:
                columns = [d[0] for d in cursor.description]
            for column_id, column in enumerate(columns, start=1):
                yield (sheet_id, name, RawCell(1, column_id, KIND_TEXT, column))
            try:
                for row_index, values in enumerate(cursor, start=1):
                    if on_progress:
                        on_progress(name, row_index)
                    if row_index > limits.max_rows:
                        report.truncated_sheets.append(name)
                        break
                    for column_id, value in enumerate(values, start=1):
                        cell = _cell(value)
                        if cell is None:
                            continue
                        cell.source_row = row_index + 1
                        cell.column_id = column_id
                        yield (sheet_id, name, cell)
            except sqlite3.OperationalError as error:
                if 'interrupted' in str(error):
                    raise SqliteTimeLimit(f'time limit in {name}') from error
                raise
            finally:
                cursor.close()
    finally:
        connection.close()
