"""The tools of one step context and the `search_agent_tools` tool.

The snapshot holds the tools of the run's packs. Each model call receives every tool in
the snapshot. Concurrent steps can share the snapshot because it does not change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent_common.tool_packs import pack_of
from research_agent import note_tools, skill_tools
from research_agent.skill_store import (
    DEFAULT_PROFILE,
    SkillContext,
    rank_matches,
)

log = logging.getLogger(__name__)

SEARCH_TOOL = "search_agent_tools"

#: The text of a search that matched nothing.
NO_MATCH_TEXT = "No available tool matches this request."

_MIN_MATCH_COUNT = 6
_MAX_MATCH_COUNT = 12


def _match_count() -> int:
    """Read `AGENT_CATALOGUE_MATCH_COUNT`. Unset or empty means 6. A value outside 6 to 12
    raises, so a wrong setting stops the service at import."""
    raw = (os.getenv("AGENT_CATALOGUE_MATCH_COUNT") or "").strip()
    if not raw:
        return _MIN_MATCH_COUNT
    value = int(raw)
    if not _MIN_MATCH_COUNT <= value <= _MAX_MATCH_COUNT:
        raise ValueError(
            f"AGENT_CATALOGUE_MATCH_COUNT is {value}, and it must be from "
            f"{_MIN_MATCH_COUNT} to {_MAX_MATCH_COUNT}"
        )
    return value


#: How many names one search returns.
CATALOGUE_MATCH_COUNT = _match_count()

_CATEGORY_PREFIXES = ("search", "doc", "pdf", "table", "folder")


def _summary_of(tool: Any) -> str:
    description = (getattr(tool, "description", "") or "").strip()
    return description.splitlines()[0].strip() if description else ""


def _category_of(name: str) -> str:
    head = name.split("_", 1)[0]
    return head if head in _CATEGORY_PREFIXES else (pack_of(name) or "other")


def tool_schema(tool: Any) -> dict:
    """Return the JSON input schema of a tool, whether it holds a dict or a pydantic model."""
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, dict):
        return schema
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    return {}


@dataclass(frozen=True)
class CatalogueSnapshot:
    version: str
    tools_by_name: Mapping[str, Any]
    summaries: Mapping[str, str]
    categories: Mapping[str, str]
    refused_names: Tuple[str, ...] = field(default=())
    skill_context: Optional[SkillContext] = None

    def callable_names(self) -> Tuple[str, ...]:
        """Return every tool name of this run."""
        return tuple(self.tools_by_name)

    def tools_for(self) -> List[Any]:
        """Return every tool object of this run."""
        return list(self.tools_by_name.values())

    def search(self, query: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """Rank the snapshot's tools against a request, and return the best matches.

        The order is an exact name, then the whole request as words of the summary, then a
        name that starts with the request, then the count of shared words, then the name.
        A tool that matches in none of these ways is left out.
        """
        limit = CATALOGUE_MATCH_COUNT if limit is None else limit
        items = [
            (name, self.summaries.get(name, ""))
            for name in self.tools_by_name if name != SEARCH_TOOL
        ]
        return [
            {"name": name, "summary": self.summaries.get(name, ""),
             "category": self.categories.get(name, "")}
            for name in rank_matches(query, items)[:limit]
        ]


def build_snapshot(
    tools: Sequence[Any],
    allowed: Iterable[str],
    kind: str,
    skill_context: Optional[SkillContext] = None,
) -> CatalogueSnapshot:
    """Build the snapshot of one graph from the tools it loaded.

    `allowed` is the tool names of the run's packs. A tool outside them is left out, and
    its name is logged once. When `search_agent_tools` is allowed, the snapshot gets its own
    search tool, which searches this snapshot and no other. The skill tools that `allowed`
    holds are built the same way, over this snapshot and its skill context, and so is the
    notes tool `write_note`.

    `skill_context` gives the profile and `collections_hint` of the run. The snapshot keeps a
    copy whose `tool_names` are the snapshot's tools. With no context, the profile is the one
    of the run kind.
    """
    allowed = frozenset(allowed)
    kept: Dict[str, Any] = {}
    refused: List[str] = []
    for tool in tools:
        name = getattr(tool, "name", "")
        if name in allowed and name not in kept:
            kept[name] = tool
        elif name:
            refused.append(name)
    unpacked = sorted(n for n in refused if pack_of(n) is None)
    if unpacked:
        log.warning("tools that no pack names, refused for every run: %s", unpacked)
    if refused:
        log.info("tools outside the %s packs, not bound: %s", kind, sorted(set(refused)))

    holder: Dict[str, CatalogueSnapshot] = {}
    if SEARCH_TOOL in allowed:
        kept[SEARCH_TOOL] = make_search_tool(lambda: holder["snapshot"])
    for tool in skill_tools.make_skill_tools(
        lambda: holder["snapshot"], lambda: holder["snapshot"].skill_context
    ) + note_tools.make_note_tools():
        if tool.name in allowed:
            kept[tool.name] = tool

    names = sorted(kept)
    digest = hashlib.sha256(
        json.dumps(
            [[n, tool_schema(kept[n])] for n in names], sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    if skill_context is None:
        skill_context = SkillContext(
            profile=DEFAULT_PROFILE, tool_names=frozenset()
        )
    skill_context = replace(skill_context, tool_names=frozenset(names))
    snapshot = CatalogueSnapshot(
        version=digest,
        tools_by_name=dict(kept),
        summaries={n: _summary_of(kept[n]) for n in names},
        categories={n: _category_of(n) for n in names},
        refused_names=tuple(sorted(set(refused))),
        skill_context=skill_context,
    )
    holder["snapshot"] = snapshot
    return snapshot


#: The most characters a `search_agent_tools` query may hold.
SEARCH_QUERY_MAX_CHARS = 160


class SearchAgentToolsArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=SEARCH_QUERY_MAX_CHARS,
        description=(
            "What you want to do, in a few words. For example: `read a table`, "
            "`search inside one document`, `list a folder`, `email attachments`."
        ),
    )


def search_result(snapshot: CatalogueSnapshot, query: str) -> Dict[str, Any]:
    """Return the result of one `search_agent_tools` call as a dict."""
    matches = snapshot.search(query)
    if not matches:
        return {"matches": [], "text": NO_MATCH_TEXT}
    return {
        "matches": matches,
        "text": (
            "These tools match your request: "
            + ", ".join(m["name"] for m in matches)
            + "."
        ),
    }


def make_search_tool(snapshot_of) -> StructuredTool:
    """Return the `search_agent_tools` tool over the snapshot that `snapshot_of` returns."""

    async def search_agent_tools(query: str) -> str:
        return json.dumps(search_result(snapshot_of(), query))

    return StructuredTool.from_function(
        coroutine=search_agent_tools,
        name=SEARCH_TOOL,
        description=(
            "Find tools for a task. Describe the task in a few words. Use it for work "
            "inside one document, a table, a "
            "folder, facets, histograms, entity explainers, email details and PDF search."
        ),
        args_schema=SearchAgentToolsArgs,
    )


__all__ = [
    "CATALOGUE_MATCH_COUNT", "CatalogueSnapshot", "NO_MATCH_TEXT", "SEARCH_TOOL",
    "build_snapshot", "make_search_tool", "search_result", "tool_schema",
]
