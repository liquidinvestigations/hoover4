"""Which files are tables, which reader opens one, and how much of one we keep.

One definition, three readers
-----------------------------
The MIME set, the caps and the "is this really a table" thresholds live here and nowhere
else, the way `mime_type_mapper._ZIP_BASED_DOCUMENT_MIMES` does for zip-based documents.
The P3 workflow routes on `is_table_mime`, `parse_table` picks its reader with
`table_reader_for`, and the delimited-text sniff shares the thresholds — three callers,
one table, no chance of the routing condition and the reader disagreeing about what a
`.xlsb` is.

The two-family split is the whole design
----------------------------------------
A **binary spreadsheet** — xlsx, xlsm, xltx, xltm, xlam, xlsb, xls, ods, ots — is a table
because of what it is. Somebody opened a spreadsheet application and saved a grid. One
non-empty cell is enough: an almost-empty workbook is a bad table, not a text file.

**Delimited text** — csv, tsv, tab, psv — has no such guarantee. Its bytes are also the
bytes of prose, of an RFC 822 message, of a log file and of a config file, and the cost
of calling one of those a table is that it acquires a grid nobody wants and leaves the
`text` bucket of the file-type facet. So delimited text has to clear a shape threshold:
`MIN_DELIMITED_ROWS` x `MIN_DELIMITED_COLUMNS`, both 2. A single-column list is text. A
single-line file is text. Two rows and two columns is a table.

The threshold is enforced in two places on purpose, and both are needed:

* `sniff_table` applies it (with a much larger line requirement) before any detector is
  allowed to *name* an unnamed file `text/csv`;
* `parse_table` applies it again after reading, because a file named `.csv` by its
  extension never went through the sniff at all.

A binary format skips both and only has to produce `MIN_BINARY_CELLS` cells.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Spreadsheet container formats. Every one of these is a table on the strength of the
#: format itself. Tika, Magika and the extension detector all name them confidently.
BINARY_TABLE_MIMES = frozenset({
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
    "application/vnd.ms-excel.sheet.macroEnabled.12",
    "application/vnd.ms-excel.template.macroEnabled.12",
    "application/vnd.ms-excel.sheet.binary.macroEnabled.12",
    "application/vnd.ms-excel.addin.macroEnabled.12",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet-template",
})

#: Delimited text. The extension detector is usually the only one that knows: every
#: content detector calls these `text/plain`.
DELIMITED_TABLE_MIMES = frozenset({
    "text/csv",
    "application/csv",
    "text/tab-separated-values",
    "application/tab-separated-values",
})

TABLE_MIMES = BINARY_TABLE_MIMES | DELIMITED_TABLE_MIMES

#: Extensions that decide the reader when the MIME set is ambiguous — which it always is
#: for delimited text, and often is for a `.xlsb` that libmagic calls a zip.
_XLSX_EXTENSIONS = frozenset({".xlsx", ".xlsm", ".xltx", ".xltm", ".xlam"})
_XLS_EXTENSIONS = frozenset({".xls", ".xlsb"})
_ODS_EXTENSIONS = frozenset({".ods", ".ots"})
DELIMITED_EXTENSIONS = frozenset({".csv", ".tsv", ".tab", ".psv"})

#: Reader names, stored verbatim in `table_documents.reader` so "the streaming reader
#: never succeeds on real workbooks" is a query rather than a suspicion.
READER_CSV = "csv"
READER_XLSX_STREAM = "xlsx_stream"
READER_ODS_STREAM = "ods_stream"
READER_CALAMINE = "calamine"

#: Bumped when a reader changes what it produces. A claim carrying an older version is
#: not trusted and the document is re-read.
READER_VERSION = 1

#: The cap set. Above any of these the document is stored up to the cap and the cap is
#: recorded in `TruncationRecord` — a cap that is invisible in the UI reads as "this file
#: has 300 columns", which is a lie about the corpus.
#:
#: The numbers are sized for a real open-data export rather than for a mail attachment:
#: an 8-million-row x 22-column crime dataset published as CSV fits inside all four.
MAX_CELLS_PER_DOCUMENT = 300_000_000
MAX_ROWS_PER_SHEET = 10_000_000
MAX_COLUMNS_PER_SHEET = 300
MAX_SHEETS = 100

#: A cell longer than this is stored truncated. Text this long is a document pasted into
#: a cell, and the grid cannot draw it either way.
MAX_CELL_BYTES = 64 * 1024

#: Sample values kept per column, for the column picker's tooltip.
MAX_COLUMN_SAMPLES = 3

#: Distinct values counted per column before the count is reported as approximate.
MAX_COLUMN_DISTINCT = 100_000

#: The shape a delimited-text file must have before it is a table rather than a text
#: file. See the module docstring: this exists to keep prose and mail out.
MIN_DELIMITED_ROWS = 2
MIN_DELIMITED_COLUMNS = 2

#: A spreadsheet only has to contain something.
MIN_BINARY_CELLS = 1

#: The cell kinds. `cell_kind` is a LowCardinality(String) and these are its values.
KIND_TEXT = "text"
KIND_INT = "int"
KIND_FLOAT = "float"
KIND_BOOL = "bool"
KIND_DATE = "date"
KIND_DATETIME = "datetime"
KIND_TIME = "time"
KIND_DURATION = "duration"
KIND_ERROR = "error"

#: Kinds whose column sorts and filters as a number.
NUMERIC_KINDS = frozenset({KIND_INT, KIND_FLOAT})
#: Kinds whose column sorts and filters as an instant.
TEMPORAL_KINDS = frozenset({KIND_DATE, KIND_DATETIME, KIND_TIME})


def is_table_mime(mime_type: str) -> bool:
    """Whether this single MIME type names a self-contained tabular document."""
    return mime_type in TABLE_MIMES


def is_delimited_mime(mime_type: str) -> bool:
    """Whether this MIME names delimited text, which has to clear the shape threshold."""
    return mime_type in DELIMITED_TABLE_MIMES


def _extension(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def table_reader_for(mime_types, path: str) -> str:
    """Which reader opens this file, or `""` when nothing here does.

    The extension wins over the MIME set wherever it is decisive, because the MIME set is
    a union of five disagreeing detectors and a `.xlsb` is `application/zip` to three of
    them. A file with a table MIME and no useful extension falls back to the MIME.
    """
    extension = _extension(path)
    if extension in _XLSX_EXTENSIONS:
        return READER_XLSX_STREAM
    if extension in _XLS_EXTENSIONS:
        return READER_CALAMINE
    if extension in _ODS_EXTENSIONS:
        return READER_ODS_STREAM
    if extension in DELIMITED_EXTENSIONS:
        return READER_CSV

    mimes = {m for m in (mime_types or []) if m}
    if mimes & DELIMITED_TABLE_MIMES:
        return READER_CSV
    if "application/vnd.oasis.opendocument.spreadsheet" in mimes \
            or "application/vnd.oasis.opendocument.spreadsheet-template" in mimes:
        return READER_ODS_STREAM
    if "application/vnd.ms-excel" in mimes \
            or "application/vnd.ms-excel.sheet.binary.macroEnabled.12" in mimes:
        return READER_CALAMINE
    if mimes & BINARY_TABLE_MIMES:
        return READER_XLSX_STREAM
    return ""


def is_delimited_reader(reader: str) -> bool:
    """Whether this reader's output has to clear the 2x2 shape threshold."""
    return reader == READER_CSV


def table_format_for(reader: str, path: str) -> str:
    """The format label stored in `table_documents.table_format`.

    Independent of what the detectors said: it is the reader's own answer, so a `.txt`
    that the sniff named `text/csv` still reports `csv`.
    """
    extension = _extension(path).lstrip(".")
    if reader == READER_CSV:
        return extension if extension in {"csv", "tsv", "tab", "psv"} else "csv"
    if reader == READER_ODS_STREAM:
        return extension if extension in {"ods", "ots"} else "ods"
    if extension:
        return extension
    return "xlsx" if reader == READER_XLSX_STREAM else "xls"


#: The limit names recorded in `TruncationRecord.limits`. They are stable identifiers,
#: not sentences: the UI turns them into a banner and the sentence would not survive
#: translation of the number into the reader's language.
LIMIT_CELLS_PER_DOCUMENT = "cells_per_document"
LIMIT_ROWS_PER_SHEET = "rows_per_sheet"
LIMIT_COLUMNS_PER_SHEET = "columns_per_sheet"
LIMIT_SHEETS = "sheets"
LIMIT_CELL_BYTES = "cell_bytes"

_LIMIT_MAXIMUMS = {
    LIMIT_CELLS_PER_DOCUMENT: MAX_CELLS_PER_DOCUMENT,
    LIMIT_ROWS_PER_SHEET: MAX_ROWS_PER_SHEET,
    LIMIT_COLUMNS_PER_SHEET: MAX_COLUMNS_PER_SHEET,
    LIMIT_SHEETS: MAX_SHEETS,
    LIMIT_CELL_BYTES: MAX_CELL_BYTES,
}

_LIMIT_SENTENCES = {
    LIMIT_CELLS_PER_DOCUMENT: "cells in the document",
    LIMIT_ROWS_PER_SHEET: "rows in a sheet",
    LIMIT_COLUMNS_PER_SHEET: "columns in a sheet",
    LIMIT_SHEETS: "sheets in the document",
    LIMIT_CELL_BYTES: "bytes in a cell",
}


@dataclass
class TruncationRecord:
    """Every cap that fired, in a shape the grid renders as a banner.

    Three parallel lists rather than a JSON blob or a Map: the two runtimes that read
    this have to agree on the container type, and parallel `Array(String)` /
    `Array(UInt64)` columns are the shape neither of them can get subtly wrong. Index i
    of each list describes the same event.
    """

    #: Stable limit identifiers, from the `LIMIT_*` constants above.
    limits: list[str] = field(default_factory=list)
    #: The maximum that limit allows, so the banner can say what the ceiling was.
    maximums: list[int] = field(default_factory=list)
    #: The sheet the cap fired on, or `""` for a document-wide cap.
    sheets: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return bool(self.limits)

    def record(self, limit: str, sheet: str = "") -> None:
        """Note that `limit` fired, once per (limit, sheet) pair."""
        for existing_limit, existing_sheet in zip(self.limits, self.sheets):
            if existing_limit == limit and existing_sheet == sheet:
                return
        self.limits.append(limit)
        self.maximums.append(_LIMIT_MAXIMUMS[limit])
        self.sheets.append(sheet)

    def reason(self) -> str:
        """One human sentence per cap, for the Metadata tab and the logs."""
        parts = []
        for limit, maximum, sheet in zip(self.limits, self.maximums, self.sheets):
            what = _LIMIT_SENTENCES.get(limit, limit)
            where = f" of sheet {sheet}" if sheet else ""
            parts.append(f"stopped at the maximum of {maximum} {what}{where}")
        return "; ".join(parts)


def column_letter(column_id: int) -> str:
    """Spreadsheet column label for a 1-based ordinal: 1 is A, 27 is AA."""
    if column_id < 1:
        return ""
    letters = ""
    while column_id:
        column_id, remainder = divmod(column_id - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def column_index(letters: str) -> int:
    """Inverse of `column_letter`. `"AB"` is 28, and it is the only correct source of a
    column index in an XLSX row — a row with a gap has fewer `<c>` elements than it has
    columns."""
    index = 0
    for character in letters:
        if not character.isalpha():
            break
        index = index * 26 + (ord(character.upper()) - ord("A") + 1)
    return index
