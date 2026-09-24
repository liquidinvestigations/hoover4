"""The tool packs: which tools each kind of agent run may bind and call.

A pack is a named set of tool names. Configuration gives each kind of run a set of packs
(`AGENT_PACKS_CHAT`, `AGENT_PACKS_SUBAGENT`, `AGENT_PACKS_PLANNER`, `AGENT_PACKS_ORGANIZER`,
rendered by `deploy.py` from `hoover4.ini`). The research agent binds, runs and lists in its
catalogue only the tools of the run's packs. A tool that an MCP server lists and no pack
names is refused for every run.

Each tool name is in exactly one pack. A test in every MCP server image lists that server's
tools with the server's own `list_tools` and checks this, so a new tool with no pack fails a
test before it reaches a model.
"""

from __future__ import annotations

import os
from typing import Dict, FrozenSet, Optional

PACKS: Dict[str, FrozenSet[str]] = {
    "catalogue": frozenset({"search_agent_tools"}),
    "collections": frozenset({
        "list_collections", "search_collections", "search_passages", "search_facet_values",
        "search_histogram", "search_entity_explainer", "read_documents", "doc_search_text",
        "doc_sources", "doc_metadata", "doc_email", "doc_diff_sources", "pdf_search",
        "list_document_entities", "cite_documents", "table_overview", "table_page",
        "table_cell", "table_column_values", "table_search_cells", "folder_overview",
        "folder_list", "folder_search", "read_more",
    }),
    "conversation": frozenset({"read_todo", "write_todo", "edit_todo", "mark_todo"}),
    "plan": frozenset({"read_plan", "append_node", "append_child", "move_node", "edit_node",
                       "remove_node", "read_plan_document"}),
    "delegation": frozenset({"run_subagent"}),
    "web": frozenset({"web_search", "list_search_sources", "whois_lookup", "read_page"}),
    "browser": frozenset({"browser_navigate", "browser_snapshot", "browser_click",
                          "browser_type", "browser_select_option", "browser_press_key"}),
}

#: The kinds of agent run. Each has its own pack setting.
RUN_KINDS = ("chat", "subagent", "planner", "organizer")

#: The value that selects every pack.
ALL = "all"


def env_name(kind: str) -> str:
    """Return the environment variable that holds the pack setting of one run kind."""
    return f"AGENT_PACKS_{kind.upper()}"


def pack_of(tool_name: str) -> Optional[str]:
    """Return the pack that holds a tool, or `None` when no pack names it."""
    for pack, names in PACKS.items():
        if tool_name in names:
            return pack
    return None


def packs_for(kind: str, configured: str) -> FrozenSet[str]:
    """Return the pack names of one run kind.

    `configured` is a comma list of pack names, or `all`. An empty value means `all`,
    because compose renders an unset key as an empty string. An unknown pack name or an
    unknown run kind raises `ValueError`.
    """
    if kind not in RUN_KINDS:
        raise ValueError(f"unknown agent run kind {kind!r}, expected one of {RUN_KINDS}")
    value = (configured or "").strip()
    if not value or value == ALL:
        return frozenset(PACKS)
    names = frozenset(part.strip() for part in value.split(",") if part.strip())
    unknown = sorted(names - set(PACKS))
    if unknown:
        raise ValueError(
            f"{env_name(kind)} names unknown tool packs {unknown}. "
            f"The packs are {sorted(PACKS)}, or {ALL!r}."
        )
    return names


def allowed_tools(kind: str, configured: str) -> FrozenSet[str]:
    """Return the union of the tools of `packs_for(kind, configured)`."""
    names: set = set()
    for pack in packs_for(kind, configured):
        names |= PACKS[pack]
    return frozenset(names)


def configured_packs(kind: str) -> str:
    """Return the pack setting of one run kind from the environment. Unset means `all`."""
    return os.getenv(env_name(kind), "") or ALL


def check_environment() -> Dict[str, FrozenSet[str]]:
    """Return the packs of every run kind, and raise on an unknown pack name.

    The agent service calls this at start, so a mistyped pack name stops the service
    before it answers a request.
    """
    return {kind: packs_for(kind, configured_packs(kind)) for kind in RUN_KINDS}
