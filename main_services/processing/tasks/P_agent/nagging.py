"""When a chat turn nags the agent to keep going, and what it says when it does.

The agent stops when the model stops calling tools. Its last reply is the answer, and the
todo list can still have open items. A nag runs the agent again, in the same turn, and asks
it to mark each open item `done` or `cancelled`. The nag does not ask for more work or for
a second answer, and the reply of the nag round does not replace the answer.

**The rules here are pure and the loop that applies them lives in `AgentRun`.** Not in
the agent: a nag counter kept inside the agent process is lost the moment that process
restarts, and the workflow is the only thing that knows the user's turn is still going.

Two numbers bound it, and each answers a different failure:

* **[`MAX_NAGS_WITHOUT_PROGRESS`]** -- an agent that is not moving will not start moving
  on the third ask. This resets when the plan itself changes.
* **[`MAX_NAGS_PER_TURN`]** -- the backstop that a resetting counter cannot lift. Past
  it the turn has failed and saying so is worth more than asking again.

**What counts as progress is [`database.chat_todos.is_material_change`], and it ignores
status on purpose.** A model that earned a reset by flipping one row from `pending` to
`in_progress` would never reach either cap and the caps would be decorative. Adding,
removing or rewriting an item is progress; marking one done is not, however welcome it
is. That question is asked of the store rather than re-derived here, so the tool the
model calls and the loop that judges it cannot disagree.

**The citation round comes before the todo nag.** An answer that names a document in a
turn with no `cite_documents` call shows the reader no document card. Such an answer gets
one more round with `CITATION_NOTE`, which asks for the citations and then the answer
again. The reply of that round replaces the answer, unless it has no text. A turn gets one
citation round at most.
"""

from __future__ import annotations

import json
import os
import re

from database import chat_todos

#: How many nags in a row are allowed while the plan itself is not moving.
MAX_NAGS_WITHOUT_PROGRESS = int(os.getenv("CHAT_MAX_NAGS_WITHOUT_PROGRESS", "2"))

#: How many nags one user-originated turn may ever contain, progress or not.
MAX_NAGS_PER_TURN = int(os.getenv("CHAT_MAX_NAGS_PER_TURN", "5"))

#: Transcript role a nag is written under. It is not the user speaking, and a transcript
#: that implies it was makes the user responsible for words they never wrote.
NAG_ROLE = "nag"


def open_items(todo: dict) -> list[dict]:
    """The items still pending or in progress, in plan order."""
    return [
        item
        for item in todo.get("items", [])
        if item.get("status") not in chat_todos.RESOLVED_STATUSES
    ]


def stop_reason(todo: dict, nags_without_progress: int, nags_this_turn: int) -> str:
    """Why this turn should stop rather than nag again -- empty means nag.

    Order matters only for what the transcript says: the caps are checked after the
    plan, so a turn that finished its work is never told it ran out of nags.
    """
    if not chat_todos.is_open(todo):
        return "resolved"
    if nags_this_turn >= MAX_NAGS_PER_TURN:
        return (
            f"Stopping after {nags_this_turn} nudges in one turn with the plan still "
            f"unfinished ({chat_todos.summarise(todo)}). Ask again to continue it."
        )
    if nags_without_progress >= MAX_NAGS_WITHOUT_PROGRESS:
        return (
            f"Stopping: the plan has not changed across {nags_without_progress} nudges "
            f"({chat_todos.summarise(todo)}). Ask again, or say what to drop."
        )
    return ""


def nag_message(todo: dict, nag_number: int) -> str:
    """What the nag says, given how many it is into the current no-progress streak.

    A nag follows a reply with no call, which the transcript already shows as the answer.
    So the nag asks only for the todo marks: `done` for each open item that the answer
    completes, and `cancelled` with a note for each other one. The store accepts both as
    resolved. The nag names each open item with its id, so one `mark_todo` call for each
    status is enough. The reply after the marks does not replace the answer
    (`tasks.P_agent.steps.keeps_answer`).

    The second nag of a streak says that the list is still open.
    """
    lines = "\n".join(f"- {item['id']}. {item['text']}" for item in open_items(todo))
    head = ("Your todo list is still not finished" if nag_number > 1
            else "Your answer is written, but your todo list is not finished")
    return (
        f"{head} ({chat_todos.summarise(todo)}). The open items are these.\n"
        f"{lines}\n\n"
        "Call `mark_todo` now. Give status `done` to each item that your answer "
        "completes. Give status `cancelled` and a note with the reason to each item that "
        "it does not complete. Do not write the answer again, and do not start new work. "
        "After the marks, stop with no text."
    )


#: The note of the citation round. A chat answer that names a document in a turn with no
#: `cite_documents` call gets one more round with this note (`needs_citation_round`).
CITATION_NOTE = (
    "Your answer names documents, but this turn has no `cite_documents` call, so the "
    "reader sees no document card. Call `cite_documents` now with each document that "
    "your answer names, quotes or relies on. Then write the whole answer again, with the "
    "handles that the call returned."
)

#: The tool whose call gives the reader a document card.
CITE_TOOL = "cite_documents"

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
    """Whether a thread message is the note of the citation round."""
    return message.role == "human" and (message.content or "") == CITATION_NOTE


def needs_citation_round(answer: str, messages) -> bool:
    """Whether a chat answer gets the citation round.

    The answer names a document (`names_documents`), and the thread holds no
    `cite_documents` call and no citation note. A turn gets one citation round at most.
    `messages` is the thread of the turn.
    """
    if not answer.strip():
        return False
    for message in messages:
        if is_citation_note(message):
            return False
        if message.role == "ai" and any(
            call.get("name") == CITE_TOOL for call in message.tool_calls
        ):
            return False
    return names_documents(answer, messages)


__all__ = [
    "CITATION_NOTE",
    "is_citation_note",
    "names_documents",
    "needs_citation_round",
    "MAX_NAGS_WITHOUT_PROGRESS",
    "MAX_NAGS_PER_TURN",
    "NAG_ROLE",
    "nag_message",
    "open_items",
    "stop_reason",
]
