"""The reading of a table sheet and the count state of a text read, through the models,
the tools and the page broker.

A count of a table route describes one reading of the sheet's first row. A page that shows
the count also shows the reading. A text read count shows whether it is exact."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_common.result_pages import decode_continuation
from collection_search_server import paging, server, tools_document, tools_table
from collection_search_server.backend_client import (
    DocumentsSearchTextResponse, TablesColumnValuesRequest, TablesOverviewRequest, TablesOverviewResponse,
    TablesPageRequest, TablesPageResponse, TablesSearchCellsRequest,
)
from test_paging import INTERPRETATION, SAMPLES, Store, token_of, walk


def _post(monkeypatch, body, sent=None):
    def post(self, route, request, response_model, expected_source=None):
        if sent is not None:
            sent.append(request)
        return response_model.model_validate(deepcopy(body))
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)


@pytest.mark.parametrize("model,values", [
    (TablesOverviewRequest, {}),
    (TablesPageRequest, {"sheet": 0}),
    (TablesColumnValuesRequest, {"sheet": 0, "column": 1}),
    (TablesSearchCellsRequest, {"sheet": 0, "query": "x"}),
])
def test_a_table_request_takes_the_three_readings_and_refuses_another(model, values):
    base = {"collectionname": "c", "file_hash": "h", **values}
    for name in ("auto", "all_rows", "first_row_header"):
        assert model.model_validate({**base, "interpretation": name}).interpretation == name
    assert "interpretation" not in model.model_validate(base).model_dump(exclude_none=True)
    with pytest.raises(ValidationError):
        model.model_validate({**base, "interpretation": "header_row_2"})


def test_the_response_models_take_the_reading_and_still_refuse_an_unknown_field():
    page = {**SAMPLES["table_page"], "source": "s"}
    assert TablesPageResponse.model_validate(page).interpretation.selected == "all_rows"
    with pytest.raises(ValidationError):
        TablesPageResponse.model_validate({**page, "interpretation": {**INTERPRETATION, "guess": 1}})
    with pytest.raises(ValidationError):
        TablesPageResponse.model_validate({**page, "header_guess": 1})
    # A backend from before the change sends no reading. The model takes the response.
    older = {key: value for key, value in page.items() if key != "interpretation"}
    assert TablesPageResponse.model_validate(older).interpretation is None
    sheet = deepcopy(SAMPLES["table_overview"]["sheets"][0])
    sheet["columns"][0]["kinds"] = {"int": 18, "text": 1}
    overview = TablesOverviewResponse.model_validate({**SAMPLES["table_overview"], "sheets": [sheet], "source": "s"})
    assert overview.sheets[0].columns[0].kinds == {"int": 18, "text": 1}


def test_a_page_compacts_empty_kinds_and_an_absent_established_count(monkeypatch):
    _post(monkeypatch, {**SAMPLES["table_overview"], "source": "s"})
    tool = tools_table.TABLE_OVERVIEW
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h"}), {}, ""))
    sheet = page["items"][0]
    assert sheet["interpretation"] == INTERPRETATION
    assert "kinds" not in sheet["columns"][0] and "established_rows" not in sheet["interpretation"]


@pytest.mark.parametrize("tool_name", ["table_overview", "table_page", "table_column_values", "table_search_cells"])
def test_each_table_tool_sends_the_selected_reading(tool_name, monkeypatch):
    sent = []
    _post(monkeypatch, {**SAMPLES[tool_name], "source": "s"}, sent)
    monkeypatch.setattr(server, "full_hashes", lambda collection, file_hash: file_hash)
    arguments = {"collection": "c", "file_hash": "h", "interpretation": "first_row_header"}
    if tool_name != "table_overview":
        arguments["sheet"] = 0
    if tool_name == "table_column_values":
        arguments["column"] = 1
    if tool_name == "table_search_cells":
        arguments["query"] = "x"
    function = getattr(tools_table, tool_name)
    function = getattr(function, "fn", function)
    result = json.loads(function(**arguments))
    assert "error" not in result, result
    assert sent[0].interpretation == "first_row_header"
    assert sent[0].model_dump(exclude_none=True)["interpretation"] == "first_row_header"


def test_a_continuation_sends_the_same_reading_to_the_next_backend_window(monkeypatch):
    Store(monkeypatch)
    sent = []
    following = {"kind": "Rows", "row_start": 50}

    def post(self, route, request, response_model, expected_source=None):
        sent.append((request.interpretation, request.position.model_dump(mode="json") if request.position else None))
        second = request.position is not None
        rows = [{"row_number": n, "row_id": n + (3 if second else 0), "cells": {"a": str(n)}} for n in range(3)]
        body = {**SAMPLES["table_page"], "rows": rows, "next_position": None if second else following,
                "total": 6, "total_rows": 6, "source": "stable"}
        return response_model.model_validate(body)

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    tool = tools_table.TABLE_PAGE
    request = tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0, "interpretation": "all_rows"})
    pages = walk(json.loads(tool.render(request, {}, "")))
    assert sent == [("all_rows", None), ("all_rows", following)]
    assert sum(len(page["items"]) for page in pages) == 6


@pytest.mark.parametrize("share", [700, 900, 1200, 2000, 4000, 24_000])
def test_a_page_never_shows_a_table_count_without_its_reading(share, monkeypatch):
    """A small page share leaves the route fields out of a page as a whole. A page that
    keeps `total_rows` also keeps `interpretation`."""
    Store(monkeypatch)
    monkeypatch.setattr(paging, "page_share", lambda: share)
    rows = [{"row_number": n, "row_id": n, "cells": {"a": "x" * 120}} for n in range(40)]
    _post(monkeypatch, {**SAMPLES["table_page"], "rows": rows, "total_rows": 40, "total": 40, "source": "stable"})
    tool = tools_table.TABLE_PAGE
    pages = walk(json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0}), {}, "")))
    assert pages
    for page in pages:
        if "error" in page:
            continue
        assert ("total_rows" in page) == ("interpretation" in page), page
        if "interpretation" in page:
            assert page["interpretation"]["selected"] == "all_rows"


@pytest.mark.parametrize("share", [900, 1200, 2000])
def test_a_cut_sheet_keeps_its_reading_beside_its_row_count(share, monkeypatch):
    """A sheet unit larger than the page share has its longest strings moved out. The
    reading stays in the unit beside `row_count`."""
    Store(monkeypatch)
    monkeypatch.setattr(paging, "page_share", lambda: share)
    columns = [{"column_id": n, "name": f"c{n}", "type": "text"} for n in range(1, 4)]
    sheet = {"sheet": 0, "name": "s" * 3000, "row_count": 19, "column_count": 3, "columns": columns,
             "interpretation": INTERPRETATION}
    _post(monkeypatch, {**SAMPLES["table_overview"], "sheets": [sheet], "source": "stable"})
    tool = tools_table.TABLE_OVERVIEW
    pages = walk(json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h"}), {}, "")))
    counted = [item for page in pages for item in page.get("items") or []
               if isinstance(item, dict) and "row_count" in item]
    assert counted and all(item["interpretation"] == INTERPRETATION for item in counted), pages
    assert any("cut" in item for item in counted), "the unit was cut inside its name"


def test_a_sheet_read_as_unit_text_names_its_reading_before_its_row_count(monkeypatch):
    """A sheet unit that does not fit a page even with its strings moved out is read as its
    canonical JSON text. The sorted keys put the reading before `row_count`."""
    Store(monkeypatch)
    monkeypatch.setattr(paging, "page_share", lambda: 700)
    columns = [{"column_id": n, "name": f"column name {n} " + "y" * 60, "type": "text"} for n in range(1, 30)]
    sheet = {"sheet": 0, "name": "s" * 400, "row_count": 19, "column_count": 29, "columns": columns,
             "interpretation": INTERPRETATION}
    _post(monkeypatch, {**SAMPLES["table_overview"], "sheets": [sheet], "source": "stable"})
    tool = tools_table.TABLE_OVERVIEW
    pages = walk(json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h"}), {}, "")))
    text = "".join(item for page in pages for item in page.get("items") or [] if isinstance(item, str))
    assert 0 <= text.index('"interpretation":') < text.index('"row_count":'), text[:200]


def test_a_lower_bound_text_read_keeps_its_state_and_a_zero_count(monkeypatch):
    document = {**SAMPLES["read_documents"]["documents"][0], "hit_count": 0, "hit_pages": [], "count_state": "lower_bound"}
    _post(monkeypatch, {**SAMPLES["read_documents"], "documents": [document], "source": "s"})
    tool = tools_document.READ_DOCUMENTS
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": ["h"], "query": "q"}), {}, ""))
    item = page["items"][0]
    assert item["count_state"] == "lower_bound" and item["hit_count"] == 0, item


def test_a_text_read_without_a_query_shows_no_count_state(monkeypatch):
    _post(monkeypatch, {**SAMPLES["read_documents"], "source": "s"})
    tool = tools_document.READ_DOCUMENTS
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": ["h"]}), {}, ""))
    assert "count_state" not in page["items"][0]


def test_a_lower_bound_text_search_shows_its_state_and_no_total(monkeypatch):
    body = {**SAMPLES["doc_search_text"], "count_state": "lower_bound", "total": None, "partial": True, "source": "s"}
    _post(monkeypatch, body)
    tool = tools_document.DOC_SEARCH_TEXT
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "query": "q"}), {}, ""))
    assert page["count_state"] == "lower_bound" and page["partial"] is True
    assert "total" not in page
    # A backend from before the change sends no count state.
    older = {key: value for key, value in body.items() if key != "count_state"}
    assert DocumentsSearchTextResponse.model_validate(older).count_state is None


def test_an_old_text_continuation_gets_the_source_changed_answer(monkeypatch):
    """A continuation stored before the source revision binding holds the older source
    text. The route answers 409, which the broker passes on as `source_changed`."""
    def post(self, route, request, response_model, expected_source=None):
        assert expected_source == "h:raw_text:3:3"
        return paging.AgentError(error="source_changed", message="the source changed after the prior page")
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    tool = tools_document.DOC_SEARCH_TEXT
    request = tool.model.model_validate({"collectionname": "c", "file_hash": "h", "query": "q"})
    page = json.loads(tool.render(request, {"window": {"kind": "HitKey", "page_id": 1, "ordinal": 49}}, "h:raw_text:3:3"))
    assert page["error"] == "source_changed"
