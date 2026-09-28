"""The run-start reads of `AgentRun`: the activity `preload_reads`.

A run that starts a thread reads its role and general skills before its first model call.
The first turn of a chat also classifies its request, reads the picked skills and tools,
and marks the first todo item done. A planner run classifies the request type only.

The activity asks the agent service for the reads (`POST /preload`) and writes them into
the thread as one synthetic `ai` message with a `tool` result for each read. The model then
sees the reads as calls of its own. The mark of the todo item goes through
`POST /tool_call`, so the todo server writes it with the session's identity, as every model
call does, and it is a second synthetic `ai` message with its result.

Every row of the thread goes in one insert (`agent_runs.write_messages`), so the thread
never holds a read call with no result. A synthetic `ai` message has empty text, `step_no`
0 and `synthetic` true in its usage, so the retry test of `model_step` never matches it.

The activity has one attempt. A failure leaves the turn going on without the reads, and
its `agent_step_events` row has step `preload`.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, Optional

import requests
from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P_agent.activities import agent_url_for
from tasks.P_agent.model_timeouts import STEP_HEARTBEAT_SECONDS
from tasks.P_agent.steps import (
    StepRef, _chat_row, _earlier_turns, _post_json, _raise_if_cancelled,
    _raise_if_past_limit, _read_row, _read_thread, _step_event, _step_run, args_digest,
    reply_end_idx,
)

log = logging.getLogger(__name__)

#: The start-to-close limit of one attempt. The two request limits below add up to it, so
#: a slow classifier and a slow mark together end the attempt at its limit.
PRELOAD_TIMEOUT = timedelta(seconds=30)
#: The read timeout of `POST /preload`.
PRELOAD_READ_SECONDS = 20
#: The read timeout of `POST /tool_call` for the mark of the todo item.
MARK_READ_SECONDS = 10

#: The values of `PreloadParams.classify`.
CLASSIFY_VALUES = ("none", "types", "all")


@dataclass
class PreloadParams(StepRef):
    #: `none`, `types` for the request type only, or `all` for types, tools and skills.
    classify: str = "none"
    #: Mark the todo item of the reads done: the first turn of a chat, after its plan.
    mark_item: bool = False


@dataclass
class PreloadResult:
    #: `written`, `nothing` or `closed`.
    outcome: str
    reads: int = 0
    #: At most two class names.
    request_classes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------ helpers


def skills_read_in(messages: Iterable[dict[str, Any]]) -> list[str]:
    """The names of the skills that a `read_skill` call with an `ok` result read, in call
    order. `messages` are the `RunMessage` rows of the earlier turns."""
    ok = {(m.get("thread_id"), m.get("tool_call_id")) for m in messages
          if m.get("role") == "tool" and m.get("status") == "ok"}
    out: list[str] = []
    for m in messages:
        if m.get("role") != "ai":
            continue
        for call in m.get("tool_calls") or []:
            name = (call.get("args") or {}).get("name")
            if (call.get("name") == "read_skill" and isinstance(name, str)
                    and (m.get("thread_id"), call.get("id")) in ok and name not in out):
                out.append(name)
    return out


def request_text(row, messages) -> str:
    """The text that the classifier reads: the opening human message, or for a planner
    run that a rejection opened, the question of the plan (the text of the tree's root)."""
    from database import agent_plans
    from tasks.P_agent.plan_runs import REJECTED_TEXT, plan_id_for

    opening = next((m for m in messages if m.role == "human"), None)
    text = opening.content if opening is not None else ""
    if row.kind == "planner" and row.plan_run_id and text.startswith(
            REJECTED_TEXT.split("{", 1)[0]):
        plan_id = plan_id_for(str(row.plan_run_id))
        snapshot = agent_plans.read_snapshot(row.username, row.session_id, plan_id)
        root_id = agent_plans.root_node_id(plan_id)
        root = next((n for n in (snapshot.nodes if snapshot else ()) if n.node_id == root_id),
                    None)
        if root is not None and root.text:
            return root.text
    return text


def open_item_with_text(todo: dict, text: str) -> Optional[dict]:
    """The first item of the list with this text and an open status, or None."""
    wanted = (text or "").strip().lower()
    for item in todo.get("items") or []:
        if (str(item.get("text") or "").strip().lower() == wanted
                and item.get("status") in ("pending", "in_progress")):
            return item
    return None


def mark_key(row, idx: int) -> str:
    """The idempotency key of the mark, in the scheme of `tool_call`."""
    from database import agent_runs

    return str(uuid.uuid5(agent_runs.RUN_ID_NAMESPACE, f"tool:{row.thread_id}:{idx}:0"))


def synthetic_ai(row, idx: int, calls: list[dict], seq: int, mode: str, usage: dict):
    """One synthetic `ai` message: empty text, one call entry for each read, in the shape
    that `_store_reply` writes, with seqs from `seq`."""
    from database import agent_runs

    entries = []
    for position, call in enumerate(calls):
        entries.append({
            "id": call["id"], "name": call["name"], "args": call["args"], "kind": "parallel",
            "briefings": None, "page_share": None, "budget_exhausted": False, "retry": True,
            "args_digest": args_digest(call["name"], call["args"]), "position": position,
            "seq": seq + position,
        })
    full = {"mode": mode, "synthetic": True, "step_no": 0, "bound_names": [], **usage}
    return agent_runs.RunMessageRow(
        idx=idx, role="ai", tool_calls_json=json.dumps(entries),
        usage_json=json.dumps(full, default=str), run_id=row.run_id)


def tool_rows(row, ai, calls: list[dict]) -> list:
    """The `tool` message of each call of a synthetic `ai` message, in call order."""
    from database import agent_runs

    out = []
    for entry, call in zip(ai.tool_calls, calls):
        out.append(agent_runs.RunMessageRow(
            idx=ai.idx + 1 + entry["position"], role="tool", content=call["content"],
            tool_call_id=entry["id"], tool_name=entry["name"], run_id=row.run_id,
            usage_json=json.dumps({"chat_seq": entry["seq"], "status": call["status"],
                                   "measure": None,
                                   "error_class": call.get("error_class") or ""})))
    return out


def page_rows(ai, calls: list[dict]) -> list[tuple[int, dict]]:
    """The finished transcript tool row of each call, as `(seq, fields)`."""
    from tasks.P_agent.stream_writer import tool_row_fields

    return [(entry["seq"], tool_row_fields(entry["name"], entry["args"], call["content"]))
            for entry, call in zip(ai.tool_calls, calls)]


def _mark(row, params: "PreloadParams", text: str, idx: int) -> Optional[dict]:
    """Mark the open item with `text` done through `POST /tool_call`, and return the call
    with its result. None when the list holds no such open item, or the request failed."""
    from database import chat_todos

    item = open_item_with_text(chat_todos.read_todo(row.username, row.session_id), text)
    if item is None:
        return None
    call = {"id": f"preload-mark-{idx}", "name": "mark_todo",
            "args": {"ids": [str(item["id"])], "status": "done"}}
    body = {**_step_run(row, params), "call": call, "bound_names": [], "page_share": None,
            "budget_exhausted": False, "idempotency_key": mark_key(row, idx)}
    try:
        result = _post_json(f"{agent_url_for(params.internet_tools)}/tool_call", body,
                            MARK_READ_SECONDS)
    except (requests.RequestException, RuntimeError) as exc:
        # The reads are still written. The model marks the item itself.
        log.warning("[P_agent] run %s: the preload mark failed: %s", row.run_id, exc)
        return None
    content = result.get("content")
    return {**call, "content": content if isinstance(content, str) else json.dumps(content),
            "status": "error" if result.get("status") == "error" else "ok",
            "error_class": str(result.get("error_class") or "")}


# ------------------------------------------------------------------------ the activity


@activity.defn
@with_heartbeat(interval_seconds=STEP_HEARTBEAT_SECONDS)
def preload_reads(params: PreloadParams) -> PreloadResult:
    """Write the run-start reads of a run that starts a thread.

    1. A terminal row returns `closed`. A thread that holds a preload message already
       returns `written`.
    2. `POST /preload` gives the reads, the request classes and the text of the todo item.
       A chat turn after the first sends the skills that the earlier turns read, and the
       service leaves them out.
    3. The reads become one synthetic `ai` message and its results. With `mark_item`, the
       open item with the text of the reads is marked done, as a second synthetic message.
    4. The late-write guard runs, then one insert writes every thread row. A run that
       writes the transcript gets a finished tool row for each call. The run row gets its
       next seq.
    """
    from database import agent_runs

    started = time.monotonic()
    row = _read_row(params)
    if agent_runs.is_terminal(row):
        return PreloadResult("closed")
    messages = _read_thread(row)
    if any(m.role == "ai" and m.usage.get("mode") == "preload" for m in messages):
        return PreloadResult("written")
    with _step_event(row, "preload", "systemone") as event:
        transcript = agent_runs.writes_transcript(row)
        already = skills_read_in(_earlier_turns(row)) if transcript else []
        body = {**_step_run(row, params), "request_text": request_text(row, messages),
                "classify": params.classify if params.classify in CLASSIFY_VALUES else "none",
                "already_read": already}
        picks = _post_json(f"{agent_url_for(params.internet_tools)}/preload", body,
                           PRELOAD_READ_SECONDS)
        classifier = picks.get("classifier") or {}
        classes = [str(c) for c in picks.get("request_classes") or []][:2]
        event.mode = str(classifier.get("state") or "")
        event.error = str(classifier.get("error") or "")

        idx = max(m.idx for m in messages) + 1
        seq = row.next_seq
        rows: list = []
        page: list = []
        reads = list(picks.get("reads") or [])
        if reads:
            calls = [{**read, "id": f"preload-{idx}-{position}"}
                     for position, read in enumerate(reads)]
            usage = {"request_classes": classes, "picks": picks.get("picks") or {},
                     "classifier": classifier}
            ai = synthetic_ai(row, idx, calls, seq, "preload", usage)
            rows += [ai] + tool_rows(row, ai, calls)
            page += page_rows(ai, calls)
            idx, seq = reply_end_idx(ai), seq + len(calls)
        if params.mark_item:
            marked = _mark(row, params, str(picks.get("todo_item_text") or ""), idx)
            if marked is not None:
                ai = synthetic_ai(row, idx, [marked], seq, "preload_mark", {})
                rows += [ai] + tool_rows(row, ai, [marked])
                page += page_rows(ai, [marked])
                seq += 1
        event.ok = True
        if not rows:
            return PreloadResult("nothing", request_classes=classes)
        _raise_if_past_limit(started)
        _raise_if_cancelled()
        agent_runs.write_messages(row.username, row.session_id, row.thread_id, row.run_id,
                                  rows)
        if transcript:
            write = _chat_row(row)
            for seq_i, fields in page:
                write(seq_i, "tool", **fields)
        agent_runs.RunRowWriter(row).write(next_seq=seq)
        log.info("[P_agent] run %s: %d run-start reads, classes %s, classifier %s",
                 row.run_id, len(reads), classes, event.mode)
        return PreloadResult("written", reads=len(reads), request_classes=classes)


__all__ = [
    "MARK_READ_SECONDS", "PRELOAD_READ_SECONDS", "PRELOAD_TIMEOUT", "PreloadParams",
    "PreloadResult", "mark_key", "open_item_with_text", "page_rows", "preload_reads",
    "request_text", "skills_read_in", "synthetic_ai", "tool_rows",
]
