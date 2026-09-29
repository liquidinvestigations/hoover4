"""The citation check of an answer, and the note of its one repair round.

`reports.check_labels` compares the `[Dn]` labels of an answer with the successful
`cite_documents` results of the whole chat session. A label that no successful result gives
is unresolved. A label that results give for more than one document conflicts. A call that
failed gives no label, so a failed call does not satisfy the check, and a call that exists
does not stop it.

An answer gets one repair round (`needs_repair`) when it has an unresolved or a conflicting
label, or when it has no label and names a document (`names_documents`). The name rule is a
reason to ask for citations. It does not show that the claims of the answer are supported.
The note of the round asks for the citations and the whole answer again. The reply of the
round replaces the answer, unless it has no text (`steps.keeps_answer`).

A logical thread gets one repair round at most. The note in the thread is the stored marker
(`REPAIR_MARKER_KEY` in its usage). A thread from before the marker holds
`LEGACY_CITATION_NOTE` with no usage, and `is_citation_note` reads both.
`steps.check_citations` runs the rule after an answer or a question of every run kind whose
model had `cite_documents`. A stopped run and a run that ended at a limit (`end_reason`) get
no round. The rules here are pure.
"""

from __future__ import annotations

import json
import re

#: The note of the repair round of an answer that names a document with no label.
CITATION_NOTE = (
    "Your answer names documents, but it has no citation handle, so the reader sees no "
    "document card. Call `cite_documents` now with each document that your answer names, "
    "quotes or relies on. Then write the whole answer again, with the handles that the "
    "successful calls returned."
)

#: The note of the same round in a thread from before `REPAIR_MARKER_KEY`. Only
#: `is_citation_note` reads it.
LEGACY_CITATION_NOTE = (
    "Your answer names documents, but this turn has no `cite_documents` call, so the "
    "reader sees no document card. Call `cite_documents` now with each document that "
    "your answer names, quotes or relies on. Then write the whole answer again, with the "
    "handles that the call returned."
)

#: The note of the repair round of an answer with labels that do not resolve.
LABEL_NOTE = (
    "Your answer uses citation labels that do not name one document. {problems} Call "
    "`cite_documents` for each document that your answer relies on. Then write the whole "
    "answer again, with the handles that the successful calls returned."
)

#: The usage key and value of the note of the repair round.
REPAIR_MARKER_KEY = "repair_marker"
REPAIR_MARKER = "citation"

#: The tool whose call gives the reader a document card.
CITE_TOOL = "cite_documents"

#: The usage key of an `ai` message that states whether its model had `CITE_TOOL`.
CITATION_TOOL_KEY = "citation_tool"

#: A citation handle as the answer writes it, for example `[D1]`.
HANDLE_PATTERN = re.compile(r"\[D\d+\]")

#: A file hash as the answer writes it.
HASH_PATTERN = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")

#: The shortest file name of a tool result that counts as a document name in an answer.
#: A shorter name, such as `12.`, also matches ordinary prose.
MIN_NAME_CHARS = 6

#: The shortest part of a file hash that counts as a document name in an answer.
MIN_HASH_CHARS = 12


def _result_documents(message) -> list[dict]:
    """The document references of one stored tool result."""
    from tasks.P_agent.trajectory import extract_doc_refs

    try:
        result = json.loads(message.content or "")
    except ValueError:
        return []
    return extract_doc_refs(message.tool_name or "", result)


def names_documents(answer: str, messages) -> bool:
    """Whether an answer names a document: a `[Dn]` handle, a file hash, or the file hash,
    path or file name of a document that a tool result of the thread returned."""
    if HANDLE_PATTERN.search(answer) or HASH_PATTERN.search(answer):
        return True
    for message in messages:
        if message.role != "tool":
            continue
        for ref in _result_documents(message):
            file_hash = ref.get("file_hash") or ""
            if len(file_hash) >= MIN_HASH_CHARS and file_hash[:MIN_HASH_CHARS] in answer:
                return True
            path = (ref.get("path") or "").strip()
            name = path.rstrip("/").rsplit("/", 1)[-1]
            if len(path) >= MIN_NAME_CHARS and path in answer:
                return True
            if len(name) >= MIN_NAME_CHARS and name in answer:
                return True
    return False


def is_citation_note(message) -> bool:
    """Whether a thread message is the note of the repair round."""
    return message.role == "human" and (
        message.usage.get(REPAIR_MARKER_KEY) == REPAIR_MARKER
        or (message.content or "") in (CITATION_NOTE, LEGACY_CITATION_NOTE))


def has_citation_tool(row, messages) -> bool:
    """Whether the model of the run had `cite_documents`, by the newest `ai` message. A
    message from before the key counts as having it for a chat run only."""
    last = next((m for m in reversed(messages) if m.role == "ai"), None)
    default = row.kind == "chat"
    if last is None:
        return default
    return bool(last.usage.get(CITATION_TOOL_KEY, default))


def repair_note(check: dict) -> str:
    """The note of a repair round for the citation check `check`."""
    problems = []
    if check.get("unresolved"):
        problems.append("No successful `cite_documents` result gives "
                        + ", ".join(check["unresolved"]) + ".")
    if check.get("conflicting"):
        problems.append("Results give " + ", ".join(check["conflicting"])
                        + " for more than one document.")
    if not problems:
        return CITATION_NOTE
    return LABEL_NOTE.format(problems=" ".join(problems))


def needs_repair(answer: str, messages, session_entries) -> tuple[bool, dict]:
    """Whether an answer gets the repair round, and its citation check.

    `messages` is the thread, and `session_entries` the citation evidence of the session.
    A thread that holds the note already gets no second round.
    """
    from tasks.P_agent import reports

    check = reports.check_labels(answer, reports.label_bindings(session_entries),
                                 session_entries)
    if not answer.strip() or any(is_citation_note(m) for m in messages):
        return False, check
    if check["unresolved"] or check["conflicting"]:
        return True, check
    return (not check["labels"] and names_documents(answer, messages)), check


__all__ = [
    "CITATION_NOTE", "CITATION_TOOL_KEY", "CITE_TOOL", "LABEL_NOTE", "LEGACY_CITATION_NOTE",
    "REPAIR_MARKER",
    "REPAIR_MARKER_KEY", "has_citation_tool", "is_citation_note", "names_documents",
    "needs_repair", "repair_note",
]
