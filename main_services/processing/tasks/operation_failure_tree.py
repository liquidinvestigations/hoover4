"""Build a failure tree from Temporal history JSON, with caps and a grouping signature.

The walker is a pure function over already-fetched history. It does not call Temporal
or ClickHouse. The capture activity fetches history itself so the tree never crosses
the Temporal activity-input blob limit.
"""

from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

#: Cap on one node's stack_trace, in UTF-8 bytes.
STACK_TRACE_CAP = 64 * 1024

#: Cap on stored nodes for one capture of one operation.
NODE_CAP = 200

#: How deep a child-workflow walk may go. Stops a cycle.
MAX_WALK_DEPTH = 32

#: Local indices per capture sit in 8 bits, which holds the 200-node cap.
_INDEX_SLOT = 256

#: Slots 1 .. 2^24-1 identify a non-root capture. Slot 0 is the Operation walk.
_INDEX_SLOTS = (1 << 24) - 1

_FRAME_RE = re.compile(r'File "([^"]+)", line \d+, in (\S+)')
_TRUNCATION_MARKER = "\n[truncated to %d bytes]"

FetchHistory = Callable[[str, str], Optional[Sequence[Dict[str, Any]]]]


@dataclass
class FailureNode:
    """One node of a failure tree, before it is written to ClickHouse."""

    node_index: int
    depth: int
    parent_index: int
    error_class: str
    error_type: str
    message: str
    stack_trace: str
    signature: str = ""
    task_name: str = ""
    workflow_id: str = ""
    run_id: str = ""
    activity_id: str = ""
    attempt: int = 0
    stage: str = ""
    details_json: str = ""
    source: str = "history"
    nodes_dropped: int = 0


@dataclass
class WalkResult:
    """The nodes of one walk, plus what the caps and a failed read did."""

    nodes: List[FailureNode] = field(default_factory=list)
    dropped: int = 0
    truncated: bool = False
    truncated_reason: str = ""


def cap_stack_trace(text: str, limit: int = STACK_TRACE_CAP) -> str:
    """Return ``text`` if it fits, otherwise a prefix plus a truncation marker.

    The result is at most ``limit`` UTF-8 bytes. A reader who sees the marker can
    tell the stored trace is incomplete.
    """
    if not text:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    marker = _TRUNCATION_MARKER % limit
    marker_bytes = marker.encode("utf-8")
    budget = max(0, limit - len(marker_bytes))
    clipped = raw[:budget].decode("utf-8", errors="ignore")
    return clipped + marker


def innermost_frame(stack_trace: str) -> Tuple[str, str]:
    """The file and function of the innermost Python frame, with no line number."""
    matches = _FRAME_RE.findall(stack_trace or "")
    if not matches:
        return "", ""
    return matches[-1]


def compute_signature(error_class: str, error_type: str, stack_trace: str) -> str:
    """Grouping key: class, Temporal type, innermost file and function.

    A line number is omitted on purpose: an edit above the raise would otherwise
    split one defect into two groups.
    """
    path, func = innermost_frame(stack_trace)
    return "|".join((error_class or "", error_type or "", path, func))


def capture_index_base(op_id: str, capturing_workflow_id: str, capturing_run_id: str) -> int:
    """Node-index origin for one capture of ``op_id``.

    The Operation walk (capturing workflow id equals ``op_id``) uses 0, so its
    tree is a prefix of ``ORDER BY (op_id, node_index)``. A child capture uses a
    hashed non-zero slot so concurrent writers do not share ``node_index``.
    """
    if capturing_workflow_id == op_id:
        return 0
    key = f"{capturing_workflow_id}\0{capturing_run_id}".encode("utf-8")
    slot = (zlib.crc32(key) % _INDEX_SLOTS) + 1
    return slot * _INDEX_SLOT


def apply_index_base(nodes: Sequence[FailureNode], base: int) -> List[FailureNode]:
    """Shift local indices by ``base``. ``parent_index`` of -1 stays -1."""
    shifted: List[FailureNode] = []
    for node in nodes:
        parent = node.parent_index if node.parent_index < 0 else node.parent_index + base
        shifted.append(replace(node, node_index=node.node_index + base, parent_index=parent))
    return shifted


def chain_node(
    chain_text: str,
    *,
    workflow_id: str,
    run_id: str,
    task_name: str = "",
    stage: str = "",
) -> FailureNode:
    """One ``source=chain`` node from ``format_temporal_exception_chain`` output."""
    error_class, error_type, message = _parse_chain_head(chain_text)
    stack = cap_stack_trace(chain_text)
    return FailureNode(
        node_index=0,
        depth=0,
        parent_index=-1,
        error_class=error_class,
        error_type=error_type,
        message=message,
        stack_trace=stack,
        signature=compute_signature(error_class, error_type, stack),
        task_name=task_name,
        workflow_id=workflow_id,
        run_id=run_id,
        stage=stage,
        source="chain",
    )


def assemble_tree(
    *,
    chain_text: str,
    walk: WalkResult,
    workflow_id: str,
    run_id: str,
    task_name: str = "",
    stage: str = "",
    node_cap: int = NODE_CAP,
) -> List[FailureNode]:
    """Chain node first, then history nodes, then the caps.

    The chain is stored even when the history read produced nothing, so a failed
    walk still leaves a record.
    """
    nodes: List[FailureNode] = []
    if chain_text:
        nodes.append(chain_node(
            chain_text,
            workflow_id=workflow_id,
            run_id=run_id,
            task_name=task_name,
            stage=stage,
        ))
    offset = len(nodes)
    dropped = walk.dropped
    truncated = walk.truncated
    truncated_reason = walk.truncated_reason
    for src in walk.nodes:
        node = replace(src)
        node.node_index = src.node_index + offset
        if src.parent_index >= 0:
            node.parent_index = src.parent_index + offset
        node.stack_trace = cap_stack_trace(src.stack_trace)
        node.signature = compute_signature(
            src.error_class, src.error_type, node.stack_trace)
        if not node.stage:
            node.stage = stage
        nodes.append(node)
    if len(nodes) > node_cap:
        extra = len(nodes) - node_cap
        nodes = nodes[:node_cap]
        dropped += extra
        truncated = True
        if not truncated_reason:
            truncated_reason = "node_cap"
    if nodes:
        details = _read_details(nodes[0].details_json)
        if truncated:
            details["truncated"] = True
            if truncated_reason:
                details["truncated_reason"] = truncated_reason
        nodes[0] = replace(
            nodes[0],
            nodes_dropped=dropped,
            details_json=json.dumps(details, ensure_ascii=False) if details else nodes[0].details_json,
        )
    return nodes


def walk_failure_tree(
    workflow_id: str,
    run_id: str,
    fetch_history: FetchHistory,
    *,
    node_cap: int = NODE_CAP,
    max_depth: int = MAX_WALK_DEPTH,
    stage: str = "",
) -> WalkResult:
    """Breadth-first walk of failed activities and failed child workflows.

    ``fetch_history(workflow_id, run_id)`` returns the history events, or ``None``
    when the read fails. A failed read stops the walk. What has already been
    collected is returned, marked truncated.
    """
    result = WalkResult()
    events = fetch_history(workflow_id, run_id)
    if events is None:
        result.truncated = True
        result.truncated_reason = "history_read_failed"
        return result
    queue: List[Tuple[str, str, int, int, Sequence[Dict[str, Any]]]] = [
        (workflow_id, run_id, -1, 0, list(events)),
    ]
    while queue:
        if len(result.nodes) >= node_cap:
            result.dropped += _count_failure_events(queue)
            result.truncated = True
            result.truncated_reason = result.truncated_reason or "node_cap"
            break
        wid, rid, parent_index, depth, hist = queue.pop(0)
        scheduled = _scheduled_index(hist)
        emitted_here = 0
        for event in hist:
            kind = _event_kind(event)
            if kind in ("ACTIVITY_TASK_FAILED", "ACTIVITY_TASK_TIMED_OUT"):
                if len(result.nodes) >= node_cap:
                    result.dropped += 1
                    result.truncated = True
                    result.truncated_reason = result.truncated_reason or "node_cap"
                    continue
                node = _activity_node(
                    event, scheduled,
                    workflow_id=wid, run_id=rid,
                    parent_index=parent_index, depth=depth + (1 if parent_index >= 0 else 0),
                    node_index=len(result.nodes), stage=stage,
                )
                result.nodes.append(node)
                emitted_here += 1
            elif kind in (
                "CHILD_WORKFLOW_EXECUTION_FAILED",
                "CHILD_WORKFLOW_EXECUTION_TIMED_OUT",
            ):
                if len(result.nodes) >= node_cap:
                    result.dropped += 1
                    result.truncated = True
                    result.truncated_reason = result.truncated_reason or "node_cap"
                    continue
                child_wid, child_rid, node = _child_node(
                    event,
                    workflow_id=wid, run_id=rid,
                    parent_index=parent_index,
                    depth=depth + (1 if parent_index >= 0 else 0),
                    node_index=len(result.nodes), stage=stage,
                )
                result.nodes.append(node)
                child_parent = node.node_index
                if not child_wid:
                    continue
                if depth + 1 >= max_depth:
                    result.dropped += 1
                    result.truncated = True
                    result.truncated_reason = result.truncated_reason or "depth_cap"
                    continue
                child_events = fetch_history(child_wid, child_rid)
                if child_events is None:
                    result.truncated = True
                    result.truncated_reason = "history_read_failed"
                    continue
                queue.append((child_wid, child_rid, child_parent, depth + 1, list(child_events)))
            elif kind in ("WORKFLOW_EXECUTION_FAILED", "WORKFLOW_EXECUTION_TIMED_OUT"):
                if parent_index >= 0:
                    continue
                if emitted_here:
                    continue
                if len(result.nodes) >= node_cap:
                    result.dropped += 1
                    result.truncated = True
                    result.truncated_reason = result.truncated_reason or "node_cap"
                    continue
                result.nodes.append(_workflow_node(
                    event,
                    workflow_id=wid, run_id=rid,
                    parent_index=parent_index, depth=depth,
                    node_index=len(result.nodes), stage=stage,
                ))
                emitted_here += 1
    return result


def parent_from_started(events: Sequence[Dict[str, Any]]) -> Optional[Tuple[str, str]]:
    """The parent workflow id and run id, or ``None`` if this history is a root."""
    for event in events:
        if _event_kind(event) != "WORKFLOW_EXECUTION_STARTED":
            continue
        attrs = _attrs(event)
        parent = attrs.get("parentWorkflowExecution") or attrs.get("parentExecution") or {}
        wid = str(parent.get("workflowId") or parent.get("workflow_id") or "")
        rid = str(parent.get("runId") or parent.get("run_id") or "")
        if wid:
            return wid, rid
        return None
    return None


def stage_for_workflow(workflow_type: str) -> str:
    """Pipeline stage id for a workflow type name, or empty."""
    return _STAGE_BY_WORKFLOW.get(workflow_type, "")


def history_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The event list from a Temporal HTTP history response body."""
    history = payload.get("history") or {}
    events = history.get("events") or payload.get("events") or []
    return list(events)


_STAGE_BY_WORKFLOW = {
    "IngestDiskDataset": "P0",
    "IngestAndProcessDataset": "P0",
    "HandleFolders": "P0",
    "HandleFiles": "P0",
    "ComputePlans": "P1",
    "ExecutePlans": "P2",
    "ExecuteSinglePlan": "P2",
    "ProcessItemsBatched": "P2",
    "ParseSingleFile": "P3",
    "ArchiveExtractionAndScan": "P3",
    "EmailExtractionAndScan": "P3",
    "PdfProcessingAndScan": "P3",
    "VideoProcessingAndScan": "P3",
    "ExtractEntitiesForPlan": "P4",
    "ScanRegexEntitiesForPlan": "P4",
    "ChunkEmbedForPlan": "P5",
    "IndexDatasetPlan": "P6",
}


def _event_kind(event: Dict[str, Any]) -> str:
    raw = str(event.get("eventType") or event.get("event_type") or "")
    if raw.startswith("EVENT_TYPE_"):
        raw = raw[len("EVENT_TYPE_"):]
    return raw.upper()


def _attrs(event: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in event.items():
        if key.endswith("EventAttributes") or key.endswith("_event_attributes"):
            if isinstance(value, dict):
                return value
    return {}


def _failure_blob(attrs: Dict[str, Any]) -> Dict[str, Any]:
    failure = attrs.get("failure") or {}
    return failure if isinstance(failure, dict) else {}


def _class_and_type(failure: Dict[str, Any]) -> Tuple[str, str]:
    app = failure.get("applicationFailureInfo") or failure.get("application_failure_info") or {}
    timeout = failure.get("timeoutFailureInfo") or failure.get("timeout_failure_info") or {}
    error_class = str(app.get("type") or "")
    if not error_class and timeout:
        error_class = "TimeoutError"
    if not error_class:
        error_class = str(failure.get("message") or "Failure")
        if " " in error_class:
            error_class = "Failure"
    if app:
        error_type = "ApplicationFailure"
    elif timeout:
        error_type = "TimeoutFailure"
    else:
        error_type = str(failure.get("source") or "")
    return error_class, error_type


def _stack(failure: Dict[str, Any]) -> str:
    stack = failure.get("stackTrace") or failure.get("stack_trace") or ""
    return str(stack)


def _message(failure: Dict[str, Any]) -> str:
    return str(failure.get("message") or "")


def _details(attrs: Dict[str, Any], extra: Dict[str, Any]) -> str:
    failure = _failure_blob(attrs)
    payload = dict(extra)
    for key in ("retryState", "identity", "scheduledEventId", "startedEventId"):
        if attrs.get(key) not in (None, ""):
            payload[key] = attrs.get(key)
    cause = failure.get("cause")
    if isinstance(cause, dict) and cause.get("message"):
        payload["cause_message"] = cause.get("message")
        app = cause.get("applicationFailureInfo") or {}
        if app.get("type"):
            payload["cause_type"] = app.get("type")
    if not payload:
        return ""
    return json.dumps(payload, ensure_ascii=False)


def _scheduled_index(events: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if _event_kind(event) != "ACTIVITY_TASK_SCHEDULED":
            continue
        event_id = str(event.get("eventId") or event.get("event_id") or "")
        if event_id:
            out[event_id] = _attrs(event)
    return out


def _activity_node(
    event: Dict[str, Any],
    scheduled: Dict[str, Dict[str, Any]],
    *,
    workflow_id: str,
    run_id: str,
    parent_index: int,
    depth: int,
    node_index: int,
    stage: str,
) -> FailureNode:
    attrs = _attrs(event)
    failure = _failure_blob(attrs)
    error_class, error_type = _class_and_type(failure)
    scheduled_id = str(attrs.get("scheduledEventId") or attrs.get("scheduled_event_id") or "")
    sched = scheduled.get(scheduled_id) or {}
    activity_type = (
        ((sched.get("activityType") or {}).get("name"))
        or ((attrs.get("activityType") or {}).get("name"))
        or ""
    )
    activity_id = str(sched.get("activityId") or attrs.get("activityId") or "")
    attempt = int(sched.get("attempt") or attrs.get("attempt") or 0)
    stack = _stack(failure)
    return FailureNode(
        node_index=node_index,
        depth=depth,
        parent_index=parent_index,
        error_class=error_class,
        error_type=error_type,
        message=_message(failure),
        stack_trace=stack,
        signature=compute_signature(error_class, error_type, stack),
        task_name=str(activity_type),
        workflow_id=workflow_id,
        run_id=run_id,
        activity_id=activity_id,
        attempt=attempt,
        stage=stage,
        details_json=_details(attrs, {"activity_type": activity_type}),
        source="history",
    )


def _child_node(
    event: Dict[str, Any],
    *,
    workflow_id: str,
    run_id: str,
    parent_index: int,
    depth: int,
    node_index: int,
    stage: str,
) -> Tuple[str, str, FailureNode]:
    attrs = _attrs(event)
    failure = _failure_blob(attrs)
    error_class, error_type = _class_and_type(failure)
    execution = attrs.get("workflowExecution") or attrs.get("execution") or {}
    child_wid = str(execution.get("workflowId") or execution.get("workflow_id") or "")
    child_rid = str(execution.get("runId") or execution.get("run_id") or "")
    child_type = str(((attrs.get("workflowType") or {}).get("name")) or "")
    stack = _stack(failure)
    node = FailureNode(
        node_index=node_index,
        depth=depth,
        parent_index=parent_index,
        error_class=error_class or "ChildWorkflowError",
        error_type=error_type,
        message=_message(failure) or "Child Workflow execution failed",
        stack_trace=stack,
        signature=compute_signature(error_class or "ChildWorkflowError", error_type, stack),
        task_name=child_type,
        workflow_id=child_wid or workflow_id,
        run_id=child_rid or run_id,
        stage=stage_for_workflow(child_type) or stage,
        details_json=_details(attrs, {"child_workflow_type": child_type}),
        source="history",
    )
    return child_wid, child_rid, node


def _workflow_node(
    event: Dict[str, Any],
    *,
    workflow_id: str,
    run_id: str,
    parent_index: int,
    depth: int,
    node_index: int,
    stage: str,
) -> FailureNode:
    attrs = _attrs(event)
    failure = _failure_blob(attrs)
    error_class, error_type = _class_and_type(failure)
    stack = _stack(failure)
    return FailureNode(
        node_index=node_index,
        depth=depth,
        parent_index=parent_index,
        error_class=error_class,
        error_type=error_type,
        message=_message(failure),
        stack_trace=stack,
        signature=compute_signature(error_class, error_type, stack),
        task_name="",
        workflow_id=workflow_id,
        run_id=run_id,
        stage=stage,
        details_json=_details(attrs, {}),
        source="history",
    )


def _count_failure_events(queue: Sequence[Tuple[Any, ...]]) -> int:
    n = 0
    for item in queue:
        hist = item[4]
        for event in hist:
            kind = _event_kind(event)
            if kind in (
                "ACTIVITY_TASK_FAILED",
                "ACTIVITY_TASK_TIMED_OUT",
                "CHILD_WORKFLOW_EXECUTION_FAILED",
                "CHILD_WORKFLOW_EXECUTION_TIMED_OUT",
            ):
                n += 1
    return n


def _parse_chain_head(chain_text: str) -> Tuple[str, str, str]:
    error_class = "Exception"
    error_type = ""
    message = ""
    for line in (chain_text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("type="):
            error_type = stripped[5:].strip()
            continue
        if stripped.startswith("message="):
            if not message:
                message = stripped[8:].strip()
            continue
        if (
            stripped
            and error_class == "Exception"
            and "=" not in stripped
            and " " not in stripped
            and stripped[0].isalpha()
            and not stripped.startswith("[")
        ):
            error_class = stripped
    if not message:
        message = (chain_text or "").strip().splitlines()[0] if chain_text else ""
    return error_class, error_type, message


def _read_details(raw: str) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
