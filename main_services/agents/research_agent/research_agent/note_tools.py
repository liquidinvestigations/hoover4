"""The tool `write_note`: a fact that the model saves for later in the run.

A compaction replaces the older steps of a run with a record (`compaction.compact`). The
result of each `write_note` call stays in the list through a compaction, in the keep class
`note`, up to `compaction.NOTES_TOTAL_TOKENS` for all notes together. When a reply reaches
`compaction.NOTE_WARNING_SHARE` of the trigger, the worker writes a warning that tells the
model to save its notes now.

The tool is local to the agent service, like the skill tools, and
`tool_catalogue.build_snapshot` builds it for each step context. It is in the `skills` pack.

A refusal raises `ToolException`, so the result of the call has status `error` and its text
is the JSON refusal.
"""

from __future__ import annotations

import json
from typing import Dict, List

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

WRITE_NOTE = "write_note"
#: The most characters of one note.
NOTE_MAX_CHARS = 2_000

DESCRIPTION = (
    "Save a fact that you need later. Notes stay when the older steps of this run are "
    "replaced by a record."
)
REFUSAL = json.dumps({"success": False, "error": "invalid_arguments",
                      "message": "A note holds 1 to 2,000 characters."})


class WriteNoteArgs(BaseModel):
    text: str = Field(description="The fact, with its source. 1 to 2,000 characters.")


def make_note_tools() -> List[StructuredTool]:
    """Return the tool `write_note` of one step context.

    `saved` counts the notes that this context saved. A step context belongs to one run, so
    the count is the count of the run's notes while the service keeps the context. A call
    sent again with the same call id counts once.
    """
    saved: Dict[str, int] = {}

    def count(key: str) -> int:
        if key not in saved:
            saved[key] = len(saved) + 1
        return saved[key]

    async def write_note(text: str) -> str:
        if not 1 <= len(text or "") <= NOTE_MAX_CHARS or not text.strip():
            raise ToolException(REFUSAL)
        from research_agent.execution import _IDEMPOTENCY_KEY

        key = _IDEMPOTENCY_KEY.get() or f"note-{len(saved) + 1}"
        return json.dumps({"saved": count(key), "note": text}, ensure_ascii=False)

    return [StructuredTool.from_function(
        coroutine=write_note, name=WRITE_NOTE, description=DESCRIPTION,
        args_schema=WriteNoteArgs, handle_tool_error=True,
    )]


__all__ = ["DESCRIPTION", "NOTE_MAX_CHARS", "REFUSAL", "WRITE_NOTE", "make_note_tools"]
