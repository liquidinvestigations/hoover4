"""The references of a text that a person sends to a model, and their block in a prompt.

A reference is a Hoover link that a person pasted into a chat message or a board text. The
website resolves it (`website/common/src/links.rs`, `ChatReference`) and the text holds the
marker `[R1]`, `[R2]` and so on at its place. The references are stored as a JSON array in
`references_json` (`chat_messages`, `board_facts`, `board_events`).

`with_references` gives the model the text and one `References:` block, with one JSON line
for each reference that a marker of the text names: its handle, kind, label, the tool and the
arguments that read the item, and a note when the tool call cannot express the whole link.
The chat turn (`activities.open_run`) and the board prompts (`P_board.prompts`) use it.

A board numbers the references of all its texts in one sequence (`P_board.commands`), so one
block can serve a prompt that holds several texts of the board.

A marker is not a citation handle. The citation checks read `[Dn]`, `[Wn]`, `[Cn]` and
`[Bn]` only (`P_workspace.references`, `reports.check_labels`).
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

#: A reference marker. The number starts at 1.
MARKER = re.compile(r"\[R([1-9][0-9]*)\]")

#: The fields of a reference that the model reads.
MODEL_FIELDS = ("handle", "kind", "label", "tool", "arguments")


def parse(value: Any) -> list[dict]:
    """The references of a `references_json` value, a JSON string or a list. A bad value
    gives none."""
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict) and item.get("handle")]


def dumps(references: list[dict]) -> str:
    """The `references_json` value of `references`, empty for none."""
    return json.dumps(references, ensure_ascii=False) if references else ""


def rich(value: Any) -> tuple[str, list[dict]]:
    """The text and the references of a command body value: a string, or an object with
    `text` and `references`. A body written before references holds a string."""
    if isinstance(value, dict):
        return str(value.get("text") or ""), parse(value.get("references"))
    return str(value or ""), []


def number(handle: str) -> int:
    """The number of a handle, 0 for a text that is not a handle."""
    match = MARKER.fullmatch(handle or "")
    return int(match.group(1)) if match else 0


def highest(references: Iterable[dict]) -> int:
    """The highest handle number of `references`, 0 for none."""
    return max((number(r.get("handle", "")) for r in references), default=0)


def shifted(text: str, references: list[dict], offset: int) -> tuple[str, list[dict]]:
    """The text and the references with the number of each marker that has a reference
    raised by `offset`. A marker without a reference is text, and it stays as it is.

    Mirrors `RichText::shifted` in `website/common/src/links.rs`."""
    if not offset:
        return text, list(references)
    known = {number(r.get("handle", "")) for r in references}
    new_text = MARKER.sub(lambda m: f"[R{int(m.group(1)) + offset}]" if int(m.group(1)) in known
                          else m.group(0), text)
    new_refs = [{**r, "handle": f"[R{number(r.get('handle', '')) + offset}]"} for r in references
                if number(r.get("handle", ""))]
    return new_text, new_refs


def used(texts: Iterable[str], references: Iterable[dict]) -> list[dict]:
    """The references that a marker of `texts` names, once each, in handle order."""
    named = {int(n) for text in texts for n in MARKER.findall(text or "")}
    seen: dict[int, dict] = {}
    for reference in references:
        n = number(reference.get("handle", ""))
        if n in named and n not in seen:
            seen[n] = reference
    return [seen[n] for n in sorted(seen)]


def block(texts: Iterable[str], references: Iterable[dict]) -> str:
    """The `References:` block of the references that `texts` name, or an empty string."""
    lines = []
    for reference in used(list(texts), references):
        line = {key: reference.get(key) for key in MODEL_FIELDS}
        if reference.get("note"):
            line["note"] = reference["note"]
        lines.append(json.dumps(line, ensure_ascii=False))
    return "References:\n" + "\n".join(lines) if lines else ""


def display_text(text: str, references: Iterable[dict]) -> str:
    """`text` with each marker that has a reference replaced by its label, else its url.
    The title and the follow-up requests read it, because they get no block.

    Mirrors `RichText::display_text` in `website/common/src/links.rs`."""
    by_number = {number(r.get("handle", "")): r for r in references}

    def label(match) -> str:
        reference = by_number.get(int(match.group(1)))
        if reference is None:
            return match.group(0)
        return str(reference.get("label") or reference.get("url") or match.group(0))

    return MARKER.sub(label, text)


def with_references(text: str, references: Iterable[dict]) -> str:
    """`text`, and after it the block of the references that its markers name."""
    found = block([text], references)
    return f"{text}\n\n{found}" if found else text
