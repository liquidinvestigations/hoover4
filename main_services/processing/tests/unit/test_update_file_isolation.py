"""One unreadable file stays selected, and the other files of its plan continue."""

import pytest

from tasks.P3_parse_files import ocr_detection
from tasks.P_admin.updates import activities, selectors
from tasks.P_admin.updates.entities import indexed_copy
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


def test_indexed_text_ends_at_the_first_nul_byte():
    assert indexed_copy("before\0after\0end") == "before"
    assert indexed_copy("no nul byte") == "no nul byte"


def test_a_text_row_is_verified_without_a_string_inequality_filter(monkeypatch):
    from tasks.P_admin.updates import entities

    statements = []

    class Pages:
        def fetchall(self):
            return [(1, "()", "()", "()", "()", "filename_index"), (2, "()", "()", "()", "()", "raw_text")]

        def execute(self, sql, _parameters=None):
            statements.append(sql)

    class Stored:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def query_arrow(self, *_a, **_k):
            class Empty:
                def to_pylist(self):
                    return []
            return Empty()

        def query(self, sql, parameters=None):
            return Result([("hash", "raw_text", 1)] if "text_content" in sql else [("hash", "shard_1")])

    monkeypatch.setattr("database.clickhouse.get_collection_client", lambda _name: Stored())
    monkeypatch.setattr("database.manticore.get_manticore_client", lambda: Connection(Pages()))
    monkeypatch.setattr("database.manticore.shard_table_from_name", lambda name: name)
    monkeypatch.setattr("tasks.P6_index_data.activities.pages_row_id", lambda *_a: 2)
    monkeypatch.setattr(entities, "completions", lambda *_a: [])
    monkeypatch.setattr(selectors, "missing_search_terms", lambda *_a: 0)
    entities.verify_index(entities.EntityUpdateParams("collection", "dataset", "op", ["hash"]))
    assert "extracted_by !=" not in statements[0]


def test_stale_hashes_stay_under_the_field_limit(monkeypatch):
    sizes = []

    def count(_client, sql, parameters, _dataset):
        if "d_stale" not in sql:
            return 5, 50
        sizes.append(len(parameters["d_stale"]))
        return len(parameters["d_stale"]) - 1, 10

    monkeypatch.setattr(selectors, "_count", count)
    monkeypatch.setattr(selectors, "detection_target", lambda: {"ocr_detection": "on"})
    monkeypatch.setattr(selectors, "target_key", lambda *_a: ("", {}))
    monkeypatch.setattr("tasks.P_admin.updates.registry.fingerprint", lambda *_a: "current")
    monkeypatch.setattr("tasks.P6_index_data.location_refresh.list_stale_location_hashes",
                        lambda *_a: ([f"{index:064d}" for index in range(2500)], 0, "affected-documents"))
    selection = selectors.select_ocr_detection(None, CTX)
    assert sizes == [1000, 1000, 500]
    assert (selection.count, selection.bytes) == (5 + 2497, 80)
    assert "d_stale" not in selection.parameters and "d_stale" not in selection.hash_sql


def test_a_step_that_never_began_counts_as_failed_at_its_fingerprint(monkeypatch):
    import json
    from datetime import datetime

    from database import processing_updates as updates

    earlier = datetime(2026, 11, 6, 8)

    class Global:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def query(self, sql, parameters=None):
            if "state = 'errored'" in sql:
                detail = json.dumps({"fingerprints": {"tables": "t1", "ocr": "o1"}})
                return Result([("op", "ehud", "ehud_ehud", detail, earlier)])
            return Result([("op", "ocr")])

    monkeypatch.setattr("database.clickhouse.get_global_client", lambda: Global())
    rows = updates.unstarted_steps()
    assert [(row["scope_id"], row["step_id"], row["desired_fingerprint"], row["effective_state"]) for row in rows] == [
        ("ehud_ehud", "tables", "t1", "failed")]
    assert updates.unstarted_steps(["other"]) == []
