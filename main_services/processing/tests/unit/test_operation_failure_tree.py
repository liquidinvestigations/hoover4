"""Failure-tree walker: recorded history, caps, dropped count, signature."""

import json
from pathlib import Path

from tasks.operation_failure_tree import (
    NODE_CAP,
    STACK_TRACE_CAP,
    assemble_tree,
    cap_stack_trace,
    compute_signature,
    walk_failure_tree,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())["events"]


def _fetch_recorded(wid: str, rid: str):
    if wid == "parent-wf":
        return _load("operation_failure_parent_history.json")
    if wid == "child-wf":
        return _load("operation_failure_child_history.json")
    return None


def test_walk_names_failing_activity_and_worker_stack():
    result = walk_failure_tree("parent-wf", "parent-run", _fetch_recorded, stage="P2")
    assert result.nodes, "the recorded parent history must produce nodes"
    activity = next(
        (n for n in result.nodes if n.task_name == "extract_plaintext_chunks"),
        None,
    )
    assert activity is not None, (
        "walk must recurse into ChildWorkflowExecutionFailed and read the "
        f"activity failure; got {[n.task_name for n in result.nodes]}"
    )
    assert activity.source == "history"
    assert "parse_text.py" in activity.stack_trace
    assert "extract_plaintext_chunks" in activity.stack_trace
    assert activity.error_class == "RuntimeError"
    assert "forced parse failure" in activity.message
    child_wf = next((n for n in result.nodes if n.task_name == "ParseSingleFile"), None)
    assert child_wf is not None
    assert child_wf.source == "history"


def test_chain_node_is_always_source_chain():
    walk = walk_failure_tree("parent-wf", "parent-run", _fetch_recorded)
    chain = (
        "\r\n [level 0]\r\n ActivityError\n"
        "message=Activity task failed\n"
        "type=activityFailed\n"
        'File "/app/tasks/P3_parse_files/parse_text.py", line 26, in extract_plaintext_chunks\n'
    )
    nodes = assemble_tree(
        chain_text=chain,
        walk=walk,
        workflow_id="parent-wf",
        run_id="parent-run",
        task_name="ExecutePlans",
        stage="P2",
    )
    assert nodes[0].source == "chain"
    assert "ActivityError" in (nodes[0].error_class, nodes[0].stack_trace)
    assert any(n.source == "history" for n in nodes)


def test_oversize_stack_is_capped_and_says_truncated():
    huge = ("x" * (STACK_TRACE_CAP + 4096))
    capped = cap_stack_trace(huge)
    assert len(capped.encode("utf-8")) <= STACK_TRACE_CAP
    assert "[truncated to %d bytes]" % STACK_TRACE_CAP in capped

    events = [
        {
            "eventId": "1",
            "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
            "workflowExecutionStartedEventAttributes": {
                "workflowType": {"name": "ParseSingleFile"},
            },
        },
        {
            "eventId": "5",
            "eventType": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
            "activityTaskScheduledEventAttributes": {
                "activityId": "1",
                "activityType": {"name": "extract_plaintext_chunks"},
            },
        },
        {
            "eventId": "7",
            "eventType": "EVENT_TYPE_ACTIVITY_TASK_FAILED",
            "activityTaskFailedEventAttributes": {
                "failure": {
                    "message": "boom",
                    "stackTrace": huge,
                    "applicationFailureInfo": {"type": "RuntimeError"},
                },
                "scheduledEventId": "5",
            },
        },
    ]
    walk = walk_failure_tree("wf", "run", lambda *_: events)
    nodes = assemble_tree(
        chain_text="",
        walk=walk,
        workflow_id="wf",
        run_id="run",
    )
    assert len(nodes) == 1
    assert len(nodes[0].stack_trace.encode("utf-8")) <= STACK_TRACE_CAP
    assert "[truncated to %d bytes]" % STACK_TRACE_CAP in nodes[0].stack_trace


def _many_activity_failures(count: int):
    events = [
        {
            "eventId": "1",
            "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
            "workflowExecutionStartedEventAttributes": {
                "workflowType": {"name": "ProcessItemsBatched"},
            },
        },
    ]
    event_id = 2
    for i in range(count):
        sched_id = event_id
        events.append({
            "eventId": str(sched_id),
            "eventType": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
            "activityTaskScheduledEventAttributes": {
                "activityId": str(i),
                "activityType": {"name": "extract_plaintext_chunks"},
            },
        })
        event_id += 1
        events.append({
            "eventId": str(event_id),
            "eventType": "EVENT_TYPE_ACTIVITY_TASK_FAILED",
            "activityTaskFailedEventAttributes": {
                "failure": {
                    "message": "fail-%d" % i,
                    "stackTrace": (
                        'File "/app/tasks/P3_parse_files/parse_text.py", '
                        "line 26, in extract_plaintext_chunks\n"
                    ),
                    "applicationFailureInfo": {"type": "RuntimeError"},
                },
                "scheduledEventId": str(sched_id),
            },
        })
        event_id += 1
    return events


def test_over_deep_tree_records_dropped_count():
    events = _many_activity_failures(NODE_CAP + 50)
    walk = walk_failure_tree("wf", "run", lambda *_: events)
    nodes = assemble_tree(
        chain_text="chain-root",
        walk=walk,
        workflow_id="wf",
        run_id="run",
        task_name="ProcessItemsBatched",
        stage="P2",
    )
    assert len(nodes) <= NODE_CAP
    assert nodes[0].nodes_dropped > 0
    details = json.loads(nodes[0].details_json or "{}")
    assert details.get("truncated") is True
    assert details.get("truncated_reason")


def test_signature_uses_innermost_file_and_function_without_line():
    stack = (
        'File "/app/tasks/heartbeat.py", line 191, in wrapper\n'
        "    return fn(*args, **kwargs)\n"
        'File "/app/tasks/P3_parse_files/parse_text.py", line 26, '
        "in extract_plaintext_chunks\n"
        '    raise RuntimeError("forced")\n'
    )
    signature = compute_signature("RuntimeError", "ApplicationFailure", stack)
    assert "RuntimeError" in signature
    assert "ApplicationFailure" in signature
    assert "parse_text.py" in signature
    assert "extract_plaintext_chunks" in signature
    assert "26" not in signature
    assert "line" not in signature


def test_capture_params_stay_under_temporal_blob_limit():
    """The activity input is ids plus one capped chain, never the tree."""
    from temporalio.converter import default as default_converter

    from tasks.operation_failure_capture import (
        TEMPORAL_BLOB_LIMIT_BYTES,
        TEMPORAL_BLOB_MARGIN_BYTES,
        CaptureOperationFailureParams,
    )

    params = CaptureOperationFailureParams(
        op_id="op-id",
        workflow_id="wf",
        run_id="run",
        chain="x" * STACK_TRACE_CAP,
    )
    payloads = default_converter().payload_converter.to_payloads([params])
    size = sum(len(p.data) for p in payloads)
    assert size < TEMPORAL_BLOB_LIMIT_BYTES - TEMPORAL_BLOB_MARGIN_BYTES


def test_failed_child_history_read_keeps_what_it_has():
    def fetch(wid: str, rid: str):
        if wid == "parent-wf":
            return _load("operation_failure_parent_history.json")
        return None

    result = walk_failure_tree("parent-wf", "parent-run", fetch)
    assert result.truncated is True
    assert result.truncated_reason == "history_read_failed"
    assert any(n.task_name == "ParseSingleFile" for n in result.nodes)
    assert not any(n.task_name == "extract_plaintext_chunks" for n in result.nodes)


def test_temporal_http_json_drops_invalid_workflow_input():
    from tasks.operation_failure_capture import loads_temporal_http_json

    body = (
        '{"history":{"events":[{"eventType":"EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",'
        '"workflowExecutionStartedEventAttributes":{"input":[{"recursivity_depth":'
        '"starting_plan_hash":}],"workflowRunTimeout":"0s"}}]}}'
    )
    payload = loads_temporal_http_json(body)
    events = payload["history"]["events"]
    assert events[0]["eventType"] == "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED"
    assert events[0]["workflowExecutionStartedEventAttributes"]["input"] == []
