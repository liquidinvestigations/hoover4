"""Folder tools backed by the website agent API."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import FoldersListRequest, FoldersOverviewRequest, FoldersSearchRequest
from collection_search_server.paging import PagedTool
from collection_search_server.server import mcp


FOLDER_OVERVIEW = PagedTool(FoldersOverviewRequest, "folders/overview", "folder_overview", "rows", "datasets")
FOLDER_LIST = PagedTool(FoldersListRequest, "folders/list", "folder_list", "tree", "__folder_items")
FOLDER_SEARCH = PagedTool(FoldersSearchRequest, "folders/search", "folder_search", "rows", "matches")
PAGED_TOOLS = {"folder_overview": FOLDER_OVERVIEW, "folder_list": FOLDER_LIST, "folder_search": FOLDER_SEARCH}


def _render(tool: PagedTool, values: dict[str, Any]) -> str:
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="folder_overview", description="Return collection and dataset storage counts. Use it to inspect the storage landing page.")
def folder_overview(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], dataset: Annotated[str | None, Field(description='Copy the dataset name from list_collections. Omission in folder_overview covers all datasets of one collection.')] = None) -> str:
    return _render(FOLDER_OVERVIEW, {"collectionname": collection, "dataset": dataset})


@mcp.tool(name="folder_list", description="Return folder children, files, breadcrumb, and container root. Use it to browse one dataset node.")
def folder_list(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], dataset: Annotated[str, Field(description='Copy the dataset name from list_collections. Omission in folder_overview covers all datasets of one collection.')], node_id: Annotated[str | None, Field(description='Copy the folder node identifier from a result. Omission selects the dataset root.')] = None) -> str:
    return _render(FOLDER_LIST, {"collectionname": collection, "dataset": dataset, "node_id": node_id})


@mcp.tool(name="folder_search", description="Find nodes under one dataset folder. Use it to locate a folder or file by name.")
def folder_search(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], dataset: Annotated[str, Field(description='Copy the dataset name from list_collections. Omission in folder_overview covers all datasets of one collection.')], query: Annotated[str, Field(description='Text or query syntax to match file names and paths.')], node_id: Annotated[str | None, Field(description='Copy the folder node identifier from a result. Omission selects the dataset root.')] = None) -> str:
    return _render(FOLDER_SEARCH, {"collectionname": collection, "dataset": dataset, "node_id": node_id, "query": query})
