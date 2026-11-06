"""Read table cells and store accepted grids.

Delimited inputs must meet the minimum table shape before any write.
Readers with a fallback store accepted batches in a temporary Arrow file.
Only a successful reader writes those batches to ClickHouse.

Each parse writes a new generation. The cells, sheets and columns of a parse carry its
generation number, and the `ok` manifest row that names the generation is the last
write. Readers read only the generation of the manifest, so an interrupted parse never
shows cells of two parses, and old cells inside the bounds of a new table stay
invisible. The generation is collection-wide for a hash, because the cells are shared by
every dataset of the collection that holds the hash. Another dataset keeps reading its
own manifest generation until its own parse or the dedup copy moves it. The sweep
`sweep_orphan_table_cells` retires owned, published generations without manifest references.
Writing generations and legacy generations without ownership records remain stored.

A parse without a table writes an `empty` manifest, so the earlier table of the hash
stops being visible for the dataset.
"""

from __future__ import annotations

import logging
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional

from temporalio import activity
from temporalio.exceptions import CancelledError
from asyncio import CancelledError as AsyncCancelledError

from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.task_timing import SkippedOutcome

#: Manifest status of a file that no reader opens. A new `READER_VERSION` reads it again.
TABLE_UNREADABLE = "unreadable"
from tasks.P3_parse_files.batch_runner import (
    BatchFile, BatchResult, StageBatchParams, run_batch, try_budget_seconds,
)
from tasks.P3_parse_files.table_formats import (
    MAX_CELL_BYTES,
    MAX_CELLS_PER_DOCUMENT,
    MAX_COLUMN_DISTINCT,
    MAX_COLUMN_SAMPLES,
    MAX_COLUMNS_PER_SHEET,
    MAX_ROWS_PER_SHEET,
    MAX_SHEETS,
    MIN_BINARY_CELLS,
    MIN_DELIMITED_COLUMNS,
    MIN_DELIMITED_ROWS,
    HEADER_AMBIGUOUS,
    HEADER_BASIS_FORMAT,
    HEADER_BASIS_HEURISTIC,
    HEADER_ESTABLISHED,
    NUMERIC_KINDS,
    READER_JSON,
    READER_VERSION,
    TEMPORAL_KINDS,
    KIND_TEXT,
    LIMIT_CELL_BYTES,
    LIMIT_CELLS_PER_DOCUMENT,
    LIMIT_COLUMNS_PER_SHEET,
    LIMIT_ROWS_PER_SHEET,
    LIMIT_SHEETS,
    TruncationRecord,
    column_letter,
    has_json_evidence,
    json_grammar,
    is_delimited_reader,
    table_format_for,
    table_reader_for,
)

log = logging.getLogger(__name__)

#: Exceptions that are the caller's business rather than the file's, and must never be
#: turned into a `failed` manifest row.
#:
#: Everything else -- including a `BaseException` -- is data. `python_calamine` is a pyo3
#: binding, and a panic inside it surfaces as a `PanicException`, which derives from
#: BaseException and is invisible to an ordinary `except Exception`. Catching only
#: `Exception` meant a workbook with a blank sheet killed the activity, consumed three
#: retries and left a `parsing` row behind on a file that would never parse.
_NOT_THE_FILES_FAULT = (KeyboardInterrupt, SystemExit, GeneratorExit, CancelledError, AsyncCancelledError)


#: Cells per ClickHouse insert. Large enough that a million-cell sheet is a few hundred
#: round trips, small enough that a batch is a few megabytes of Python objects.
INSERT_BATCH_CELLS = 50_000

#: Distinct values that the collector keeps across all columns of one document. A wide
#: table can otherwise keep up to 1000 x MAX_COLUMN_DISTINCT strings. A column that
#: reaches the budget reports its distinct count as approximate.
MAX_DOCUMENT_DISTINCT = 2_000_000

#: Manifest status of a parse that found no table.
STATUS_EMPTY = "empty"


@dataclass
class ParseTableParams:
    collectionname: str
    collection_dataset: str
    file_hash: str
    file_path: str
    timeout_seconds: int
    #: What the detectors said, so the reader is picked from the same MIME set the
    #: workflow routed on rather than from the extension alone.
    mime_types: list[str] | None = None
    #: `file_types.mime_encodings`, so a delimited file is decoded with the recorded
    #: codec instead of a guess.
    mime_encodings: list[str] | None = None
    op_id: str = ""
    file_names: list[str] = field(default_factory=list)
    sniff_mime_type: str = ""
    file_mime_type: str = ""


@dataclass
class _ColumnStats:
    """What one column looked like, accumulated as its cells stream past."""

    kinds: Counter = None  # type: ignore[assignment]
    header: str = ""
    non_empty: int = 0
    distinct: set = None  # type: ignore[assignment]
    distinct_overflow: bool = False
    samples: list = None  # type: ignore[assignment]
    bounds: dict = None  # type: ignore[assignment]
    min_text: str = ""
    max_text: str = ""
    #: The cell of row 1 and its stored text, kept until `_Collector.settle_headers`
    #: decides whether row 1 is the header or the first data row.
    first: Any = None
    first_text: str = ""

    def __post_init__(self) -> None:
        self.kinds = Counter()
        self.distinct = set()
        self.samples = []
        self.bounds = {}


@dataclass
class _SheetStats:
    name: str
    row_count: int = 0
    column_count: int = 0
    cell_count: int = 0
    min_source_row: int = 0
    max_source_row: int = 0
    header_row: int = 0
    #: How row 1 reads: `table_sheets.header_state`, `header_basis` and `header_candidates`.
    #: `header_row` is the display choice among the candidates.
    header_state: str = HEADER_ESTABLISHED
    header_basis: str = HEADER_BASIS_FORMAT
    header_candidates: list = None  # type: ignore[assignment]
    truncated: bool = False
    columns: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.columns = {}
        self.header_candidates = []


def _sort_key(cell) -> Any:
    if cell.float_value is not None:
        return cell.float_value
    if cell.time_value is not None:
        return cell.time_value
    return None


def _column_type(kinds: Counter) -> str:
    """The type a column sorts and filters as: its most common kind, text on a tie.

    Text is the tie-breaker rather than the numeric type because a column the UI calls
    numeric offers a range filter, and a range filter over a column that is half text is
    a control that silently hides rows.
    """
    if not kinds:
        return KIND_TEXT
    ordered = sorted(kinds.items(), key=lambda item: (-item[1], item[0]))
    if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
        return KIND_TEXT
    return ordered[0][0]


def _uniform_kind(stats: _ColumnStats) -> str:
    """The one kind of every non-empty data cell of a column, or empty when they differ."""
    return next(iter(stats.kinds)) if len(stats.kinds) == 1 else ""


def _digits(value: float) -> int:
    return len(str(int(abs(value))))


def first_row_is_data(sheet: _SheetStats) -> bool:
    """Whether row 1 of a delimited sheet is a data row and not a header.

    A delimited file states no header. A header labels numbers with text, so row 1 is the
    header when a column whose data cells are all numbers or all dates has a text cell in
    row 1. Row 1 is data when no column has such a label, and at least one such column has
    a row 1 cell of the same kind: a number with as many integer digits as the smallest or
    the largest number below it, or a date. A run of consecutive integers across the
    columns of row 1, such as 2019, 2020 and 2021, is a header of periods. A sheet of text
    columns only keeps row 1 as its header, because its cells cannot show the difference.
    """
    agreeing: list[float] = []
    for stats in sheet.columns.values():
        kind = _uniform_kind(stats)
        if kind not in NUMERIC_KINDS and kind not in TEMPORAL_KINDS:
            continue
        first = stats.first
        if first is None or not stats.first_text.strip():
            continue
        if first.kind == KIND_TEXT:
            return False
        if first.kind != kind:
            continue
        if kind in TEMPORAL_KINDS:
            agreeing.append(float("nan"))
            continue
        bounds = stats.bounds.get("number")
        if bounds and first.float_value is not None and _digits(first.float_value) in (
                _digits(bounds[0]), _digits(bounds[2])):
            agreeing.append(first.float_value)
    numbers = sorted(v for v in agreeing if v == v)
    periods = (len(numbers) >= 2 and all(float(v).is_integer() for v in numbers)
               and all(b - a == 1 for a, b in zip(numbers, numbers[1:])))
    return bool(agreeing) and not periods


def first_row_labels_typed_data(sheet: _SheetStats) -> bool:
    """Whether row 1 of a delimited sheet is a header by its cells: every non-empty cell of
    row 1 is text, and at least one of them is above a column whose other cells are all
    numbers or all dates.

    A label above typed data is the one shape that only a header gives. A text row above
    text rows, a row of numbers, and a row of years above numbers can each be a header or a
    data row, so none of them establishes a reading.
    """
    labelled = False
    for stats in sheet.columns.values():
        first = stats.first
        if first is None or not stats.first_text.strip():
            continue
        if first.kind != KIND_TEXT:
            return False
        kinds = set(stats.kinds)
        if kinds and (kinds <= NUMERIC_KINDS or kinds <= TEMPORAL_KINDS):
            labelled = True
    return labelled


def header_reading(sheet: _SheetStats, delimited: bool) -> tuple[str, str, list[int]]:
    """`(state, basis, candidates)` of row 1 of a sheet, while row 1 is still its header.

    A workbook, a markup table and a database table read row 1 as the header by the
    convention of their format, which is established. A delimited sheet states no header.
    Its row 1 is an established header when it labels typed data
    (`first_row_labels_typed_data`). Every other delimited sheet keeps both readings:
    candidate 0 reads row 1 as data, and candidate 1 reads it as the header.
    """
    if not delimited:
        return HEADER_ESTABLISHED, HEADER_BASIS_FORMAT, [sheet.header_row]
    if sheet.row_count >= 2 and first_row_labels_typed_data(sheet):
        return HEADER_ESTABLISHED, HEADER_BASIS_HEURISTIC, [1]
    return HEADER_AMBIGUOUS, HEADER_BASIS_HEURISTIC, [0, 1]


def _add_body_cell(stats: _ColumnStats, cell, text: str, first: bool = False) -> None:
    """Count one data cell in the statistics of its column. `first` puts its sample before
    the samples of the later rows."""
    stats.kinds[cell.kind] += 1
    stats.non_empty += 1
    if first:
        stats.samples = [text] + stats.samples[:MAX_COLUMN_SAMPLES - 1]
    elif len(stats.samples) < MAX_COLUMN_SAMPLES:
        stats.samples.append(text)
    if not stats.distinct_overflow:
        stats.distinct.add(text)
        if len(stats.distinct) > MAX_COLUMN_DISTINCT:
            stats.distinct_overflow = True
            stats.distinct.clear()
    key = _sort_key(cell)
    if key is None:
        if not stats.min_text or text < stats.min_text:
            stats.min_text = text
        if text > stats.max_text:
            stats.max_text = text
    else:
        family = "number" if cell.float_value is not None else "time"
        bounds = stats.bounds.get(family)
        if bounds is None:
            stats.bounds[family] = [key, text, key, text]
        else:
            if key < bounds[0]:
                bounds[0:2] = [key, text]
            if key > bounds[2]:
                bounds[2:4] = [key, text]


class _Collector:
    """Collect accepted cells within shared limits.

    Readers with a fallback use a temporary Arrow file.
    """

    def __init__(self, params: ParseTableParams, reader: str):
        self.params = params
        self.reader = reader
        self.truncation = TruncationRecord()
        self.sheets: dict[int, _SheetStats] = {}
        self.cell_count = 0
        self.stored_bytes = 0
        self.batch: list[tuple] = []
        self.rows: list[tuple] = []
        self._current_sheet = -1
        self._current_source_row = -1
        self._row_id = 0
        self._done = False
        self.parsing_started = False
        #: The generation that this parse writes, and whether the dataset already has an
        #: `ok` manifest, which the `parsing` row must not replace.
        self.generation = 0
        self.published = False
        self.distinct_total = 0
        self.spool = None
        self.spool_writer = None
        from tasks.P3_parse_files.table_text import TableText
        self.text = TableText() if reader == "sqlite" else None

    def consume(self, stream: Iterable, client) -> None:
        try:
            for sheet_id, sheet_name, cell in stream:
                if self._done or not self._accept(sheet_id, sheet_name, cell, client):
                    break
            self._flush(client, final=True)
        finally:
            close = getattr(stream, "close", None)
            if close:
                close()

    def _accept(self, sheet_id: int, sheet_name: str, cell, client) -> bool:
        if sheet_id not in self.sheets:
            if len(self.sheets) >= MAX_SHEETS:
                self.truncation.record(LIMIT_SHEETS)
                self._done = True
                return False
            self.sheets[sheet_id] = _SheetStats(name=sheet_name)
        sheet = self.sheets[sheet_id]

        if sheet_id != self._current_sheet:
            self._current_sheet = sheet_id
            self._current_source_row = -1
            self._row_id = 0
        if cell.source_row != self._current_source_row:
            if self._row_id >= MAX_ROWS_PER_SHEET:
                self.truncation.record(LIMIT_ROWS_PER_SHEET, sheet.name)
                sheet.truncated = True
                # Skip the rest of this sheet, but keep reading the next one.
                self._current_source_row = cell.source_row
                return True
            self._current_source_row = cell.source_row
            self._row_id += 1
            sheet.row_count = self._row_id
            if sheet.min_source_row == 0:
                sheet.min_source_row = cell.source_row
            sheet.max_source_row = cell.source_row
        elif self._row_id > MAX_ROWS_PER_SHEET:
            return True

        if cell.column_id > MAX_COLUMNS_PER_SHEET:
            self.truncation.record(LIMIT_COLUMNS_PER_SHEET, sheet.name)
            sheet.truncated = True
            return True
        if self.cell_count >= MAX_CELLS_PER_DOCUMENT:
            self.truncation.record(LIMIT_CELLS_PER_DOCUMENT)
            self._done = True
            return False

        text = cell.text
        encoded = text.encode("utf-8", "replace")
        if len(encoded) > MAX_CELL_BYTES:
            text = encoded[:MAX_CELL_BYTES].decode("utf-8", "ignore")
            self.truncation.record(LIMIT_CELL_BYTES, sheet.name)
            sheet.truncated = True

        self.cell_count += 1
        self.stored_bytes += len(encoded)
        sheet.cell_count += 1
        sheet.column_count = max(sheet.column_count, cell.column_id)

        stats = sheet.columns.get(cell.column_id)
        if stats is None:
            stats = sheet.columns[cell.column_id] = _ColumnStats()
        self._observe(sheet, stats, self._row_id, cell, text)

        if self.text is not None:
            self.text.add(sheet_id, sheet.name, cell, text)

        self.batch.append((
            self.params.file_hash, sheet_id, cell.column_id, self._row_id,
            cell.source_row, cell.kind, text, cell.int_value, cell.float_value,
            cell.time_value, cell.link, cell.formula,
        ))
        if len(self.batch) >= INSERT_BATCH_CELLS:
            if not self.meets_threshold():
                self._done = True
                return False
            self._flush(client)
        return True

    def _observe(self, sheet: _SheetStats, stats: _ColumnStats, row_id: int, cell,
                 text: str) -> None:
        # The first row that produces cells is the header row, and its text is the header
        # of every column it touches. A delimited sheet can change this decision at its
        # end (`settle_headers`). Another sheet whose first row is data gets headers that
        # are data, which is what a spreadsheet application shows too.
        if row_id == 1:
            sheet.header_row = 1
            stats.header = text
            stats.first, stats.first_text = cell, text
            return
        self._add(stats, cell, text)

    def _add(self, stats: _ColumnStats, cell, text: str, first: bool = False) -> None:
        """`_add_body_cell` within the document budget of distinct values."""
        if not stats.distinct_overflow and self.distinct_total >= MAX_DOCUMENT_DISTINCT:
            self.distinct_total -= len(stats.distinct)
            stats.distinct_overflow = True
            stats.distinct.clear()
        before = len(stats.distinct)
        _add_body_cell(stats, cell, text, first=first)
        self.distinct_total += len(stats.distinct) - before

    def settle_headers(self) -> None:
        """Record the readings of row 1 of each sheet (`header_reading`), then read row 1 of
        a delimited sheet as data when its cells have the kinds of the rows below it
        (`first_row_is_data`). That choice is the display choice of the website grid. Every
        stored row stays stored either way."""
        delimited = is_delimited_reader(self.reader)
        for sheet in self.sheets.values():
            sheet.header_state, sheet.header_basis, sheet.header_candidates = header_reading(sheet, delimited)
        if not delimited:
            return
        for sheet in self.sheets.values():
            if sheet.header_row != 1 or sheet.row_count < 2 or sheet.header_state == HEADER_ESTABLISHED \
                    or not first_row_is_data(sheet):
                continue
            sheet.header_row = 0
            for stats in sheet.columns.values():
                stats.header = ""
                if stats.first is not None:
                    self._add(stats, stats.first, stats.first_text, first=True)


    def _flush(self, client, *, final=False) -> None:
        if not self.batch or not self.meets_threshold():
            return
        import pyarrow as pa

        from database.clickhouse import insert_parser_arrow

        rows = self.batch
        self.batch = []
        table = pa.table({
            "file_hash": pa.array([r[0] for r in rows], type=pa.string()),
            "sheet_id": pa.array([r[1] for r in rows], type=pa.uint16()),
            "column_id": pa.array([r[2] for r in rows], type=pa.uint32()),
            "row_id": pa.array([r[3] for r in rows], type=pa.uint64()),
            "source_row": pa.array([r[4] for r in rows], type=pa.uint64()),
            "cell_kind": pa.array([r[5] for r in rows], type=pa.string()),
            "cell_text": pa.array([r[6] for r in rows], type=pa.string()),
            "cell_int": pa.array([r[7] for r in rows], type=pa.int64()),
            "cell_float": pa.array([r[8] for r in rows], type=pa.float64()),
            "cell_time": pa.array([r[9] for r in rows], type=pa.timestamp("ms", tz="UTC")),
            "cell_link": pa.array([r[10] for r in rows], type=pa.string()),
            "cell_formula": pa.array([r[11] for r in rows], type=pa.string()),
            "generation": pa.array([self.generation] * len(rows), type=pa.uint32()),
        })
        from tasks.P3_parse_files.table_readers import fallback_reader
        if fallback_reader(self.reader):
            import os
            import tempfile
            if self.spool is None:
                self.spool = tempfile.TemporaryFile(dir=os.path.dirname(os.path.abspath(self.params.file_path)))
                self.spool_writer = pa.ipc.new_file(self.spool, table.schema,
                    options=pa.ipc.IpcWriteOptions(compression="lz4"))
            self.spool_writer.write_table(table)
        else:
            if not final or self.parsing_started:
                self.start_manifest(client)
            insert_parser_arrow(client, "table_cells", table)

    def start_manifest(self, client) -> None:
        if not self.parsing_started:
            self.parsing_started = True
            if self.published:
                # The published table stays readable until this parse publishes.
                return
            _write_manifest(client, self.params, status="parsing", reader=self.reader,
                generation=self.generation,
                table_format=table_format_for(self.reader, (self.params.file_names or [self.params.file_path])[0]),
                durable=True)

    def commit_spool(self, client) -> None:
        if self.spool_writer is None:
            return
        import pyarrow as pa
        from database.clickhouse import insert_parser_arrow
        self.spool_writer.close()
        self.spool_writer = None
        self.spool.seek(0)
        try:
            batches = pa.ipc.open_file(self.spool)
            if self.cell_count >= INSERT_BATCH_CELLS:
                self.start_manifest(client)
            for index in range(batches.num_record_batches):
                insert_parser_arrow(client, "table_cells", pa.Table.from_batches([batches.get_batch(index)]))
        finally:
            self.close()

    def close(self) -> None:
        if self.spool_writer is not None:
            self.spool_writer.close()
            self.spool_writer = None
        if self.spool is not None:
            self.spool.close()
            self.spool = None

    def meets_threshold(self) -> bool:
        """Whether what was read is a table at all. See the module docstring."""
        if not self.sheets:
            return False
        if is_delimited_reader(self.reader):
            return any(sheet.row_count >= MIN_DELIMITED_ROWS
                       and sheet.column_count >= MIN_DELIMITED_COLUMNS
                       for sheet in self.sheets.values())
        return self.cell_count >= MIN_BINARY_CELLS


def _sheet_rows(params: ParseTableParams, collector: _Collector):
    import pyarrow as pa

    ids = sorted(collector.sheets)
    sheets = [collector.sheets[i] for i in ids]
    return pa.table({
        "collection_dataset": pa.array([params.collection_dataset] * len(ids), type=pa.string()),
        "hash": pa.array([params.file_hash] * len(ids), type=pa.string()),
        "sheet_id": pa.array(ids, type=pa.uint16()),
        "name": pa.array([s.name for s in sheets], type=pa.string()),
        "row_count": pa.array([s.row_count for s in sheets], type=pa.uint64()),
        "column_count": pa.array([s.column_count for s in sheets], type=pa.uint32()),
        "min_source_row": pa.array([s.min_source_row for s in sheets], type=pa.uint64()),
        "max_source_row": pa.array([s.max_source_row for s in sheets], type=pa.uint64()),
        "cell_count": pa.array([s.cell_count for s in sheets], type=pa.uint64()),
        "header_row": pa.array([s.header_row for s in sheets], type=pa.uint64()),
        "truncated": pa.array([1 if s.truncated else 0 for s in sheets], type=pa.uint8()),
        "header_state": pa.array([s.header_state for s in sheets], type=pa.string()),
        "header_basis": pa.array([s.header_basis for s in sheets], type=pa.string()),
        "header_candidates": pa.array([s.header_candidates for s in sheets], type=pa.list_(pa.uint64())),
        "generation": pa.array([collector.generation] * len(ids), type=pa.uint32()),
    })


def _column_rows(params: ParseTableParams, collector: _Collector):
    import pyarrow as pa

    sheet_ids: list[int] = []
    column_ids: list[int] = []
    headers: list[str] = []
    letters: list[str] = []
    types: list[str] = []
    kind_names: list[list[str]] = []
    kind_counts: list[list[int]] = []
    non_empty: list[int] = []
    distinct: list[int] = []
    minimums: list[str] = []
    maximums: list[str] = []
    samples: list[list[str]] = []

    for sheet_id in sorted(collector.sheets):
        sheet = collector.sheets[sheet_id]
        for column_id in sorted(sheet.columns):
            stats = sheet.columns[column_id]
            ordered = sorted(stats.kinds.items(), key=lambda item: (-item[1], item[0]))
            column_type = _column_type(stats.kinds)
            if column_type in NUMERIC_KINDS or column_type in TEMPORAL_KINDS:
                family = "number" if column_type in NUMERIC_KINDS else "time"
                bounds = stats.bounds.get(family)
                low = bounds[1] if bounds else ""
                high = bounds[3] if bounds else ""
            else:
                low, high = stats.min_text, stats.max_text
            sheet_ids.append(sheet_id)
            column_ids.append(column_id)
            headers.append(stats.header)
            letters.append(column_letter(column_id))
            types.append(column_type)
            kind_names.append([name for name, _ in ordered])
            kind_counts.append([count for _, count in ordered])
            non_empty.append(stats.non_empty)
            distinct.append(stats.non_empty if stats.distinct_overflow else len(stats.distinct))
            minimums.append(low)
            maximums.append(high)
            samples.append(stats.samples)

    return pa.table({
        "collection_dataset": pa.array([params.collection_dataset] * len(sheet_ids), type=pa.string()),
        "hash": pa.array([params.file_hash] * len(sheet_ids), type=pa.string()),
        "sheet_id": pa.array(sheet_ids, type=pa.uint16()),
        "column_id": pa.array(column_ids, type=pa.uint32()),
        "header": pa.array(headers, type=pa.string()),
        "letter": pa.array(letters, type=pa.string()),
        "column_type": pa.array(types, type=pa.string()),
        "kind_names": pa.array(kind_names, type=pa.list_(pa.string())),
        "kind_counts": pa.array(kind_counts, type=pa.list_(pa.uint64())),
        "non_empty": pa.array(non_empty, type=pa.uint64()),
        "distinct_count": pa.array(distinct, type=pa.uint64()),
        "min_value": pa.array(minimums, type=pa.string()),
        "max_value": pa.array(maximums, type=pa.string()),
        "samples": pa.array(samples, type=pa.list_(pa.string())),
        "generation": pa.array([collector.generation] * len(sheet_ids), type=pa.uint32()),
    })


def _write_manifest(client, params: ParseTableParams, *, status: str, reader: str,
                    table_format: str, sheet_count: int = 0, row_count: int = 0,
                    column_count: int = 0, cell_count: int = 0, stored_bytes: int = 0,
                    truncation: Optional[TruncationRecord] = None, parse_ms: int = 0,
                    parse_error: str = "", durable: bool = False, generation: int = 0) -> None:
    import pyarrow as pa

    from database.clickhouse import insert_parser_arrow, insert_arrow_durable

    truncation = truncation or TruncationRecord()
    table = pa.table({
        "collection_dataset": pa.array([params.collection_dataset], type=pa.string()),
        "hash": pa.array([params.file_hash], type=pa.string()),
        "status": pa.array([status], type=pa.string()),
        "reader": pa.array([reader], type=pa.string()),
        "reader_version": pa.array([READER_VERSION], type=pa.uint16()),
        "table_format": pa.array([table_format], type=pa.string()),
        "sheet_count": pa.array([sheet_count], type=pa.uint16()),
        "row_count": pa.array([row_count], type=pa.uint64()),
        "column_count": pa.array([column_count], type=pa.uint32()),
        "cell_count": pa.array([cell_count], type=pa.uint64()),
        "stored_bytes": pa.array([stored_bytes], type=pa.uint64()),
        "truncated": pa.array([1 if truncation.truncated else 0], type=pa.uint8()),
        "truncated_limits": pa.array([truncation.limits], type=pa.list_(pa.string())),
        "truncated_maximums": pa.array([truncation.maximums], type=pa.list_(pa.uint64())),
        "truncated_sheets": pa.array([truncation.sheets], type=pa.list_(pa.string())),
        "truncated_reason": pa.array([truncation.reason()], type=pa.string()),
        "parse_ms": pa.array([parse_ms], type=pa.uint32()),
        "parse_error": pa.array([parse_error], type=pa.string()),
        "generation": pa.array([generation], type=pa.uint32()),
        "text_digest": pa.array([getattr(params, "_table_text_digest", "")], type=pa.string()),
        "text_page_count": pa.array([getattr(params, "_table_text_count", 0)], type=pa.uint32()),
        "text_complete": pa.array([getattr(params, "_table_text_complete", 0)], type=pa.uint8()),
    })
    if status in ("ok", STATUS_EMPTY):
        from tasks.P3_parse_files.insert_batch import current_batch
        from tasks.P3_parse_files.table_generations import GenerationCommand, send_command
        batch = current_batch()
        if batch is not None:
            batch.flush()
            if batch.index in batch.errors:
                raise batch.errors[batch.index]
            batch.finish_file(batch.index)
        buffer = pa.BufferOutputStream()
        with pa.ipc.new_stream(buffer, table.schema) as stream:
            stream.write_table(table)
        send_command(GenerationCommand(params.collectionname, params.file_hash, "publish",
                                       getattr(params, "_generation_token", ""), generation,
                                       params.op_id, buffer.getvalue().to_pybytes(),
                                       getattr(params, "_expected_column_rows", -1)))
        return
    if status == "failed" and _has_published(client, params):
        return
    writer = insert_arrow_durable if durable else insert_parser_arrow
    writer(client, "table_documents", table)


def _existing_parse(client, file_hash: str, collection_dataset: str = ""):
    """A finished parse of this hash in any dataset of this collection, or None.

    This is the cross-dataset dedup: `table_cells` is keyed by hash alone, so a hash
    another dataset has already read needs a manifest row and nothing else. A corpus with
    the same price list mailed to forty people parses it once.
    """
    rows = client.query("""
        SELECT reader, table_format, sheet_count, row_count, column_count, cell_count,
               stored_bytes, truncated, truncated_limits, truncated_maximums,
               truncated_sheets, truncated_reason, collection_dataset, generation,
               text_digest, text_page_count, text_complete
        FROM table_documents FINAL
        WHERE hash = {h:String} AND status = 'ok' AND reader_version = {v:UInt16}
          AND collection_dataset != {cd:String}
        ORDER BY generation DESC
        LIMIT 1
    """, parameters={"h": file_hash, "v": READER_VERSION, "cd": collection_dataset}).result_rows
    if not rows:
        return None
    from tasks.P3_parse_files.table_generations import complete_column_coverage
    candidate = rows[0]
    if not complete_column_coverage(client, candidate[12], file_hash, int(candidate[13])):
        return None
    from tasks.P3_parse_files.table_text import complete_table_text
    if candidate[0] == "sqlite" and not complete_table_text(client, candidate[12], file_hash, int(candidate[13])):
        return None
    return candidate


def _next_generation(client, params: "ParseTableParams") -> int:
    """Allocate one owned generation before the first cell write."""
    import uuid
    from tasks.P3_parse_files.table_generations import GenerationCommand, send_command
    params._generation_token = str(uuid.uuid4())
    return send_command(GenerationCommand(params.collectionname, params.file_hash, "allocate",
                                         params._generation_token, owner_op=params.op_id))


def _has_published(client, params: "ParseTableParams") -> bool:
    rows = client.query(
        "SELECT count() FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String} AND status IN ('ok', 'empty')",
        parameters={"cd": params.collection_dataset, "h": params.file_hash}).result_rows
    return bool(rows and int(rows[0][0]))


def _write_empty(client, params: "ParseTableParams", reader: str, table_format: str,
                 run_time_ms: int) -> None:
    """Publish a parse without a table, so an earlier table of the hash is not shown."""
    if reader == "sqlite":
        from tasks.P3_parse_files.parse_common import insert_text_pages
        from tasks.P3_parse_files.table_text import text_identity
        from tasks.text_sources import TABLE_TEXT
        insert_text_pages(params.collectionname, params.collection_dataset, params.file_hash, TABLE_TEXT, [])
        params._table_text_count, params._table_text_digest = text_identity([])
        params._table_text_complete = 1
    _write_manifest(client, params, status=STATUS_EMPTY, reader=reader,
                    table_format=table_format, parse_ms=run_time_ms,
                    generation=getattr(params, "_current_generation", 0))


def _copy_structure(client, params: ParseTableParams, source_dataset: str, generation: int) -> None:
    """Point this dataset's manifest at cells another dataset already read.

    The sheet and column rows are copied rather than recomputed: they are per-dataset
    rows describing per-collection data, and re-deriving them would mean re-reading the
    file, which is the whole cost this short-circuit exists to avoid.
    """
    rows = client.query(
        "SELECT count() FROM table_columns FINAL WHERE collection_dataset = {dataset:String} "
        "AND hash = {hash:String} AND generation = {generation:UInt32}",
        parameters={"dataset": source_dataset, "hash": params.file_hash, "generation": generation}).result_rows
    params._expected_column_rows = int(rows[0][0]) if rows else 0
    for table in ("table_sheets", "table_columns"):
        columns = [row[0] for row in client.query(f"DESCRIBE TABLE `{table}`").result_rows]
        selected = ", ".join(
            "{cd:String}" if name == "collection_dataset" else f"`{name}`"
            for name in columns if name != "updated_at"
        )
        names = ", ".join(f"`{name}`" for name in columns if name != "updated_at")
        client.command(
            f"INSERT INTO `{table}` ({names}) SELECT {selected} FROM `{table}` FINAL "
            f"WHERE collection_dataset = {{src:String}} AND hash = {{h:String}} "
            f"AND generation = {{g:UInt32}}",
            parameters={"cd": params.collection_dataset, "src": source_dataset,
                        "h": params.file_hash, "g": generation},
        )


def delimited_evidence(params: ParseTableParams, file_name: str) -> bool:
    """Whether the MIME and name rules alone choose the CSV reader for this file."""
    return table_reader_for(params.mime_types or [], file_name, authoritative_type=params.sniff_mime_type,
                            content_type=params.file_mime_type) == "csv"


def select_table_reader(params: ParseTableParams, file_name: str) -> str:
    """The reader of one file: the MIME and name rules, then the JSON structure check.

    The JSON reader replaces the CSV reader, or no reader, when the bytes have a JSON
    grammar (`json_grammar`). An authoritative markup sniff and a spreadsheet keep their
    reader.
    """
    reader = table_reader_for(params.mime_types or [], file_name,
                              authoritative_type=params.sniff_mime_type, content_type=params.file_mime_type)
    if reader not in ("", "csv"):
        return reader
    evidence = has_json_evidence(params.mime_types, file_name)
    if (evidence or reader == "csv") and json_grammar(params.file_path, json_evidence=evidence):
        return READER_JSON
    return reader


@activity.defn
@with_heartbeat
def parse_table_and_store(params: ParseTableParams) -> Dict[str, Any] | SkippedOutcome:
    """Read one tabular document into `table_cells` and describe it in the manifest."""
    from database.clickhouse import get_collection_client, insert_parser_arrow
    from tasks.P3_parse_files.table_readers import fallback_reader, read_cells

    started = time.time()
    file_name = (params.file_names or [params.file_path])[0]
    reader = select_table_reader(params, file_name)

    with get_collection_client(params.collectionname) as client:
        if not reader:
            params._current_generation = _next_generation(client, params)
            _write_empty(client, params, "", "", 0)
            return SkippedOutcome({"status": "skipped", "reason": "no reader for this file"})
        table_format = table_format_for(reader, file_name)
        existing = _existing_parse(client, params.file_hash, params.collection_dataset)
        if existing is not None:
            truncation = TruncationRecord(
                limits=list(existing[8]), maximums=[int(m) for m in existing[9]],
                sheets=list(existing[10]),
            )
            # The structure lands before the manifest that names its generation.
            _copy_structure(client, params, existing[12], int(existing[13]))
            if existing[0] == "sqlite":
                from tasks.P3_parse_files.parse_common import insert_text_pages
                from tasks.text_sources import TABLE_TEXT
                pages = client.query(
                    "SELECT page_id, argMax(text, version) AS text FROM text_content "
                    "WHERE collection_dataset = {ds:String} AND file_hash = {h:String} "
                    "AND extracted_by = {source:String} GROUP BY page_id ORDER BY page_id",
                    parameters={"ds": existing[12], "h": params.file_hash, "source": TABLE_TEXT},
                ).result_rows
                from tasks.P3_parse_files.table_text import text_identity
                params._table_text_count, params._table_text_digest = text_identity(pages)
                if (params._table_text_count, params._table_text_digest) != (int(existing[15]), existing[14]):
                    raise RuntimeError("The source table text changed during its copy")
                params._table_text_complete = 1
                insert_text_pages(params.collectionname, params.collection_dataset,
                                  params.file_hash, TABLE_TEXT, pages)

            _write_manifest(
                client, params, status="ok", reader=existing[0],
                table_format=existing[1], sheet_count=int(existing[2]),
                row_count=int(existing[3]), column_count=int(existing[4]),
                cell_count=int(existing[5]), stored_bytes=int(existing[6]),
                truncation=truncation, parse_ms=0, generation=int(existing[13]),
            )
            log.info("[P3] table %s already parsed by %s, claimed for %s",
                     params.file_hash, existing[12], params.collection_dataset)
            return {"status": "ok", "reader": existing[0], "deduped": True,
                    "cell_count": int(existing[5])}

        heartbeat = HeartbeatClock()

        def on_progress(sheet_name: str, row: int) -> None:
            heartbeat.beat(f"table {sheet_name or table_format} row {row}")

        generation = _next_generation(client, params)
        params._current_generation = generation
        published = _has_published(client, params)

        def new_collector(name: str) -> _Collector:
            made = _Collector(params, name)
            made.generation, made.published = generation, published
            return made

        collector = new_collector(reader)
        attempted = [reader]
        reader_limits = {"time_limit_seconds": max(1, params.timeout_seconds - 60)} if reader == "sqlite" else {}
        if reader == "csv":
            extension = os.path.splitext(file_name.lower())[1]
            delimiter = {".tsv": "\t", ".tab": "\t", ".psv": "|"}.get(extension, "")
            if not delimiter and "text/tab-separated-values" in (params.mime_types or []):
                delimiter = "\t"
            reader_limits["delimiter"] = delimiter
        stream = None
        try:
            stream = read_cells(params.file_path, reader,
                                encodings=params.mime_encodings or [], on_progress=on_progress, **reader_limits)
            collector.consume(stream, client)
        except _NOT_THE_FILES_FAULT:
            collector.close()
            raise
        except BaseException as first_error:  # noqa: BLE001 - every failure is data here
            collector.close()
            alternative = fallback_reader(reader)
            if not alternative:
                run_time_ms = max(int((time.time() - started) * 1000), 0)
                _write_manifest(client, params, status=TABLE_UNREADABLE, reader=reader,
                                table_format=table_format, parse_ms=run_time_ms,
                                parse_error=f"{type(first_error).__name__}: {first_error}",
                                generation=generation)
                log.info("[P3] Table %s is unreadable (%s): %s", params.file_hash, reader, first_error)
                return SkippedOutcome({"status": TABLE_UNREADABLE, "reader": reader,
                                       "error": str(first_error)})
            log.warning("[P3] table reader %s failed on %s (%s), falling back to %s",
                        reader, params.file_hash, first_error, alternative)
            attempted.append(alternative)
            collector = new_collector(alternative)
            try:
                collector.consume(
                    read_cells(params.file_path, alternative, on_progress=on_progress),
                    client,
                )
            except _NOT_THE_FILES_FAULT:
                collector.close()
                raise
            except BaseException as second_error:
                collector.close()  # noqa: BLE001
                run_time_ms = max(int((time.time() - started) * 1000), 0)
                _write_manifest(client, params, status=TABLE_UNREADABLE, reader=alternative,
                                table_format=table_format, parse_ms=run_time_ms,
                                parse_error=f"{type(second_error).__name__}: {second_error}",
                                generation=generation)
                log.info("[P3] Table %s is unreadable (%s): %s", params.file_hash,
                         " then ".join(attempted), second_error)
                return SkippedOutcome({"status": TABLE_UNREADABLE, "reader": alternative,
                                       "error": str(second_error)})
            reader = alternative

        json_cells = getattr(stream, "cells", None)
        if json_cells is not None and json_cells.none_reason and delimited_evidence(params, file_name):
            # JSON without an array of objects, such as JSON Lines of arrays, keeps the
            # delimited reading that its detection permits.
            reader, table_format, json_cells = "csv", table_format_for("csv", file_name), None
            collector = new_collector(reader)
            try:
                collector.consume(read_cells(params.file_path, reader, encodings=params.mime_encodings or [],
                                             on_progress=on_progress), client)
            except _NOT_THE_FILES_FAULT:
                collector.close()
                raise
            except BaseException:  # noqa: BLE001 - a failed fallback is a parse without a table
                collector.close()
                collector = new_collector(reader)
        run_time_ms = max(int((time.time() - started) * 1000), 0)
        if json_cells is not None:
            table_format = json_cells.mode or table_format
            if json_cells.sheets_truncated:
                collector.truncation.record(LIMIT_SHEETS)

        if not collector.meets_threshold():
            collector.close()
            reason = (json_cells.none_reason if json_cells is not None and json_cells.none_reason
                      else "below the minimum table shape")
            _write_empty(client, params, reader, table_format, run_time_ms)
            log.info("[P3] table skip for %s: table_not_a_table (%s) %d cell(s): %s",
                      params.file_hash, reader, collector.cell_count, reason)
            return SkippedOutcome({"status": "skipped", "reader": reader,
                                    "cell_count": collector.cell_count,
                                    "reason": reason})

        collector.commit_spool(client)

        collector.settle_headers()
        insert_parser_arrow(client, "table_sheets", _sheet_rows(params, collector))
        columns = _column_rows(params, collector)
        params._expected_column_rows = columns.num_rows
        if columns.num_rows:
            insert_parser_arrow(client, "table_columns", columns)

        if collector.text is not None:
            from tasks.P3_parse_files.parse_common import insert_text_pages
            from tasks.text_sources import TABLE_TEXT
            pages = collector.text.pages()
            from tasks.P3_parse_files.table_text import text_identity
            params._table_text_count, params._table_text_digest = text_identity(pages)
            params._table_text_complete = 1
            insert_text_pages(params.collectionname, params.collection_dataset,
                              params.file_hash, TABLE_TEXT, pages)
            if collector.text.truncated:
                collector.truncation.record("text_characters")

        row_count = sum(s.row_count for s in collector.sheets.values())
        column_count = max((s.column_count for s in collector.sheets.values()), default=0)
        _write_manifest(
            client, params, status="ok", reader=reader, table_format=table_format,
            sheet_count=len(collector.sheets), row_count=row_count,
            column_count=column_count, cell_count=collector.cell_count,
            stored_bytes=collector.stored_bytes, truncation=collector.truncation,
            parse_ms=run_time_ms, generation=generation,
        )

    if collector.truncation.truncated:
        log.warning("[P3] table %s truncated: %s", params.file_hash,
                    collector.truncation.reason())
    log.info("[P3] table %s: %d cells in %d sheet(s) via %s in %d ms",
             params.file_hash, collector.cell_count, len(collector.sheets),
             reader, run_time_ms)
    return {"status": "ok", "reader": reader, "sheet_count": len(collector.sheets),
            "row_count": row_count, "column_count": column_count,
            "cell_count": collector.cell_count,
            "truncated": collector.truncation.truncated}


@activity.defn
@with_heartbeat
def parse_table_batch(params: StageBatchParams) -> BatchResult:
    """The cell grid of each file of a group, one `parse_table_and_store` call a file.

    Each call gets the MIME types and encodings that the detectors recorded for its file.
    """
    def step(file: BatchFile) -> Dict[str, Any] | SkippedOutcome:
        return parse_table_and_store(ParseTableParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            file_hash=file.item_hash,
            file_path=file.file_path,
            timeout_seconds=try_budget_seconds("parse_table_batch", file.file_size_bytes),
            mime_types=file.mime_types,
            mime_encodings=file.mime_encodings,
            op_id=params.op_id, file_names=file.file_names,
            sniff_mime_type=file.sniff_mime_type, file_mime_type=file.file_mime_type,
        ))

    return run_batch("parse_table_batch", params.files, key=lambda f: f.item_hash,
                     size=lambda f: f.file_size_bytes, step=step,
                     task_name="parse_table_and_store")
