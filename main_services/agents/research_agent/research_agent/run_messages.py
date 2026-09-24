"""The message rebuild: stored run messages to langchain messages.

A `/run/stream` request carries the run's thread as `RunMessage` rows, in the form the
agent run storage keeps them. `to_langchain` converts them into the messages the graph
starts from. A `human` row becomes a `HumanMessage`, an `ai` row an `AIMessage` with its
tool calls and its stored usage, and a `tool` row a `ToolMessage`.

The stored usage of the last `AIMessage` lets compaction measure the thread before the first
new model call, so a long continued thread is compacted on that call.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field


class ToolCallRecord(BaseModel):
    id: str
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class RunMessage(BaseModel):
    role: Literal["human", "ai", "tool"]
    content: str
    #: `ai` only.
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    #: `tool` only.
    tool_call_id: Optional[str] = None
    #: `tool` only.
    name: Optional[str] = None
    #: `ai` only: `input_tokens`, `output_tokens`, `total_tokens`.
    usage: Optional[Dict[str, int]] = None


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
                )
            )
    return out


def history_to_langchain(history: Sequence[Dict[str, str]]) -> List[BaseMessage]:
    """Convert chat history rows (`type` `human` or `ai`, and `content`) to messages."""
    out: List[BaseMessage] = []
    for row in history or ():
        if row.get("type") == "human":
            out.append(HumanMessage(content=row.get("content") or ""))
        elif row.get("type") == "ai":
            out.append(AIMessage(content=row.get("content") or ""))
    return out
