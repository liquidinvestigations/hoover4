"""The skill line of an error: a failed tool result that shows a known stumble names the
skill that teaches the fix.

`run_tool_call` (`steps.py`) calls `with_skill_line` on each result before it returns it,
for every tool, so no MCP server holds this text. `stumble_skill` reads the result and
its arguments and gives the name of one stumble or technique skill, or `None`.

A result gets no line when it shows no failure, when it is a result page
(`is_canonical_page`, whose bytes must not change), when the run does not list the skill, or when
it holds the line already. A repeat refusal gets no line here, because the worker writes
that text.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, FrozenSet, Optional

from agent_common.result_pages import is_canonical_page

#: The sentence that a stumble adds to an error.
SKILL_LINE = "Before you call this tool again, read the skill `{skill}` with `read_skill`."

#: The key of a JSON error that gets the sentence when it has no `message` or `error` text.
NEXT_KEY = "next"


TODO_TOOLS = frozenset({"read_todo", "write_todo", "edit_todo", "mark_todo"})
PLAN_TOOLS = frozenset({"read_plan", "append_node", "append_child", "move_node", "edit_node",
                        "remove_node", "read_plan_document"})
#: The tools whose `not_found` error means a document id that no readable dataset holds.
DOCUMENT_TOOLS = frozenset({"read_documents", "list_document_entities"})

_HASH = re.compile(r"^[0-9a-f]{64}$")

#: The skill of each cause.
CAUSE_SKILLS = {
    "document_id": "document_ids",
    "document_not_found": "document_ids",
    "collection_name": "collection_names",
    "query_syntax": "search",
    "todo_arguments": "todo_upkeep",
    "tool_arguments": "call_arguments",
    "plan_tree_arguments": "plan_editing",
    "browser_error": "browser_use",
}


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _hashes(args: Dict[str, Any]) -> list:
    value = args.get("file_hash")
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _is_document_tool(name: str) -> bool:
    return name in DOCUMENT_TOOLS or name.startswith("doc_")


def _cause(name: str, content: str, args: Dict[str, Any]) -> Optional[str]:
    """The stumble cause of one tool result, or `None` when the result shows no failure
    or a cause that no skill teaches."""
    head = content[:600]
    data = _parse(content)
    if name.startswith("browser_"):
        if "### Error" in head or '"failed": true' in content[-200:]:
            return "browser_error"
        return None
    failed = False
    error = message = ""
    if isinstance(data, dict):
        if name == "run_subagent":
            return None
        err = data.get("error")
        error = str(err or "")
        message = str(data.get("message", "")) + " " + str(data.get("code", ""))
        failed = data.get("success") is False or (bool(err) and not isinstance(err, dict))
    elif head.startswith("Error"):
        failed = True
        message = head
    if not failed:
        return None
    low = (error + " " + message).lower()
    if error in ("repeated_call", "not_run"):
        return None
    if "is not ready. Call read_tool" in message or "No tool of this run is named" in message:
        return None
    if "transport failure" in message or error in ("tool_unavailable", "backend_unavailable"):
        return None
    bad_ids = [h for h in _hashes(args) if not _HASH.match(str(h))]
    if bad_ids or ("file_hash" in message and "characters" in message) \
            or "REPLACE_WITH" in head \
            or ("file_hash" in message and "at least 1 item" in message) \
            or "must be a content hash" in message:
        return "document_id"
    if "outside the permitted collection" in message \
            or "not a collection that this chat" in message \
            or "outside the selected collection" in message:
        return "collection_name"
    if "negations alone" in message or message.startswith("queries:") \
            or "filename_only" in message:
        return "query_syntax"
    if name in PLAN_TOOLS:
        return "plan_tree_arguments"
    if name in TODO_TOOLS:
        return "todo_arguments"
    if "stored page" in message or "no column" in message or "no node" in message:
        return None
    if "validation error" in low or "unexpected keyword" in low \
            or "invalid_argument" in low or "malformed continuation" in low:
        return "tool_arguments"
    if "not_found" in low and _is_document_tool(name):
        return "document_not_found"
    return None


def stumble_skill(name: str, content: str, status: str, args: dict) -> Optional[str]:
    """The skill that teaches the fix of a failed result, or `None`.

    `status` is the status of the result. A result with status `ok` still gets a skill
    when its JSON says `success` false, because an MCP server can report a refusal as a
    successful call.
    """
    if not isinstance(content, str) or not content:
        return None
    if is_canonical_page(content):
        return None
    data = _parse(content)
    if status == "ok" and not isinstance(data, dict) and not name.startswith("browser_"):
        return None
    cause = _cause(name, content, args if isinstance(args, dict) else {})
    return CAUSE_SKILLS.get(cause) if cause else None


def with_skill_line(response: dict, args: dict, listed: FrozenSet[str]) -> dict:
    """The tool response with the skill line added to its content, once.

    For a JSON object the sentence goes after the text under `message`, else after the text
    under `error`, else under `next`. For other text it goes after a blank line. A response
    whose skill the run does not list comes back unchanged.
    """
    content = response.get("content")
    skill = stumble_skill(response.get("name") or "", content, response.get("status") or "",
                          args)
    if skill is None or skill not in listed:
        return response
    line = SKILL_LINE.format(skill=skill)
    if line in content:
        return response
    data = _parse(content)
    if isinstance(data, dict):
        if isinstance(data.get("message"), str) and data["message"]:
            data["message"] = f"{data['message'].rstrip()} {line}"
        elif isinstance(data.get("error"), str) and data["error"]:
            data["error"] = f"{data['error'].rstrip()} {line}"
        else:
            data[NEXT_KEY] = line
        text = json.dumps(data, ensure_ascii=False)
    else:
        text = f"{content.rstrip()}\n\n{line}"
    return {**response, "content": text}


__all__ = [
    "CAUSE_SKILLS", "NEXT_KEY", "SKILL_LINE", "stumble_skill", "with_skill_line",
]
