from types import SimpleNamespace
import json
import asyncio

import pytest

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
    monkeypatch.setattr(ledger, "selection_snapshot", lambda *_args: None)
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
        "events", "events", "events", "events", "delete", "nlp", "regex", "reopen"
    ]
    assert calls[3][1][0]["event"] == "selection_complete"
    assert result.errors_before_run == 4


def test_reconciliation_preserves_current_errors_and_records_outcomes(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    client = _Client(
        [("FROM processing_document_outcomes", [
            ("h-recovered", "P4_ScanRegexEntities", "scan_regex_entities_for_hashes")
        ])]
    )
    calls = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(
        ledger,
        "pairs_with_event",
        lambda *_args: [
            ("h-recovered", "P4_ScanRegexEntities"),
            ("h-fail", "P4_ScanRegexEntities"),
        ] if _args[-1] == "selected" else [("h-fail", "P4_ScanRegexEntities")],
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
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.reconcile_selected_errors(
        ReconcileErrorsParams("op", "collection", "dataset")
    )

    assert result == {"recovered_errors": 1, "still_failing_errors": 1,
                      "unknown_task_errors": 0}
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


def test_incomplete_snapshot_removes_partial_events_synchronously(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger

    client = _Client([("event = 'selection_complete'", [])])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)

    assert ledger.selection_snapshot("collection", "op", "dataset") is None
    assert "ALTER TABLE operation_error_events DELETE" in client.commands[0][0]
    assert client.commands[0][2] == {"mutations_sync": 2}


def test_empty_selection_writes_complete_zero_marker(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    import tasks.P_admin.failed_file_retry as retry

    client = _Client([("SELECT DISTINCT hash, task_name FROM processing_errors", [])])
    events = []
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(ledger, "selection_snapshot", lambda *_args: None)
    monkeypatch.setattr(ledger, "insert_error_events", lambda _name, rows:
                        events.extend(rows))
    monkeypatch.setattr(retry, "plans_for_hashes", lambda *_args: [])
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.select_historical_errors(
        SelectErrorsParams("op", "collection", "dataset"))

    assert result.errors_before_run == 0
    assert len(events) == 1
    assert events[0]["event"] == "selection_complete"
    assert json.loads(events[0]["error_logs"])["selected"] == 0


def test_complete_snapshot_preserves_count_after_error_deletion(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger

    counts = {"errors_before_run": 2, "selected": 1,
              "removed_stage_off": 1, "without_plan": 0,
              "task_name": "P4_ExtractEntities", "hash": ""}
    client = _Client([
        ("event = 'selection_complete'", [(json.dumps(counts),)]),
        ("event IN ('selected'", [
            ("h1", "P4_ExtractEntities", "selected"),
            ("h2", "P4_ExtractEntities", "removed_stage_off"),
        ]),
    ])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    stored, classes = ledger.selection_snapshot("collection", "op", "dataset")

    assert stored["errors_before_run"] == 2
    assert classes["selected"] == [("h1", "P4_ExtractEntities")]
    assert client.commands == []


def test_selector_retry_uses_filtered_snapshot_after_disabled_row_deletion(monkeypatch):
    import database.operation_ledger as ledger
    import tasks.P_admin.failed_file_retry as retry

    counts = {"errors_before_run": 1, "selected": 0,
              "removed_stage_off": 1, "without_plan": 0,
              "task_name": "P4_ExtractEntities", "hash": "h"}
    classes = {"selected": [], "removed_stage_off": [("h", "P4_ExtractEntities")],
               "without_plan": []}
    monkeypatch.setattr(ledger, "selection_snapshot", lambda *_args:
                        (counts, classes))
    monkeypatch.setattr(rerun_selection, "_candidate_pairs", lambda _params:
                        pytest.fail("A complete retry must not read changed Errors"))
    deleted = []
    monkeypatch.setattr(ledger, "delete_error_pairs", lambda *_args:
                        deleted.extend(_args[-1]))
    monkeypatch.setattr(retry, "plans_for_hashes", lambda *_args: [])
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.select_historical_errors(SelectErrorsParams(
        "op", "collection", "dataset", "P4_ExtractEntities", "h"))

    assert result.errors_before_run == 1
    assert result.removed_stage_off_errors == 1
    assert deleted == [("h", "P4_ExtractEntities")]


def test_complete_snapshot_rejects_partial_class_events(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger

    client = _Client([
        ("event = 'selection_complete'", [(json.dumps({
            "errors_before_run": 2, "selected": 2,
            "removed_stage_off": 0, "without_plan": 0,
        }),)]),
        ("event IN ('selected'", [("h1", "P5_ChunkEmbed", "selected")]),
    ])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    with pytest.raises(ValueError, match="does not match"):
        ledger.selection_snapshot("collection", "op", "dataset")


def test_recovery_needs_exact_outcome_and_current_error_veto(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger

    selected = [(f"h{i}", "P6_IndexTextPages") for i in range(1, 5)]
    selected += [("h5", "parse_office_xml_and_store"),
                 ("h6", "unknown_task")]
    client = _Client([("FROM processing_document_outcomes", [
        ("h1", "P6_IndexTextPages", "index_text_pages"),
        ("h2", "P6_IndexTextPages", "index_text_pages"),
        ("h5", "parse_office_xml_and_store", "parse_office_xml_and_store"),
    ])])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(ledger, "pairs_with_event", lambda *_args:
                        selected if _args[-1] == "selected" else
                        [("h2", "P6_IndexTextPages"),
                         ("h5", "parse_office_xml_and_store")])
    deleted = []
    monkeypatch.setattr(ledger, "delete_error_pairs", lambda *_args:
                        deleted.extend(_args[-1]))
    monkeypatch.setattr(ledger, "insert_error_events", lambda *_args: None)
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.reconcile_selected_errors(
        ReconcileErrorsParams("op", "collection", "dataset"))

    assert result == {"recovered_errors": 1, "still_failing_errors": 4,
                      "unknown_task_errors": 1}
    assert set(deleted) == set(selected)
    assert "r.activity_id = o.activity_id" in client.queries[0][0]
    assert "r.outcome = o.outcome" in client.queries[0][0]


def test_reconciliation_deletes_selected_older_rows_on_retry(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger

    supported = ("h-unproven", "P6_IndexTextPages")
    unknown = ("h-unknown", "unknown_task")
    recovered = ("h-recovered", "P6_IndexTextPages")
    replaced = ("h-replaced", "P6_IndexTextPages")
    current_only = ("h-current", "P6_IndexTextPages")
    selected = [supported, unknown, recovered, replaced]
    older_rows = set(selected) | {current_only}
    current_rows = {replaced, current_only}
    events = []

    class DeletingClient(_Client):
        def command(self, query, parameters, settings):
            super().command(query, parameters, settings)
            assert "ALTER TABLE processing_errors DELETE" in query
            assert settings == {"mutations_sync": 2}
            assert parameters["op"] == "op"
            for key in parameters["keys"]:
                older_rows.discard(tuple(key.split(chr(31), 1)))

    client = DeletingClient([("FROM processing_document_outcomes", [
        (recovered[0], recovered[1], "index_text_pages"),
    ])])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(ledger, "pairs_with_event", lambda *_args:
                        selected if _args[-1] == "selected" else list(current_rows))
    monkeypatch.setattr(ledger, "insert_error_events", lambda _name, rows:
                        events.extend(rows))
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)
    params = ReconcileErrorsParams("op", "collection", "dataset")

    for _ in range(2):
        assert rerun_selection.reconcile_selected_errors(params) == {
            "recovered_errors": 1, "still_failing_errors": 2,
            "unknown_task_errors": 1,
        }
        assert older_rows == set()

    assert len(client.commands) == 2
    assert {tuple(key.split(chr(31), 1)) for key in client.commands[0][1]["keys"]} == {
        supported, unknown, recovered, replaced, current_only,
    }
    assert [row["event"] for row in events].count("recovered") == 2
    assert [row["event"] for row in events].count("still_failing") == 4


def test_office_xml_direct_error_vetoes_same_execution_outcome(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    import tasks.P2_execute_plan.activities as error_writer
    import tasks.P3_parse_files.parse_office_xml as office
    import tasks.P3_parse_files.parse_common as parse_common
    from tasks import task_timing
    from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput

    params = office.ParseOfficeXmlParams(
        "collection", "dataset", "hash", "/tmp/document.docx", 30, "op")
    monkeypatch.setattr(office, "extract_office_xml_text", lambda *_args, **_kwargs:
                        SimpleNamespace(ok=False, kind="docx", dropped=["bad part"],
                                        parts_read=[], text=""))
    error_rows = []
    monkeypatch.setattr(error_writer, "record_processing_errors", lambda arg:
                        error_rows.extend(arg.errors))
    fields = SimpleNamespace(
        task_name="parse_office_xml_and_store", attempt=1, task_queue="queue",
        scheduled_at=task_timing._EPOCH, schedule_to_start_ms=0,
        retry_backoff_ms=0, workflow_id="workflow", workflow_run_id="run",
        workflow_type="ParseSingleFile", activity_id="activity")
    monkeypatch.setattr(parse_common.activity, "info", lambda: fields)
    monkeypatch.setattr(task_timing, "_activity_fields", lambda _input: fields)
    monkeypatch.setattr(task_timing, "_recorder", SimpleNamespace(
        begin=lambda *_args: 1, end=lambda _token: None))
    written = []
    monkeypatch.setattr(task_timing, "_write_operation_result", lambda _collection,
                        row, outcomes: written.append((row, outcomes)))

    class Next(ActivityInboundInterceptor):
        def __init__(self):
            pass

        async def execute_activity(self, _input):
            return office.parse_office_xml_and_store.__wrapped__(params)

    input = ExecuteActivityInput(
        fn=office.parse_office_xml_and_store, args=[params], executor=None, headers={})
    result = asyncio.run(task_timing._TimingActivityInbound(Next()).execute_activity(input))
    assert isinstance(result, dict)
    assert error_rows[0]["op_id"] == "op"
    assert error_rows[0]["hash"] == "hash"
    [run_row], outcomes = written[0]
    columns = dict(zip(task_timing._RUNS_COLUMNS, run_row))
    assert columns["outcome"] == "ok"
    assert columns["op_id"] == outcomes[0][0] == "op"
    assert (columns["workflow_run_id"], columns["activity_id"], columns["attempt"]) == \
        (outcomes[0][5], outcomes[0][6], outcomes[0][7])

    client = _Client([("FROM processing_document_outcomes", [
        ("hash", "parse_office_xml_and_store", "parse_office_xml_and_store")])])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    pair = ("hash", "parse_office_xml_and_store")
    monkeypatch.setattr(ledger, "pairs_with_event", lambda *_args: [pair])
    monkeypatch.setattr(ledger, "delete_error_pairs", lambda *_args: None)
    monkeypatch.setattr(ledger, "insert_error_events", lambda *_args: None)
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)
    counts = rerun_selection.reconcile_selected_errors(
        ReconcileErrorsParams("op", "collection", "dataset"))
    assert counts["recovered_errors"] == 0
    assert counts["still_failing_errors"] == 1


def _join_outcomes_to_runs(outcomes, runs):
    """The join of `reconcile_selected_errors`, over rows that the interceptor built."""
    from tasks.task_timing import _OUTCOME_COLUMNS, _RUNS_COLUMNS

    o_at = {name: index for index, name in enumerate(_OUTCOME_COLUMNS)}
    r_at = {name: index for index, name in enumerate(_RUNS_COLUMNS)}
    joined = set()
    for o in outcomes:
        for r in runs:
            if (r[r_at["op_id"]] == o[o_at["op_id"]]
                    and r[r_at["collection_dataset"]] == o[o_at["collection_dataset"]]
                    and r[r_at["task_name"]] == o[o_at["activity_name"]]
                    and r[r_at["workflow_run_id"]] == o[o_at["workflow_run_id"]]
                    and r[r_at["activity_id"]] == o[o_at["activity_id"]]
                    and r[r_at["attempt"]] == o[o_at["attempt"]]
                    and r[r_at["outcome"]] == o[o_at["outcome"]]
                    and o[o_at["outcome"]] in ("ok", "skipped")):
                joined.add((o[o_at["hash"]], o[o_at["error_task_name"]],
                            o[o_at["activity_name"]]))
    return sorted(joined)


def test_two_files_of_one_stage_activity_each_prove_their_own_recovery(monkeypatch):
    import database.clickhouse as clickhouse
    import database.operation_ledger as ledger
    from tasks import task_timing
    from tasks.P3_parse_files.batch_runner import BatchResult, FileResult

    fields = SimpleNamespace(workflow_run_id="run", activity_id="3", attempt=1)
    stage_row = [None] * len(task_timing._RUNS_COLUMNS)
    columns = list(task_timing._RUNS_COLUMNS)
    for name, value in (("collection_dataset", "dataset"), ("op_id", "op"),
                        ("workflow_run_id", "run"), ("activity_id", "3"), ("attempt", 1)):
        stage_row[columns.index(name)] = value
    batch = BatchResult(stage="extract_plaintext_batch", results=[
        FileResult("h1", "extract_plaintext_chunks", "ok"),
        FileResult("h2", "extract_plaintext_chunks", "skipped"),
        FileResult("h3", "extract_plaintext_chunks", "ok"),
    ])
    runs, outcomes = task_timing._batch_rows(batch, stage_row, fields, "op", "dataset", "")

    selected = [("h1", "extract_plaintext_chunks"), ("h2", "extract_plaintext_chunks"),
                ("h3", "extract_plaintext_chunks"), ("h4", "unknown_task")]
    client = _Client([("FROM processing_document_outcomes",
                       _join_outcomes_to_runs(outcomes, runs))])
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: client)
    monkeypatch.setattr(ledger, "pairs_with_event", lambda *_args:
                        selected if _args[-1] == "selected"
                        else [("h3", "extract_plaintext_chunks")])
    monkeypatch.setattr(ledger, "delete_error_pairs", lambda *_args: None)
    monkeypatch.setattr(ledger, "insert_error_events", lambda *_args: None)
    monkeypatch.setattr(rerun_selection.activity, "heartbeat", lambda: None)

    result = rerun_selection.reconcile_selected_errors(
        ReconcileErrorsParams("op", "collection", "dataset"))

    # h1 and h2 recovered. h3 has an outcome row and a current Error. h4 has no
    # recovery activity.
    assert result == {"recovered_errors": 2, "still_failing_errors": 1,
                      "unknown_task_errors": 1}
