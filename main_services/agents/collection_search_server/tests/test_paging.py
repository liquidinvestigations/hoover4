"""Check response fields and source positions in collection result pages."""

import json

import pytest

from agent_common.artifacts import ArtifactWriteFailed
from agent_common.result_pages import ByteLimit, decode_continuation
from collection_search_server import tools_document, tools_folder, tools_search, tools_table
from collection_search_server.paging import RESPONSE_MODELS, _read_more_response


TOOLS = {
    **tools_search.PAGED_TOOLS,
    **tools_document.PAGED_TOOLS,
    **tools_table.PAGED_TOOLS,
    **tools_folder.PAGED_TOOLS,
}


SAMPLES = {
    "list_collections": {"collections": [{"collectionname": "c", "document_count": 1, "datasets": [{"name": "d", "document_count": 1}]}]},
    "search_collections": {"documents": [{"file_hash": "h"}], "total_count": 3, "facet_counts": {"type": [{"value": "pdf", "count": 2}]}, "page": 0, "has_more": True},
    "search_facet_values": {"terms": [{"id": 1, "text": "pdf", "count": 2}], "resolved": {"1": "pdf"}},
    "search_date_histogram": {"buckets": [{"start": 1, "end": 2, "count": 1}], "date_field": "date"},
    "search_entity_explainer": {"explanation": {"title": "person"}, "documents": [{"file_hash": "h"}]},
    "read_documents": {"documents": [{"file_hash": "h", "text": "a", "hit_count": 1, "hit_positions": [0]}]},
    "doc_sources": {"sources": [{"source": "text", "hit_count": 1}]},
    "doc_metadata": {"raw_metadata": {"author": ["a"]}, "dates": [{"value": "today"}], "file_locations": ["p"], "path": "p", "canonical_file_type": "pdf", "download_links": {"original": "/x"}},
    "doc_email": {"envelope": {"subject": "s"}, "headers": {"x": "y"}, "attachments": [{"name": "a"}], "graph": {"nodes": [1], "edges": []}},
    "doc_diff_sources": {"source_a": "a", "source_b": "b", "unified_diff": "-a\n+b"},
    "pdf_search": {"pdf_url": "/x", "hit_positions": [{"page": 1}], "hit_count": 1},
    "table_overview": {"sheets": [{"name": "s", "row_count": 1, "column_count": 1, "columns": [{"name": "a", "type": "text"}]}]},
    "table_page": {"columns": [{"name": "a", "type": "text", "hidden": False}], "rows": [{"row_number": 1, "cells": {"a": "x"}}], "page": 0, "total_rows": 1},
    "table_column_values": {"values": [{"value": "x", "count": 1}]},
    "table_search_cells": {"hit_count": 1, "hits": [{"row_number": 1, "column": "a", "value": "x"}]},
    "folder_overview": {"datasets": [{"name": "d"}], "folder_count": 1, "file_count": 2, "total_bytes": 3},
    "folder_list": {"breadcrumb": [{"node_id": "r", "name": "root"}], "container_root": "r", "children": [{"node_id": "a", "name": "a"}], "files": [{"node_id": "b", "name": "b"}], "page": 0},
    "folder_search": {"matches": [{"node_id": "a", "name": "a"}]},
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_route_fields_reach_page(name, monkeypatch):
    tool = TOOLS[name]
    response = {**SAMPLES[name], "source": "fingerprint"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, source=None: response_model.model_validate(response))
    monkeypatch.setattr("collection_search_server.paging._artifact", lambda tool_name, complete: "artifact")
    request = tool.model.model_construct()
    page = json.loads(tool.render(request, {}, ""))
    assert page["success"] is True
    assert page["tool_name"] == name
    assert RESPONSE_MODELS[tool.route].model_fields.keys() == response.keys()
    assert page["fields"]["source"] == "fingerprint"
    for key, value in SAMPLES[name].items():
        if key == tool.item_key:
            assert page["items"] == (value if isinstance(value, list) else [value])
        elif key == tool.columns_key:
            assert page["columns"] == value
        elif key == "raw_metadata":
            assert page["items"] == [{"field": "raw_metadata", "key": k, "value": v} for k, v in value.items()]
        elif name == "folder_list" and key in ("children", "files"):
            assert {"field": key, "value": value[0]} in page["items"]
        else:
            assert page["fields"][key] == value


def test_changed_source_returns_typed_error(monkeypatch):
    tool = TOOLS["search_collections"]
    response = {**SAMPLES["search_collections"], "source": "new"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, source=None: response_model.model_validate(response))
    page = json.loads(tool.render(tool.model.model_construct(), {"page": 1, "offset": 0}, "old"))
    assert page["error"] == "source_changed"


@pytest.mark.parametrize("change", [{"position": "bad"}, {"position": {"page": "one"}}, {"position": {}}, {"position": {"page": 0, "offset": 0, "blob": 2}}, {"tool": []}, {"source": []}, {"input": []}])
def test_malformed_continuation_fields_return_invalid_argument(change):
    token = {"tool": "search_collections", "input": {}, "position": {"page": 0}, "source": ""}
    token.update(change)
    assert json.loads(_read_more_response(token))["error"] == "invalid_argument"


@pytest.mark.parametrize("name", ["search_collections", "table_page", "folder_list"])
def test_two_backend_pages_and_inside_page_cut(name, monkeypatch):
    tool = TOOLS[name]
    batch_size = {"search_collections": 2, "table_page": 50, "folder_list": 200}[name]
    first = [{"node_id": str(n), "file_hash": str(n), "text": "x" * (350 if name == "search_collections" else 1)} for n in range(batch_size)]
    second = [{"node_id": str(n), "file_hash": str(n), "text": "x" * (350 if name == "search_collections" else 1)} for n in range(batch_size, batch_size * 2)]
    calls = []

    def post(self, route, request, response_model, source=None):
        page = request.position.page if request.position else 0
        calls.append(page)
        items = first if page == 0 else second if page == 1 else []
        if name == "search_collections":
            body = {"documents": items, "total_count": 4, "facet_counts": {}, "page": page, "has_more": page == 0}
        elif name == "table_page":
            body = {"columns": [{"name": "text", "type": "text", "hidden": False}], "rows": items, "page": page, "total_rows": 100}
        else:
            body = {"breadcrumb": [], "container_root": None, "children": [], "files": items, "page": page}
        return response_model.model_validate({**body, "source": "stable"})

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    monkeypatch.setattr("collection_search_server.paging._artifact", lambda tool_name, complete: "artifact")
    monkeypatch.setattr("collection_search_server.paging.PAGE_LIMIT", ByteLimit(1_000 if name == "search_collections" else 24_000))
    request_values = {"search_collections": {}, "table_page": {"collectionname": "c", "file_hash": "h", "sheet": 0}, "folder_list": {"collectionname": "c", "dataset": "d"}}[name]
    page = json.loads(tool.render(tool.model.model_validate(request_values), {}, ""))
    if name == "folder_list":
        assert page["total_units"] > page["returned_units"]
    seen = []
    for _ in range(20):
        assert page["success"], page
        seen.extend(page["items"])
        if not page["continuation"]:
            break
        page = json.loads(_read_more_response(decode_continuation(page["continuation"])))
    assert len(seen) == batch_size * 2
    ids = [item["value"]["file_hash"] if name == "folder_list" else item["file_hash"] for item in seen]
    assert ids == [str(n) for n in range(batch_size * 2)]
    assert calls[:2] == ([0, 0] if name == "search_collections" else [0, 1])
    assert page["continuation"] is None


def test_required_artifact_failure_is_returned(monkeypatch):
    tool = TOOLS["search_collections"]
    response = {**SAMPLES["search_collections"], "source": "stable"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, source=None: response_model.model_validate(response))

    def fail(tool_name, complete):
        raise ArtifactWriteFailed("write failed")

    monkeypatch.setattr("collection_search_server.paging._artifact", fail)
    page = json.loads(tool.render(tool.model.model_construct(), {}, ""))
    assert page["error"] == "artifact_write_failed"


def test_large_field_uses_utf8_blob_with_field_name(monkeypatch):
    tool = TOOLS["doc_email"]
    response = {**SAMPLES["doc_email"], "headers": {"subject": "é" * 12_000}, "source": "stable"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, source=None: response_model.model_validate(response))
    monkeypatch.setattr("collection_search_server.paging._artifact", lambda tool_name, complete: "artifact")
    first = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h"}), {}, ""))
    assert first["shape"] == "blob"
    text = first["items"][0]
    page = first
    for _ in range(10):
        if not page["continuation"]:
            break
        page = json.loads(_read_more_response(decode_continuation(page["continuation"])))
        text += page["items"][0]
    assert page["continuation"] is None
    assert json.loads(text)["headers"] == response["headers"]
