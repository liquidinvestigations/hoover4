from types import SimpleNamespace

from tasks.P_admin import rerun_selection
from tasks.P_admin.rerun_params import ReconcileErrorsParams, SelectErrorsParams


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def query(self, query, parameters):
        self.queries.append((query, parameters))
        for marker, rows in self.rows:
            if marker in query:
                return SimpleNamespace(result_rows=rows)
        raise AssertionError(query)

    def command(self, query, parameters, settings):
        self.commands.append((query, parameters, settings))


def test_selection_records_events_before_deleting_or_reopening(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    import database.operations as operations
    import tasks.P_admin.failed_file_retry as retry
    import tasks.P_admin.stage_eligibility as eligibility

    client = _Client(
        [
            ("SELECT count() FROM (SELECT DISTINCT", [(4,)]),
            (
                "SELECT DISTINCT hash, task_name FROM processing_errors",
                [
                    ("h-off", "P4_ExtractEntities"),
                    ("", "P3_ParseSingleFile"),
                    ("h-none", "extract_plaintext_chunks"),
                    ("h-good", "some_unknown_task"),
                ],
            ),
            ("FROM processing_plan_hits", [("h-good", "plan-good")]),
        ]
    )
    calls = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(operations, "merge_detail", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ledger,
        "insert_error_events",
        lambda _collection, rows: calls.append(("events", rows)),
    )
    monkeypatch.setattr(
        ledger,
        "delete_error_pairs",
        lambda *_args: calls.append(("delete", _args[-1])),
    )
    monkeypatch.setattr(
        retry,
        "clear_nlp_state",
        lambda *_args: calls.append(("nlp", _args[-1])),
    )
    monkeypatch.setattr(
        retry,
        "clear_regex_state",
        lambda *_args: calls.append(("regex", _args[-1])),
    )
    monkeypatch.setattr(
        retry,
        "plans_for_hashes",
        lambda *_args: ["plan-good"],
    )
    monkeypatch.setattr(
        retry,
        "reopen_plans",
        lambda *_args: calls.append(("reopen", _args[-1])),
    )
    monkeypatch.setattr(
        eligibility,
        "stage_is_off",
        lambda task_name, _dataset: task_name == "P4_ExtractEntities",
    )
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.select_historical_errors(
        SelectErrorsParams("op", "collection", "dataset")
    )

    assert result.selected_errors == 1
    assert result.plan_hashes == ["plan-good"]
    assert [name for name, _ in calls] == [
        "events", "events", "events", "delete", "nlp", "regex", "reopen"
    ]


def test_reconciliation_preserves_current_errors_and_records_outcomes(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    import database.operations as operations

    client = _Client(
        [("FROM processing_errors", [("h-fail", "P4_ScanRegexEntities")])]
    )
    calls = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(
        ledger,
        "pairs_with_event",
        lambda *_args: [
            ("h-recovered", "P4_ScanRegexEntities"),
            ("h-fail", "P4_ScanRegexEntities"),
        ],
    )
    monkeypatch.setattr(
        ledger,
        "delete_error_pairs",
        lambda *_args: calls.append(("delete", _args[-1])),
    )
    monkeypatch.setattr(
        ledger,
        "insert_error_events",
        lambda _collection, rows: calls.append(("events", rows)),
    )
    monkeypatch.setattr(operations, "merge_detail", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.reconcile_selected_errors(
        ReconcileErrorsParams("op", "collection", "dataset")
    )

    assert result == "reconciled 2 Error pairs"
    assert calls[0][0] == "delete"
    assert {row["event"] for _, rows in calls[1:] for row in rows} == {
        "recovered",
        "still_failing",
    }


def test_clear_regex_state_deletes_the_watermark_before_hits(monkeypatch):
    import database.clickhouse as clickhouse
    import tasks.P_admin.failed_file_retry as retry

    client = _Client(
        [
            ("FROM regex_scanned", [(2,)]),
            ("FROM regex_entity_hit", [(3,)]),
        ]
    )
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)

    assert retry.clear_regex_state("collection", "dataset", ["hash"]) == (2, 3)
    assert "ALTER TABLE regex_scanned DELETE" in client.commands[0][0]
    assert "ALTER TABLE regex_entity_hit DELETE" in client.commands[1][0]
