"""The files of a turn: the report versions that the turn delivered, and the expanded report.

Two presentation contracts exist. The opening message of a turn records its contract in
`presentation` (`PRESENTATION_KEY`). `open_run` writes `EXPLICIT_PRESENTATION` on every new
turn. A turn without the key used `MUTATION_PRESENTATION`.

**Explicit selection (contract 2).** The turn delivers only the versions that a successful
`finish_with_report` call selects. The call names one primary report and optional
additional reports. The primary report is the expanded file, and the delivered list holds
the primary report first and then the additional reports in call order. A write, a patch
and a read select nothing. A turn without a successful finish call delivers no file, and
its chat answer is the response.

**Mutation selection (contract 1).** Turns that started before contract 2 delivered every
successful workspace write and patch of the run thread, in the order of the tool calls.
Each file name appears once, at the position of its first delivery, with the version of its
last successful mutation in the turn. The file of the last successful mutation is the
report. The readers of these turns stay, so the export and the task record of an earlier
turn still read their stored threads in the same way.

A tool message that repeats a stored call identity counts once. The names and versions go
into the metadata of the assistant row, so a later edit of a file does not change an
earlier answer.
"""

from __future__ import annotations

import json
from typing import Iterable, Optional

#: The write and patch tools. Rows written before the rename hold the `workspace_` names.
MUTATION_TOOLS = ("write_file", "patch_file", "workspace_write", "workspace_patch")

#: The terminal tool that selects the report versions of a turn and ends the turn.
#: Mirrored as `FINISH_TOOL` in the research agent's `execution.py`.
FINISH_TOOL = "finish_with_report"

#: The usage key of the opening message that records the presentation contract of a turn.
PRESENTATION_KEY = "presentation"
#: The contract of a turn without the key: every mutation delivers its file.
MUTATION_PRESENTATION = 1
#: The contract of a turn that `open_run` opened with the key: explicit selection only.
EXPLICIT_PRESENTATION = 2


def presentation(messages: Iterable) -> int:
    """The presentation contract of a run thread, from its opening message."""
    opening = next((m for m in sorted(messages, key=lambda m: m.idx)
                    if m.role == "human"), None)
    if opening is None:
        return MUTATION_PRESENTATION
    try:
        return int(opening.usage.get(PRESENTATION_KEY) or MUTATION_PRESENTATION)
    except (TypeError, ValueError):
        return MUTATION_PRESENTATION


def _success_body(message, tools) -> Optional[dict]:
    if message.role != "tool" or (message.tool_name or "") not in tools:
        return None
    if message.usage.get("status") == "error":
        return None
    try:
        body = json.loads(message.content or "")
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("success") is not True:
        return None
    return body


def _file_ref(value) -> Optional[dict]:
    if not isinstance(value, dict):
        return None
    name, version = value.get("name"), value.get("version")
    if not isinstance(name, str) or not name or not isinstance(version, int) or version < 1:
        return None
    handles = [h for h in value.get("citations") or [] if isinstance(h, str)]
    return {"name": name, "version": version, "citations": handles}


def mutation_result(message) -> Optional[dict]:
    """The name, the version and the citation handles of a successful workspace write or
    patch message, or None. An unchanged result names the current version."""
    body = _success_body(message, MUTATION_TOOLS)
    return _file_ref(body) if body is not None else None


def finish_result(message) -> Optional[list[dict]]:
    """The selected versions of a successful `finish_with_report` message, the primary
    report first, or None."""
    body = _success_body(message, (FINISH_TOOL,))
    if body is None:
        return None
    primary = _file_ref(body.get("report"))
    if primary is None:
        return None
    out = [primary]
    for item in body.get("additional") or []:
        ref = _file_ref(item)
        if ref is not None and all(r["name"] != ref["name"] for r in out):
            out.append(ref)
    return out


def _results(messages: Iterable, read) -> list:
    """The non-None `read` results of a run thread in index order. A result whose tool call
    identity an earlier result holds counts once."""
    out, seen = [], set()
    for message in sorted(messages, key=lambda m: m.idx):
        result = read(message)
        if result is None:
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        if call_id and call_id in seen:
            continue
        seen.add(call_id)
        out.append(result)
    return out


def _mutations(messages: Iterable) -> list[dict]:
    """The successful mutation results of a run thread in call order, each tool call once."""
    return _results(messages, mutation_result)


def _finish(messages: Iterable) -> list[dict]:
    """The versions that the last successful finish call of a run thread selects."""
    found = _results(messages, finish_result)
    return found[-1] if found else []


def selected_report(messages: Iterable) -> Optional[dict]:
    """The expanded report of a run thread: the primary report of the finish call, or for
    contract 1 the result of the last successful write or patch."""
    messages = list(messages)
    found = (_finish(messages) if presentation(messages) >= EXPLICIT_PRESENTATION
             else _mutations(messages)[-1:])
    return found[0] if found else None


def delivered_reports(messages: Iterable) -> list[dict]:
    """Every file version that the run thread delivered, with the name, version and
    citation handles of each. Contract 2 gives the selection of the finish call. Contract 1
    gives one entry for each mutated name, in the order of its first successful mutation,
    with its last successful mutation."""
    messages = list(messages)
    if presentation(messages) >= EXPLICIT_PRESENTATION:
        return _finish(messages)
    by_name: dict[str, dict] = {}
    for result in _mutations(messages):
        by_name[result["name"]] = result
    return list(by_name.values())


def manifest(messages: Iterable) -> dict:
    """The answer metadata of the delivered files: `report`, the expanded file, and
    `reports`, every delivered file. Empty when the turn delivered no file."""
    messages = list(messages)
    report = selected_report(messages)
    if report is None:
        return {}
    return {"report": {"name": report["name"], "version": int(report["version"])},
            "reports": [{"name": r["name"], "version": int(r["version"]),
                         "citations": list(r["citations"])} for r in delivered_reports(messages)]}


__all__ = ["EXPLICIT_PRESENTATION", "FINISH_TOOL", "MUTATION_PRESENTATION",
           "MUTATION_TOOLS", "PRESENTATION_KEY", "delivered_reports", "finish_result",
           "manifest", "mutation_result", "presentation", "selected_report"]
