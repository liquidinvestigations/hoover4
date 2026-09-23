"""Check response fields and source positions in collection result pages."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

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
    "search_collections": {"documents": [{"collectionname": "c", "file_hash": "h", "path": "/h", "title": "h", "snippet": "h", "canonical_file_type": "text", "size": 1, "document_date": None, "dataset": "d"}], "total_count": 3, "facet_counts": {"type": [{"value": "pdf", "count": 2}]}, "page": 0, "has_more": True},
    "search_facet_values": {"terms": [{"id": 1, "text": "pdf", "count": 2}], "resolved": {"1": "pdf"}},
    "search_date_histogram": {"buckets": [{"start": 1, "end": 2, "count": 1}], "date_field": "date"},
    "search_entity_explainer": {"explanation": {"title": "person", "subtitle": "", "body": "", "facts": [], "references": []}, "documents": [{"file_hash": "h", "path": "/h", "title": "h", "snippet": "h"}]},
    "read_documents": {"documents": [{"collectionname": "c", "file_hash": "h", "path": "/h", "title": "h", "source_used": "raw_text", "text": "a", "hit_count": 1, "hit_positions": [0]}]},
    "doc_sources": {"sources": [{"source": "text", "hit_count": 1}]},
    "doc_metadata": {"raw_metadata": {"author": ["a"]}, "dates": [{"value": 1, "kind": "created", "provenance": "tika"}], "file_locations": ["p"], "path": "p", "canonical_file_type": "pdf", "download_links": {"original": "/x", "ocr_pdf": None}},
    "doc_email": {"envelope": {"subject": "s", "date": None, "from": [], "to": [], "cc": [], "bcc": []}, "headers": {"x": "y"}, "attachments": [{"file_hash": "h", "name": "a", "size": 1}], "graph": {"nodes": [{"file_hash": "h", "subject": "s", "is_centre": True}], "edges": []}},
    "doc_diff_sources": {"source_a": "a", "source_b": "b", "unified_diff": "-a\n+b"},
    "pdf_search": {"pdf_url": "/x", "hit_positions": [{"page": 1, "start": 0, "end": 2}], "hit_count": 1},
    "table_overview": {"sheets": [{"name": "s", "row_count": 1, "column_count": 1, "columns": [{"name": "a", "type": "text"}]}]},
    "table_page": {"columns": [{"name": "a", "type": "text", "hidden": False}], "rows": [{"row_number": 1, "cells": {"a": "x"}}], "page": 0, "total_rows": 1},
    "table_column_values": {"values": [{"value": "x", "count": 1}]},
    "table_search_cells": {"hit_count": 1, "hits": [{"row_number": 1, "column": "a", "value": "x"}], "has_more": False},
    "folder_overview": {"datasets": [{"name": "d", "document_count": 2}], "folder_count": 1, "file_count": 2, "total_bytes": 3},
    "folder_list": {"breadcrumb": [{"node_id": "r", "name": "root"}], "container_root": "r", "children": [{"node_id": "a", "name": "a", "kind": "dir", "child_count": 1, "term_id": None}], "files": [{"node_id": "b", "file_hash": "h", "name": "b", "size": 1, "date": None, "canonical_file_type": "text", "is_container": False, "term_id": None}], "page": 0},
    "folder_search": {"matches": [{"node_id": "a", "parent_id": "r", "name": "a", "kind": "dir", "path": "/a", "term_id": None}]},
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_route_fields_reach_page(name, monkeypatch):
    tool = TOOLS[name]
    response = {**SAMPLES[name], "source": "fingerprint"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate(response))
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


@pytest.mark.parametrize("name,item_key,missing", [
    ("search_collections", "documents", "collectionname"),
    ("table_page", "rows", "row_number"),
])
def test_missing_nested_route_field_is_refused(name, item_key, missing):
    response = {**deepcopy(SAMPLES[name]), "source": "fingerprint"}
    del response[item_key][0][missing]
    with pytest.raises(ValidationError):
        RESPONSE_MODELS[TOOLS[name].route].model_validate(response)


def test_changed_source_returns_typed_error(monkeypatch):
    tool = TOOLS["search_collections"]
    response = {**SAMPLES["search_collections"], "source": "new"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate(response))
    page = json.loads(tool.render(tool.model.model_construct(), {"page": 1, "offset": 0}, "old"))
    assert page["error"] == "source_changed"


@pytest.mark.parametrize("change", [{"position": "bad"}, {"position": {"page": "one"}}, {"position": {}}, {"position": {"page": 0, "offset": 0, "blob": 2}}, {"tool": []}, {"source": []}, {"input": []}])
def test_malformed_continuation_fields_return_invalid_argument(change):
    token = {"tool": "search_collections", "input": {}, "position": {"page": 0}, "source": ""}
    token.update(change)
    assert json.loads(_read_more_response(token))["error"] == "invalid_argument"


@pytest.mark.parametrize("name", ["search_collections", "table_page", "table_search_cells", "folder_list"])
def test_two_backend_pages_and_inside_page_cut(name, monkeypatch):
    tool = TOOLS[name]
    batch_size = {"search_collections": 2, "table_page": 50, "table_search_cells": 200, "folder_list": 200}[name]
    def item(n):
        if name == "search_collections":
            return {**SAMPLES[name]["documents"][0], "file_hash": str(n), "snippet": "x" * 350}
        if name == "table_page":
            return {"row_number": n, "cells": {"text": str(n)}}
        if name == "table_search_cells":
            return {"row_number": n, "column": "A", "value": str(n)}
        return {**SAMPLES[name]["files"][0], "node_id": str(n), "file_hash": str(n)}

    first = [item(n) for n in range(batch_size)]
    second = [item(n) for n in range(batch_size, batch_size * 2)]
    calls = []

    def post(self, route, request, response_model, expected_source=None):
        page = request.position.page if request.position else 0
        calls.append(page)
        items = first if page == 0 else second if page == 1 else []
        if name == "search_collections":
            body = {"documents": items, "total_count": 4, "facet_counts": {}, "page": page, "has_more": page == 0}
        elif name == "table_page":
            body = {"columns": [{"name": "text", "type": "text", "hidden": False}], "rows": items, "page": page, "total_rows": 100}
        elif name == "table_search_cells":
            body = {"hit_count": 400, "hits": items, "has_more": page == 0}
        else:
            body = {"breadcrumb": [], "container_root": None, "children": [], "files": items, "page": page}
        return response_model.model_validate({**body, "source": "stable"})

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    monkeypatch.setattr("collection_search_server.paging._artifact", lambda tool_name, complete: "artifact")
    monkeypatch.setattr("collection_search_server.paging.PAGE_LIMIT", ByteLimit(1_000 if name == "search_collections" else 24_000))
    request_values = {"search_collections": {}, "table_page": {"collectionname": "c", "file_hash": "h", "sheet": 0}, "table_search_cells": {"collectionname": "c", "file_hash": "h", "sheet": 0, "query": "x"}, "folder_list": {"collectionname": "c", "dataset": "d"}}[name]
    page = json.loads(tool.render(tool.model.model_validate(request_values), {}, ""))
    if name == "folder_list":
        assert page["total_units"] > page["returned_units"]
    seen = []
    blob_parts = {}
    backend_page = 0
    for _ in range(20):
        assert page["success"], page
        if page["shape"] == "blob":
            blob_parts.setdefault(backend_page, []).extend(page["items"])
        else:
            seen.extend(page["items"])
        if not page["continuation"]:
            break
        token = decode_continuation(page["continuation"])
        backend_page = token["position"]["page"]
        page = json.loads(_read_more_response(token))
    if name == "folder_list" and blob_parts:
        ids = [item["file_hash"] for page_number in sorted(blob_parts)
               for item in json.loads("".join(blob_parts[page_number]))["files"]]
    else:
        assert len(seen) == batch_size * 2
        ids = [item["value"]["file_hash"] if name == "folder_list" else str(item["row_number"]) if name in ("table_page", "table_search_cells") else item["file_hash"] for item in seen]
    assert ids == [str(n) for n in range(batch_size * 2)]
    assert 0 in calls and 1 in calls
    assert page["continuation"] is None


def test_required_artifact_failure_is_returned(monkeypatch):
    tool = TOOLS["search_collections"]
    response = {**SAMPLES["search_collections"], "source": "stable"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate(response))

    def fail(tool_name, complete):
        raise ArtifactWriteFailed("write failed")

    monkeypatch.setattr("collection_search_server.paging._artifact", fail)
    page = json.loads(tool.render(tool.model.model_construct(), {}, ""))
    assert page["error"] == "artifact_write_failed"


def test_large_field_uses_utf8_blob_with_field_name(monkeypatch):
    tool = TOOLS["doc_email"]
    response = {**SAMPLES["doc_email"], "headers": {"subject": "é" * 12_000}, "source": "stable"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate(response))
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
