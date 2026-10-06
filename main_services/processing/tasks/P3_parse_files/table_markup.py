"""Read HTML, MHTML, and SpreadsheetML workbook cells."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterator
from tasks.P3_parse_files.table_formats import KIND_FLOAT, KIND_INT, KIND_TEXT
from tasks.P3_parse_files.table_readers import RawCell, infer_delimited_kind
MIME_HTML_TABLE = 'application/x-hoover-html-table'
MIME_SPREADSHEETML = 'application/vnd.ms-spreadsheetml'
MIME_MHTML_WORKBOOK = 'application/x-hoover-mhtml-workbook'
READER_HTML = 'html_table'
SPREADSHEET_EXTENSIONS = ('.xls', '.xlsx', '.xlsm', '.xlsb')
SNIFF_READ_SIZE = 64 * 1024
_OFFICE_EXCEL = re.compile(b'urn:schemas-microsoft-com:office:excel|<meta[^>]+progid[^>]*excel\\.sheet', re.IGNORECASE)
_MHT_WORKBOOK = re.compile(b'^X-Document-Type:\\s*Workbook', re.IGNORECASE | re.MULTILINE)
_SPREADSHEETML = re.compile(b'urn:schemas-microsoft-com:office:spreadsheet', re.IGNORECASE)
_PREAMBLE = re.compile(b'\\A(?:\\s+|<!doctype[^>]*>|<!--.*?-->|<html\\b[^>]*>|<head\\b.*?</head\\s*>|<body\\b[^>]*>|<meta\\b[^>]*>|<style\\b.*?</style\\s*>|<title\\b.*?</title\\s*>)*', re.IGNORECASE | re.DOTALL)

@dataclass
class HtmlTableSniff:
    mime_type: str
    rule: str

def sniff_html_table(data: bytes, path: str) -> HtmlTableSniff | None:
    if not path.lower().endswith(SPREADSHEET_EXTENSIONS):
        return None
    head = data[:SNIFF_READ_SIZE]
    for bom in (b'\xef\xbb\xbf',):
        if head.startswith(bom):
            head = head[len(bom):]
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        codec = 'utf-16-le' if head[:2] == b'\xff\xfe' else 'utf-16-be'
        head = head[2:].decode(codec, errors='replace').encode('utf-8')
    head = head.lstrip()
    if head[:13].upper() == b'MIME-VERSION:' and _MHT_WORKBOOK.search(head[:4096]):
        return HtmlTableSniff(MIME_MHTML_WORKBOOK, 'mhtml_workbook')
    if not head.startswith(b'<'):
        return None
    if head.startswith(b'<?xml'):
        if _SPREADSHEETML.search(head):
            return HtmlTableSniff(MIME_SPREADSHEETML, 'spreadsheetml')
        return None
    if _OFFICE_EXCEL.search(head):
        return HtmlTableSniff(MIME_HTML_TABLE, 'office_namespace')
    rest = head[_PREAMBLE.match(head).end():]
    if rest[:6].lower() == b'<table':
        return HtmlTableSniff(MIME_HTML_TABLE, 'leading_table')
    return None

def sniff_html_table_path(path: str) -> HtmlTableSniff | None:
    with open(path, 'rb') as handle:
        return sniff_html_table(handle.read(SNIFF_READ_SIZE), path)
_BLOCK_BREAKS = {'br', 'p', 'div', 'li'}
_META_CHARSET = re.compile(b'charset\\s*=\\s*[\\"\']?([A-Za-z0-9_\\-]+)', re.IGNORECASE)

def _decode(data: bytes) -> str:
    if data.startswith(b'\xef\xbb\xbf'):
        return data[3:].decode('utf-8', errors='replace')
    if data[:2] == b'\xff\xfe':
        return data[2:].decode('utf-16-le', errors='replace')
    if data[:2] == b'\xfe\xff':
        return data[2:].decode('utf-16-be', errors='replace')
    match = _META_CHARSET.search(data[:4096])
    if match:
        try:
            return data.decode(match.group(1).decode('ascii'), errors='replace')
        except LookupError:
            pass
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('windows-1252', errors='replace')

def _span(value: str | None) -> int:
    try:
        return max(1, min(int(value or 1), 1000))
    except ValueError:
        return 1

class _TableParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: list[tuple[int, int, int, str, dict]] = []
        self.sheet_names: list[str] = []
        self._in_sheet_name = False
        self._depth = 0
        self._table = -1
        self._row = 0
        self._column = 0
        self._occupied: dict[tuple[int, int], bool] = {}
        self._cell: list[str] | None = None
        self._cell_attrs: dict = {}
        self._cell_pos = (0, 0)

    def handle_comment(self, data: str) -> None:
        for name in re.findall('<x:Name>(.*?)</x:Name>', data, re.IGNORECASE | re.DOTALL):
            self.sheet_names.append(name.strip())

    def handle_starttag(self, tag: str, attrs) -> None:
        attributes = {k.lower(): v if v is not None else '' for k, v in attrs}
        if tag == 'table':
            self._depth += 1
            if self._depth == 1:
                self._table += 1
                self._row = 0
                self._occupied = {}
            return
        if self._depth != 1:
            if self._cell is not None and tag in _BLOCK_BREAKS | {'tr'}:
                self._cell.append('\n')
            return
        if tag == 'tr':
            self._close_cell()
            self._row += 1
            self._column = 0
        elif tag in ('td', 'th'):
            self._close_cell()
            if self._row == 0:
                self._row = 1
            column = self._column + 1
            while self._occupied.get((self._row, column)):
                column += 1
            colspan, rowspan = (_span(attributes.get('colspan')), _span(attributes.get('rowspan')))
            for r in range(self._row, self._row + rowspan):
                for c in range(column, column + colspan):
                    self._occupied[r, c] = True
            self._column = column + colspan - 1
            self._cell = []
            self._cell_attrs = attributes
            self._cell_pos = (self._row, column)
        elif tag in _BLOCK_BREAKS and self._cell is not None:
            self._cell.append('\n')

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_BREAKS and self._cell is not None:
            self._cell.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag == 'table':
            if self._depth == 1:
                self._close_cell()
            self._depth = max(0, self._depth - 1)
        elif self._depth == 1 and tag in ('td', 'th', 'tr'):
            self._close_cell()

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _close_cell(self) -> None:
        if self._cell is None:
            return
        raw = ''.join(self._cell)
        lines = [re.sub('[ \\t\\r\\n\\xa0]+', ' ', line).strip() for line in raw.split('\n')]
        text = '\n'.join((line for line in lines if line))
        row, column = self._cell_pos
        if text:
            self.cells.append((self._table, row, column, text, self._cell_attrs))
        self._cell = None

def _typed(text: str, attrs: dict) -> RawCell:
    style = attrs.get('style', '').replace(' ', '').lower()
    if 'x:str' in attrs or 'mso-number-format:\\@' in style or 'mso-number-format:"\\@"' in style:
        return RawCell(0, 0, KIND_TEXT, text)
    number = attrs.get('x:num')
    if number:
        try:
            value = float(number)
        except ValueError:
            value = None
        if value is not None:
            if value.is_integer() and abs(value) < 2 ** 53:
                return RawCell(0, 0, KIND_INT, text, int_value=int(value), float_value=value)
            return RawCell(0, 0, KIND_FLOAT, text, float_value=value)
    kind, int_value, float_value, time_value = infer_delimited_kind(text)
    return RawCell(0, 0, kind, text, int_value=int_value, float_value=float_value, time_value=time_value)

def read_html_table_cells(path: str, *, max_bytes: int=256 * 1024 * 1024) -> Iterator[tuple[int, str, RawCell]]:
    with open(path, 'rb') as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f'HTML table file larger than {max_bytes} bytes')
    parser = _TableParser()
    parser.feed(_decode(data))
    parser.close()
    parser._close_cell()
    for table, row, column, text, attrs in parser.cells:
        name = parser.sheet_names[table] if table < len(parser.sheet_names) else f'Sheet{table + 1}'
        cell = _typed(text, attrs)
        cell.source_row = row
        cell.column_id = column
        yield (table, name, cell)
_SHEET_PART = re.compile('sheet(\\d+)\\.html?$', re.IGNORECASE)

def read_mhtml_workbook_cells(path: str, *, max_bytes: int=256 * 1024 * 1024) -> Iterator[tuple[int, str, RawCell]]:
    import email
    import email.policy
    with open(path, 'rb') as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f'MHTML file larger than {max_bytes} bytes')
    message = email.message_from_bytes(data, policy=email.policy.compat32)
    names: list[str] = []
    sheets: list[tuple[int, str]] = []
    for part in message.walk():
        if part.get_content_type() != 'text/html':
            continue
        payload = part.get_payload(decode=True) or b''
        charset = part.get_content_charset() or ''
        try:
            text = payload.decode(charset) if charset else _decode(payload)
        except (LookupError, UnicodeDecodeError):
            text = _decode(payload)
        match = _SHEET_PART.search(part.get('Content-Location', ''))
        if match:
            sheets.append((int(match.group(1)), text))
        elif not names:
            names = re.findall('<x:Name>(.*?)</x:Name>', text, re.IGNORECASE | re.DOTALL)
    for sheet_id, (_number, text) in enumerate(sorted(sheets)):
        parser = _TableParser()
        parser.feed(text)
        parser.close()
        parser._close_cell()
        name = names[sheet_id].strip() if sheet_id < len(names) else f'Sheet{sheet_id + 1}'
        for _table, row, column, cell_text, attrs in parser.cells:
            cell = _typed(cell_text, attrs)
            cell.source_row = row
            cell.column_id = column
            yield (sheet_id, name, cell)

import os
import re
from datetime import datetime
from typing import Iterator
from xml.parsers import expat
from tasks.P3_parse_files.table_formats import KIND_BOOL, KIND_DATETIME, KIND_ERROR, KIND_FLOAT, KIND_INT, KIND_TEXT
from tasks.P3_parse_files.table_readers import RawCell
MIME_SPREADSHEETML = 'application/vnd.ms-spreadsheetml'
READER_SPREADSHEETML = 'spreadsheetml'
NS = 'urn:schemas-microsoft-com:office:spreadsheet'
SNIFF_READ_SIZE = 64 * 1024
BLOCK = 1024 * 1024
_PROGID = re.compile(b'<\\?mso-application\\s+progid\\s*=\\s*[\\"\']Excel\\.Sheet[\\"\']', re.IGNORECASE)
_WORKBOOK = re.compile(b'<(?:\\w+:)?Workbook\\b[^>]*urn:schemas-microsoft-com:office:spreadsheet', re.IGNORECASE | re.DOTALL)

def sniff_spreadsheetml(data: bytes) -> str | None:
    head = data[:SNIFF_READ_SIZE]
    if head[:2] in (b'\xff\xfe', b'\xfe\xff'):
        head = head.decode('utf-16', errors='replace').encode('utf-8')
    if head.startswith(b'\xef\xbb\xbf'):
        head = head[3:]
    if not head.lstrip().startswith(b'<'):
        return None
    if _PROGID.search(head) or _WORKBOOK.search(head):
        return MIME_SPREADSHEETML
    return None

def sniff_spreadsheetml_path(path: str) -> str | None:
    with open(path, 'rb') as handle:
        return sniff_spreadsheetml(handle.read(SNIFF_READ_SIZE))

def _spreadsheetml_typed(text: str, data_type: str) -> RawCell:
    data_type = data_type.lower()
    if data_type == 'number':
        try:
            value = float(text)
        except ValueError:
            return RawCell(0, 0, KIND_TEXT, text)
        if value.is_integer() and abs(value) < 2 ** 53 and ('e' not in text.lower()):
            return RawCell(0, 0, KIND_INT, text, int_value=int(value), float_value=value)
        return RawCell(0, 0, KIND_FLOAT, text, float_value=value)
    if data_type == 'datetime':
        try:
            moment = datetime.fromisoformat(text.rstrip('Z'))
        except ValueError:
            return RawCell(0, 0, KIND_TEXT, text)
        return RawCell(0, 0, KIND_DATETIME, text, time_value=moment)
    if data_type == 'boolean':
        flag = text.strip() in ('1', 'true', 'TRUE')
        return RawCell(0, 0, KIND_BOOL, text, int_value=int(flag))
    if data_type == 'error':
        return RawCell(0, 0, KIND_ERROR, text)
    return RawCell(0, 0, KIND_TEXT, text)

class _Reader:

    def __init__(self) -> None:
        self.ready: list[tuple[int, str, RawCell]] = []
        self.sheet_id = -1
        self.sheet_name = ''
        self.row = 0
        self.column = 0
        self.depth_comment = 0
        self.cell: dict | None = None
        self.text: list[str] | None = None

    @staticmethod
    def _attr(attrs: dict, name: str) -> str:
        return attrs.get(f'{NS} {name}', attrs.get(name, ''))

    def start(self, tag: str, attrs: dict) -> None:
        local = tag.rsplit(' ', 1)[-1]
        if local == 'Worksheet':
            self.sheet_id += 1
            self.sheet_name = self._attr(attrs, 'Name') or f'Sheet{self.sheet_id + 1}'
            self.row = 0
        elif local == 'Row':
            index = self._attr(attrs, 'Index')
            self.row = int(index) if index.isdigit() else self.row + 1
            self.column = 0
        elif local == 'Cell':
            index = self._attr(attrs, 'Index')
            self.column = int(index) if index.isdigit() else self.column + 1
            across = self._attr(attrs, 'MergeAcross')
            self.cell = {'column': self.column, 'type': '', 'text': [], 'formula': self._attr(attrs, 'Formula'), 'link': self._attr(attrs, 'HRef')}
            if across.isdigit():
                self.column += int(across)
        elif local == 'Comment':
            self.depth_comment += 1
        elif local == 'Data' and self.cell is not None and (not self.depth_comment):
            self.cell['type'] = self._attr(attrs, 'Type')
            self.text = self.cell['text']

    def end(self, tag: str) -> None:
        local = tag.rsplit(' ', 1)[-1]
        if local == 'Comment':
            self.depth_comment -= 1
        elif local == 'Data' and (not self.depth_comment):
            self.text = None
        elif local == 'Cell' and self.cell is not None:
            text = ''.join(self.cell['text'])
            if text != '' or self.cell['formula']:
                cell = _spreadsheetml_typed(text, self.cell['type'])
                cell.source_row = max(self.row, 1)
                cell.column_id = self.cell['column']
                cell.formula = self.cell['formula']
                cell.link = self.cell['link']
                self.ready.append((self.sheet_id, self.sheet_name, cell))
            self.cell = None

    def data(self, value: str) -> None:
        if self.text is not None and (not self.depth_comment):
            self.text.append(value)

def _refuse_doctype(*_args) -> None:
    raise ValueError('SpreadsheetML file with a document type declaration')

def read_spreadsheetml_cells(path: str, *, max_bytes: int=256 * 1024 * 1024) -> Iterator[tuple[int, str, RawCell]]:
    reader = _Reader()
    parser = expat.ParserCreate(namespace_separator=' ')
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.data
    parser.StartDoctypeDeclHandler = _refuse_doctype
    parser.EntityDeclHandler = _refuse_doctype
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    read = 0
    with open(path, 'rb') as handle:
        while True:
            block = handle.read(BLOCK)
            read += len(block)
            if read > max_bytes:
                raise ValueError(f'SpreadsheetML file larger than {max_bytes} bytes')
            parser.Parse(block, not block)
            yield from reader.ready
            reader.ready.clear()
            if not block:
                break
