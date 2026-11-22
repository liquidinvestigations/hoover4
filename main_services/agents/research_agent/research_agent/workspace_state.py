"""The saved workspace files in the model input of every step.

The worker reads the files of the session from storage for each model step
(`processing/tasks/P_agent/steps.workspace_inventory`) and sends them as
`ModelStepRequest.workspace`. `inventory_text` renders the names, the current versions and
the sizes, and the read instructions. `with_inventory` adds that text to the newest message
of the model input.

Each model request uses the current inventory from storage. A compaction also records
the working files and versions available at the time of its summary. A later request
can therefore show newer versions than the saved compaction record.

The text gives no file content. The model reads a file with `read_file`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage

#: The most files that the text names. The text says how to list the others.
MAX_LISTED_FILES = 30


def inventory_text(files: Optional[Sequence[Dict[str, Any]]]) -> str:
    """The inventory text of the saved files, or an empty string for no file. `files` holds
    `name`, `version`, `chars` and `updated` of each file. The newest files come first."""
    if not files:
        return ""
    ordered = sorted(files, key=lambda f: (str(f.get("updated") or ""), str(f.get("name") or "")),
                     reverse=True)
    lines = ["Saved workspace files (system inventory)."]
    for item in ordered[:MAX_LISTED_FILES]:
        lines.append(f"- {item.get('name')}: version {int(item.get('version') or 0)}, "
                     f"{int(item.get('chars') or 0):,} characters")
    hidden = len(ordered) - MAX_LISTED_FILES
    if hidden > 0:
        lines.append(f"{hidden} older files are not listed. Call read_file without a name "
                     "to list every file.")
    lines.append("Use read_file with a name to recover the current text.")
    return "\n".join(lines)


def compaction_inventory(files: Optional[Sequence[Dict[str, Any]]]) -> str:
    """Describe the non-scratch files at the time of compaction."""
    if files is None:
        return "At compaction the workspace inventory was unavailable."
    if not files:
        return "At compaction there were no saved working files. Source captures and citations are indexed separately."
    return "Workspace at compaction:\n" + inventory_text(files)


def with_inventory(messages: List[BaseMessage], text: str) -> List[BaseMessage]:
    """The model input with `text` after the content of its newest human or tool message.
    The input is unchanged when `text` is empty or the newest message has another role."""
    if not text or not messages or not isinstance(messages[-1], (HumanMessage, ToolMessage)):
        return messages
    last = messages[-1]
    block = "\n\n" + text
    if isinstance(last.content, str):
        content: Any = last.content + block
    else:
        content = list(last.content) + [{"type": "text", "text": block}]
    return messages[:-1] + [last.model_copy(update={"content": content})]


__all__ = ["MAX_LISTED_FILES", "inventory_text", "with_inventory"]
