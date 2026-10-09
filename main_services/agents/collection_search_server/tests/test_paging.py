"""Check response fields and source positions in collection result pages."""

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from agent_common import artifacts
from agent_common.artifacts import ArtifactWriteFailed
from agent_common import result_pages
from agent_common.result_pages import ByteLimit, canonical_json, decode_continuation, replace_at_pointer
from collection_search_server import tools_document, tools_folder, tools_search, tools_table
from collection_search_server import paging
from collection_search_server.paging import RESPONSE_MODELS, _read_more_response


TOOLS = {
    **tools_search.PAGED_TOOLS,
    **tools_document.PAGED_TOOLS,
    **tools_table.PAGED_TOOLS,
    **tools_folder.PAGED_TOOLS,
}


SAMPLES = {
    "list_collections": {"collections": [{"collectionname": "c", "document_count": 1, "datasets": [{"name": "d", "document_count": 1}]}]},
    "search_collections": {"documents": [{"collectionname": "c", "file_hash": "h", "path": "/h", "title": "h", "snippet": "h", "canonical_file_type": "text", "size": 1, "document_date": None, "dataset": "d", "collection_dataset": "c_d"}], "total_count": 3, "facet_counts": {"file_types": [{"value": "pdf", "id": 7, "count": 2}]}, "page": 0, "has_more": True, "query_notes": [], "next_position": None, "total": 3, "partial": False},
    "search_facet_values": {"terms": [{"id": 1, "text": "pdf", "count": 2}], "resolved": {"1": "pdf"}},
    "search_histogram": {"buckets": [{"start": 1, "end": 2, "count": 1, "label": None}], "date_field": "date"},
    "search_entity_explainer": {"explanation": {"title": "person", "subtitle": "", "body": "", "facts": [], "references": []}, "documents": [{"file_hash": "h", "path": "/h", "title": "h", "snippet": "h"}]},
    "read_documents": {"documents": [{"collectionname": "c", "collection_dataset": "c_d", "file_hash": "h", "path": "/h", "title": "h", "source_used": "raw_text", "page": 1, "min_page": 1, "max_page": 3, "text": "a", "text_start": 0, "text_end": 1, "text_length": 1, "source_version": "h:raw_text:3:3", "hit_count": 1, "hit_pages": [1], "count_state": "read", "next_position": {"kind": "TextPage", "source": "raw_text", "page_id": 2}}], "next_position": {"kind": "TextPage", "source": "raw_text", "page_id": 2}, "total": 3, "partial": False},
    "doc_search_text": {"source_used": "raw_text", "hit_count": 1, "hits": [{"page": 1, "ordinal": 0, "start": 0, "end": 1, "snippet": "a"}], "next_position": None, "total": 1, "partial": False},
    "doc_sources": {"sources": [{"kind": "text", "source": "raw_text", "label": "Plain text", "hit_count": 1, "count_state": "counted", "min_page": 1, "max_page": 1, "page_count": None, "sheet_count": None, "row_count": None, "column_count": None}], "next_position": None, "total": 1, "partial": False},
    "doc_metadata": {"raw_metadata": {"author": ["a"]}, "dates": [{"value": 1, "kind": "created", "provenance": "tika"}], "file_locations": [{"path": "p", "container_hash": "", "container_chain": ["/", "p"]}], "file_locations_total": 1, "path": "p", "canonical_file_type": "pdf", "download_links": {"original": "/x", "ocr_pdf": None}},
    "doc_email": {"envelope": {"subject": "s", "date": None, "from": [], "to": [], "cc": [], "bcc": []}, "parent": None, "cluster_size": 1, "headers": {"x": "y"}, "attachments": [{"file_hash": "h", "name": "a", "size": 1, "coarse_type": "pdf"}], "graph": {"nodes": [{"file_hash": "h", "subject": "s", "from": "a", "date": None, "truncated": False, "is_centre": True}], "edges": [], "cluster_size": 1, "truncated": False}, "next_position": None, "total": 1, "partial": False},
    "doc_diff_sources": {"source_a": "a", "source_b": "b", "page_a": 1, "page_b": 1, "unified_diff": "-a\n+b"},
    "pdf_search": {"source_used": "", "pdf_url": "/x", "hit_positions": [{"page": 1, "start": 0, "end": 2}], "hit_count": 1, "next_position": None, "total": 1, "partial": False},
    "table_overview": {"sheets": [{"sheet": 0, "name": "s", "row_count": 1, "column_count": 1, "columns": [{"column_id": 1, "name": "a", "type": "text"}]}], "next_position": None, "total": 1, "partial": False},
    "table_page": {"columns": [{"column_id": 1, "name": "a", "type": "text"}], "rows": [{"row_number": 1, "row_id": 1, "cells": {"a": "x", "b": {"text": "y", "cut": {"field": "/rows/0/cells/b", "returned_bytes": 1, "total_bytes": 3}}}}], "row_start": 0, "total_rows": 1, "clamps": {"rows_requested": 50, "rows_applied": 50, "columns_requested": 1, "columns_applied": 1}, "next_position": None, "total": 1, "partial": False},
    "table_cell": {"row_number": 1, "column": "a", "offset": 0, "text": "x", "next_position": None, "total": 1, "partial": False},
    "table_column_values": {"values": [{"value": "x", "count": 1}], "next_position": None, "total": None, "partial": False},
    "table_search_cells": {"hit_count": 1, "hits": [{"row_number": 1, "row_id": 1, "column": "a", "column_id": 1, "value": "x"}], "next_position": None, "total": 1, "partial": False},
    "folder_overview": {"datasets": [{"name": "d", "document_count": 2}], "folder_count": 1, "file_count": 2, "total_bytes": 3, "indexed_count": 2, "error_count": 0},
    "folder_list": {"breadcrumb": [{"node_id": "r", "name": "root"}], "container_root": "r", "children": [{"node_id": "a", "name": "a", "kind": "dir", "child_count": 1, "term_id": None}], "files": [{"node_id": "b", "file_hash": "h", "name": "b", "size": 1, "date": None, "canonical_file_type": "text", "is_container": False, "term_id": None}], "dataset": "d", "next_position": None, "total": 2, "partial": False},
    "folder_search": {"matches": [{"node_id": "a", "parent_id": "r", "name": "a", "kind": "dir", "path": "/a", "term_id": None}], "dataset": "d", "next_position": None, "total": 1, "partial": False},
}


@pytest.mark.parametrize("name", sorted(set(SAMPLES) - {"search_collections", "doc_email", "search_facet_values"}))
def test_route_fields_reach_page(name, monkeypatch):
    """A route page shows its units under `items` and its route fields at the top level,
    with every empty value, `source`, `total_count` and `next_position` left out."""
    tool = TOOLS[name]
    response = {**SAMPLES[name], "source": "fingerprint"}
    if name == "search_histogram":
        response["filter_notes"] = []
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate(response))
    request = tool.model.model_construct()
    page = json.loads(tool.render(request, {}, ""))
    assert "success" not in page and "kind" not in page and "tool_name" not in page
    assert RESPONSE_MODELS[tool.route].model_fields.keys() == response.keys()
    assert "source" not in page
    for key, value in SAMPLES[name].items():
        if key == tool.item_key:
            expected = value if isinstance(value, list) else [value]
            if name == "read_documents":
                expected = tool.window({**response}).items
            else:
                expected = expected if tool.shape == "blob" else paging.slim_items(name, expected)[0]
            assert page["items"] == expected
        elif key == tool.columns_key:
            assert page["columns"] == value
        elif key == "raw_metadata":
            assert page["items"] == [{"field": "raw_metadata", "key": k, "value": v} for k, v in value.items()]
        elif name == "folder_list" and key in ("children", "files"):
            assert {"field": key, "value": value[0]} in page["items"]
        elif key in ("source", "total_count", "page_info", "next_position") or value is None or value is False or value in ("", [], {}):
            assert key not in page
        else:
            assert page[result_pages.FIELD_NAMES.get(key, key)] == value


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
    page = json.loads(tool.render(tool.model.model_construct(), {"window": {"kind": "Page", "page": 1}}, "old"))
    assert page["error"] == "source_changed"


@pytest.mark.parametrize("change", [
    {"position": "bad"}, {"position": {"page": "one"}}, {"position": {"window": "Page"}},
    {"position": {"start": -1}}, {"position": {"artifact": "a"}}, {"position": {"blob": 2}},
    {"position": {"artifact": "a", "head": 1, "start": 1, "cut": {"field": 1, "base": 0, "end": 1}}},
    {"tool": []}, {"source": []}, {"input": []},
])
def test_malformed_continuation_fields_return_invalid_argument(change):
    token = {"tool": "search_collections", "input": {}, "position": {"window": None}, "source": ""}
    token.update(change)
    assert json.loads(_read_more_response(token))["error"] == "invalid_argument"


class Store:
    """An in-memory artifact store with the owner check and the clamp of `read_range`."""

    def __init__(self, monkeypatch, owner="alice"):
        self.bodies: dict[str, bytes] = {}
        self.owner = owner
        self.reads: list[tuple[int, int]] = []
        self.caller = owner
        monkeypatch.setattr(artifacts, "write_required", self.write)
        monkeypatch.setattr(paging, "_artifact_reader", self.reader)

    def write(self, request, artifact_id, key, body, content_type):
        self.bodies[artifact_id] = body
        return artifact_id

    def reader(self, artifact_id):
        def read(start, length):
            if artifact_id not in self.bodies:
                raise artifacts.ArtifactNotFound(artifact_id)
            if self.caller != self.owner:
                raise artifacts.ArtifactForbidden(artifact_id)
            body = self.bodies[artifact_id]
            if start >= len(body):
                raise artifacts.ArtifactRangeRefused("start is past the end")
            length = min(length, paging.MAX_HEADER_BYTES, len(body) - start)
            self.reads.append((start, length))
            return body[start:start + length], len(body)
        return read


def token_of(page):
    """The encoded continuation that the page's `more` handle names, or None."""
    return paging._TOKENS.get(page.get("more")) if page.get("more") else None


@pytest.mark.parametrize("name", ["doc_search_text", "pdf_search", "table_search_cells"])
@pytest.mark.parametrize("count", [0, 3])
def test_document_search_records_its_resolved_keyword_source(name, count, monkeypatch):
    tool = TOOLS[name]
    response = {**deepcopy(SAMPLES[name]), "source": "fingerprint", "hit_count": count, "total": count}
    response[tool.item_key] = response[tool.item_key] * count
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post",
                        lambda self, route, request, response_model, expected_source=None:
                        response_model.model_validate(response))
    request = tool.model.model_validate({"collectionname": "c", "file_hash": "a" * 64, "query": "needle",
                                        **({"sheet": 0} if name == "table_search_cells" else {})})
    page = json.loads(tool.render(request, {}, ""))
    assert page.get("keyword_sources", []) == (["c/" + "a" * 16] if count else [])


@pytest.mark.parametrize("name", ["doc_search_text", "pdf_search", "table_search_cells"])
def test_document_search_keeps_one_source_through_continuation(name, monkeypatch):
    tool = TOOLS[name]
    response = {**deepcopy(SAMPLES[name]), "source": "fingerprint", "hit_count": 120, "total": 120}
    response[tool.item_key] *= 120
    Store(monkeypatch)
    monkeypatch.setattr(paging, "page_share", lambda: 1024)
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post",
                        lambda self, route, request, response_model, expected_source=None:
                        response_model.model_validate(response))
    request = tool.model.model_validate({"collectionname": "c", "file_hash": "a" * 64, "query": "needle",
                                        **({"sheet": 0} if name == "table_search_cells" else {})})
    pages = walk(json.loads(tool.render(request, {}, "")))
    assert len(pages) > 1
    assert sum(len(page.get("items", [])) for page in pages) == 120
    assert all(page["keyword_sources"] == ["c/" + "a" * 16] for page in pages)


def units_of(page):
    """The units of a page: its rows, or the bytes of its text."""
    items = page.get("items") or []
    if len(items) == 1 and isinstance(items[0], str):
        return len(items[0].encode("utf-8"))
    return len(items)


def walk(page, limit=200):
    """Every page of a result, following its continuations."""
    pages = [page]
    for _ in range(limit):
        if not page.get("more"):
            break
        page = json.loads(_read_more_response(decode_continuation(token_of(page))))
        pages.append(page)
    return pages


# Two backend windows of each position kind. `first` is the position the route returns
# after the first window, and the second window must be requested with it.
KINDS = {
    "search_collections": ({"kind": "Page", "page": 1}, "documents", {}),
    "read_documents": ({"kind": "TextPage", "source": "raw_text", "page_id": 2, "offset": None}, "documents", {"collectionname": "c", "file_hash": ["h"]}),
    "table_page": ({"kind": "Rows", "row_start": 50}, "rows", {"collectionname": "c", "file_hash": "h", "sheet": 0}),
    "table_search_cells": ({"kind": "Offset", "offset": 200}, "hits", {"collectionname": "c", "file_hash": "h", "sheet": 0, "query": "x"}),
    "table_column_values": ({"kind": "ValueKey", "count": 3, "value": "x"}, "values", {"collectionname": "c", "file_hash": "h", "sheet": 0, "column": 1}),
    "folder_list": ({"kind": "NodeKey", "node_key": "d\x1f\x1f/a"}, "files", {"collectionname": "c", "dataset": "d"}),
    "doc_search_text": ({"kind": "HitKey", "page_id": 1, "ordinal": 49}, "hits", {"collectionname": "c", "file_hash": "h", "query": "x"}),
}


def unit(name, n):
    if name == "folder_list":
        return {**SAMPLES[name]["files"][0], "node_id": str(n), "file_hash": str(n)}
    if name == "read_documents":
        return {**SAMPLES[name]["documents"][0], "file_hash": str(n), "next_position": None}
    if name == "table_page":
        return {"row_number": n, "row_id": n, "cells": {"a": str(n)}}
    if name == "table_search_cells":
        return {"row_number": n, "row_id": n, "column": "a", "column_id": 1, "value": str(n)}
    if name == "table_column_values":
        return {"value": str(n), "count": 1}
    if name == "doc_search_text":
        return {"page": 1, "ordinal": n, "start": 0, "end": 1, "snippet": str(n)}
    return {**SAMPLES[name]["documents"][0], "file_hash": str(n)}


@pytest.mark.parametrize("name", sorted(KINDS))
def test_the_broker_continues_with_the_route_next_position(name, monkeypatch):
    tool = ROUTE_SEARCH if name == "search_collections" else TOOLS[name]
    following, item_key, values = KINDS[name]
    store = Store(monkeypatch)
    sent = []

    def post(self, route, request, response_model, expected_source=None):
        position = request.position.model_dump(mode="json") if request.position else None
        sent.append(position)
        second = position == following
        units = [unit(name, n + (3 if second else 0)) for n in range(3)]
        body = {key: value for key, value in SAMPLES[name].items()}
        if name == "folder_list":
            body.update(children=[], files=units)
        else:
            body[item_key] = units
        body.update(next_position=None if second else following, total=6, source="stable")
        return response_model.model_validate(body)

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    pages = walk(json.loads(tool.render(tool.model.model_validate(values), {}, "")))
    items = [item for page in pages for item in page["items"]]
    assert len(items) == 6
    assert sent == [None, following]
    assert "more" not in pages[-1]
    assert not store.bodies


def test_a_large_window_is_stored_once_and_later_pages_read_ranges(monkeypatch):
    tool = TOOLS["table_page"]
    store = Store(monkeypatch)
    calls = []
    rows = [{"row_number": n, "row_id": n, "cells": {"a": "x" * 900}} for n in range(50)]

    def post(self, route, request, response_model, expected_source=None):
        calls.append(request.position)
        body = {**SAMPLES["table_page"], "rows": rows, "total_rows": 50, "total": 50, "source": "stable"}
        return response_model.model_validate(body)

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    pages = walk(json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0}), {}, "")))
    assert len(calls) == 1
    assert len(store.bodies) == 1
    assert len(pages) > 1
    assert len({decode_continuation(token_of(page))["position"]["artifact"] for page in pages[:-1]}) == 1
    assert [row["row_number"] for page in pages for row in page["items"]] == list(range(50))
    assert all(page["columns"] == SAMPLES["table_page"]["columns"] for page in pages)
    assert all(length <= paging.page_share() for _, length in store.reads)


def test_a_unit_larger_than_a_page_is_cut_inside_its_largest_field(monkeypatch):
    tool = TOOLS["read_documents"]
    Store(monkeypatch)
    text = "é" * 30_000 + "end"
    document = {**SAMPLES["read_documents"]["documents"][0], "text": text, "next_position": None}
    small = {**document, "file_hash": "small", "text": "short"}

    def post(self, route, request, response_model, expected_source=None):
        return response_model.model_validate({"documents": [document, small], "next_position": None, "total": 2, "partial": False, "source": "stable"})

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": ["h", "small"]}), {}, ""))
    first, second = page["items"]
    assert first["cut"].endswith(f"of {len(text.encode('utf-8'))} bytes")
    assert second["file_hash"] == "small" and "more" not in second
    parts = [first["text"]]
    more = first["more"]
    while more:
        following = json.loads(paging.finish(paging.read_more.fn(more)))
        parts.append(following["items"][0])
        more = following.get("more")
    assert "".join(parts) == text


@pytest.mark.parametrize("count,share", [(5, 120_000), (10, 240_000), (20, 240_000)])
def test_each_read_document_gets_an_equal_page_part(monkeypatch, count, share):
    store = Store(monkeypatch)
    monkeypatch.setattr(paging, "get_http_headers", lambda: {paging.PAGE_SHARE_HEADER: str(share)})
    documents = [{**SAMPLES["read_documents"]["documents"][0],
                  "file_hash": f"{n:016x}" + "0" * 48, "text": "x" * 90_000,
                  "next_position": None} for n in range(count)]

    def post(self, route, request, response_model, expected_source=None):
        return response_model.model_validate({"documents": documents, "next_position": None,
                                              "total": count, "partial": False, "source": "stable"})

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    page = json.loads(tools_document.READ_DOCUMENTS.render(
        tools_document.READ_DOCUMENTS.model.model_validate({
            "collectionname": "c", "file_hash": [row["file_hash"] for row in documents]}), {}, ""))
    assert len(page["items"]) == count
    assert all("more" in item and item["cut"].endswith("of 90000 bytes") for item in page["items"])
    lengths = [len(item["text"].encode()) for item in page["items"]]
    assert max(lengths) - min(lengths) <= 1
    assert len(canonical_json(page).encode()) <= share
    assert len([body for body in store.bodies.values() if len(body) > 100_000]) == 1


def test_short_read_documents_write_no_artifact(monkeypatch):
    store = Store(monkeypatch)
    documents = [{**SAMPLES["read_documents"]["documents"][0],
                  "file_hash": f"{n:016x}" + "0" * 48, "text": "short",
                  "next_position": None} for n in range(5)]
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request,
                        response_model, expected_source=None: response_model.model_validate({
                            "documents": documents, "next_position": None, "total": 5,
                            "partial": False, "source": "stable"}))
    page = json.loads(tools_document.READ_DOCUMENTS.render(
        tools_document.READ_DOCUMENTS.model.model_validate({
            "collectionname": "c", "file_hash": [row["file_hash"] for row in documents]}), {}, ""))
    assert len(page["items"]) == 5
    assert store.bodies == {}


def test_complete_read_items_fit_below_the_old_256_byte_floor(monkeypatch):
    store = Store(monkeypatch)
    documents = [{**SAMPLES["read_documents"]["documents"][0],
                  "text": "x", "min_page": None, "max_page": None, "hit_count": 0, "hit_pages": [], "next_position": None}]
    response = {"documents": documents, "next_position": None, "total": 1,
                "partial": False, "source": "stable"}
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post",
                        lambda self, route, request, response_model, expected_source=None:
                        response_model.model_validate(response))
    tool = tools_document.READ_DOCUMENTS
    window = tool.window(RESPONSE_MODELS[tool.route].model_validate(response).model_dump(mode="json", by_alias=True))
    envelope = len(canonical_json({"items": [], **window.fields}).encode("utf-8")) + 70
    assert max(len(canonical_json(item).encode("utf-8")) for item in window.items) < 255
    monkeypatch.setattr(paging, "get_http_headers",
                        lambda: {paging.PAGE_SHARE_HEADER: str(envelope + 255)})
    assert paging.page_share() == envelope + 255
    assert paging.unit_limits(paging.page_share(), envelope, 1) == [255]
    page = json.loads(tool.render(tool.model.model_validate({
        "collectionname": "c", "file_hash": [row["file_hash"] for row in documents]}), {}, ""))
    assert len(page["items"]) == 1
    assert store.bodies == {}


def test_a_continuation_into_another_callers_artifact_is_refused(monkeypatch):
    tool = TOOLS["table_page"]
    store = Store(monkeypatch)
    rows = [{"row_number": n, "row_id": n, "cells": {"a": "x" * 900}} for n in range(50)]
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate({**SAMPLES["table_page"], "rows": rows, "source": "stable"}))
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0}), {}, ""))
    token = decode_continuation(token_of(page))
    store.caller = "mallory"
    assert json.loads(_read_more_response(token))["error"] == "permission_denied"
    store.caller = store.owner
    token["position"]["start"] = 10**9
    assert json.loads(_read_more_response(token))["error"] == "invalid_argument"
    token["position"]["artifact"] = "unknown"
    assert json.loads(_read_more_response(token))["error"] == "not_found"


def test_required_artifact_failure_is_returned(monkeypatch):
    tool = TOOLS["table_page"]
    rows = [{"row_number": n, "row_id": n, "cells": {"a": "x" * 900}} for n in range(50)]
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate({**SAMPLES["table_page"], "rows": rows, "source": "stable"}))

    def fail(*args, **kwargs):
        raise ArtifactWriteFailed("write failed")

    monkeypatch.setattr(artifacts, "write_required", fail)
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0}), {}, ""))
    assert page["error"] == "artifact_write_failed"


def test_a_blob_window_pages_by_utf8_bytes(monkeypatch):
    tool = TOOLS["doc_diff_sources"]
    Store(monkeypatch)
    diff = "-é\n+b\n" * 9_000
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate({**SAMPLES["doc_diff_sources"], "unified_diff": diff, "source": "stable"}))
    pages = walk(json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "source_a": "a", "source_b": "b"}), {}, "")))
    assert all(len(page["items"]) == 1 and isinstance(page["items"][0], str) for page in pages)
    assert "".join(page["items"][0] for page in pages) == diff


def test_a_server_deadline_504_is_not_retried():
    from collection_search_server.backend_client import BackendClient, CollectionsListRequest

    class Response:
        def __init__(self, status, body):
            self.status_code, self._body, self.text = status, body, json.dumps(body)

        def json(self):
            return self._body

    class Session:
        def __init__(self, responses):
            self.responses, self.calls = list(responses), 0

        def post(self, *args, **kwargs):
            self.calls += 1
            return self.responses.pop(0)

    fired = Session([Response(504, {"error": "timed_out", "message": "the server deadline fired"})])
    result = BackendClient("http://x", fired).post("collections/list", CollectionsListRequest())
    assert (result.error, fired.calls) == ("timed_out", 1)
    proxy = Session([Response(504, {"message": "gateway"}), Response(200, {"collections": [], "source": "s"})])
    assert BackendClient("http://x", proxy).post("collections/list", CollectionsListRequest()) == {"collections": [], "source": "s"}
    assert proxy.calls == 2


def test_a_value_key_position_holding_control_characters_continues(monkeypatch):
    tool = TOOLS["table_column_values"]
    Store(monkeypatch)
    value = "a\nb\tc"
    following = {"kind": "ValueKey", "count": 3, "value": value}
    sent = []

    def post(self, route, request, response_model, expected_source=None):
        position = request.position.model_dump(mode="json") if request.position else None
        sent.append(position)
        second = position is not None
        body = {"values": [{"value": value if second else "x", "count": 1}], "source": "stable",
                "next_position": None if second else following, "total": 2, "partial": False}
        return response_model.model_validate(body)

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    values = {"collectionname": "c", "file_hash": "h", "sheet": 0, "column": 1}
    pages = walk(json.loads(tool.render(tool.model.model_validate(values), {}, "")))
    assert [page.get("success", True) for page in pages] == [True, True]
    assert sent == [None, following]
    assert sent[1]["value"] == value


def test_model_written_fields_keep_the_control_character_check():
    from collection_search_server.backend_client import TablesColumnValuesRequest

    base = {"collectionname": "c", "file_hash": "h", "sheet": 0, "column": 1}
    with pytest.raises(ValidationError):
        TablesColumnValuesRequest.model_validate({**base, "search": "a\nb"})
    with pytest.raises(ValidationError):
        TablesColumnValuesRequest.model_validate({**base, "position": {"kind": "TextPage", "source": "a\nb", "page_id": 1}})
    request = TablesColumnValuesRequest.model_validate({**base, "position": {"kind": "ValueKey", "count": 1, "value": "a\nb"}})
    assert request.position.value == "a\nb"


def wide_row_walk(monkeypatch, cells, share=None):
    """Every page of a `table_page` window whose first row holds `cells` cells of 1,500
    characters, each cell a different letter, and whose second row is short."""
    if share is not None:
        monkeypatch.setattr(paging, "page_share", lambda: share)
    tool = TOOLS["table_page"]
    Store(monkeypatch)
    letters = [chr(ord("A") + n % 26) + chr(ord("a") + n // 26) for n in range(cells)]
    wide = {"row_number": 1, "row_id": 1, "cells": {f"c{n}": letters[n] * 750 for n in range(cells)}}
    short = {"row_number": 2, "row_id": 2, "cells": {"c0": "row two"}}

    def post(self, route, request, response_model, expected_source=None):
        body = {**SAMPLES["table_page"], "rows": [wide, short], "total_rows": 2, "total": 2, "source": "stable"}
        return response_model.model_validate(body)

    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", post)
    first = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0}), {}, ""))
    return wide, walk(first, limit=500)


@pytest.mark.parametrize("cells, share", [(20, None), (40, None), (20, 8_192), (40, 8_192)])
def test_a_row_still_too_large_after_one_cut_is_read_field_by_field(monkeypatch, cells, share):
    wide, pages = wide_row_walk(monkeypatch, cells, share)
    assert all(page.get("success", True) and page["items"] for page in pages), [page.get("status") for page in pages]
    assert "more" not in pages[-1]
    head = pages[0]["items"][0]
    assert head["row_number"] == 1
    # Rebuild every cell from the pages in order: the cell text on the row page, then
    # the continuation pages of each moved field.
    rebuilt = {key: value for key, value in head["cells"].items()}
    order = [head["cut"]["field"], *head["cut"].get("next_fields", [])]
    assert len(order) == len(set(order))
    current = head["cut"]["field"]
    rest = []
    for page in pages[1:]:
        marker = page.get("cut")
        if marker is None:
            rest.append(page)
            continue
        assert not rest, "a moved field page came after the next row"
        if marker["field"] != current:
            assert order.index(marker["field"]) == order.index(current) + 1
            assert marker["start_bytes"] == 0
            current = marker["field"]
        key = marker["field"].rsplit("/", 1)[1]
        rebuilt[key] += page["items"][0]
    assert current == order[-1]
    assert rebuilt == wide["cells"]
    assert [row["row_number"] for page in rest for row in page["items"]] == [2]


def test_a_stored_line_with_no_string_longer_than_a_page_is_read_as_unit_text(monkeypatch):
    tool = TOOLS["table_page"]
    store = Store(monkeypatch)
    rows = [{"row_number": n, "row_id": n, "cells": {"a": "x" * 900}} for n in range(50)]
    monkeypatch.setattr("collection_search_server.paging.BackendClient.post", lambda self, route, request, response_model, expected_source=None: response_model.model_validate({**SAMPLES["table_page"], "rows": rows, "source": "stable"}))
    page = json.loads(tool.render(tool.model.model_validate({"collectionname": "c", "file_hash": "h", "sheet": 0}), {}, ""))
    token = decode_continuation(token_of(page))
    artifact_id = token["position"]["artifact"]
    start = token["position"]["start"]
    body = store.bodies[artifact_id]
    wide = {"row_number": 9, "pad": [1] * 30_001}
    store.bodies[artifact_id] = body[:start] + b'{"row_number": 9, "pad": [' + b"1," * 30_000 + b'1]}\n' + body[start:]
    pages = walk(json.loads(_read_more_response(token)), limit=500)
    assert all("items" in page and units_of(page) > 0 for page in pages)
    rebuilt = rebuild(pages)
    assert rebuilt[0] == wide
    assert rebuilt[1:] == rows[units_of(page):]


def share_header(monkeypatch, share):
    """Sends `share` as the page share of the calls that follow, as the agent does."""
    headers = {} if share is None else {paging.PAGE_SHARE_HEADER: str(share)}
    monkeypatch.setattr(paging, "get_http_headers", lambda: headers)


def large_table(monkeypatch):
    rows = [{"row_number": n, "row_id": n, "cells": {"a": "x" * 900}} for n in range(50)]
    body = {**SAMPLES["table_page"], "rows": rows, "total_rows": 50, "total": 50, "source": "stable"}
    monkeypatch.setattr(
        "collection_search_server.paging.BackendClient.post",
        lambda self, route, request, response_model, expected_source=None: response_model.model_validate(body),
    )
    return TOOLS["table_page"], {"collectionname": "c", "file_hash": "h", "sheet": 0}


def test_the_page_share_header_sizes_the_page(monkeypatch):
    Store(monkeypatch)
    tool, values = large_table(monkeypatch)
    share_header(monkeypatch, 5_000)
    assert paging.page_share() == 5_000
    page = tool.render(tool.model.model_validate(values), {}, "")
    assert len(page.encode("utf-8")) <= 5_000
    assert units_of(json.loads(page)) >= 1
    share_header(monkeypatch, "not a number")
    assert paging.page_share() == paging.PAGE_LIMIT.max_bytes
    share_header(monkeypatch, 10**9)
    assert paging.page_share() == paging.MAX_PAGE_SHARE


def test_a_later_page_with_a_smaller_share_keeps_the_fields_and_the_source(monkeypatch):
    store = Store(monkeypatch)
    tool, values = large_table(monkeypatch)
    share_header(monkeypatch, None)
    first = json.loads(tool.render(tool.model.model_validate(values), {}, ""))
    assert json.loads(next(iter(store.bodies.values())).split(b"\n", 1)[0])["share"] == paging.PAGE_LIMIT.max_bytes
    share_header(monkeypatch, 2_500)
    pages = walk(first)
    assert [row["row_number"] for page in pages for row in page["items"]] == list(range(50))
    for page in pages[1:]:
        assert len(canonical_json(page).encode("utf-8")) <= 2_500
        assert "source" not in page
        assert page["columns"] == SAMPLES["table_page"]["columns"]
        assert decode_continuation(token_of(page))["source"] == "stable" if page.get("more") else True


def test_the_call_measure_is_the_build_page_measure_of_the_returned_page(monkeypatch):
    import asyncio
    import hashlib

    from fastmcp import Client

    from collection_search_server import server

    store = Store(monkeypatch)
    hits = [{"collectionname": "c", "collection_dataset": "c_d", "file_hash": f"{n:016x}" + "0" * 48, "page_id": 1, "score": 1.0, "snippet": "s" * 300} for n in range(120)]
    monkeypatch.setattr(server, "search_passages", lambda **kwargs: server.SearchResponse(success=True, query="q", queries=["q"], collections_searched=["c"], results=hits))

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool("search_passages", {"queries": ["q"]})

    result = asyncio.run(call())
    page, resource, refs = result.content
    assert page.type == "text" and resource.type == "resource"
    assert str(refs.resource.uri) == paging.DOC_REFS_URI
    assert [ref["file_hash"] for ref in json.loads(refs.resource.text)] == [
        hit["file_hash"] for hit in hits[:len(json.loads(page.text)["items"])]]
    assert str(resource.resource.uri) == paging.CALL_MEASURE_URI
    measure = json.loads(resource.resource.text)
    assert measure["page_sha256"] == hashlib.sha256(page.text.encode("utf-8")).hexdigest()
    assert measure["page_bytes"] == len(page.text.encode("utf-8"))
    assert measure["page_share"] == paging.PAGE_LIMIT.max_bytes
    assert measure["returned_units"] == units_of(json.loads(page.text))
    assert "page_sha256" not in page.text
    assert len(store.bodies) == 2


def pointer_value(unit, pointer):
    """The value at the JSON `pointer` inside `unit`."""
    for token in pointer[1:].split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        unit = unit[int(key)] if isinstance(unit, list) else unit[key]
    return unit


def rebuild(pages):
    """The units of a walk, rebuilt from its pages in order. It checks that each piece
    starts where the one before it ended, so a byte returned twice or skipped fails."""
    units, text, open_unit = [], b"", [None]

    def close():
        if open_unit[0] is not None:
            finished = dict(open_unit[0])
            finished.pop("cut")
            units.append(finished)
            open_unit[0] = None

    def take(item):
        close()
        if isinstance(item, dict) and isinstance(item.get("cut"), dict) and "returned_bytes" in item["cut"]:
            open_unit[0] = item
        else:
            units.append(item)

    for page in pages:
        marker = page.get("cut")
        if marker is not None and marker["field"] == "":
            assert marker["start_bytes"] == len(text)
            text += page["items"][0].encode("utf-8")
            if len(text) == marker["total_bytes"]:
                take(json.loads(text))
                text = b""
        elif marker is not None:
            current = pointer_value(open_unit[0], marker["field"])
            assert marker["start_bytes"] == len(current.encode("utf-8"))
            open_unit[0] = replace_at_pointer(open_unit[0], marker["field"], current + page["items"][0])
        else:
            for item in page["items"]:
                take(item)
    assert text == b""
    close()
    return units


#: The route search as a plain paged tool, which pages the whole route window. Every
#: `search_collections` call goes through the query forms, so the broker's stored-window
#: cases use this tool.
ROUTE_SEARCH = paging.PagedTool(tools_search.SearchResultsRequest,
                                "search/results", "search_collections", "rows", "documents")


def search_window(monkeypatch, field_bytes, unit_bytes, count):
    """A `search_collections` window whose page fields are `field_bytes` bytes and whose
    `count` units each hold a `unit_bytes`-byte snippet. Returns the tool, its input and
    the units as the route returns them."""
    documents = [
        {**SAMPLES["search_collections"]["documents"][0], "file_hash": str(n), "snippet": chr(ord("a") + n) * unit_bytes}
        for n in range(count)
    ]
    body = {**SAMPLES["search_collections"], "next_position": None, "total": count, "source": "stable"}
    body["facet_counts"] = {"file_types": [{"value": "", "id": 7, "count": 2}]}
    fields = {key: value for key, value in body.items() if key != "documents"}
    body["facet_counts"]["file_types"][0]["value"] = "v" * (field_bytes - len(canonical_json(fields).encode("utf-8")))
    body["documents"] = documents
    response = RESPONSE_MODELS["search/results"].model_validate(body)
    monkeypatch.setattr(
        "collection_search_server.paging.BackendClient.post",
        lambda self, route, request, response_model, expected_source=None: response,
    )
    return ROUTE_SEARCH, {}, response.model_dump(mode="json", by_alias=True)["documents"]


def walk_at(monkeypatch, tool, values, store_share, read_share, limit=2_000):
    """The page texts of a walk: the first page at `store_share`, and every continuation
    at `read_share`."""
    share = [store_share]
    monkeypatch.setattr(paging, "page_share", lambda: share[0])
    texts = [tool.render(tool.model.model_validate(values), {}, "")]
    share[0] = read_share
    for _ in range(limit):
        page = json.loads(texts[-1])
        if not page.get("more"):
            return texts
        texts.append(_read_more_response(decode_continuation(token_of(page))))
    raise AssertionError("the walk did not end")


def assert_walk_invariants(texts, units, store_share, read_share):
    """Every page is within its share, every page has content, and the rebuilt units equal
    the units of the window."""
    pages = [json.loads(text) for text in texts]
    for index, (text, page) in enumerate(zip(texts, pages)):
        assert len(text.encode("utf-8")) <= (store_share if index == 0 else read_share), index
        assert "items" in page and units_of(page) > 0, (index, page)
    assert "more" not in pages[-1]
    assert rebuild(pages) == [{("collection" if k == "collectionname" else k): v for k, v in unit.items()} for unit in units]


# The smallest share of these cases is the share of one call in a batch of about twenty
# calls in safe mode. The field sizes include the measured `search/results` fields.
SHARES = [1_000, 1_500, 2_000, 3_000, 4_000, 5_000, 6_000, 7_800, 8_000, 12_000, 16_000, 23_700, 24_000]
FIELD_BYTES = [300, 1_200, 4_500, 5_244]


@pytest.mark.parametrize("share", SHARES)
@pytest.mark.parametrize("field_bytes", FIELD_BYTES)
def test_every_stored_unit_is_readable_at_every_share(monkeypatch, share, field_bytes):
    Store(monkeypatch)
    tool, values, units = search_window(monkeypatch, field_bytes, 3_000, 4)
    texts = walk_at(monkeypatch, tool, values, share, share)
    assert_walk_invariants(texts, units, share, share)


@pytest.mark.parametrize("store_share, read_share, field_bytes, unit_bytes, count", [
    (8_000, 8_000, 4_500, 3_000, 4),
    (23_700, 7_800, 300, 12_000, 3),
    (24_000, 1_000, 5_244, 12_000, 3),
    (24_000, 2_000, 1_200, 12_000, 3),
    (8_000, 1_000, 5_244, 12_000, 3),
    (8_000, 2_000, 5_244, 12_000, 3),
    (8_000, 4_000, 5_244, 3_000, 4),
    (2_000, 2_000, 300, 3_000, 4),
    (2_000, 2_000, 1_200, 3_000, 4),
    (3_000, 3_000, 300, 3_000, 4),
    (3_000, 3_000, 1_200, 3_000, 4),
    (2_000, 24_000, 1_200, 12_000, 3),
    (1_000, 8_000, 300, 500, 20),
])
def test_a_window_read_at_another_share_keeps_every_page_within_its_share(
    monkeypatch, store_share, read_share, field_bytes, unit_bytes, count,
):
    Store(monkeypatch)
    tool, values, units = search_window(monkeypatch, field_bytes, unit_bytes, count)
    texts = walk_at(monkeypatch, tool, values, store_share, read_share)
    assert_walk_invariants(texts, units, store_share, read_share)


def test_a_share_smaller_than_the_page_envelope_keeps_the_continuation(monkeypatch):
    Store(monkeypatch)
    tool, values, units = search_window(monkeypatch, 300, 12_000, 3)
    share = [24_000]
    monkeypatch.setattr(paging, "page_share", lambda: share[0])
    first = json.loads(tool.render(tool.model.model_validate(values), {}, ""))
    token = decode_continuation(token_of(first))
    share[0] = 40
    answer = json.loads(_read_more_response(token))
    assert answer["error"] == "invalid_argument"
    assert "fewer tool calls" in answer["message"]
    share[0] = 24_000
    pages = [first, *walk(json.loads(_read_more_response(token)), limit=500)]
    assert rebuild(pages) == [{("collection" if k == "collectionname" else k): v for k, v in unit.items()} for unit in units]


def test_a_unit_stored_with_a_moved_field_is_read_as_unit_text_at_a_smaller_share(monkeypatch):
    Store(monkeypatch)
    cells = {**{f"c{n}": chr(ord("a") + n % 26) * 60 for n in range(60)}, "big": "é" * 10_000}
    body = {**SAMPLES["table_page"], "rows": [{"row_number": 1, "row_id": 1, "cells": {"c0": "row one"}},
                                              {"row_number": 2, "row_id": 2, "cells": cells}],
            "total_rows": 2, "total": 2, "source": "stable"}
    response = RESPONSE_MODELS["tables/page"].model_validate(body)
    monkeypatch.setattr(
        "collection_search_server.paging.BackendClient.post",
        lambda self, route, request, response_model, expected_source=None: response,
    )
    tool, values = TOOLS["table_page"], {"collectionname": "c", "file_hash": "h", "sheet": 0}
    texts = walk_at(monkeypatch, tool, values, 24_000, 2_000)
    pages = [json.loads(text) for text in texts]
    assert any((page.get("cut") or {}).get("field") == "" for page in pages)
    assert any((page.get("cut") or {}).get("field") == "/cells/big" for page in pages)
    assert_walk_invariants(texts, response.model_dump(mode="json", by_alias=True)["rows"], 24_000, 2_000)


@pytest.mark.parametrize("unit_bytes,count", [(2_500, 9), (15_000, 3)])
def test_rows_keep_their_identity_when_the_facets_fill_the_page(monkeypatch, unit_bytes, count):
    """Rows and 10 KB of facets in a 24,000-byte page: no row loses a field, and the
    facets wait for a later page before any row is cut. A 15,000-byte row fits a page
    only without the facets."""
    Store(monkeypatch)
    tool, values, documents = search_window(monkeypatch, 10_000, unit_bytes, count)
    pages = walk(json.loads(tool.render(tool.model.model_validate(values), {}, "")))
    shown = [row for page in pages for row in page["items"]]
    assert [row["file_hash"] for row in shown] == [row["file_hash"] for row in documents]
    for row in shown:
        assert row["file_hash"] and row["path"] and row["collection"]
        assert "cut" not in row
    # The facets are on each page that can hold them beside a row. No page holds 10 KB of
    # facets beside a 15,000-byte row, so that result shows no facets.
    with_facets = [page for page in pages if "facet_counts" in page]
    assert bool(with_facets) == (unit_bytes < 10_000)
    # Only the facets move. The other window fields stay on the first page.
    assert "has_more" in pages[0]


def test_a_row_larger_than_the_page_keeps_its_identity_and_moves_its_snippet(monkeypatch):
    Store(monkeypatch)
    tool, values, documents = search_window(monkeypatch, 500, 40_000, 1)
    pages = walk(json.loads(tool.render(tool.model.model_validate(values), {}, "")))
    first = pages[0]["items"][0]
    assert first["cut"]["field"] == "/snippet"
    assert (first["file_hash"], first["path"], first["collection"]) == ("0", "/h", "c")


def test_the_identity_fields_are_never_the_largest_string_field():
    from agent_common.result_pages import largest_string_field

    row = {"file_hash": "h" * 100, "path": "/" + "p" * 90, "collectionname": "c", "snippet": "s" * 10}
    assert largest_string_field(row, exclude=paging.IDENTITY_FIELDS) == ("/snippet", "s" * 10)
    assert largest_string_field({"path": "p"}, exclude=paging.IDENTITY_FIELDS) is None


def forms_backend(monkeypatch, found, failing=()):
    """A route that answers each query form with the rows in `found[form]`, and fails for
    each form in `failing`. Returns the list of the forms it was asked for."""
    from collection_search_server.backend_client import AgentError

    asked = []

    def post(self, route, request, response_model, expected_source=None):
        asked.append(request.query)
        if request.query in failing:
            return AgentError(error="invalid_argument", message="query has no searchable terms")
        documents = [{**SAMPLES["search_collections"]["documents"][0], "file_hash": h, "path": "/" + h} for h in found[request.query]]
        return response_model.model_validate({
            **SAMPLES["search_collections"], "documents": documents, "total_count": len(documents),
            "has_more": False, "total": len(documents), "source": "s-" + request.query,
            "query_notes": ["read 1 OR as |, because OR is an ordinary word in a search"] if " OR " in request.query else [],
        })

    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post", post)
    return asked


def test_the_query_forms_run_in_one_call_and_merge_their_rows(monkeypatch):
    Store(monkeypatch)
    found = {"a@x.com": ["1", "2"], '"A B"': ["2", "3"], '"B, A"': ["4"], "aB": ["1", "4", "5"]}
    asked = forms_backend(monkeypatch, found)
    page = json.loads(tools_search.search_collections.fn(queries=list(found)))
    assert asked == list(found)
    rows = {row["file_hash"]: row["q"] for row in page["items"]}
    assert rows == {"1": [0, 3], "2": [0, 1], "3": [1], "4": [2, 3], "5": [3]}
    assert [row["file_hash"] for row in page["items"]] == ["1", "2", "3", "4", "5"]


def test_a_failing_query_form_is_a_note_and_the_others_return_rows(monkeypatch):
    Store(monkeypatch)
    forms_backend(monkeypatch, {"a": ["1"], "b": ["2"]}, failing={"NOT"})
    page = json.loads(tools_search.search_collections.fn(queries=["a", "NOT", "b"], query=""))
    assert [row["file_hash"] for row in page["items"]] == ["1", "2"]
    assert any("'NOT' failed" in note for note in page["notes"])


def test_the_query_is_the_first_form_and_its_rewrite_is_noted(monkeypatch):
    Store(monkeypatch)
    asked = forms_backend(monkeypatch, {"a OR b": ["1"], "c": ["1"]})
    page = json.loads(tools_search.search_collections.fn(query="a OR b", queries=["c"]))
    assert asked == ["a OR b", "c"]
    assert page["items"][0]["q"] == [0, 1]
    assert any("OR as |" in note for note in page["notes"])


def test_each_form_keeps_its_first_rows(monkeypatch):
    Store(monkeypatch)
    found = {"a": [f"a{n}" for n in range(200)], "b": [f"b{n}" for n in range(200)]}
    forms_backend(monkeypatch, found)
    page = json.loads(paging.finish(tools_search.search_collections.fn(queries=["a", "b"])))
    following = json.loads(paging.finish(paging.read_more.fn(page["more"])))
    shown = [row["file_hash"] for row in page["items"] + following["items"]]
    assert shown == found["a"][:15] + found["b"][:15]
    assert [row["q"] for row in following["items"]] == [[1]] * 15
    later = json.loads(paging.read_more.fn(following["more"]))
    assert all(row["q"] == [0] for row in later["items"])
    assert "'a': 200 found, first 15 shown" in page["notes"]


def test_one_query_without_the_list_is_one_form(monkeypatch):
    asked = forms_backend(monkeypatch, {"a OR b": ["1"]})
    page = json.loads(tools_search.search_collections.fn(query="a OR b"))
    assert asked == ["a OR b"]
    assert "q" not in page["items"][0]
    assert page["notes"] == ["the query 'a OR b': read 1 OR as |, because OR is an ordinary word in a search"]


def test_one_form_of_40_rows_has_three_pages(monkeypatch):
    Store(monkeypatch)
    seen = []

    def post(self, route, request, response_model, expected_source=None):
        page = request.position.page if request.position else 0
        seen.append((page, expected_source))
        documents = [{**SAMPLES["search_collections"]["documents"][0],
                      "file_hash": f"{n:016x}" + "0" * 48, "path": f"/{n}"}
                     for n in range(page * 20, (page + 1) * 20)]
        return response_model.model_validate({
            **SAMPLES["search_collections"], "documents": documents, "total_count": 40,
            "total": 40, "source": "stable", "has_more": page == 0,
            "next_position": {"kind": "Page", "page": 1} if page == 0 else None,
        })

    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post", post)
    first = json.loads(paging.finish(tools_search.search_collections.fn(query="x")))
    second = json.loads(paging.finish(paging.read_more.fn(first["more"])))
    third = json.loads(paging.read_more.fn(second["more"]))
    assert all("items" in page for page in (first, second, third)), (first, second, third)
    assert [len(page["items"]) for page in (first, second, third)] == [15, 15, 10]
    assert "more" not in third
    assert [row["file_hash"] for page in (first, second, third) for row in page["items"]] == [
        f"{n:016x}" for n in range(40)
    ]
    assert seen == [(0, None), (0, "stable"), (1, "stable"), (1, "stable")]


def dataset_backend(monkeypatch):
    """A route that lists the collection `consulate` with the dataset `files`, and answers
    each search with one row. Returns the collection names each search was asked for."""
    asked = []

    def post(self, route, request, response_model, expected_source=None):
        if route == "collections/list":
            return response_model.model_validate({"source": "c", "collections": [
                {"collectionname": "consulate", "document_count": 3,
                 "datasets": [{"name": "files", "document_count": 3}]}]})
        asked.append(list(request.collectionname))
        document = {**SAMPLES["search_collections"]["documents"][0], "file_hash": "1", "path": "/1"}
        return response_model.model_validate({
            **SAMPLES["search_collections"], "documents": [document], "total_count": 1,
            "has_more": False, "total": 1, "source": "s", "query_notes": []})

    monkeypatch.setattr("collection_search_server.backend_client.BackendClient.post", post)
    return asked


@pytest.mark.parametrize("name", ["consulate_files", "consulate/files", "files"])
def test_a_dataset_name_in_collectionname_searches_its_collection_and_says_so(monkeypatch, name):
    Store(monkeypatch)
    asked = dataset_backend(monkeypatch)
    page = json.loads(tools_search.search_collections.fn(collection=[name], query="budget"))
    assert asked == [["consulate"]]
    assert [row["file_hash"] for row in page["items"]] == ["1"]
    assert page["notes"][0] == (
        f"{name!r} is a dataset of the collection 'consulate', not a collection, so this "
        "search covers the collection 'consulate'. Give collection 'consulate'.")


def test_a_collection_name_and_an_unknown_name_are_not_mapped(monkeypatch):
    dataset_backend(monkeypatch)
    assert tools_search.collections_for(["consulate", "enron_kean_s"]) == (
        ["consulate", "enron_kean_s"], [])
    assert tools_search.collections_for(None) == (None, [])


def test_email_first_page_defers_graph_rows(monkeypatch):
    Store(monkeypatch)
    response = {**deepcopy(SAMPLES["doc_email"]), "source": "email-stable"}
    response["graph"]["nodes"] *= 400
    monkeypatch.setattr(paging.BackendClient, "post", lambda self, route, request, model, **kw: model.model_validate(response))
    request = tools_document.DOC_EMAIL.model.model_validate({"collectionname": "c", "file_hash": "h"})
    page = json.loads(paging.finish(tools_document.DOC_EMAIL.render(request, {}, "")))
    assert page["graph_counts"]["nodes"] == 400
    assert all(item["field"] == "attachments" for item in page["items"])
    following = json.loads(paging.read_more.fn(page["more"]))
    assert following["items"][0]["field"] == "graph_nodes"
    assert len(canonical_json(following).encode()) <= paging.page_share()


@pytest.mark.parametrize("node_count", [1, 400])
def test_email_without_attachments_returns_fields_and_graph_rows(monkeypatch, node_count):
    Store(monkeypatch)
    response = {**deepcopy(SAMPLES["doc_email"]), "source": "email-stable"}
    response["attachments"] = []
    response["graph"]["nodes"] *= node_count
    monkeypatch.setattr(paging.BackendClient, "post", lambda self, route, request, model, **kw: model.model_validate(response))
    request = tools_document.DOC_EMAIL.model.model_validate({"collectionname": "c", "file_hash": "h"})
    pages = [json.loads(paging.finish(tools_document.DOC_EMAIL.render(request, {}, "")))]
    assert "error" not in pages[0]
    assert pages[0]["envelope"]["subject"] == "s"
    assert pages[0]["graph_counts"]["nodes"] == node_count
    while pages[-1].get("more"):
        pages.append(json.loads(paging.finish(paging.read_more.fn(pages[-1]["more"]))))
    assert sum(len(page["items"]) for page in pages) == node_count
    assert all(len(canonical_json(page).encode()) <= paging.page_share() for page in pages)


def test_runtime_reduction_recovers_all_utf8_bytes_after_retry(monkeypatch):
    store = Store(monkeypatch)
    headers = {"x-hoover4-chat-session": "one", "x-hoover4-user": "alice", "x-hoover4-agent-run": "run"}
    monkeypatch.setattr(paging, "get_http_headers", lambda: headers)
    monkeypatch.setattr("collection_search_server.server._caller", lambda: object())
    content = "A statement. Χώρος. 中文。\n" * 10000
    first = json.loads(paging.page_tool_result.fn("run", "call", content, 2000))
    ids = set(store.bodies)
    assert len(canonical_json(first).encode()) <= 2000
    assert json.loads(paging.page_tool_result.fn("run", "call", content, 2000)) == first
    assert set(store.bodies) == ids
    paging._TOKENS.clear()
    pages = [first]
    while pages[-1].get("more"):
        pages.append(json.loads(paging.finish(paging.read_more.fn(pages[-1]["more"]))))
    assert "".join(page["items"][0] for page in pages) == content
    headers["x-hoover4-chat-session"] = "another"
    monkeypatch.setattr(paging, "_issued_handles", lambda: [])
    assert json.loads(paging.read_more.fn(first["more"]))["error"] == "not_found"


def test_handle_repair_requires_one_candidate_and_keeps_owner_scope(monkeypatch):
    Store(monkeypatch)
    original = "0123456789ab"
    damaged = "1023456789ab"
    monkeypatch.setattr(paging, "_issued_handles", lambda: [original])
    monkeypatch.setattr(paging, "_handle_token", lambda value: "encoded" if value == original else None)
    monkeypatch.setattr(paging, "decode_continuation", lambda value: {})
    monkeypatch.setattr(paging, "_read_more_response", lambda value: '{"items":["complete"]}')
    page = json.loads(paging.read_more.fn(damaged))
    assert original in page["continuation_note"]
    monkeypatch.setattr(paging, "_issued_handles", lambda: [original, "1023456789ac"])
    assert json.loads(paging.read_more.fn(damaged))["error"] == "not_found"
    assert not paging._one_character_damage("xx23456789ab", original)


def test_metadata_batch_divides_the_page_share(monkeypatch):
    seen = []
    def render(tool, values, resolve=True):
        seen.append((values["file_hash"], paging.page_share()))
        return '{"items":[]}'
    monkeypatch.setattr(tools_document, "_render", render)
    monkeypatch.setattr(paging, "get_http_headers", lambda: {"x-hoover4-page-share": "6000"})
    page = json.loads(tools_document.doc_metadata.fn("c", ["a", "b", "c"]))
    assert len(page["documents"]) == 3
    assert len({share for _, share in seen}) == 1
    assert seen[0][1] < 2000
    assert json.loads(tools_document.doc_metadata.fn("c", ["a"] * 11))["error"] == "invalid_argument"


def test_email_graph_continuation_keeps_the_next_attachment_window(monkeypatch):
    Store(monkeypatch)
    seen = []
    def post(self, route, request, model, **kw):
        seen.append(request.position)
        response = {**deepcopy(SAMPLES["doc_email"]), "source": "email-stable"}
        if request.position is None:
            response["next_position"] = {"kind": "Offset", "offset": 1}
        else:
            response["attachments"][0]["name"] = "second"
        return model.model_validate(response)
    monkeypatch.setattr(paging.BackendClient, "post", post)
    request = tools_document.DOC_EMAIL.model.model_validate({"collectionname": "c", "file_hash": "h"})
    pages = [json.loads(paging.finish(tools_document.DOC_EMAIL.render(request, {}, "")))]
    while pages[-1].get("more"):
        pages.append(json.loads(paging.finish(paging.read_more.fn(pages[-1]["more"]))))
    assert len(seen) == 2
    assert any(item.get("value", {}).get("name") == "second" for page in pages for item in page["items"])


def test_content_continuations_keep_their_document_read_reference():
    document = {"collectionname": "c", "file_hash": "a" * 64, "text": "continued text"}
    _, refs = paging.slim_items("read_documents", [document])
    assert refs[0]["evidence_kind"] == "document_read"
    assert paging.page_doc_refs(json.dumps({"items": ["continued table text"]}), refs) == refs
    _, search_refs = paging.slim_items("search_collections", [document])
    assert "evidence_kind" not in search_refs[0]
    assert paging.page_doc_refs(json.dumps({"items": ["search text"]}), search_refs) == []
