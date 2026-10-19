"""The citation status of an answer row, and the marker of a stored repair note.

`answer_metadata` gives the metadata of an answer row: the tool scope, and the citation
status of the response. When the turn wrote a workspace file, the response is that report,
and the status describes its stored version. Otherwise the status describes the chat text,
from `reports.check_labels`: a handle that no successful citation gives, or that names more
than one source, makes it `invalid`. No rule asks a paragraph for a citation, and no note
asks the model to repeat an answer. The workspace tools check the handles of a report when
it is written (`tasks/P_workspace/references.py`).

Earlier turns can hold citation repair notes. `is_citation_note` reads their marker, so the
policy counters and the transcript still recognise them.
"""

from __future__ import annotations

#: The usage key and value of a stored citation repair note.
REPAIR_MARKER_KEY = "repair_marker"
REPAIR_MARKER = "citation"


def is_citation_note(message) -> bool:
    """Whether a stored human message is a citation repair note of an earlier turn."""
    return message.role == "human" and message.usage.get(REPAIR_MARKER_KEY) == REPAIR_MARKER


def answer_metadata(answer: str, session_entries, internet_tools: bool,
                    report: dict | None = None, files: list | None = None) -> dict:
    """Return the citation status, the available tool scope and the files of an answer.

    `report` is the report of the turn (`tasks.P_workspace.selection.selected_report`), or
    None. `files` is every file that the turn delivered
    (`tasks.P_workspace.selection.manifest`). With a report, the status describes that file
    version: `cited` when it holds resolved citation handles, else `none`, `report` names
    the version, and `reports` lists `files`. Without a
    report, the status describes the chat text: `invalid` for a handle that no successful
    citation gives or that names more than one source, `cited` for resolved handles, else
    `none`. No rule asks a paragraph for a citation.
    """
    from tasks.P_agent import reports

    out: dict = {"tool_scope": "documents_and_web" if internet_tools else "documents_only"}
    if report:
        out["citation_status"] = "cited" if report.get("citations") else "none"
        out["report"] = {"name": report["name"], "version": int(report["version"])}
        if files:
            out["reports"] = list(files)
        return out
    check = reports.check_labels(answer, reports.label_bindings(session_entries), session_entries)
    if check["unresolved"] or check["conflicting"]:
        out["citation_status"] = "invalid"
    elif check["labels"]:
        out["citation_status"] = "cited"
    else:
        out["citation_status"] = "none"
    return out
