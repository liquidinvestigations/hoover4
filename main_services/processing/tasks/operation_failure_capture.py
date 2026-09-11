"""Capture an operation failure tree into ``operation_failures``.

The activity fetches Temporal history over HTTP and writes ClickHouse itself, so
the tree is never an activity argument. A 200-node tree of 64 KB traces is larger
than the Temporal blob limit of 2097121 bytes. Passing that tree as input would
fail the caller, which is the defect this capture must not recreate.

Every write is wrapped. ClickHouse being unreachable logs and returns. It does
not raise into the workflow that is already failing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from temporalio import activity
from temporalio.worker import (
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)

from tasks.heartbeat import HEARTBEAT_TIMEOUT, with_heartbeat
from tasks.operation_failure_tree import (
    FailureNode,
    STACK_TRACE_CAP,
    apply_index_base,
    assemble_tree,
    cap_stack_trace,
    capture_index_base,
    history_events,
    stage_for_workflow,
    walk_failure_tree,
)

log = logging.getLogger(__name__)

#: Live Temporal ``limit.blobSize.error`` on this stack. The tree must not be
#: sent as one activity argument. Named so a reader can check a payload against
#: it without guessing a default.
TEMPORAL_BLOB_LIMIT_BYTES = 2097121

#: Bytes kept in reserve under that limit. The capture activity's input is the
#: params dataclass (ids plus one capped chain string), which stays under this
#: ceiling by construction.
TEMPORAL_BLOB_MARGIN_BYTES = 256 * 1024

FAILURE_COLUMNS = [
    "op_id", "node_index", "depth", "parent_index",
    "error_class", "error_type", "message", "stack_trace", "signature",
    "task_name", "workflow_id", "run_id", "activity_id", "attempt",
    "collectionname", "collection_dataset", "stage", "details_json",
    "source", "nodes_dropped", "captured_at",
]

_SKIP_WORKFLOW_TYPES = frozenset({
    "Operation",
    "CollectEtaSamples",
    "SweepChatArtifacts",
    "ChatTurn",
    "ResearchTask",
})


@dataclass
class CaptureOperationFailureParams:
    """What the capture activity needs. The tree is not in this object."""

    op_id: str
    workflow_id: str
    run_id: str
    collectionname: str = ""
    collection_dataset: str = ""
    stage: str = ""
    chain: str = ""
    capturing_workflow_id: str = ""
    capturing_run_id: str = ""
    task_name: str = ""


@activity.defn
@with_heartbeat
def capture_operation_failure(params: CaptureOperationFailureParams) -> str:
    """Fetch history, assemble the tree, write ``operation_failures``. Never raises."""
    try:
        return _capture_operation_failure_body(params)
    except Exception:
        log.exception("operation failure capture failed")
        return "failed"


def _capture_operation_failure_body(params: CaptureOperationFailureParams) -> str:
    chain = cap_stack_trace(params.chain or "")
    cache: Dict[Tuple[str, str], Optional[List[Dict[str, Any]]]] = {}

    def fetch(workflow_id: str, run_id: str) -> Optional[List[Dict[str, Any]]]:
        key = (workflow_id, run_id)
        if key not in cache:
            cache[key] = _fetch_history_http(workflow_id, run_id)
        return cache[key]

    capturing_wid = params.capturing_workflow_id or params.workflow_id
    capturing_rid = params.capturing_run_id or params.run_id
    op_id = _resolve_op_id(params.op_id, params.workflow_id, params.run_id)
    walk = walk_failure_tree(
        params.workflow_id,
        params.run_id,
        fetch,
        stage=params.stage,
    )
    nodes = assemble_tree(
        chain_text=chain,
        walk=walk,
        workflow_id=params.workflow_id,
        run_id=params.run_id,
        task_name=params.task_name,
        stage=params.stage,
    )
    if not nodes:
        return "empty"
    base = capture_index_base(op_id, capturing_wid, capturing_rid)
    nodes = apply_index_base(nodes, base)
    captured_at = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = [
        _row(op_id, node, params.collectionname, params.collection_dataset, captured_at)
        for node in nodes
    ]
    written = _insert_rows(rows)
    return f"wrote {written}"


async def capture_failure_best_effort(
    exc: BaseException,
    *,
    op_id: str = "",
    collectionname: str = "",
    collection_dataset: str = "",
    stage: str = "",
    task_name: str = "",
) -> None:
    """Schedule the capture activity. Swallows every error from that path."""
    from temporalio import workflow
    from temporalio.common import RetryPolicy

    if _is_cancellation(exc):
        return
    try:
        from tasks.P3_parse_files.parse_common import format_temporal_exception_chain
        chain = cap_stack_trace(format_temporal_exception_chain(exc))
        info = workflow.info()
        params = CaptureOperationFailureParams(
            op_id=op_id or "",
            workflow_id=info.workflow_id,
            run_id=info.run_id,
            collectionname=collectionname,
            collection_dataset=collection_dataset,
            stage=stage or stage_for_workflow(info.workflow_type),
            chain=chain,
            capturing_workflow_id=info.workflow_id,
            capturing_run_id=info.run_id,
            task_name=task_name or info.workflow_type,
        )
        await workflow.execute_activity(
            capture_operation_failure,
            params,
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
    except Exception as err:
        try:
            workflow.logger.warning(
                "operation failure capture failed: %s", type(err).__name__)
        except Exception:
            pass


class OperationFailureInterceptor(Interceptor):
    """Capture a failing pipeline workflow. ``Operation`` does this itself."""

    def workflow_interceptor_class(self, input: WorkflowInterceptorClassInput):
        return _FailureCaptureInbound


class _FailureCaptureInbound(WorkflowInboundInterceptor):
    async def execute_workflow(self, input: ExecuteWorkflowInput):
        try:
            return await self.next.execute_workflow(input)
        except Exception as exc:
            wf_type = getattr(input.type, "__name__", "") or ""
            if wf_type in _SKIP_WORKFLOW_TYPES:
                raise
            collectionname, collection_dataset = _scope_from_arg(
                input.args[0] if input.args else None)
            await capture_failure_best_effort(
                exc,
                collectionname=collectionname,
                collection_dataset=collection_dataset,
                stage=stage_for_workflow(wf_type),
                task_name=wf_type,
            )
            raise


def _scope_from_arg(arg: Any) -> Tuple[str, str]:
    if arg is None:
        return "", ""
    if isinstance(arg, dict):
        return (
            str(arg.get("collectionname") or ""),
            str(arg.get("collection_dataset") or ""),
        )
    return (
        str(getattr(arg, "collectionname", "") or ""),
        str(getattr(arg, "collection_dataset", "") or ""),
    )


def _is_cancellation(exc: BaseException) -> bool:
    seen = 0
    current: Optional[BaseException] = exc
    while current is not None and seen < 5:
        if type(current).__name__ == "CancelledError":
            return True
        current = current.__cause__
        seen += 1
    return False


def _resolve_op_id(
    explicit: str,
    workflow_id: str,
    run_id: str,
) -> str:
    """Walk parent executions via the describe API until a root, which is the op_id.

    History JSON from the HTTP API can be invalid when a workflow input omits a
    field, so parent identity is taken from describe instead of from the started
    event.
    """
    if explicit:
        return explicit
    wid, rid = workflow_id, run_id
    seen = set()
    last = wid
    while (wid, rid) not in seen:
        seen.add((wid, rid))
        parent = _describe_parent(wid, rid)
        if not parent:
            return wid
        last = parent[0]
        wid, rid = parent
    return last


def _temporal_http_base() -> str:
    import os
    return os.environ.get("TEMPORAL_HTTP_URL", "http://temporal:7243").rstrip("/")


def _describe_parent(workflow_id: str, run_id: str) -> Optional[Tuple[str, str]]:
    from urllib.parse import quote

    import requests

    params = {}
    if run_id:
        params["execution.runId"] = run_id
    url = (
        f"{_temporal_http_base()}/api/v1/namespaces/default/workflows/"
        f"{quote(workflow_id, safe='')}"
    )
    try:
        response = requests.get(url, params=params, timeout=(2, 30))
        response.raise_for_status()
        payload = response.json()
    except Exception:
        log.exception(
            "operation failure capture: describe failed for %s", workflow_id)
        return None
    info = payload.get("workflowExecutionInfo") or {}
    parent = info.get("parentExecution") or {}
    wid = str(parent.get("workflowId") or "")
    rid = str(parent.get("runId") or "")
    if wid:
        return wid, rid
    return None


_INPUT_PAYLOAD_RE = re.compile(
    r'"input":\[.*?\],"workflowRunTimeout"',
    re.DOTALL,
)


def loads_temporal_http_json(text: str) -> dict:
    """Parse a Temporal HTTP JSON body, dropping invalid workflow-input payloads.

    The HTTP history encoder can emit a missing input field as two keys in a row,
    which is not JSON. Failure events do not need that input, so it is replaced
    with an empty list and the rest of the body is kept.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        repaired = _INPUT_PAYLOAD_RE.sub(
            '"input":[],"workflowRunTimeout"', text)
        return json.loads(repaired)


def _fetch_history_http(workflow_id: str, run_id: str) -> Optional[List[Dict[str, Any]]]:
    from urllib.parse import quote

    import requests

    events: List[Dict[str, Any]] = []
    token = ""
    try:
        while True:
            params = {"maximumPageSize": "1000"}
            if run_id:
                params["execution.runId"] = run_id
            if token:
                params["nextPageToken"] = token
            url = (
                f"{_temporal_http_base()}/api/v1/namespaces/default/workflows/"
                f"{quote(workflow_id, safe='')}/history"
            )
            response = requests.get(url, params=params, timeout=(2, 30))
            response.raise_for_status()
            payload = loads_temporal_http_json(response.text)
            events.extend(history_events(payload))
            token = payload.get("nextPageToken") or ""
            if not token:
                return events
    except Exception:
        log.exception(
            "operation failure capture: history read failed for %s", workflow_id)
        return None


def _row(
    op_id: str,
    node: FailureNode,
    collectionname: str,
    collection_dataset: str,
    captured_at: datetime,
) -> list:
    return [
        op_id,
        int(node.node_index),
        int(node.depth),
        int(node.parent_index),
        node.error_class or "",
        node.error_type or "",
        node.message or "",
        node.stack_trace or "",
        node.signature or "",
        node.task_name or "",
        node.workflow_id or "",
        node.run_id or "",
        node.activity_id or "",
        int(node.attempt or 0),
        collectionname or "",
        collection_dataset or "",
        node.stage or "",
        node.details_json or "",
        node.source or "history",
        int(node.nodes_dropped or 0),
        captured_at,
    ]


def _insert_rows(rows: Sequence[list]) -> int:
    """Insert the whole tree in one statement.

    A chunked insert can store a prefix and then fail. The screen treats
    ``nodes_dropped > 0`` as truncated, and a later-chunk failure would not set
    that flag. One statement either stores every node or stores none.
    """
    from database.clickhouse import get_global_client, insert_idempotent

    if not rows:
        return 0
    try:
        with get_global_client() as client:
            insert_idempotent(
                client,
                "operation_failures",
                list(rows),
                column_names=FAILURE_COLUMNS,
            )
        return len(rows)
    except Exception:
        log.exception("operation_failures ClickHouse is unreachable")
        return 0
