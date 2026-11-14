"""A retry of the ingestion check of automatic OCR continues after the applied files.

The check verifies each file of a plan, about one to three seconds a file, and a plan
holds up to 1,000 files. Each attempt started again at the first file, so a large plan
reached the 30-minute timeout on all five attempts and its plan failed.
"""

from contextlib import contextmanager

from tasks.P_admin import automatic_ocr
from tasks.P_admin.automatic_ocr import AutomaticOcrScope


def test_a_retry_verifies_only_the_files_without_an_applied_plan(monkeypatch):
    queries = []

    class Client:
        def query(self, sql, parameters):
            queries.append((sql, parameters))
            if "processing_output_receipts" in sql:
                rows = [("a", "plan-a"), ("b", "plan-b"), ("c", "plan-c")]
            else:
                # File a has its prepared plan applied. File b has an earlier plan applied.
                rows = [("a", "plan-a"), ("b", "plan-old")]
            return type("R", (), {"result_rows": rows})()

    @contextmanager
    def client(_):
        yield Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    verified = []
    monkeypatch.setattr(automatic_ocr, "verify_automatic_ocr_files",
                        lambda params: verified.append((list(params.hashes), dict(params.plans))))
    automatic_ocr.verify_ingested_automatic_ocr(AutomaticOcrScope("c", "d", "op", hashes=["a", "b", "c"]))
    assert verified == [(["b", "c"], {"b": "plan-b", "c": "plan-c"})]
    assert "state = 'applied'" in queries[1][0]
    assert queries[1][1]["hashes"] == ["a", "b", "c"]


def test_no_prepared_file_skips_the_applied_query(monkeypatch):
    queries = []

    class Client:
        def query(self, sql, parameters):
            queries.append(sql)
            return type("R", (), {"result_rows": []})()

    @contextmanager
    def client(_):
        yield Client()

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    verified = []
    monkeypatch.setattr(automatic_ocr, "verify_automatic_ocr_files", lambda params: verified.append(params.hashes))
    automatic_ocr.verify_ingested_automatic_ocr(AutomaticOcrScope("c", "d", "op", hashes=["a"]))
    assert verified == [[]]
    assert len(queries) == 1
