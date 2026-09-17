"""Error writers keep the operation id on rows and event records."""

import ast
from pathlib import Path
import pytest

from database import clickhouse, operation_ledger
from tasks.P2_execute_plan.activities import (
    RecordProcessingErrorsParams,
    record_processing_errors,
)


PROCESSING_ROOT = Path(__file__).parents[2]
ERROR_WRITER_CALL_FILES = (
    "tasks/P2_execute_plan/workflows.py",
    "tasks/P3_parse_files/workflows.py",
    "tasks/P3_parse_files/parse_pdf.py",
    "tasks/P4_extract_entities/workflows.py",
    "tasks/P5_chunk_embed/workflows.py",
    "tasks/P6_index_data/workflows.py",
)


class _Client:
    def __init__(self):
        self.tables = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def insert_arrow(self, table_name, table):
        self.tables.append((table_name, table))


def test_error_writer_requires_source_identity(monkeypatch):
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name:
                        pytest.fail("missing identity reached ClickHouse"))
    with pytest.raises(ValueError, match="nonempty error_identity"):
        record_processing_errors(RecordProcessingErrorsParams(
            "collection", [{"collection_dataset": "dataset", "hash": "hash"}]
        ))

def _called_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_error_rows_and_events_keep_op_id(monkeypatch):
    client = _Client()
    events = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _: client)
    monkeypatch.setattr(
        operation_ledger,
        "insert_error_events",
        lambda collectionname, rows: events.append((collectionname, rows)) or len(rows),
    )

    written = record_processing_errors(RecordProcessingErrorsParams(
        collectionname="collection",
        errors=[
            {
                "collection_dataset": "dataset-a",
                "hash": "hash-a",
                "task_name": "P3_ParseSingleFile",
                "run_time_ms": 1,
                "error_logs": "first error",
                "op_id": "operation-a",
                "error_identity": "source-a",
            },
            {
                "collection_dataset": "dataset-b",
                "hash": "hash-b",
                "task_name": "P4_ScanRegexEntities",
                "run_time_ms": 2,
                "error_logs": "second error",
                "op_id": "operation-b",
                "error_identity": "source-b",
            },
            {
                "collection_dataset": "dataset-a",
                "hash": "hash-c",
                "task_name": "P5_ChunkEmbed",
                "run_time_ms": 3,
                "error_logs": "unattributed error",
                "error_identity": "source-c",
            },
        ],
    ))

    assert written == 3
    table_name, table = client.tables[0]
    assert table_name == "processing_errors"
    assert "op_id" in table.column_names
    assert table.column("op_id").to_pylist() == ["operation-a", "operation-b", ""]
    assert events == [
        ("collection", [{
            "op_id": "operation-a",
            "collection_dataset": "dataset-a",
            "hash": "hash-a",
            "task_name": "P3_ParseSingleFile",
            "event": "error",
            "error_logs": "first error",
        }]),
        ("collection", [{
            "op_id": "operation-b",
            "collection_dataset": "dataset-b",
            "hash": "hash-b",
            "task_name": "P4_ScanRegexEntities",
            "event": "error",
            "error_logs": "second error",
        }]),
    ]


def test_every_error_writer_call_passes_op_id():
    calls = []
    for relative_path in ERROR_WRITER_CALL_FILES:
        tree = ast.parse((PROCESSING_ROOT / relative_path).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called_name(node.func) == "record_errors_from_results":
                calls.append((relative_path, node))
    missing = [
        f"{relative_path}:{node.lineno}"
        for relative_path, node in calls
        if "op_id" not in {keyword.arg for keyword in node.keywords}
    ]
    assert len(calls) == 8
    assert not missing, "Error writer calls without op_id: " + ", ".join(missing)
