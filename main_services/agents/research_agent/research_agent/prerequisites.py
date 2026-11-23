"""The reads that must precede the first call of a tool.

Before a model calls a tool, two texts must be in its current model input:

* each listed skill whose `required_by` front matter names the tool (`skill_store`), as a
  successful `read_skill` result, and
* the full definition of the tool, as a successful `read_tool` result or as a match of a
  successful `search` call with `detail` set (the Code Mode discovery).

The model input is the thread after every stored compaction (`steps.model_input_rows`). A
read that a compaction removed does not count, so the model reads the text again.

A call that lacks a read is refused before it has any effect. The refusal names each
missing read, so the next reply can make the reads and send the call again. A call inside
an `execute` program gets the same refusal as its operation result, and the earlier
operations of the program keep their receipts.

Exempt calls:

* the discovery and read tools (`EXEMPT_TOOLS`), so a run can always start the reads, and
* the calls of a worker policy action, whose ids start with `POLICY_CALL_PREFIX`.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, List, Optional, Sequence, Set

from research_agent.run_messages import RunMessage
from research_agent.skill_store import Skill

#: The tools that need no earlier read: the skill and tool reads, the tool searches, and
#: the list of collections and of web sources, which only name what a run can use.
EXEMPT_TOOLS = frozenset({
    "search_skills", "read_skill", "read_tool", "search_agent_tools", "search",
    "list_collections", "list_search_sources",
})

#: The start of the id of a call that a worker policy action makes (`coordinator.py` of
#: the worker).
POLICY_CALL_PREFIX = "ctl-"

MISSING_PREREQUISITE = "missing_prerequisite"

_SKILL_HEAD = re.compile(r"Skill `([a-z_]+)`\.")


def _json(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def visible_reads(applied: Sequence[RunMessage]) -> tuple[Set[str], Set[str]]:
    """The skills and the tool definitions whose successful read is in the model input."""
    skills: Set[str] = set()
    tools: Set[str] = set()
    for message in applied:
        if message.role != "tool" or message.status == "error":
            continue
        name = message.name or ""
        content = message.content or ""
        if name == "read_skill":
            match = _SKILL_HEAD.match(content)
            if match:
                skills.add(match.group(1))
        elif name == "read_tool":
            data = _json(content)
            if isinstance(data, dict) and isinstance(data.get("tool"), str) \
                    and isinstance(data.get("parameters"), dict):
                tools.add(data["tool"])
        elif name == "search":
            data = _json(content)
            matches = data.get("matches") if isinstance(data, dict) else None
            for match in matches or []:
                if isinstance(match, dict) and isinstance(match.get("tool"), str) \
                        and isinstance(match.get("parameters"), dict):
                    tools.add(match["tool"])
    return skills, tools


def required_skills(tool: str, listed: Iterable[Skill]) -> List[str]:
    """The listed skills that must be read before the first call of `tool`, by name."""
    return sorted(skill.name for skill in listed if tool in skill.required_by)


def missing_reads(tool: str, call_id: str, applied: Sequence[RunMessage],
                  listed: Iterable[Skill]) -> tuple[List[str], bool]:
    """The skills to read, and whether the tool definition is still to read, before a call
    of `tool` can run. An exempt call needs nothing."""
    if tool in EXEMPT_TOOLS or (call_id or "").startswith(POLICY_CALL_PREFIX):
        return [], False
    skills, tools = visible_reads(applied)
    needed = [name for name in required_skills(tool, listed) if name not in skills]
    return needed, tool not in tools


def refusal_text(tool: str, skills: Sequence[str], definition: bool,
                 nested: bool = False) -> Optional[str]:
    """The message of the refusal of a call that lacks reads, or None when nothing lacks."""
    if not skills and not definition:
        return None
    reads = [f"read_skill with name `{name}`" for name in skills]
    if definition:
        reads.append(f"read_tool with name `{tool}`" if not nested else
                     f"read_tool with name `{tool}`, or search with detail true")
    return (f"The call of `{tool}` was not run. First call {' and '.join(reads)}. "
            "Then send the call again. A read stays valid until a compaction removes it.")


__all__ = [
    "EXEMPT_TOOLS", "MISSING_PREREQUISITE", "POLICY_CALL_PREFIX", "missing_reads",
    "refusal_text", "required_skills", "visible_reads",
]
