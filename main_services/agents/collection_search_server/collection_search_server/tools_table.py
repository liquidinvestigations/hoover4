"""Table tools backed by the website agent API."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import AgentTableFilter, AgentTableSort, TablesCellRequest, TablesColumnValuesRequest, TablesOverviewRequest, TablesPageRequest, TablesSearchCellsRequest
from collection_search_server.paging import PagedTool
from collection_search_server.server import mcp


TABLE_OVERVIEW = PagedTool(TablesOverviewRequest, "tables/overview", "table_overview", "rows", "sheets")
TABLE_PAGE = PagedTool(TablesPageRequest, "tables/page", "table_page", "table", "rows", "columns")
TABLE_CELL = PagedTool(TablesCellRequest, "tables/cell", "table_cell", "blob", "text")
TABLE_COLUMN_VALUES = PagedTool(TablesColumnValuesRequest, "tables/column_values", "table_column_values", "rows", "values")
TABLE_SEARCH_CELLS = PagedTool(TablesSearchCellsRequest, "tables/search_cells", "table_search_cells", "rows", "hits")
PAGED_TOOLS = {"table_overview": TABLE_OVERVIEW, "table_page": TABLE_PAGE, "table_cell": TABLE_CELL, "table_column_values": TABLE_COLUMN_VALUES, "table_search_cells": TABLE_SEARCH_CELLS}


def _render(tool: PagedTool, values: dict[str, Any]) -> str:
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="table_overview", description="List sheets and columns in one table document. Use it before reading a sheet.")
def table_overview(collectionname: str, file_hash: str) -> str:
    return _render(TABLE_OVERVIEW, {"collectionname": collectionname, "file_hash": file_hash})


@mcp.tool(name="table_page", description="Return one window of 50 table rows, sorted and filtered as asked. Use it to read rows. Pass `columns` (column ids, at most 60) to read columns after the 60th, and `row_start` (0-based) to jump into a large sheet. A cell over 2,000 characters is cut: read it whole with table_cell.")
def table_page(collectionname: str, file_hash: str, sheet: int, sort: AgentTableSort | None = None, filters: list[AgentTableFilter] | None = None, columns: list[int] | None = None, search: str = "", row_start: int | None = None) -> str:
    return _render(TABLE_PAGE, {"collectionname": collectionname, "file_hash": file_hash, "sheet": sheet, "sort": sort, "filters": filters or [], "columns": columns or [], "search": search, "row_start": row_start})


@mcp.tool(name="table_cell", description="Read one whole table cell, in slices of 2,000 characters. Use it when table_page cut a long cell. `row` is the row_id of the table_page row, and `column` is the column id.")
def table_cell(collectionname: str, file_hash: str, sheet: int, row: int, column: int) -> str:
    return _render(TABLE_CELL, {"collectionname": collectionname, "file_hash": file_hash, "sheet": sheet, "row": row, "column": column})


@mcp.tool(name="table_column_values", description="List values and counts for one table column, most frequent first. Use it to choose a table filter. `search` keeps the values that contain its text.")
def table_column_values(collectionname: str, file_hash: str, sheet: int, column: int, search: str = "") -> str:
    return _render(TABLE_COLUMN_VALUES, {"collectionname": collectionname, "file_hash": file_hash, "sheet": sheet, "column": column, "search": search})


@mcp.tool(name="table_search_cells", description="Find matching cells in one table sheet. Use it to locate values before reading rows.")
def table_search_cells(collectionname: str, file_hash: str, sheet: int, query: str) -> str:
    return _render(TABLE_SEARCH_CELLS, {"collectionname": collectionname, "file_hash": file_hash, "sheet": sheet, "query": query})
