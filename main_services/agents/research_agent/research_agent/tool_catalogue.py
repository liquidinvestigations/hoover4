"""The tool catalogue of one agent graph, and the `search_agent_tools` tool.

A graph binds a small core set of tools on every model call. The other tools of the run's
packs are deferred: the model finds them with `search_agent_tools`, and the execution node
binds the matches for the next model call (see `research_agent/execution.py`).

`CatalogueSnapshot` is built once for each graph from the tools that graph loaded. It holds
only the tools of the run's packs, so the model cannot bind, run or find a tool outside
them. The snapshot never changes, so concurrent runs that share one graph can share it.
Every per-run value is in the run's own state (`bound_names`).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agent_common.tool_packs import PACKS, pack_of

log = logging.getLogger(__name__)

SEARCH_TOOL = "search_agent_tools"
DELEGATION_TOOL = "run_subagent"

#: The collection tools that every model call binds. The other collection tools are
#: deferred.
CORE_COLLECTION_TOOLS = frozenset({
    "list_collections", "search_collections", "search_passages", "read_documents",
    "list_document_entities", "cite_documents", "read_more",
})

#: The run kinds that bind the plan tools on every call. For other kinds they are deferred.
PLAN_KINDS = frozenset({"planner", "organizer"})

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


#: How many names one search returns, and how many deferred names one run keeps bound.
CATALOGUE_MATCH_COUNT = _match_count()

_STOP_WORDS = frozenset({
    "a", "an", "and", "the", "of", "to", "in", "on", "for", "by", "with", "or", "is",
    "are", "it", "its", "this", "that", "from", "at", "as", "be", "i", "me", "my", "all",
    "one", "tool", "tools",
})

_CATEGORY_PREFIXES = ("search", "doc", "pdf", "table", "folder")


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


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
    core_names: Tuple[str, ...]
    deferred_names: Tuple[str, ...]
    summaries: Mapping[str, str]
    categories: Mapping[str, str]
    refused_names: Tuple[str, ...] = field(default=())

    def callable_names(self, bound_names: Iterable[str] = ()) -> Tuple[str, ...]:
        """Return the core names and then the bound names that this snapshot holds."""
        names = list(self.core_names)
        for name in bound_names or ():
            if name in self.tools_by_name and name not in names:
                names.append(name)
        return tuple(names)

    def tools_for(self, bound_names: Iterable[str] = ()) -> List[Any]:
        """Return the tool objects that one model call binds."""
        return [self.tools_by_name[name] for name in self.callable_names(bound_names)]

    def search(self, query: str, limit: Optional[int] = None) -> List[Dict[str, str]]:
        """Rank the snapshot's tools against a request, and return the best matches.

        The order is an exact name, then the whole request as words of the summary, then a
        name that starts with the request, then the count of shared words, then the name.
        A tool that matches in none of these ways is left out.
        """
        limit = CATALOGUE_MATCH_COUNT if limit is None else limit
        text = (query or "").strip().lower()
        joined = "_".join(_words(text))
        query_words = [w for w in _words(text) if w not in _STOP_WORDS]
        phrase = " ".join(_words(text))
        ranked = []
        for name in self.tools_by_name:
            if name == SEARCH_TOOL:
                continue
            summary = self.summaries.get(name, "")
            summary_words = _words(summary)
            name_words = _words(name)
            if joined and name == joined:
                rank = 0
            elif phrase and re.search(rf"\b{re.escape(phrase)}\b", " ".join(summary_words)):
                rank = 1
            elif joined and name.startswith(joined):
                rank = 2
            else:
                rank = 3
            overlap = len(set(query_words) & (set(name_words) | set(summary_words)))
            if rank == 3 and overlap == 0:
                continue
            ranked.append(((rank, -overlap, name), name))
        ranked.sort()
        return [
            {"name": name, "summary": self.summaries.get(name, ""),
             "category": self.categories.get(name, "")}
            for _, name in ranked[:limit]
        ]


def _is_core(name: str, kind: str) -> bool:
    pack = pack_of(name)
    if pack == "collections":
        return name in CORE_COLLECTION_TOOLS
    if pack == "plan":
        return kind in PLAN_KINDS
    return True


def build_snapshot(tools: Sequence[Any], allowed: Iterable[str], kind: str) -> CatalogueSnapshot:
    """Build the snapshot of one graph from the tools it loaded.

    `allowed` is the tool names of the run's packs. A tool outside them is left out, and
    its name is logged once. When `search_agent_tools` is allowed, the snapshot gets its own
    search tool, which searches this snapshot and no other.
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

    names = sorted(kept)
    digest = hashlib.sha256(
        json.dumps(
            [[n, tool_schema(kept[n])] for n in names], sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    core = tuple(n for n in names if _is_core(n, kind))
    deferred = tuple(n for n in names if not _is_core(n, kind))
    snapshot = CatalogueSnapshot(
        version=digest,
        tools_by_name=dict(kept),
        core_names=core,
        deferred_names=deferred,
        summaries={n: _summary_of(kept[n]) for n in names},
        categories={n: _category_of(n) for n in names},
        refused_names=tuple(sorted(set(refused))),
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
            "These tools are bound for your next call: "
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
            "Find more tools for a task that your current tools cannot do. Describe the "
            "task in a few words. The tools that match are bound for your next call, and "
            "you can call them then. Use it for work inside one document, a table, a "
            "folder, facets, histograms, entity explainers, email details, PDF search, and "
            "plan tools."
        ),
        args_schema=SearchAgentToolsArgs,
    )


def matched_names(content: Any) -> List[str]:
    """Return the tool names out of one `search_agent_tools` result, or an empty list."""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return [
        m["name"] for m in data.get("matches") or []
        if isinstance(m, dict) and isinstance(m.get("name"), str)
    ]


def bind_names(
    snapshot: CatalogueSnapshot,
    earlier: Sequence[str],
    newest_batch: Sequence[str],
) -> Tuple[str, ...]:
    """The bind step. Put the newest batch's matches first, then the earlier bound names.
    Remove duplicates, core names and names the snapshot does not hold. Keep the first
    `CATALOGUE_MATCH_COUNT`."""
    out: List[str] = []
    for name in list(newest_batch) + list(earlier or ()):
        if name in out or name in snapshot.core_names or name not in snapshot.tools_by_name:
            continue
        out.append(name)
    return tuple(out[:CATALOGUE_MATCH_COUNT])


__all__ = [
    "CATALOGUE_MATCH_COUNT", "CatalogueSnapshot", "NO_MATCH_TEXT", "PACKS", "SEARCH_TOOL",
    "bind_names", "build_snapshot", "make_search_tool", "matched_names", "search_result",
    "tool_schema",
]
