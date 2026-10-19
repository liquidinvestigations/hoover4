"""The files of a turn: every file version that the turn delivered, and the report.

The delivered files are the successful workspace writes and patches of the run thread, in
the order of the tool calls. Each file name appears once, at the position of its first
delivery, with the version of its last successful mutation in the turn. A read selects
nothing, and a failed mutation selects nothing. An unchanged successful mutation names the
existing version. A tool message that repeats a stored call identity counts once.

The report is the file of the last successful mutation. The page shows it expanded, and
lists the other delivered files with links to their versions. A turn without a successful
write or patch has no report, and its chat answer is the response. An earlier turn's file
is listed again only when this turn writes or patches it. The names and versions go into
the metadata of the assistant row, so a later edit of a file does not change an earlier
answer.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

#: The write and patch tools. Rows written before the rename hold the `workspace_` names.
MUTATION_TOOLS = ("write_file", "patch_file", "workspace_write", "workspace_patch")


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


def _mutations(messages: Iterable) -> list[dict]:
    """The successful mutation results of a run thread in call order, each tool call once."""
    out, seen = [], set()
    for message in sorted(messages, key=lambda m: m.idx):
        result = mutation_result(message)
        if result is None:
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id and call_id in seen:
            continue
        seen.add(call_id)
        out.append(result)
    return out


def selected_report(messages: Iterable) -> Optional[dict]:
    """The report of a run thread: the result of its last successful write or patch."""
    found = _mutations(messages)
    return found[-1] if found else None


def delivered_reports(messages: Iterable) -> list[dict]:
    """Every file that the run thread delivered: one entry for each name, in the order of
    its first successful mutation, with the name, version and citation handles of its last
    successful mutation."""
    by_name: dict[str, dict] = {}
    for result in _mutations(messages):
        by_name[result["name"]] = result
    return list(by_name.values())


def manifest(messages: Iterable) -> dict:
    """The answer metadata of the delivered files: `report`, the expanded file, and
    `reports`, every delivered file. Empty when the turn delivered no file."""
    report = selected_report(messages)
    if report is None:
        return {}
    return {"report": {"name": report["name"], "version": int(report["version"])},
            "reports": [{"name": r["name"], "version": int(r["version"]),
                         "citations": list(r["citations"])} for r in delivered_reports(messages)]}


__all__ = ["MUTATION_TOOLS", "delivered_reports", "manifest", "mutation_result",
           "selected_report"]
