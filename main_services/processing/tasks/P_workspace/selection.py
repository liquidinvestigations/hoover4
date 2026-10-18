"""The report of a turn: the file version that the turn shows as its final response.

The report is the last successful workspace write or patch of the run thread, in the order
of the tool calls. A read selects nothing. A turn without a successful write or patch has
no report, and its chat answer is the response. An earlier turn's report is never selected
again. The selected name and version go into the metadata of the assistant row, so a later
edit of the file does not change an earlier answer.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

MUTATION_TOOLS = ("workspace_write", "workspace_patch")


def mutation_result(message) -> Optional[dict]:
    """The name, the version and the citation handles of a successful workspace write or
    patch message, or None. An unchanged result names the current version."""
    if message.role != "tool" or (message.tool_name or "") not in MUTATION_TOOLS:
        return None
    if message.usage.get("status") == "error":
        return None
    try:
        body = json.loads(message.content or "")
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("success") is not True:
        return None
    name, version = body.get("name"), body.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, int) or version < 1:
        return None
    handles = [h for h in body.get("citations") or [] if isinstance(h, str)]
    return {"name": name, "version": version, "citations": handles}


def selected_report(messages: Iterable) -> Optional[dict]:
    """The report of a run thread: the result of its last successful write or patch."""
    found = None
    for message in sorted(messages, key=lambda m: m.idx):
        result = mutation_result(message)
        if result is not None:
            found = result
    return found


__all__ = ["MUTATION_TOOLS", "mutation_result", "selected_report"]
