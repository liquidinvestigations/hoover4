"""One unreadable file stays selected, and the other files of its plan continue."""

import pytest

from tasks.P3_parse_files import ocr_detection
from tasks.P_admin.updates import activities, selectors
from tasks.P_admin.updates.params import TablePlanParams


class Result:
    def __init__(self, rows):
        self.result_rows = rows


class Client:
    """Answer the selection query, and report no published table for each file."""

    def __init__(self, selected):
        self.selected = selected

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def query(self, sql, parameters=None):
        return Result(self.selected if "processing_plan_hits" in sql else [])


PARAMS = TablePlanParams("op", "collection", "dataset", "plan")


def clients(monkeypatch, selected):
    monkeypatch.setattr("database.clickhouse.get_collection_client", lambda _name: Client(selected))
    monkeypatch.setattr("tasks.P2_execute_plan.activities.write_blob_files", lambda *_a, **_k: None)
    monkeypatch.setattr(activities.os, "remove", lambda _path: None)


def test_an_undetectable_file_does_not_stop_its_plan(monkeypatch):
    clients(monkeypatch, [("bad", 1, "s3://b/bad"), ("good", 1, "s3://b/good")])
    seen = []

    def detect(_scope, file):
        seen.append(file.item_hash)
        if file.item_hash == "bad":
            raise ocr_detection.NotDetectable("OCR detector returned no processable result")

    monkeypatch.setattr(ocr_detection, "stored_pdf_pages", lambda *_a: [])
    monkeypatch.setattr(ocr_detection, "_detect_file", detect)
    assert activities.detect_update_files.__wrapped__(PARAMS) == 2
    assert seen == ["bad", "good"]


def test_a_service_failure_keeps_its_temporal_retry(monkeypatch):
    clients(monkeypatch, [("file", 1, "s3://b/file")])

    def detect(_scope, _file):
        raise RuntimeError("OCR service is unavailable")

    monkeypatch.setattr(ocr_detection, "stored_pdf_pages", lambda *_a: [])
    monkeypatch.setattr(ocr_detection, "_detect_file", detect)
    with pytest.raises(RuntimeError, match="unavailable"):
        activities.detect_update_files.__wrapped__(PARAMS)


def test_an_unreadable_table_does_not_stop_its_plan(monkeypatch):
    columns = (1, "s3://b/x", ["x.xlsx"], [], [], [], "")
    clients(monkeypatch, [("bad", *columns), ("good", *columns)])
    prepared = []
    monkeypatch.setattr("tasks.P3_parse_files.parse_table.parse_table_and_store", lambda params: (
        {"status": "failed", "error": "Cannot detect file format"} if params.file_hash == "bad" else {"status": "ok"}))
    monkeypatch.setattr("tasks.P_admin.updates.table_receipts.prepare_table_text",
                        lambda _client, receipt: prepared.append(receipt.hashes))
    assert activities.reparse_update_tables(PARAMS) == ["good"]
    assert prepared == [["good"]]


class Cursor:
    """Return wrong text for one correct row in a wide read, as Manticore 29.9.0 did."""

    def __init__(self, stored, wide):
        self.stored, self.wide, self.rows = stored, wide, []

    def execute(self, sql):
        self.rows = ([(row_id, *self.wide[row_id]) for row_id in self.wide] if "IN (" in sql
                     else [self.stored[int(sql.rsplit("=", 1)[1])]])

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, cursor):
        self.handle = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.handle


class Terms:
    def __init__(self, rows):
        self.pages = [rows, []]

    def query(self, _sql, parameters=None):
        return Result(self.pages.pop(0))


CTX = selectors.ScopeContext("dataset", "dataset", "collection")


def compare(monkeypatch, stored, wide):
    from tasks.P6_index_data.activities import entity_term_row_id

    ids = {name: entity_term_row_id("dataset", "ner", number) for name, number in (("first", 1), ("second", 2))}
    monkeypatch.setattr("database.manticore.create_entities_table", lambda _name: "terms")
    cursor = Cursor({ids[k]: row for k, row in stored.items()}, {ids[k]: row for k, row in wide.items()})
    monkeypatch.setattr("database.manticore.get_manticore_client", lambda: Connection(cursor))
    return selectors.missing_search_terms(Terms([("ner", 1, "alpha"), ("ner", 2, "beta")]), CTX)


def test_a_correct_row_with_wrong_text_in_a_wide_read_is_not_missing(monkeypatch):
    stored = {"first": ("ner", 1, "alpha"), "second": ("ner", 2, "beta")}
    wide = {"first": ("ner", 1, "beta"), "second": ("ner", 2, "beta")}
    assert compare(monkeypatch, stored, wide) == 0


def test_a_row_that_differs_alone_and_an_absent_row_are_missing(monkeypatch):
    stored = {"first": ("ner", 1, "stale")}
    assert compare(monkeypatch, stored, {"first": ("ner", 1, "stale")}) == 2
