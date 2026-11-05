"""JSON and JSON Lines tables: reader selection, detection, the reader protocol and storage."""

import json
import shutil
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from database import clickhouse as db
from tasks.P3_parse_files import parse_table as table
from tasks.P3_parse_files.sniff_table import sniff_table
from tasks.P3_parse_files.table_formats import json_grammar
from tasks.P3_parse_files.table_readers import JSON_TABLE_BINARY, json_number_cell, read_cells
from tasks.P3_parse_files.workflows import route_stages
from tasks.task_timing import SkippedOutcome

JSONL = '{"id": 1, "user": {"name": "a"}}\n{"id": 2, "user": {"name": "b"}}\n'
CSV_WITH_JSON = '"{""a"": 1}",x\n"{""a"": 2}",y\n'

needs_binary = pytest.mark.skipif(shutil.which(JSON_TABLE_BINARY) is None,
                                  reason="json-table is not in this image")


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def params(path, mime_types, names):
    return table.ParseTableParams("c", "ds", "h", path, 900, mime_types=mime_types, file_names=names)


@pytest.mark.parametrize("name, text, mimes, expected", [
    ("a.jsonl", JSONL, ["application/x-ndjson", "text/csv"], "json"),
    ("noext", JSONL, ["application/json", "text/csv", "text/plain"], "json"),
    ("noext2", JSONL, ["text/csv"], "json"),
    ("b.json", '{\n\t"rows": [\n\t\t{"a": 1}\n\t]\n}\n', ["application/json", "text/plain"], "json"),
    ("c.json", JSONL, ["application/json"], "json"),
    ("d.csv", CSV_WITH_JSON, ["text/csv"], "csv"),
    ("e.csv", "[x],1\n[y],2\n", ["text/csv"], "csv"),
    ("f.txt", "plain words\n", ["text/plain"], ""),
])
def test_reader_selection(tmp_path, name, text, mimes, expected):
    path = write(tmp_path, name, text)
    assert table.select_table_reader(params(path, mimes, [name]), name) == expected


def test_grammar_needs_strong_evidence_without_a_json_type(tmp_path):
    formatted = write(tmp_path, "x", '{\n  "a": [1]\n}\n')
    assert json_grammar(formatted, json_evidence=False) == "json"
    broken = write(tmp_path, "y", '{\n  "a": [1\n')
    assert json_grammar(broken, json_evidence=False) == ""
    assert json_grammar(broken, json_evidence=True) == "json"
    assert json_grammar(write(tmp_path, "z", JSONL), json_evidence=False) == "jsonl"


def test_sniff_refuses_json_lines_and_keeps_csv_with_json_cells():
    assert sniff_table((JSONL * 10).encode()) is None
    assert sniff_table((CSV_WITH_JSON * 10).encode()) is not None


def test_json_types_get_the_table_route():
    combined = {"coarse_types": ["text"], "mime_types": ["application/json", "text/plain"],
                "authoritative_types": [], "permitted_delimited": []}
    assert "table" in route_stages(combined, True, ["b.json"], 10)


def test_numbers_keep_exact_text():
    assert json_number_cell(2, 1, "12").int_value == 12
    long_id = json_number_cell(2, 1, "123456789012345678901234567890")
    assert long_id.kind == "text" and long_id.text == "123456789012345678901234567890"
    decimal = json_number_cell(2, 1, "1.50")
    assert decimal.kind == "float" and decimal.text == "1.50"
    assert json_number_cell(2, 1, "1e+400").kind == "text"


@needs_binary
def test_reader_stream_has_a_header_row_and_typed_cells(tmp_path):
    path = write(tmp_path, "a.jsonl", JSONL)
    cells = list(read_cells(path, "json"))
    assert [(s, c.source_row, c.column_id, c.text) for s, _, c in cells[:2]] == [
        (0, 1, 1, "id"), (0, 1, 2, "user.name")]
    assert [(c.source_row, c.kind, c.text) for _, _, c in cells[2:4]] == [(2, "int", "1"), (2, "text", "a")]


@needs_binary
def test_reader_failure_raises_with_stderr(tmp_path):
    path = write(tmp_path, "bad.jsonl", JSONL + "{oops\n")
    with pytest.raises(RuntimeError, match="line 3"):
        list(read_cells(path, "json"))


@needs_binary
def test_closing_the_stream_stops_the_process(tmp_path):
    path = write(tmp_path, "big.jsonl", "".join(json.dumps({"n": i}) + "\n" for i in range(50_000)))
    stream = read_cells(path, "json")
    next(stream)
    stream.close()
    assert stream.cells._process.poll() is not None


@pytest.fixture
def writes(monkeypatch, table_generation_commands):
    rows = []
    def query(sql, **kwargs):
        # Aggregates return one row. The dedup lookup finds no earlier parse.
        return SimpleNamespace(result_rows=[[0]] if ("max(" in sql or "count()" in sql) else [])

    client = SimpleNamespace(query=query,
                             command=lambda *a, **k: pytest.fail("Table parsing issued a delete"))
    monkeypatch.setattr(db, "get_collection_client", lambda *a: nullcontext(client))
    monkeypatch.setattr(db, "insert_parser_arrow", lambda c, name, data: rows.append((name, data.to_pylist())))
    monkeypatch.setattr(db, "insert_arrow_durable", lambda c, name, data: rows.append((name, data.to_pylist())))
    monkeypatch.setattr(table, "_record_skip", lambda *a: None)
    return rows


@needs_binary
def test_a_json_table_is_published_with_its_generation_last(tmp_path, writes):
    path = write(tmp_path, "a.jsonl", JSONL)
    result = table.parse_table_and_store(params(path, ["application/x-ndjson"], ["a.jsonl"]))
    assert result["status"] == "ok" and result["reader"] == "json"
    names = [name for name, _ in writes]
    assert names[-1] == "table_documents"
    manifest = writes[-1][1][0]
    assert manifest["status"] == "ok" and manifest["generation"] == 1 and manifest["table_format"] == "jsonl"
    sheets = next(batch for name, batch in writes if name == "table_sheets")
    assert sheets[0]["header_state"] == "established" and sheets[0]["generation"] == 1
    columns = next(batch for name, batch in writes if name == "table_columns")
    assert [c["header"] for c in columns] == ["id", "user.name"]
    assert columns[0]["column_type"] == "int"


@needs_binary
def test_a_json_file_without_an_array_of_objects_publishes_empty(tmp_path, writes):
    path = write(tmp_path, "o.json", '{"alice": {"age": 3}}')
    result = table.parse_table_and_store(params(path, ["application/json"], ["o.json"]))
    assert isinstance(result, SkippedOutcome) and result.value["reason"] == "no array of objects"
    assert [(name, batch[0]["status"]) for name, batch in writes] == [("table_documents", "empty")]


@needs_binary
def test_json_lines_of_arrays_keep_the_delimited_reading(tmp_path, writes):
    text = '["a","b"]\n["1","2"]\n["3","4"]\n'
    path = write(tmp_path, "rows.ndjson", text)
    result = table.parse_table_and_store(params(path, ["application/x-ndjson", "text/csv"], ["rows.ndjson"]))
    assert result["status"] == "ok" and result["reader"] == "csv"
