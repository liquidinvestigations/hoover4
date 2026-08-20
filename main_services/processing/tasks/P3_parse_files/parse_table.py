"""P3 activity: read a tabular document into cells and store the grid.

This runs *alongside* the text extractors, never instead of them. A `.xlsx` still gets
its office-XML flattening and its Tika text, a `.csv` still gets its raw text stored, and
a search for a value inside cell G4713 still finds the file through Manticore. What this
adds is the structural reading: which columns exist, what type each one is, and a grid
that can be sorted, filtered and paged without loading the document.

The claim order, and why it is the opposite of the OCR one
-----------------------------------------------------------
`parse_ocr_pdf` writes its MinIO object before its ClickHouse row, because there an
object with no row is findable by a prefix scan while a row with no object is a broken
link. Here the order is reversed for the mirrored reason: `table_cells` has no
`collection_dataset` column, so **cells with no `table_documents` row are invisible to
the permission check and to the orphan sweeper alike**. The manifest row is therefore
written first, as `status = 'parsing'`, and rewritten as `ok` when the cells are in.

A concurrent claim from a second dataset is possible -- ClickHouse has no uniqueness --
and it is harmless: both runs produce byte-identical cell rows for identical positions
and ReplacingMergeTree collapses them.

Failure is data, not a retry
-----------------------------
A password-protected workbook, a truncated zip, a `.csv` that is really prose: the row
gets `status = 'failed'`, a `processing_errors` row explains why, and the activity
**succeeds**. Consuming three retries on a file that will never parse is the failure mode
`parse_office_xml._record_skip` and `parse_ocr._record_skip` both exist to avoid.

Where the 2x2 rule is applied
------------------------------
Delimited text has to produce at least `MIN_DELIMITED_ROWS` rows and
`MIN_DELIMITED_COLUMNS` columns in one sheet before any row is written -- below that it
is a text file and nothing here happened, recorded as `table_not_a_table`. A binary
spreadsheet is a table on the strength of its format and only has to produce
`MIN_BINARY_CELLS` cells. See `table_formats` for why the asymmetry is the point.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from temporalio import activity

from tasks.heartbeat import HeartbeatClock, with_heartbeat
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
    NUMERIC_KINDS,
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
_NOT_THE_FILES_FAULT = (KeyboardInterrupt, SystemExit, GeneratorExit)


#: Cells per ClickHouse insert. Large enough that a million-cell sheet is a few hundred
#: round trips, small enough that a batch is a few megabytes of Python objects.
INSERT_BATCH_CELLS = 50_000


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


@dataclass
class _ColumnStats:
    """What one column looked like, accumulated as its cells stream past."""

    kinds: Counter = None  # type: ignore[assignment]
    header: str = ""
    non_empty: int = 0
    distinct: set = None  # type: ignore[assignment]
    distinct_overflow: bool = False
    samples: list = None  # type: ignore[assignment]
    min_sort: Any = None
    max_sort: Any = None
    min_text: str = ""
    max_text: str = ""

    def __post_init__(self) -> None:
        self.kinds = Counter()
        self.distinct = set()
        self.samples = []


@dataclass
class _SheetStats:
    name: str
    row_count: int = 0
    column_count: int = 0
    cell_count: int = 0
    min_source_row: int = 0
    max_source_row: int = 0
    header_row: int = 0
    truncated: bool = False
    columns: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.columns = {}


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


class _Collector:
    """Consumes a reader's cell stream into ClickHouse batches, applying every cap.

    The caps live here rather than in the readers so that a reader can never be the thing
    that runs the box out of memory: when a cap fires the collector stops pulling and the
    generator is closed.
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

    def consume(self, stream: Iterable, client) -> None:
        for sheet_id, sheet_name, cell in stream:
            if self._done:
                break
            if not self._accept(sheet_id, sheet_name, cell, client):
                break
        self._flush(client)

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

        self.batch.append((
            self.params.file_hash, sheet_id, cell.column_id, self._row_id,
            cell.source_row, cell.kind, text, cell.int_value, cell.float_value,
            cell.time_value, cell.link, cell.formula,
        ))
        if len(self.batch) >= INSERT_BATCH_CELLS:
            self._flush(client)
        return True

    def _observe(self, sheet: _SheetStats, stats: _ColumnStats, row_id: int, cell,
                 text: str) -> None:
        # The first row that produces cells is the header row, and its text is the header
        # of every column it touches. A sheet whose first row is data gets headers that
        # are data, which is what a spreadsheet application shows too.
        if row_id == 1:
            sheet.header_row = 1
            stats.header = text
            return
        stats.kinds[cell.kind] += 1
        stats.non_empty += 1
        if len(stats.samples) < MAX_COLUMN_SAMPLES:
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
            if stats.min_sort is None or key < stats.min_sort[0]:
                stats.min_sort = (key, text)
            if stats.max_sort is None or key > stats.max_sort[0]:
                stats.max_sort = (key, text)

    def _flush(self, client) -> None:
        if not self.batch:
            return
        import pyarrow as pa

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
        })
        client.insert_arrow("table_cells", table)

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
                low = stats.min_sort[1] if stats.min_sort else ""
                high = stats.max_sort[1] if stats.max_sort else ""
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
    })


def _write_manifest(client, params: ParseTableParams, *, status: str, reader: str,
                    table_format: str, sheet_count: int = 0, row_count: int = 0,
                    column_count: int = 0, cell_count: int = 0, stored_bytes: int = 0,
                    truncation: Optional[TruncationRecord] = None, parse_ms: int = 0,
                    parse_error: str = "") -> None:
    import pyarrow as pa

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
    })
    client.insert_arrow("table_documents", table)


def _record_skip(params: ParseTableParams, run_time_ms: int, reason: str) -> None:
    """Record what this reader could not do, without failing the activity."""
    from tasks.P2_execute_plan.activities import (
        RecordProcessingErrorsParams,
        record_processing_errors,
    )

    record_processing_errors(RecordProcessingErrorsParams(
        collectionname=params.collectionname,
        errors=[{
            "collection_dataset": params.collection_dataset,
            "hash": params.file_hash,
            "task_name": "parse_table_and_store",
            "run_time_ms": run_time_ms,
            "error_logs": f"{reason}: {params.file_path}",
        }],
    ))


def _existing_parse(client, file_hash: str):
    """A finished parse of this hash in any dataset of this collection, or None.

    This is the cross-dataset dedup: `table_cells` is keyed by hash alone, so a hash
    another dataset has already read needs a manifest row and nothing else. A corpus with
    the same price list mailed to forty people parses it once.
    """
    rows = client.query("""
        SELECT reader, table_format, sheet_count, row_count, column_count, cell_count,
               stored_bytes, truncated, truncated_limits, truncated_maximums,
               truncated_sheets, truncated_reason, collection_dataset
        FROM table_documents FINAL
        WHERE hash = {h:String} AND status = 'ok' AND reader_version = {v:UInt16}
        LIMIT 1
    """, parameters={"h": file_hash, "v": READER_VERSION}).result_rows
    return rows[0] if rows else None


def _copy_structure(client, params: ParseTableParams, source_dataset: str) -> None:
    """Point this dataset's manifest at cells another dataset already read.

    The sheet and column rows are copied rather than recomputed: they are per-dataset
    rows describing per-collection data, and re-deriving them would mean re-reading the
    file, which is the whole cost this short-circuit exists to avoid.
    """
    for table in ("table_sheets", "table_columns"):
        columns = [row[0] for row in client.query(f"DESCRIBE TABLE `{table}`").result_rows]
        selected = ", ".join(
            "{cd:String}" if name == "collection_dataset" else f"`{name}`"
            for name in columns if name != "updated_at"
        )
        names = ", ".join(f"`{name}`" for name in columns if name != "updated_at")
        client.command(
            f"INSERT INTO `{table}` ({names}) SELECT {selected} FROM `{table}` FINAL "
            f"WHERE collection_dataset = {{src:String}} AND hash = {{h:String}}",
            parameters={"cd": params.collection_dataset, "src": source_dataset,
                        "h": params.file_hash},
        )


@activity.defn
@with_heartbeat
def parse_table_and_store(params: ParseTableParams) -> Dict[str, Any]:
    """Read one tabular document into `table_cells` and describe it in the manifest."""
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.table_readers import fallback_reader, read_cells

    started = time.time()
    reader = table_reader_for(params.mime_types or [], params.file_path)
    if not reader:
        _record_skip(params, 0, "table_no_reader")
        return {"status": "skipped", "reason": "no reader for this file"}
    table_format = table_format_for(reader, params.file_path)

    with get_collection_client(params.collectionname) as client:
        existing = _existing_parse(client, params.file_hash)
        if existing is not None and existing[12] != params.collection_dataset:
            truncation = TruncationRecord(
                limits=list(existing[8]), maximums=[int(m) for m in existing[9]],
                sheets=list(existing[10]),
            )
            _write_manifest(
                client, params, status="ok", reader=existing[0],
                table_format=existing[1], sheet_count=int(existing[2]),
                row_count=int(existing[3]), column_count=int(existing[4]),
                cell_count=int(existing[5]), stored_bytes=int(existing[6]),
                truncation=truncation, parse_ms=0,
            )
            _copy_structure(client, params, existing[12])
            log.info("[P3] table %s already parsed by %s, claimed for %s",
                     params.file_hash, existing[12], params.collection_dataset)
            return {"status": "ok", "reader": existing[0], "deduped": True,
                    "cell_count": int(existing[5])}

        # The manifest row before the cells: a cell with no manifest row is invisible to
        # the permission check and to the orphan sweeper alike.
        _write_manifest(client, params, status="parsing", reader=reader,
                        table_format=table_format)

        heartbeat = HeartbeatClock()

        def on_progress(sheet_name: str, row: int) -> None:
            heartbeat.beat(f"table {sheet_name or table_format} row {row}")

        collector = _Collector(params, reader)
        attempted = [reader]
        try:
            collector.consume(
                read_cells(params.file_path, reader,
                           encodings=params.mime_encodings or [], on_progress=on_progress),
                client,
            )
        except _NOT_THE_FILES_FAULT:
            raise
        except BaseException as first_error:  # noqa: BLE001 - every failure is data here
            alternative = fallback_reader(reader)
            if not alternative:
                run_time_ms = max(int((time.time() - started) * 1000), 0)
                _write_manifest(client, params, status="failed", reader=reader,
                                table_format=table_format, parse_ms=run_time_ms,
                                parse_error=f"{type(first_error).__name__}: {first_error}")
                _record_skip(params, run_time_ms,
                             f"table_read_failed ({reader}) {first_error}")
                return {"status": "failed", "reader": reader, "error": str(first_error)}
            log.warning("[P3] table reader %s failed on %s (%s), falling back to %s",
                        reader, params.file_hash, first_error, alternative)
            attempted.append(alternative)
            collector = _Collector(params, alternative)
            try:
                collector.consume(
                    read_cells(params.file_path, alternative, on_progress=on_progress),
                    client,
                )
            except _NOT_THE_FILES_FAULT:
                raise
            except BaseException as second_error:  # noqa: BLE001
                run_time_ms = max(int((time.time() - started) * 1000), 0)
                _write_manifest(client, params, status="failed", reader=alternative,
                                table_format=table_format, parse_ms=run_time_ms,
                                parse_error=f"{type(second_error).__name__}: {second_error}")
                _record_skip(params, run_time_ms,
                             f"table_read_failed ({' then '.join(attempted)}) {second_error}")
                return {"status": "failed", "reader": alternative,
                        "error": str(second_error)}
            reader = alternative

        run_time_ms = max(int((time.time() - started) * 1000), 0)

        if not collector.meets_threshold():
            # No manifest row means no evidence, which means no `table` canonical type,
            # which means no glyph and no Table source. One rule, five consequences.
            client.command(
                "DELETE FROM table_documents WHERE collection_dataset = {cd:String} "
                "AND hash = {h:String}",
                parameters={"cd": params.collection_dataset, "h": params.file_hash},
            )
            _record_skip(params, run_time_ms,
                         f"table_not_a_table ({reader}) {collector.cell_count} cell(s)")
            return {"status": "skipped", "reader": reader,
                    "cell_count": collector.cell_count,
                    "reason": "below the minimum table shape"}

        client.insert_arrow("table_sheets", _sheet_rows(params, collector))
        columns = _column_rows(params, collector)
        if columns.num_rows:
            client.insert_arrow("table_columns", columns)

        row_count = sum(s.row_count for s in collector.sheets.values())
        column_count = max((s.column_count for s in collector.sheets.values()), default=0)
        _write_manifest(
            client, params, status="ok", reader=reader, table_format=table_format,
            sheet_count=len(collector.sheets), row_count=row_count,
            column_count=column_count, cell_count=collector.cell_count,
            stored_bytes=collector.stored_bytes, truncation=collector.truncation,
            parse_ms=run_time_ms,
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
