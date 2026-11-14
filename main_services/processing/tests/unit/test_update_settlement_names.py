"""A settlement that fails for some files names them.

The `ocr_detection` and `search_terms` steps reported only a count. The person could not
find the file or the term behind "1 files have no OCR detection result".
"""

from contextlib import contextmanager
from types import SimpleNamespace

from tasks.P_admin.updates import activities, selectors
from tasks.P_admin.updates.registry import SCOPE_DATASET


def settle(monkeypatch, step_id):
    import database.clickhouse
    import database.processing_updates

    @contextmanager
    def client(_):
        yield "client"

    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    monkeypatch.setattr(database.processing_updates, "stored_applied", lambda scopes: {})
    params = SimpleNamespace(op_id="op", scope_kind=SCOPE_DATASET, collectionname="c",
                             collection_dataset="d", step=SimpleNamespace(step_id=step_id))
    return activities._settle(params)


def test_ocr_detection_names_the_files_without_a_result(monkeypatch):
    monkeypatch.setattr(selectors, "select_ocr_detection",
                        lambda client, ctx: selectors.Selection(1, 10, 1, "SELECT 'h1' AS hash", {"cd": "d"}))
    asked = []

    def examples(client, selection):
        asked.append(selection.hash_sql)
        return ["h1"]

    monkeypatch.setattr(selectors, "example_hashes", examples)
    settled, message = settle(monkeypatch, "ocr_detection")
    assert not settled
    assert message.startswith("1 files have no OCR detection result, for example h1.")
    assert asked == ["SELECT 'h1' AS hash"]


def test_a_settled_ocr_detection_step_reads_no_examples(monkeypatch):
    monkeypatch.setattr(selectors, "select_ocr_detection", lambda client, ctx: selectors.Selection())
    monkeypatch.setattr(selectors, "example_hashes", lambda *a: (_ for _ in ()).throw(AssertionError()))
    assert settle(monkeypatch, "ocr_detection") == (True, "0 files have no OCR detection result.")


def test_search_terms_names_the_wrong_terms(monkeypatch):
    def missing(client, ctx, examples):
        examples.extend(["ner term 7", "email_address term 9"])
        return 2

    monkeypatch.setattr(selectors, "missing_search_terms", missing)
    assert settle(monkeypatch, "search_terms") == (
        False, "2 filter terms remain absent or incorrect, for example ner term 7, email_address term 9.")


def test_example_hashes_read_a_bounded_sorted_list():
    seen = {}

    class Client:
        def query(self, sql, parameters):
            seen.update(sql=sql, parameters=parameters)
            return type("R", (), {"result_rows": [("a",), ("b",)]})()

    selection = selectors.Selection(2, 0, 2, "SELECT hash FROM x WHERE d = {cd:String}", {"cd": "d"})
    assert selectors.example_hashes(Client(), selection) == ["a", "b"]
    assert seen["sql"].endswith("ORDER BY hash LIMIT 5")
    assert seen["parameters"] == {"cd": "d"}
    assert selectors.example_hashes(Client(), selectors.Selection()) == []
