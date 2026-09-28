"""The message rebuild: stored run messages to langchain messages.

A `/model_step` request carries the run's thread, and the earlier turns of the chat, as
`RunMessage` rows, in the form the agent run storage keeps them. `to_langchain` converts them
into the messages of one model call. A `human` row becomes a `HumanMessage`, an `ai` row an
`AIMessage` with its tool calls and its stored usage, and a `tool` row a `ToolMessage`.

The stored usage of the last `AIMessage` lets compaction measure the thread before the model
call, so a long thread is compacted on that call.

A `compaction` row records one compaction that the service applied to an earlier model call.
Its content is JSON. A version 1 row holds `layer`, `evicted` and `summarised` as lists of
`[thread_id, idx]`, `handoff`, `tokens_before` and `threshold`. A version 2 row
(`"version": 2`, written by `compaction.compact`) also holds `text_removed`, `dropped` and
`cuts`. `apply_compactions` applies every such row before the next call measures the list, so
the next call sends the compacted list again and not the full thread. The stored thread and
the transcript keep every message in full.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    id: str
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class RunMessage(BaseModel):
    role: Literal["human", "ai", "tool", "compaction"]
    content: str
    #: The stored key of the message. A `compaction` row names messages by this key.
    thread_id: Optional[str] = None
    idx: Optional[int] = None
    #: `ai` only.
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    #: `tool` only.
    tool_call_id: Optional[str] = None
    #: `tool` only.
    name: Optional[str] = None
    #: `ai` only: `input_tokens`, `output_tokens`, `total_tokens`.
    usage: Optional[Dict[str, int]] = None
    #: `tool` only: `error` when the call failed. The worker copies it from the stored
    #: usage of the row. A failed `search_agent_tools` result binds no name.
    status: Optional[Literal["ok", "error"]] = None


def _usage_metadata(usage: Optional[Dict[str, int]]) -> Optional[Dict[str, int]]:
    if not usage:
        return None
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}


def to_langchain(messages: Sequence[RunMessage]) -> List[BaseMessage]:
    """Convert stored run messages to langchain messages, in the same order."""
    out: List[BaseMessage] = []
    for message in messages:
        if message.role == "compaction":
            # A record for `apply_compactions`, never a message of the model input.
            continue
        if message.role == "human":
            out.append(HumanMessage(content=message.content))
        elif message.role == "ai":
            kwargs: Dict[str, Any] = {
                "content": message.content,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "args": dict(c.args), "type": "tool_call"}
                    for c in message.tool_calls
                ],
            }
            usage = _usage_metadata(message.usage)
            if usage:
                kwargs["usage_metadata"] = usage
            out.append(AIMessage(**kwargs))
        else:
            if not message.tool_call_id:
                raise ValueError("a tool message needs its tool_call_id")
            out.append(
                ToolMessage(
                    content=message.content,
                    tool_call_id=message.tool_call_id,
                    name=message.name,
                    status="error" if message.status == "error" else "success",
                )
            )
    return out



def _placeholder() -> str:
    """The eviction placeholder of `compaction`, imported at call time."""
    from research_agent.compaction import EVICTION_PLACEHOLDER

    return EVICTION_PLACEHOLDER


def _key(message: RunMessage) -> Optional[Tuple[str, int]]:
    if message.thread_id is None or message.idx is None:
        return None
    return (str(message.thread_id), int(message.idx))


def _keys(value: Any) -> set:
    out = set()
    for item in value or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            try:
                out.add((str(item[0]), int(item[1])))
            except (TypeError, ValueError):
                continue
    return out


def _drop_orphan_results(messages: List[RunMessage]) -> List[RunMessage]:
    """Remove each `tool` message whose call is not in an `ai` message of the list. A
    request with a result that no call asked for is refused by the model server."""
    asked = {c.id for m in messages if m.role == "ai" for c in m.tool_calls}
    return [m for m in messages if m.role != "tool" or m.tool_call_id in asked]


def _drop_unanswered_calls(messages: List[RunMessage]) -> List[RunMessage]:
    """Remove from each `ai` message the calls that have no result in the list, and remove
    an `ai` message that is then left with no call and no text."""
    answered = {m.tool_call_id for m in messages if m.role == "tool"}
    out: List[RunMessage] = []
    for m in messages:
        if m.role == "ai" and m.tool_calls:
            calls = [c for c in m.tool_calls if c.id in answered]
            if len(calls) != len(m.tool_calls):
                if not calls and not (m.content or "").strip():
                    continue
                m = m.model_copy(update={"tool_calls": calls})
        out.append(m)
    return out


def _cuts(value: Any) -> Dict[Tuple[str, int], int]:
    out: Dict[Tuple[str, int], int] = {}
    for item in value or []:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            try:
                out[(str(item[0]), int(item[1]))] = max(0, int(item[2]))
            except (TypeError, ValueError):
                continue
    return out


def apply_record(messages: Sequence[RunMessage], record: Dict[str, Any]) -> List[RunMessage]:
    """Apply one version 2 compaction record to a list with no `compaction` row.

    A `dropped` message leaves the list, and no record takes its place. The `summarised`
    messages leave the list, and one `human` message with the handoff takes the place of
    the first of them, with its key. A `tool` message in `cuts` keeps that many characters
    and gets the cut mark. An `ai` message in `text_removed` keeps its calls and loses its
    text. Then each result with no call and each call with no result leaves the list.
    """
    from research_agent.compaction import CUT_MARK

    gone = _keys(record.get("summarised"))
    blank = _keys(record.get("text_removed"))
    drop = _keys(record.get("dropped"))
    cuts = _cuts(record.get("cuts"))
    handoff = str(record.get("handoff") or "")
    placed = False
    out: List[RunMessage] = []
    for message in messages:
        key = _key(message)
        if key is not None and key in drop:
            continue
        if key is not None and key in gone:
            if not placed and handoff:
                out.append(RunMessage(role="human", content=handoff,
                                      thread_id=key[0], idx=key[1]))
                placed = True
            continue
        if key is not None and key in cuts and message.role == "tool" \
                and len(message.content) > cuts[key]:
            message = message.model_copy(
                update={"content": message.content[:cuts[key]] + CUT_MARK})
        if key is not None and key in blank and message.role == "ai":
            message = message.model_copy(update={"content": ""})
        out.append(message)
    return _drop_unanswered_calls(_drop_orphan_results(out))


def apply_compactions(messages: Sequence[RunMessage]) -> List[RunMessage]:
    """Apply every `compaction` row of the list, in list order, and remove the rows.

    A version 2 row goes through `apply_record`. For a version 1 row, an evicted `tool`
    message keeps its call and gets the eviction placeholder. The summarised messages leave
    the list, and one `human` message with the handoff takes the place of the first of
    them. It has the key of that message, so a later compaction can name it.
    """
    out = [m for m in messages if m.role != "compaction"]
    for row in (m for m in messages if m.role == "compaction"):
        try:
            record = json.loads(row.content or "{}")
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if record.get("version") == 2:
            out = apply_record(out, record)
            continue
        evicted = _keys(record.get("evicted"))
        summarised = _keys(record.get("summarised"))
        handoff = str(record.get("handoff") or "")
        placeholder = _placeholder()
        next_out: List[RunMessage] = []
        placed = False
        for message in out:
            key = _key(message)
            if key is not None and key in summarised and handoff:
                if not placed:
                    next_out.append(RunMessage(role="human", content=handoff,
                                               thread_id=key[0], idx=key[1]))
                    placed = True
                continue
            if key is not None and key in evicted and message.role == "tool":
                message = message.model_copy(update={"content": placeholder})
            next_out.append(message)
        out = _drop_orphan_results(next_out)
    return out


#: The result that a request gives a call of an earlier turn that has no stored result.
NOT_RUN_RESULT = json.dumps({
    "success": False, "error": "not_run",
    "message": "The turn was stopped before this call ran.",
})


def close_unanswered(messages: Sequence[RunMessage]) -> List[RunMessage]:
    """Add a `not_run` result for each call that has no `tool` message, after the results
    of its `ai` message. A stopped turn leaves such calls. The rows exist in the request
    only, so the model input has one result for each call."""
    answered = {m.tool_call_id for m in messages if m.role == "tool"}
    out: List[RunMessage] = []
    missing: List[ToolCallRecord] = []
    for message in messages:
        if missing and message.role not in ("tool", "compaction"):
            out.extend(_not_run(missing))
            missing = []
        out.append(message)
        if message.role == "ai":
            missing = [c for c in message.tool_calls if c.id not in answered]
    out.extend(_not_run(missing))
    return out


def _not_run(calls: Sequence[ToolCallRecord]) -> List[RunMessage]:
    return [RunMessage(role="tool", content=NOT_RUN_RESULT, tool_call_id=c.id, name=c.name,
                       status="error") for c in calls]
