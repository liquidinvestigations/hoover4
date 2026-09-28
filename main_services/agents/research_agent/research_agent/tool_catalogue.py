"""The tool catalogue of one step context, and the `search_agent_tools` tool.

A model step binds the tools of `ALWAYS_BOUND` on every model call, the same set for every
run kind. The other tools of the run's packs are deferred. The model binds one for the next
model call in two ways: a match of `search_agent_tools`, or a successful `read_tool` call.
A plan tool or `run_subagent` that the model bound stays bound for the rest of the run.

`CatalogueSnapshot` is built once for each step context from the tools that context loaded.
It holds only the tools of the run's packs, so the model cannot bind, run or find a tool
outside them. The snapshot never changes, so concurrent steps that share one context can
share it. The bound names of a run are not stored anywhere. `bound_names_from_thread`
derives them again from the stored thread at each step.
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

from agent_common.tool_packs import PACKS, pack_of
from research_agent import skill_tools
from research_agent.skill_store import (
    DEFAULT_PROFILE,
    RUN_KIND_PROFILES,
    SkillContext,
    rank_matches,
)

log = logging.getLogger(__name__)

SEARCH_TOOL = "search_agent_tools"
DELEGATION_TOOL = "run_subagent"

#: The tools that every model call binds, for every run kind. A name that the run's packs
#: do not hold is not in the snapshot, so it is not bound.
ALWAYS_BOUND = frozenset({
    "search_agent_tools", "search_skills", "read_skill", "read_tool",
    "read_todo", "write_todo", "edit_todo", "mark_todo",
    "list_collections", "search_collections", "search_passages",
    "read_documents", "cite_documents",
})

#: The deferred tools that stay bound for the rest of the run once the model binds them. They
#: do not count against `CATALOGUE_MATCH_COUNT`, so a planner that binds its plan tools and
#: then a research tool keeps every plan tool.
STICKY = PACKS["plan"] | {DELEGATION_TOOL}

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
    core_names: Tuple[str, ...]
    deferred_names: Tuple[str, ...]
    summaries: Mapping[str, str]
    categories: Mapping[str, str]
    refused_names: Tuple[str, ...] = field(default=())
    skill_context: Optional[SkillContext] = None

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
        items = [
            (name, self.summaries.get(name, ""))
            for name in self.tools_by_name if name != SEARCH_TOOL
        ]
        return [
            {"name": name, "summary": self.summaries.get(name, ""),
             "category": self.categories.get(name, "")}
            for name in rank_matches(query, items)[:limit]
        ]


def _is_core(name: str, kind: str) -> bool:
    """Whether every model call binds a tool. `kind` is not read, because the set is the same
    for every run kind."""
    return name in ALWAYS_BOUND


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
    holds are built the same way, over this snapshot and its skill context.

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
    ):
        if tool.name in allowed:
            kept[tool.name] = tool

    names = sorted(kept)
    digest = hashlib.sha256(
        json.dumps(
            [[n, tool_schema(kept[n])] for n in names], sort_keys=True, default=str
        ).encode()
    ).hexdigest()
    core = tuple(n for n in names if _is_core(n, kind))
    deferred = tuple(n for n in names if not _is_core(n, kind))
    if skill_context is None:
        skill_context = SkillContext(
            profile=RUN_KIND_PROFILES.get(kind, DEFAULT_PROFILE), tool_names=frozenset()
        )
    skill_context = replace(skill_context, tool_names=frozenset(names))
    snapshot = CatalogueSnapshot(
        version=digest,
        tools_by_name=dict(kept),
        core_names=core,
        deferred_names=deferred,
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
    """The bind step. Put the newest batch's names first, then the earlier bound names.
    Remove duplicates, core names and names the snapshot does not hold. Keep every name of
    `STICKY`, and the first `CATALOGUE_MATCH_COUNT` of the other names."""
    out: List[str] = []
    sticky: List[str] = []
    for name in list(newest_batch) + list(earlier or ()):
        if (name in out or name in sticky or name in snapshot.core_names
                or name not in snapshot.tools_by_name):
            continue
        (sticky if name in STICKY else out).append(name)
    return tuple(sticky + out[:CATALOGUE_MATCH_COUNT])


def bound_names_from_thread(snapshot: CatalogueSnapshot, messages: Sequence[Any]) -> Tuple[str, ...]:
    """Replay the bind step over a stored thread, and return the bound names after it.

    `messages` are `RunMessage` rows in thread order. For each `ai` message with calls, the
    `tool` messages that follow it are its batch. The names that the successful
    `search_agent_tools` results of the batch matched, and then the names of its successful
    `read_tool` results in call order, are bound first, before the earlier names. The
    function is pure, so each step of a run derives the same names from the
    same thread, and a retried step keeps the names that earlier searches bound.
    """
    bound: Tuple[str, ...] = ()
    for i, message in enumerate(messages):
        if getattr(message, "role", None) != "ai" or not getattr(message, "tool_calls", None):
            continue
        ids = {call.id for call in message.tool_calls}
        newest: List[str] = []
        read: List[str] = []
        for answer in messages[i + 1:]:
            if getattr(answer, "role", None) != "tool":
                break
            if answer.tool_call_id not in ids or getattr(answer, "status", None) == "error":
                continue
            if answer.name == SEARCH_TOOL:
                newest.extend(matched_names(answer.content))
            elif answer.name == skill_tools.READ_TOOL:
                name = skill_tools.read_tool_name(answer.content)
                if name:
                    read.append(name)
        bound = bind_names(snapshot, bound, newest + read)
    return bound


__all__ = [
    "ALWAYS_BOUND", "CATALOGUE_MATCH_COUNT", "CatalogueSnapshot", "NO_MATCH_TEXT", "PACKS",
    "SEARCH_TOOL", "STICKY",
    "bind_names", "bound_names_from_thread", "build_snapshot", "make_search_tool",
    "matched_names", "search_result", "tool_schema",
]
