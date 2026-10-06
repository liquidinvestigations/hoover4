"""Verify table threshold and fallback writes before cell publication."""

from contextlib import nullcontext
from types import SimpleNamespace
import pytest

from database import clickhouse as db
from tasks.P3_parse_files import parse_table as table, table_readers as readers
from tasks.task_timing import SkippedOutcome


def cell(row, column, text):
    return 0, "Sheet", readers.RawCell(row, column, "text", text)


@pytest.fixture
def writes(monkeypatch, tmp_path):
    rows = []
    client = SimpleNamespace(query=lambda *a, **k: SimpleNamespace(result_rows=[]),
                             command=lambda *a, **k: pytest.fail("Table parsing issued a delete"))
    monkeypatch.setattr(db, "get_collection_client", lambda *a: nullcontext(client))
    monkeypatch.setattr(db, "insert_parser_arrow", lambda c, name, data: rows.append((name, False, data.to_pylist())))
    monkeypatch.setattr(db, "insert_arrow_durable", lambda c, name, data: rows.append((name, True, data.to_pylist())))
    monkeypatch.setattr(table, "_record_skip", lambda *a: None)
    monkeypatch.setattr(table, "INSERT_BATCH_CELLS", 3)
    return rows, tmp_path


def params(tmp_path, reader):
    return table.ParseTableParams("c", "ds", "h", str(tmp_path / ("file.csv" if reader == "csv" else "file.xlsx")),
                                  900, mime_types=["text/csv" if reader == "csv" else "application/vnd.ms-excel"])


def test_below_threshold_has_no_writes(writes, monkeypatch):
    rows, path = writes
    monkeypatch.setattr(readers, "read_cells", lambda *a, **k: iter([cell(1, 1, "one")]))
    assert isinstance(table.parse_table_and_store(params(path, "csv")), SkippedOutcome)
    assert rows == []


def test_manifest_waits_before_cells(writes, monkeypatch):
    rows, path = writes
    monkeypatch.setattr(table, "INSERT_BATCH_CELLS", 6)
    monkeypatch.setattr(readers, "read_cells", lambda *a, **k: iter([
        cell(row, column, str(row)) for row in range(1, 4) for column in range(1, 4)]))
    assert table.parse_table_and_store(params(path, "csv"))["status"] == "ok"
    assert rows[0][0:2] == ("table_documents", True)
    assert rows[0][2][0]["status"] == "parsing"
    assert rows[1][0] == "table_cells"


@pytest.mark.parametrize("fallback", ["ok", "empty", "fail"])
def test_failed_stream_has_no_published_cells(writes, monkeypatch, fallback):
    rows, path = writes
    def stream(*args, **kwargs):
        if args[1] == "xlsx_stream":
            yield cell(1, 1, "discarded")
            yield cell(1, 2, "discarded")
            yield cell(1, 3, "discarded")
            assert rows == []
            raise ValueError("stream failed after a flush")
        if fallback == "fail":
            raise ValueError("fallback failed")
        if fallback == "ok":
            yield cell(1, 1, "accepted")
    monkeypatch.setattr(readers, "read_cells", stream)
    result = table.parse_table_and_store(params(path, "xlsx"))
    cells = [row for name, _, batch in rows if name == "table_cells" for row in batch]
    assert all(row["cell_text"] == "accepted" for row in cells)
    if fallback == "ok":
        assert result["status"] == "ok" and len(cells) == 1
        assert not any(name == "table_documents" and batch[0]["status"] == "parsing"
                       for name, _, batch in rows)
    elif fallback == "empty":
        assert isinstance(result, SkippedOutcome) and rows == []
    else:
        assert result["status"] == "failed" and not cells


def test_below_threshold_stops_at_buffer_limit(writes, monkeypatch):
    rows, path = writes
    seen = []
    def stream(*args, **kwargs):
        for index in range(100):
            seen.append(index)
            yield cell(1, index + 1, "one row")
    monkeypatch.setattr(readers, "read_cells", stream)
    assert isinstance(table.parse_table_and_store(params(path, "csv")), SkippedOutcome)
    assert len(seen) == 3 and rows == []


@pytest.mark.parametrize('cancel_type', ['temporal', 'asyncio'])
def test_cancelled_reader_closes_spool_without_fallback(writes, monkeypatch, cancel_type):
    import tempfile
    from temporalio.exceptions import CancelledError
    from asyncio import CancelledError as AsyncCancelledError
    rows, path = writes
    files = []
    original = tempfile.TemporaryFile
    def opened(*args, **kwargs):
        handle = original(*args, **kwargs)
        files.append(handle)
        return handle
    monkeypatch.setattr(tempfile, 'TemporaryFile', opened)
    error = CancelledError if cancel_type == 'temporal' else AsyncCancelledError
    def stream(*args, **kwargs):
        assert args[1] == 'xlsx_stream'
        for column in range(1, 4):
            yield cell(1, column, 'discarded')
        raise error()
    monkeypatch.setattr(readers, 'read_cells', stream)
    with pytest.raises(error):
        table.parse_table_and_store(params(path, 'xlsx'))
    assert rows == [] and files and all(handle.closed for handle in files)
