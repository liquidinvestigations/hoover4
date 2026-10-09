"""Table tools backed by the website agent API."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import AgentTableFilter, AgentTableSort, TablesCellRequest, TablesColumnValuesRequest, TablesOverviewRequest, TablesPageRequest, TablesSearchCellsRequest
from collection_search_server import server
from collection_search_server.paging import PagedTool
from collection_search_server.tools_document import DocumentSearchTool
from collection_search_server.server import mcp


TABLE_OVERVIEW = PagedTool(TablesOverviewRequest, "tables/overview", "table_overview", "rows", "sheets")
TABLE_PAGE = PagedTool(TablesPageRequest, "tables/page", "table_page", "table", "rows", "columns")
TABLE_CELL = PagedTool(TablesCellRequest, "tables/cell", "table_cell", "blob", "text")
TABLE_COLUMN_VALUES = PagedTool(TablesColumnValuesRequest, "tables/column_values", "table_column_values", "rows", "values")
TABLE_SEARCH_CELLS = DocumentSearchTool(TablesSearchCellsRequest, "tables/search_cells", "table_search_cells", "rows", "hits")
PAGED_TOOLS = {"table_overview": TABLE_OVERVIEW, "table_page": TABLE_PAGE, "table_cell": TABLE_CELL, "table_column_values": TABLE_COLUMN_VALUES, "table_search_cells": TABLE_SEARCH_CELLS}


def _render(tool: PagedTool, values: dict[str, Any]) -> str:
    """The first page of `tool` for `values`. A hash start in `file_hash` becomes its whole
    hash first."""
    try:
        values["file_hash"] = server.full_hashes(values["collectionname"], values["file_hash"])
    except server.HashPrefixError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
    except Exception:  # noqa: BLE001, a failed lookup leaves the hash to the route
        server.log.warning("the file_hash of %s was not looked up", tool.tool_name, exc_info=True)
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="table_overview", description="List sheets and columns in one table document. Use it before reading a sheet.")
def table_overview(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')]) -> str:
    return _render(TABLE_OVERVIEW, {"collectionname": collection, "file_hash": file_hash})


@mcp.tool(name="table_page", description="Return one window of 50 table rows, sorted and filtered as asked. Use it to read rows. Pass `columns` (column ids, at most 60) to read columns after the 60th, and `row_start` (0-based) to jump into a large sheet. A cell over 2,000 characters is cut: read it whole with table_cell.")
def table_page(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], sheet: Annotated[int, Field(description='Copy the sheet identifier returned by table_overview.')], sort: Annotated[AgentTableSort | None, Field(description='Sort field and direction. Omission uses the backend default order.')] = None, filters: Annotated[list[AgentTableFilter] | None, Field(description='Table predicates using returned column identifiers. All predicates must match.')] = None, columns: Annotated[list[int] | None, Field(description='Column identifiers to return. Omission uses the first available columns.')] = None, search: Annotated[str, Field(description='Optional text filter for returned rows or values. Omission applies no text filter.')] = "", row_start: Annotated[int | None, Field(description='Zero-based position in the requested row order. Omission starts at the first row.')] = None) -> str:
    return _render(TABLE_PAGE, {"collectionname": collection, "file_hash": file_hash, "sheet": sheet, "sort": sort, "filters": filters or [], "columns": columns or [], "search": search, "row_start": row_start})


@mcp.tool(name="table_cell", description="Read one whole table cell, in slices of 2,000 characters. Use it when table_page cut a long cell. `row` is the row_id of the table_page row, and `column` is the column id.")
def table_cell(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], sheet: Annotated[int, Field(description='Copy the sheet identifier returned by table_overview.')], row: Annotated[int, Field(description='Copy the returned row_id. This is a row identity, not its position in a sorted result.')], column: Annotated[int, Field(description='Copy the column identifier returned by table_overview.')]) -> str:
    return _render(TABLE_CELL, {"collectionname": collection, "file_hash": file_hash, "sheet": sheet, "row": row, "column": column})


@mcp.tool(name="table_column_values", description="List values and counts for one table column, most frequent first. Use it to choose a table filter. `search` keeps the values that contain its text.")
def table_column_values(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], sheet: Annotated[int, Field(description='Copy the sheet identifier returned by table_overview.')], column: Annotated[int, Field(description='Copy the column identifier returned by table_overview.')], search: Annotated[str, Field(description='Optional text filter for returned rows or values. Omission applies no text filter.')] = "") -> str:
    return _render(TABLE_COLUMN_VALUES, {"collectionname": collection, "file_hash": file_hash, "sheet": sheet, "column": column, "search": search})


@mcp.tool(name="table_search_cells", description="Find matching cells in one table sheet. Use it to locate values before reading rows.")
def table_search_cells(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], sheet: Annotated[int, Field(description='Copy the sheet identifier returned by table_overview.')], query: Annotated[str, Field(description='Text or query syntax to match. An empty search_collections query lists filter matches.')]) -> str:
    return _render(TABLE_SEARCH_CELLS, {"collectionname": collection, "file_hash": file_hash, "sheet": sheet, "query": query})
