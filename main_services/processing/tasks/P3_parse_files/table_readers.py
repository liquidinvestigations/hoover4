"""Turning a tabular file into a stream of cells, one format at a time.

Every reader here is a generator of `(sheet_id, sheet_name, RawCell)` triples in
document order, and none of them accumulates a sheet in memory. The caps live in the
*consumer* (`parse_table`), which is what makes it impossible for a reader to be the
thing that runs the box out of memory: a reader that hands back too much is stopped by
the consumer closing the generator.

What each reader knows, and what it cannot know
------------------------------------------------
* **CSV/TSV/PSV** carry no types at all, so the typing rules in `infer_delimited_kind`
  are strict and few. They are the only reader whose types are inferred rather than read.
* **XLSX** is streamed with `ET.iterparse` over the zip member, one row resident at a
  time. Its cell hyperlinks live in a `<hyperlinks>` block *after* the cells in the same
  part, so a streaming reader has already emitted the cell by the time it sees the link:
  `cell_link` is therefore always empty for this reader. Formulas are inline (`<f>`) and
  are kept.
* **ODS** carries the display text and the machine value side by side, which is the one
  format that hands us both for free. It also carries hyperlinks inline, so it is the one
  reader that fills `cell_link`.
* **calamine** returns typed Python values and no source text at all, so `cell_text` is
  this reader's own rendering of the value. It has no formulas and no hyperlinks. That is
  the price of reading BIFF and XLSB, and it is why it is not used for XLSX or ODS unless
  the streaming reader raised.

The date traps, both of which are wrong by a day if skipped
------------------------------------------------------------
An XLSX number is a date only when its *style* says so, and the style is an index into
`cellXfs` in `xl/styles.xml` whose `numFmtId` is either a builtin date id or a custom
format code containing an unquoted date letter. Every naive reader gets this wrong and
reports a column of five-digit integers.

The serial-to-date conversion carries Lotus 1-2-3's deliberate leap-year bug: the 1900
system counts a 29th of February 1900 that never existed, so serial 60 has no date and
every serial above it is offset by one against a naive epoch calculation.
"""

from __future__ import annotations

import csv
import logging
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterator, Optional, Sequence
from xml.etree import ElementTree as ET

from tasks.P3_parse_files.parse_office_xml import _local, _shared_strings
from tasks.P3_parse_files.table_formats import (
    KIND_BOOL,
    KIND_DATE,
    KIND_DATETIME,
    KIND_DURATION,
    KIND_ERROR,
    KIND_FLOAT,
    KIND_INT,
    KIND_TEXT,
    KIND_TIME,
    READER_CALAMINE,
    READER_CSV,
    READER_ODS_STREAM,
    READER_XLSX_STREAM,
    column_index,
)

log = logging.getLogger(__name__)

#: Largest `sharedStrings.xml` / `styles.xml` read into memory. Both genuinely have to be
#: resident, unlike a worksheet, so they keep the byte budget the office-XML text
#: extractor uses. A workbook whose string table is larger than this is handed to
#: calamine rather than read as a grid of integers.
MAX_RESIDENT_PART_BYTES = 64 * 1024 * 1024


@dataclass(slots=True)
class RawCell:
    """One non-empty cell, as the file gives it.

    `source_row` is the row number the *file* has, which is what the grid draws in its
    `#` column. The dense `row_id` used for pagination is assigned by the consumer, which
    is the only thing that knows which rows produced cells at all.
    """

    source_row: int
    column_id: int
    kind: str
    text: str
    int_value: Optional[int] = None
    float_value: Optional[float] = None
    time_value: Optional[datetime] = None
    link: str = ""
    formula: str = ""


CellStream = Iterator[tuple[int, str, RawCell]]


# --------------------------------------------------------------------------- typing


_INT_RE = re.compile(r"^[+-]?[0-9]+$")
_FLOAT_RE = re.compile(r"^[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?$")
_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?\s*(Z|[+-]\d{2}:?\d{2})?)?$"
)

_INT64_MIN = -(2 ** 63)
_INT64_MAX = 2 ** 63 - 1


def infer_delimited_kind(text: str) -> tuple[str, Optional[int], Optional[float], Optional[datetime]]:
    """The kind and typed values of one CSV field. Text is the answer whenever in doubt.

    The rules are deliberately few, because a wrong type here is not a cosmetic problem:
    a column filtered on a silently wrong reading of a date is worse than one that cannot
    be filtered at all.

    * an integer must be all digits with an optional sign, must fit Int64, and must not
      have a leading zero -- `007` is an identifier and `01` is a month;
    * a float must use `.` as its separator with no thousands separators, no currency
      symbol and no trailing `%`;
    * a date must be ISO 8601. `03/04/2020` stays text, because nothing in the file says
      whether it is the 3rd of April or the 4th of March;
    * `TRUE`/`FALSE` stay text. A CSV has no booleans, only words.
    """
    stripped = text.strip()
    if not stripped:
        return KIND_TEXT, None, None, None

    if _INT_RE.match(stripped):
        digits = stripped.lstrip("+-")
        if len(digits) > 1 and digits.startswith("0"):
            return KIND_TEXT, None, None, None
        value = int(stripped)
        if _INT64_MIN <= value <= _INT64_MAX:
            # Float64 cannot represent an Int64 above 2^53, and a 19-digit account number
            # in a spreadsheet is an ordinary thing, so cell_int carries the exact value
            # and cell_float carries the sortable approximation of it.
            return KIND_INT, value, float(value), None
        return KIND_TEXT, None, None, None

    if _FLOAT_RE.match(stripped):
        try:
            return KIND_FLOAT, None, float(stripped), None
        except ValueError:
            return KIND_TEXT, None, None, None

    parsed = parse_iso_datetime(stripped)
    if parsed is not None:
        kind = KIND_DATE if len(stripped) == 10 else KIND_DATETIME
        return kind, None, None, parsed

    return KIND_TEXT, None, None, None


def parse_iso_datetime(text: str) -> Optional[datetime]:
    """`YYYY-MM-DD` with an optional time and offset, or None. No other format at all."""
    match = _ISO_RE.match(text)
    if not match:
        return None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    hour = int(match.group(4) or 0)
    minute = int(match.group(5) or 0)
    second = int(match.group(6) or 0)
    micro = int((match.group(7) or "0").ljust(6, "0"))
    try:
        value = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    offset = match.group(8)
    if offset and offset != "Z":
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        value -= sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return value


# ------------------------------------------------------------------ excel date serials

#: Builtin `numFmtId` values that mean a date or a time. Anything outside this set is a
#: date only if its custom format code says so.
BUILTIN_DATE_FORMAT_IDS = frozenset(range(14, 23)) | frozenset({45, 46, 47})

#: Builtin ids that are a time of day with no date part.
BUILTIN_TIME_FORMAT_IDS = frozenset({18, 19, 20, 21, 45, 46, 47})

_FORMAT_LITERAL_RE = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]')


def format_code_is_date(code: str) -> bool:
    """Whether a custom number-format code renders a date or a time.

    Quoted literals, escaped characters and `[Red]`-style condition blocks are stripped
    first: a currency format of `"$"#,##0.00` contains a `d` in nobody's calendar.
    """
    body = _FORMAT_LITERAL_RE.sub("", code)
    return any(character in body for character in "ymdhs")


def excel_serial_to_datetime(serial: float, date1904: bool = False) -> Optional[datetime]:
    """A spreadsheet date serial as an instant, or None when the serial has no date.

    The 1900 system carries Lotus 1-2-3's deliberate leap-year bug: it counts a
    29th of February 1900, which did not exist. Serial 60 is that day and therefore has
    no answer; serials above it are one greater than a naive epoch calculation would
    give, and serials below it are not. Skipping this is a silent off-by-one-day across
    every date in every workbook written before 1900-03-01 is irrelevant -- which is to
    say across every date above serial 60, which is all of them.
    """
    if date1904:
        return datetime(1904, 1, 1) + timedelta(days=serial)
    if serial == 60:
        return None
    epoch = datetime(1899, 12, 30) if serial > 60 else datetime(1899, 12, 31)
    return epoch + timedelta(days=serial)


def _render_number(value: float) -> str:
    """A number as text, without the `.0` an integral float would otherwise carry."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def _typed_from_number(value: float) -> tuple[str, Optional[int], Optional[float]]:
    if value == int(value) and _INT64_MIN <= value <= _INT64_MAX:
        return KIND_INT, int(value), value
    return KIND_FLOAT, None, value


# ------------------------------------------------------------------------------- csv


#: Codecs we refuse to believe from `file --mime-encoding`, because they name the absence
#: of an answer rather than an encoding.
_UNUSABLE_ENCODINGS = frozenset({"unknown-8bit", "binary", "", "us-ascii/binary"})


def resolve_text_encoding(encodings: Sequence[str]) -> str:
    """Which codec to decode a delimited file with. Never fails, never raises.

    `file_types.mime_encodings` already records what `file -i` said per detector, so the
    reader consults the record before guessing. `latin-1` is the last resort precisely
    because it decodes any byte sequence: a table with a few mojibake cells is far better
    than no table.
    """
    for candidate in encodings or ():
        name = (candidate or "").strip().lower()
        if name in _UNUSABLE_ENCODINGS:
            continue
        try:
            "".encode(name)
        except LookupError:
            continue
        return name
    return "utf-8"


def read_csv_cells(path: str, *, encodings: Sequence[str] = (), delimiter: str = "",
                   on_progress: Optional[Callable[[str, int], None]] = None) -> CellStream:
    """One sheet, `sheet_id = 0`, name `""`, cells typed by `infer_delimited_kind`."""
    from tasks.P3_parse_files.sniff_table import sniff_table_path

    if not delimiter:
        sniff = sniff_table_path(path)
        if sniff is not None:
            delimiter = sniff.delimiter
        else:
            lowered = path.lower()
            delimiter = "\t" if lowered.endswith((".tsv", ".tab")) else \
                "|" if lowered.endswith(".psv") else ","

    encoding = resolve_text_encoding(encodings)
    handle = open(path, "r", encoding=encoding, errors="replace", newline="")
    try:
        first = handle.read(1)
        if first != "﻿":
            handle.seek(0)
        reader = csv.reader(handle, delimiter=delimiter)
        for source_row, fields in enumerate(reader, start=1):
            if on_progress and source_row % 1000 == 0:
                on_progress("", source_row)
            for column_id, raw in enumerate(fields, start=1):
                if not raw:
                    continue
                kind, int_value, float_value, time_value = infer_delimited_kind(raw)
                yield 0, "", RawCell(
                    source_row=source_row,
                    column_id=column_id,
                    kind=kind,
                    text=raw,
                    int_value=int_value,
                    float_value=float_value,
                    time_value=time_value,
                )
    except UnicodeDecodeError:
        # `errors="replace"` makes this all but unreachable, and "all but" is not "never"
        # for a codec whose decoder rejects a byte outright.
        log.warning("[P3] table csv reader could not decode %s as %s", path, encoding)
    finally:
        handle.close()


# ------------------------------------------------------------------------------ xlsx


def _read_resident(zf: zipfile.ZipFile, name: str) -> Optional[bytes]:
    try:
        with zf.open(name) as handle:
            data = handle.read(MAX_RESIDENT_PART_BYTES + 1)
    except (KeyError, OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError):
        return None
    if len(data) > MAX_RESIDENT_PART_BYTES:
        return None
    if b"<!ENTITY" in data:
        # ElementTree expands internal entities in-process. No spreadsheet format
        # declares any, so refusing is cheaper and more correct than bounding it.
        return None
    return data


def _xlsx_styles(zf: zipfile.ZipFile) -> list[tuple[bool, bool]]:
    """Per `cellXfs` entry: `(is a date, is a time of day)`.

    A cell's `s="12"` indexes this list. Anything not in it is not a date, which is the
    correct answer for a workbook with no styles part at all.
    """
    data = _read_resident(zf, "xl/styles.xml")
    if data is None:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []

    custom: dict[int, str] = {}
    for element in root.iter():
        if _local(element.tag) != "numFmt":
            continue
        try:
            custom[int(element.get("numFmtId", "-1"))] = element.get("formatCode", "")
        except ValueError:
            continue

    styles: list[tuple[bool, bool]] = []
    for container in root:
        if _local(container.tag) != "cellXfs":
            continue
        for xf in container:
            if _local(xf.tag) != "xf":
                continue
            try:
                format_id = int(xf.get("numFmtId", "0"))
            except ValueError:
                format_id = 0
            if format_id in BUILTIN_DATE_FORMAT_IDS:
                styles.append((True, format_id in BUILTIN_TIME_FORMAT_IDS))
                continue
            code = custom.get(format_id, "")
            if code and format_code_is_date(code):
                body = _FORMAT_LITERAL_RE.sub("", code)
                styles.append((True, not any(c in body for c in "yd")))
                continue
            styles.append((False, False))
    return styles


def _xlsx_sheet_names(zf: zipfile.ZipFile) -> tuple[list[tuple[str, str]], bool]:
    """`[(sheet name, relationship id)]` in workbook order, and whether the 1904 epoch is
    in force."""
    data = _read_resident(zf, "xl/workbook.xml")
    if data is None:
        return [], False
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return [], False
    date1904 = False
    sheets: list[tuple[str, str]] = []
    for element in root.iter():
        tag = _local(element.tag)
        if tag == "workbookPr":
            date1904 = element.get("date1904", "0") in ("1", "true")
        elif tag == "sheet":
            rel = ""
            for key, value in element.attrib.items():
                if _local(key) == "id":
                    rel = value
            sheets.append((element.get("name", ""), rel))
    return sheets, date1904


def _xlsx_relationships(zf: zipfile.ZipFile) -> dict[str, str]:
    data = _read_resident(zf, "xl/_rels/workbook.xml.rels")
    if data is None:
        return {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    targets: dict[str, str] = {}
    for element in root:
        if _local(element.tag) != "Relationship":
            continue
        target = element.get("Target", "")
        if target.startswith("/"):
            target = target.lstrip("/")
        elif not target.startswith("xl/"):
            target = "xl/" + target
        targets[element.get("Id", "")] = target
    return targets


def _cell_reference_row(reference: str) -> int:
    digits = "".join(character for character in reference if character.isdigit())
    return int(digits) if digits else 0


def read_xlsx_cells(path: str, *,
                    on_progress: Optional[Callable[[str, int], None]] = None) -> CellStream:
    """Stream an OOXML workbook, one row resident at a time.

    Three things this does that the office-XML *text* extractor does not, and every one
    of them is why a tab-joined flattening is not a grid: the member is decompressed as
    it is read rather than held whole, the `r` attribute is parsed so a row with a gap
    keeps its column ordinals, and a number is resolved against the styles table so a
    date is a date rather than a five-digit integer.
    """
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            data = _read_resident(zf, "xl/sharedStrings.xml")
            if data is None:
                # An unresolvable string table would make every text cell an integer
                # index. calamine reads the whole workbook instead.
                raise ValueError("xl/sharedStrings.xml is too large or unreadable to resolve")
            try:
                shared = _shared_strings(data)
            except ET.ParseError as exc:
                raise ValueError(f"xl/sharedStrings.xml is malformed: {exc}") from exc

        styles = _xlsx_styles(zf)
        declared, date1904 = _xlsx_sheet_names(zf)
        targets = _xlsx_relationships(zf)

        ordered: list[tuple[str, str]] = []
        for name, rel in declared:
            part = targets.get(rel, "")
            if part in names:
                ordered.append((name, part))
        if not ordered:
            ordered = [(f"Sheet{index + 1}", part) for index, part in
                       enumerate(sorted(n for n in names
                                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)))]
        if not ordered:
            raise ValueError("no worksheet parts in the workbook")

        for sheet_id, (sheet_name, part) in enumerate(ordered):
            yield from _xlsx_sheet(zf, part, sheet_id, sheet_name, shared, styles,
                                   date1904, on_progress)


def _xlsx_sheet(zf, part, sheet_id, sheet_name, shared, styles, date1904,
                on_progress) -> CellStream:
    with zf.open(part) as handle:
        container = None
        source_row = 0
        for event, element in ET.iterparse(handle, events=("start", "end")):
            tag = _local(element.tag)
            if event == "start":
                if tag == "sheetData":
                    container = element
                continue
            if tag != "row":
                continue
            declared_row = element.get("r")
            source_row = int(declared_row) if declared_row and declared_row.isdigit() \
                else source_row + 1
            if on_progress and source_row % 1000 == 0:
                on_progress(sheet_name, source_row)
            for cell in element:
                if _local(cell.tag) != "c":
                    continue
                raw_cell = _xlsx_cell(cell, source_row, shared, styles, date1904)
                if raw_cell is not None:
                    yield sheet_id, sheet_name, raw_cell
            element.clear()
            if container is not None:
                # The parser keeps every completed row attached to `sheetData`, so
                # clearing the row alone still grows one empty element per row. Emptying
                # the parent is what makes peak memory one row rather than one sheet.
                container.clear()


def _xlsx_cell(cell, source_row: int, shared, styles, date1904) -> Optional[RawCell]:
    reference = cell.get("r", "")
    column_id = column_index(reference)
    if column_id <= 0:
        return None
    cell_type = cell.get("t")

    formula = ""
    value_text = ""
    inline: list[str] = []
    for child in cell:
        child_tag = _local(child.tag)
        if child_tag == "f":
            formula = child.text or ""
        elif child_tag == "v":
            value_text = child.text or ""
        elif child_tag == "is":
            inline.append("".join(el.text or "" for el in child.iter()
                                  if _local(el.tag) == "t"))

    if cell_type == "inlineStr":
        text = "".join(inline)
        return RawCell(source_row, column_id, KIND_TEXT, text, formula=formula) if text else None
    if cell_type == "s":
        try:
            text = shared[int(value_text)]
        except (ValueError, IndexError):
            text = ""
        return RawCell(source_row, column_id, KIND_TEXT, text, formula=formula) if text else None
    if cell_type == "str":
        return RawCell(source_row, column_id, KIND_TEXT, value_text,
                       formula=formula) if value_text else None
    if cell_type == "e":
        return RawCell(source_row, column_id, KIND_ERROR, value_text,
                       formula=formula) if value_text else None
    if cell_type == "b":
        text = "TRUE" if value_text == "1" else "FALSE"
        return RawCell(source_row, column_id, KIND_BOOL, text,
                       int_value=1 if value_text == "1" else 0,
                       float_value=1.0 if value_text == "1" else 0.0, formula=formula)

    if not value_text:
        return None
    try:
        number = float(value_text)
    except ValueError:
        return RawCell(source_row, column_id, KIND_TEXT, value_text, formula=formula)

    style_index = cell.get("s")
    is_date = is_time = False
    if style_index is not None and style_index.isdigit():
        index = int(style_index)
        if index < len(styles):
            is_date, is_time = styles[index]

    if is_date:
        moment = excel_serial_to_datetime(number, date1904)
        if moment is not None:
            if is_time:
                kind, text = KIND_TIME, moment.strftime("%H:%M:%S")
            elif moment.time() == time(0, 0):
                kind, text = KIND_DATE, moment.strftime("%Y-%m-%d")
            else:
                kind, text = KIND_DATETIME, moment.strftime("%Y-%m-%d %H:%M:%S")
            return RawCell(source_row, column_id, kind, text, time_value=moment,
                           float_value=number, formula=formula)

    kind, int_value, float_value = _typed_from_number(number)
    return RawCell(source_row, column_id, kind, _render_number(number),
                   int_value=int_value, float_value=float_value, formula=formula)


# ------------------------------------------------------------------------------- ods


def _ods_repeat(element, attribute: str) -> int:
    for key, value in element.attrib.items():
        if _local(key) == attribute:
            try:
                return max(int(value), 1)
            except ValueError:
                return 1
    return 1


def _ods_attribute(element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return ""


def read_ods_cells(path: str, *,
                   on_progress: Optional[Callable[[str, int], None]] = None) -> CellStream:
    """Stream an OpenDocument spreadsheet's `content.xml`.

    The repeat attributes are the whole difficulty. LibreOffice writes
    `table:number-columns-repeated="16384"` for the trailing empty run of every row and
    `table:number-rows-repeated="1048576"` for the empty tail of every sheet; expanding
    those naively is an instant out-of-memory on an ordinary file. A repeat is expanded
    only for a cell or a row that has content -- an empty repeat merely advances the
    cursor, so the trailing runs cost nothing at all.
    """
    with zipfile.ZipFile(path) as zf:
        if "content.xml" not in set(zf.namelist()):
            raise ValueError("no content.xml in the OpenDocument package")
        with zf.open("content.xml") as handle:
            sheet_id = -1
            sheet_name = ""
            source_row = 0
            container = None
            for event, element in ET.iterparse(handle, events=("start", "end")):
                tag = _local(element.tag)
                if event == "start":
                    if tag == "table":
                        sheet_id += 1
                        sheet_name = _ods_attribute(element, "name")
                        source_row = 0
                        container = element
                    continue
                if tag != "table-row":
                    continue
                repeat = _ods_repeat(element, "number-rows-repeated")
                cells = list(_ods_row(element))
                if not cells:
                    source_row += repeat
                else:
                    # A repeated row WITH content is a real duplicate and is expanded,
                    # but only up to a bound: a 1 048 576-row repeat of one filled row is
                    # a pathological file, not a table.
                    for _ in range(min(repeat, 4096)):
                        source_row += 1
                        if on_progress and source_row % 1000 == 0:
                            on_progress(sheet_name, source_row)
                        for column_id, cell in cells:
                            yield sheet_id, sheet_name, RawCell(
                                source_row=source_row,
                                column_id=column_id,
                                kind=cell.kind,
                                text=cell.text,
                                int_value=cell.int_value,
                                float_value=cell.float_value,
                                time_value=cell.time_value,
                                link=cell.link,
                                formula=cell.formula,
                            )
                    source_row += max(repeat - 4096, 0)
                element.clear()
                if container is not None:
                    container.clear()


def _ods_row(row) -> Iterator[tuple[int, RawCell]]:
    column_id = 0
    for cell in row:
        tag = _local(cell.tag)
        if tag not in ("table-cell", "covered-table-cell"):
            continue
        repeat = _ods_repeat(cell, "number-columns-repeated")
        text = "".join(_ods_text(cell))
        if not text.strip() or tag == "covered-table-cell":
            column_id += repeat
            continue
        link = ""
        for element in cell.iter():
            if _local(element.tag) == "a":
                link = _ods_attribute(element, "href")
                break
        parsed = _ods_typed(cell, text)
        for _ in range(min(repeat, 4096)):
            column_id += 1
            yield column_id, RawCell(
                source_row=0,
                column_id=column_id,
                kind=parsed.kind,
                text=text,
                int_value=parsed.int_value,
                float_value=parsed.float_value,
                time_value=parsed.time_value,
                link=link,
                formula=_ods_attribute(cell, "formula"),
            )
        column_id += max(repeat - 4096, 0)


def _ods_text(cell) -> Iterator[str]:
    """The cell's display text: one `text:p` per line, spans and their tails included."""
    for index, paragraph in enumerate(cell):
        if _local(paragraph.tag) != "p":
            continue
        if index:
            yield "\n"
        for element in paragraph.iter():
            if element is not paragraph and element.text:
                yield element.text
            elif element is paragraph and element.text:
                yield element.text
            if element is not paragraph and element.tail:
                yield element.tail


def _ods_typed(cell, text: str) -> RawCell:
    """The machine value beside the display text, which ODS is the one format to give us."""
    value_type = _ods_attribute(cell, "value-type")
    if value_type in ("float", "percentage", "currency"):
        try:
            number = float(_ods_attribute(cell, "value"))
        except ValueError:
            return RawCell(0, 0, KIND_TEXT, text)
        kind, int_value, float_value = _typed_from_number(number)
        return RawCell(0, 0, kind, text, int_value=int_value, float_value=float_value)
    if value_type == "date":
        moment = parse_iso_datetime(_ods_attribute(cell, "date-value"))
        if moment is None:
            return RawCell(0, 0, KIND_TEXT, text)
        kind = KIND_DATE if moment.time() == time(0, 0) else KIND_DATETIME
        return RawCell(0, 0, kind, text, time_value=moment)
    if value_type == "time":
        return RawCell(0, 0, KIND_DURATION, text)
    if value_type == "boolean":
        raw = _ods_attribute(cell, "boolean-value").lower()
        return RawCell(0, 0, KIND_BOOL, text,
                       int_value=1 if raw == "true" else 0,
                       float_value=1.0 if raw == "true" else 0.0)
    return RawCell(0, 0, KIND_TEXT, text)


# -------------------------------------------------------------------------- calamine


def read_calamine_cells(path: str, *,
                        on_progress: Optional[Callable[[str, int], None]] = None) -> CellStream:
    """Read any format calamine understands: BIFF, XLSB, and XLSX/ODS as a fallback.

    Not a streaming reader -- `iter_rows` decodes the sheet before yielding -- which for
    BIFF is a property of the format rather than a risk: BIFF8 caps a sheet at
    65 536 rows by 256 columns. For XLSB there is no such cap and the consumer's caps are
    what bound it.

    Being a Rust extension, this reader can fail by *panicking* rather than by raising,
    and a `pyo3_runtime.PanicException` derives from BaseException -- an ordinary
    `except Exception` around the call does not see it. The caller catches BaseException
    for exactly this reason.
    """
    from python_calamine import CalamineWorkbook

    workbook = CalamineWorkbook.from_path(path)
    for sheet_id, sheet_name in enumerate(workbook.sheet_names):
        sheet = workbook.get_sheet_by_index(sheet_id)
        start = getattr(sheet, "start", None)
        if start is None:
            # An empty sheet has no used range, and `iter_rows` unwraps that None in Rust
            # and panics the interpreter rather than raising. A workbook with a blank
            # sheet -- a pivot-table template, for instance -- is entirely ordinary, so
            # this guard is the format rather than defensive coding.
            continue
        row_offset, column_offset = start
        for row_index, values in enumerate(sheet.iter_rows()):
            source_row = row_offset + row_index + 1
            if on_progress and source_row % 1000 == 0:
                on_progress(sheet_name, source_row)
            for column_index_, value in enumerate(values):
                cell = _calamine_cell(value)
                if cell is None:
                    continue
                cell.source_row = source_row
                cell.column_id = column_offset + column_index_ + 1
                yield sheet_id, sheet_name, cell


def _calamine_cell(value) -> Optional[RawCell]:
    """A calamine Python value as a cell. `cell_text` is this reader's own rendering.

    calamine hands back a decoded value and never the source text, so unlike every other
    reader here this one cannot promise the cell exactly as the source application draws
    it -- a currency symbol and a thousands separator are gone before we see the value.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return RawCell(0, 0, KIND_BOOL, "TRUE" if value else "FALSE",
                       int_value=1 if value else 0, float_value=1.0 if value else 0.0)
    if isinstance(value, int):
        return RawCell(0, 0, KIND_INT, str(value), int_value=value, float_value=float(value))
    if isinstance(value, float):
        kind, int_value, float_value = _typed_from_number(value)
        return RawCell(0, 0, kind, _render_number(value),
                       int_value=int_value, float_value=float_value)
    if isinstance(value, datetime):
        return RawCell(0, 0, KIND_DATETIME, value.strftime("%Y-%m-%d %H:%M:%S"),
                       time_value=value)
    if isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
        return RawCell(0, 0, KIND_DATE, value.isoformat(), time_value=moment)
    if isinstance(value, time):
        return RawCell(0, 0, KIND_TIME, value.strftime("%H:%M:%S"))
    if isinstance(value, timedelta):
        return RawCell(0, 0, KIND_DURATION, str(value),
                       float_value=value.total_seconds())
    text = str(value)
    return RawCell(0, 0, KIND_TEXT, text) if text.strip() else None


# ------------------------------------------------------------------------- dispatch


def read_cells(path: str, reader: str, *, encodings: Sequence[str] = (),
               on_progress: Optional[Callable[[str, int], None]] = None) -> CellStream:
    """The one entry point: a stream of `(sheet_id, sheet_name, RawCell)` for `reader`."""
    if reader == READER_CSV:
        return read_csv_cells(path, encodings=encodings, on_progress=on_progress)
    if reader == READER_XLSX_STREAM:
        return read_xlsx_cells(path, on_progress=on_progress)
    if reader == READER_ODS_STREAM:
        return read_ods_cells(path, on_progress=on_progress)
    if reader == READER_CALAMINE:
        return read_calamine_cells(path, on_progress=on_progress)
    raise ValueError(f"no table reader named {reader!r}")


def fallback_reader(reader: str) -> str:
    """The reader to try when `reader` raised. calamine reads what the streamers do."""
    if reader in (READER_XLSX_STREAM, READER_ODS_STREAM):
        return READER_CALAMINE
    return ""
