"""Document tools backed by the website agent API, and `list_document_entities`, which
this server reads from ClickHouse and pages through the same broker."""

from __future__ import annotations

import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_common.result_pages import canonical_json
from agent_common.result_pages import PageInput
from collection_search_server import server
from collection_search_server.acl import AccessDenied
from collection_search_server.backend_client import (
    DocumentsDiffSourcesRequest, DocumentsEmailRequest, DocumentsMetadataRequest,
    DocumentsPdfSearchRequest, DocumentsReadRequest, DocumentsSearchTextRequest, DocumentsSourcesRequest,
)
from collection_search_server import paging
from collection_search_server.paging import PagedTool
from collection_search_server.server import mcp
from collection_search_server.tools_search import LocalPagedTool, collections_for


class DocumentReference(BaseModel):
    """One explicit document identity supplied by the model."""

    model_config = ConfigDict(extra="forbid")
    collection: str = Field(description="Copy the collection of this document from a result.")
    file_hash: str = Field(description="Copy the document hash from the same result.")


class DocumentEntitiesRequest(BaseModel):
    """The arguments of `list_document_entities`, in any of the shapes it accepts."""

    model_config = ConfigDict(extra="forbid")

    documents: list[dict] | str | None = None
    collectionname: list[str] | str | None = None
    file_hash: list[str] | str | None = None


def _document_entities(request: DocumentEntitiesRequest) -> dict[str, Any]:
    response = server.list_document_entities(
        documents=request.documents, collectionname=request.collectionname, file_hash=request.file_hash,
    )
    return response.model_dump(mode="json")


class ReadDocumentsTool(PagedTool):
    """Give each document an equal part of the result page."""

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if position:
            return super().render(request, position, source)
        return paging.render_document_reads(self, request)

    def window(self, result: dict[str, Any], request: BaseModel | None = None) -> paging.Window:
        result = {**result, "documents": [dict(row) for row in result.get("documents", [])]}
        for row in result.get("documents", []):
            if row.get("page") is None:
                row["error"] = ("The document read timed out." if row.get("count_state") == "timed_out"
                                else "The document has no extracted text.")
                continue
            start, end, total = row["text_start"], row["text_end"], row["text_length"]
            length = getattr(request, "length", None) or 6_000
            base = {"collection": row["collectionname"], "file_hash": [paging.hash_start(row["file_hash"])],
                    "source": row["source_used"], "page": row["page"], "length": length,
                    "source_version": row["source_version"]}
            row["text_range"] = {"start": start, "end": end, "total": total, "unit": "characters"}
            if start:
                row["read_before"] = {**base, "offset": max(0, start - length), "length": min(length, start)}
            if end < total:
                row["read_after"] = {**base, "offset": end}
            row["page_complete"] = start == 0 and end == total
            for key in ("text_start", "text_end", "text_length"):
                row.pop(key)
        return super().window(result, request)


class EmailTool(PagedTool):
    """Return email fields and at least one available row before graph continuation."""

    def render(self, request: BaseModel, position: dict[str, Any], source: str) -> str:
        if position:
            return super().render(request, position, source)
        result = paging.BackendClient().post(self.route, request, paging.RESPONSE_MODELS[self.route])
        if isinstance(result, paging.AgentError):
            return paging.error_text(result)
        body = result.model_dump(mode="json", by_alias=True)
        window = self.window(body)
        count = len(body.get("attachments", []))
        if count == len(window.items):
            return paging._live_page(self, request, None, window)
        artifact_id, data, head, ends = paging._store_window(self, window, paging._input(request), None)

        def after(n: int) -> dict[str, Any] | None:
            if n == len(window.items) and not window.next:
                return None
            return {"artifact": artifact_id, "head": head,
                    "start": ends[n - 1] if n else head, "total": window.total,
                    **({"next": window.next} if window.next else {})}
        text, _ = paging._build(PageInput(self.tool_name, "rows", window.items[:max(count, 1)], None,
            window.total, {}, window.fields.get("source", ""), paging._input(request), artifact_id,
            after, window.fields), paging._page_limit())
        if len(text.encode("utf-8")) <= paging.page_share():
            return text
        return paging._stored_page(self, request, after(0), paging._memory_reader(data))


class DocumentSearchTool(PagedTool):
    """Record the resolved document when its query has keyword matches."""

    def window(self, result: dict[str, Any], request: BaseModel | None = None) -> paging.Window:
        window = super().window(result, request)
        collection = getattr(request, "collectionname", "")
        file_hash = getattr(request, "file_hash", "")
        if result.get("hit_count", 0) > 0 and collection and file_hash and getattr(request, "query", ""):
            window.fields["keyword_sources"] = [f"{collection}/{paging.hash_start(file_hash)}"]
        return window


READ_DOCUMENTS = ReadDocumentsTool(DocumentsReadRequest, "documents/read", "read_documents", "rows", "documents")
DOC_SEARCH_TEXT = DocumentSearchTool(DocumentsSearchTextRequest, "documents/search_text", "doc_search_text", "rows", "hits")
DOC_SOURCES = PagedTool(DocumentsSourcesRequest, "documents/sources", "doc_sources", "rows", "sources")
DOC_METADATA = PagedTool(DocumentsMetadataRequest, "documents/metadata", "doc_metadata", "rows", "__metadata_entries")
DOC_EMAIL = EmailTool(DocumentsEmailRequest, "documents/email", "doc_email", "rows", "__email_entries")
DOC_DIFF_SOURCES = PagedTool(DocumentsDiffSourcesRequest, "documents/diff_sources", "doc_diff_sources", "blob", "unified_diff")
PDF_SEARCH = DocumentSearchTool(DocumentsPdfSearchRequest, "documents/pdf_search", "pdf_search", "rows", "hit_positions")
LIST_DOCUMENT_ENTITIES = LocalPagedTool(DocumentEntitiesRequest, "list_document_entities", "documents", _document_entities)
PAGED_TOOLS = {
    "read_documents": READ_DOCUMENTS, "doc_search_text": DOC_SEARCH_TEXT, "doc_sources": DOC_SOURCES,
    "doc_metadata": DOC_METADATA, "doc_email": DOC_EMAIL, "doc_diff_sources": DOC_DIFF_SOURCES,
    "pdf_search": PDF_SEARCH, "list_document_entities": LIST_DOCUMENT_ENTITIES,
}


def _readable(names: list[str]) -> bool:
    """False only when the caller's ACL was read and refuses a name. The check reads the
    request headers only, so the common call costs no backend request. A request with no
    readable ACL is left to the route, which refuses it."""
    try:
        acl = server._caller()
    except AccessDenied:
        return True
    try:
        acl.check(names)
    except AccessDenied:
        return False
    return True


def _map_collections(values: dict[str, Any]) -> list[str]:
    """Replace a dataset name in `values["collectionname"]` with its collection, by the rule
    of `collections_for`, and return a note for each name that was mapped. A name that the
    caller can read stays as it is."""
    name = values.get("collectionname")
    if isinstance(name, str) and name and _readable([name]):
        return []
    if isinstance(name, list) and name and _readable([str(n) for n in name]):
        return []
    if isinstance(name, str) and name:
        mapped, notes = collections_for([name])
        if mapped:
            values["collectionname"] = mapped[0]
        return notes
    if isinstance(name, list) and name:
        mapped, notes = collections_for([str(n) for n in name])
        values["collectionname"] = mapped
        return notes
    return []


def _with_notes(text: str, notes: list[str], hash_notes: list[str] | None = None) -> str:
    """The result `text` with `collection_notes` and `file_hash_notes` added, when it is a
    JSON object."""
    if not notes and not hash_notes:
        return text
    try:
        body = json.loads(text)
    except ValueError:
        return text
    if not isinstance(body, dict):
        return text
    if notes:
        body["collection_notes"] = notes
    if hash_notes:
        body["file_hash_notes"] = hash_notes
    return canonical_json(body)


def _full_hashes(values: dict[str, Any]) -> None:
    """Replace a hash start in `file_hash` and `node` with its whole hash. Raises
    `server.HashPrefixError` for a start that names more than one document."""
    collectionname = values.get("collectionname")
    if not isinstance(collectionname, str) or not collectionname:
        return
    for key in ("file_hash", "node"):
        if isinstance(values.get(key), str) and values[key]:
            values[key] = server.full_hashes(collectionname, values[key])


def _render(tool: PagedTool | LocalPagedTool, values: dict[str, Any], resolve: bool = True) -> str:
    """The first page of `tool` for `values`. A dataset name in `collectionname` becomes its
    collection first. A name that is already readable costs nothing. With `resolve`, a hash
    start in `file_hash` or `node` becomes its whole hash."""
    notes = _map_collections(values)
    if resolve:
        try:
            _full_hashes(values)
        except server.HashPrefixError as exc:
            return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
        except Exception:  # noqa: BLE001, a failed lookup leaves the hash to the route
            server.log.warning("the file_hash of %s was not looked up", tool.tool_name, exc_info=True)
    try:
        return _with_notes(tool.render(tool.model.model_validate(values), {}, ""), notes)
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="read_documents", description="Read one text page of each of up to 20 documents in one collection. A document can be named by its hash, or by a file name or path that resolves to one document. With a query, the tool opens text around the first hit on the selected page. With no page, it selects the page with the most hits. Give page to read another page id, and use min_page, max_page and hit_pages to choose it. offset uses Unicode character positions within a page. length defaults to 6,000 characters. Copy read_before or read_after arguments to inspect surrounding text. Copy more into read_more to continue. Page 0 counts as no page. With no page and no query, the tool opens the first stored page, which can be above 1.")
def read_documents(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[list[str], Field(min_length=1, max_length=20, description="Copy 1 to 20 document hashes from results in this collection.")], source: Annotated[str | None, Field(description='Copy a text source from doc_sources. Omission selects the preferred text source.')] = None, query: Annotated[str | None, Field(description='Optional keyword query. Omission reads from the start. A query opens the best matching page around nearby distinct matched words.')] = None, page: Annotated[int | None, Field(description='Stored page identifier. Copy a returned page. Omission or zero selects the first or best matching page.')] = None, offset: Annotated[int | None, Field(ge=0, description="Character offset within the selected page. Omission opens around a query hit or starts at zero.")] = None, length: Annotated[int | None, Field(ge=1, description="Maximum characters to read. Omission uses 6,000.")] = None, source_version: Annotated[str | None, Field(description="Copy the returned source_version for a targeted reread. A changed source is refused.")] = None) -> str:
    values: dict[str, Any] = {"collectionname": collection, "file_hash": file_hash, "source": source, "query": query, "page": page, "offset": offset, "length": length, "expected_source": source_version}
    notes = _map_collections(values)
    hash_notes: list[str] = []
    try:
        values["file_hash"], hash_notes = server.resolve_hashes(values["collectionname"], file_hash)
    except server.HashPrefixError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
    except Exception:  # noqa: BLE001, a failed lookup leaves the hashes to the route
        server.log.warning("the file_hashes of read_documents were not looked up", exc_info=True)
    if not values["file_hash"] and hash_notes:
        return canonical_json({"success": False, "error": "not_found", "message": " ".join(hash_notes)})
    return _with_notes(_render(READ_DOCUMENTS, values, resolve=False), notes, hash_notes)


@mcp.tool(name="doc_search_text", description="List the hits of a query in one document text source, in page order, with the page, the offsets and a snippet of each hit. Use it to find the pages of a long document to read.")
def doc_search_text(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], query: Annotated[str, Field(description='Keyword query to match within this document.')], source: Annotated[str | None, Field(description='Copy a text source from doc_sources. Omission selects the preferred text source.')] = None) -> str:
    return _render(DOC_SEARCH_TEXT, {"collectionname": collection, "file_hash": file_hash, "query": query, "source": source})


@mcp.tool(name="doc_sources", description="List every source of one document: text, PDF, email, table, image, audio and video, with the page range of each text source. With a query, give the hit count of each source. Use it to select a source before reading or comparing text.")
def doc_sources(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], query: Annotated[str | None, Field(description='Optional keyword query to count hits in each extraction. Omission lists sources without matching a query.')] = None) -> str:
    return _render(DOC_SOURCES, {"collectionname": collection, "file_hash": file_hash, "query": query})


def _render_batch(tool: PagedTool, collectionname: str, file_hash: str | list[str], **values) -> str:
    """Give each document an equal page share and retain each continuation."""
    if isinstance(file_hash, str):
        return _render(tool, {"collectionname": collectionname, "file_hash": file_hash, **values})
    if not 1 <= len(file_hash) <= 10:
        return canonical_json({"success": False, "error": "invalid_argument", "message": "Give between one and ten document hashes."})
    share = paging.page_share()
    per_document = max(1, (share - 256 - len(file_hash) * 100) // len(file_hash))
    results = []
    token = paging._UNIT_SHARE.set(per_document)
    try:
        for value in file_hash:
            text = paging.finish(_render(tool, {"collectionname": collectionname, "file_hash": value, **values}))
            results.append({"file_hash": value, "result": json.loads(text)})
    finally:
        paging._UNIT_SHARE.reset(token)
    return canonical_json({"documents": results})


@mcp.tool(name="doc_metadata", description="Return metadata, dates, locations, and download links for one document or up to ten hashes. Each document gets an equal page share. Use read_more for each continuation.")
def doc_metadata(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str | list[str], Field(description='Copy the document hash from a result in this collection.')]) -> str:
    return _render_batch(DOC_METADATA, collection, file_hash)


@mcp.tool(name="doc_email", description="Return email fields, attachments, and graph counts for one document or up to ten hashes. Each document gets an equal page share. Use read_more for graph nodes and edges. Give node to centre the graph on another message.")
def doc_email(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str | list[str], Field(description='Copy the document hash from a result in this collection.')], node: Annotated[str | None, Field(description='Copy another message file_hash from the graph to centre the email graph there.')] = None) -> str:
    return _render_batch(DOC_EMAIL, collection, file_hash, node=node)


@mcp.tool(name="doc_diff_sources", description="Return a unified diff between one page of two extracted document sources. Use it to compare parser or OCR output. page_a and page_b default to the first page of each source.")
def doc_diff_sources(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], source_a: Annotated[str, Field(description='First extracted source name from doc_sources.')], source_b: Annotated[str, Field(description='Second extracted source name from doc_sources.')], page_a: Annotated[int | None, Field(description='Page identifier in source_a. Omission selects its first stored page.')] = None, page_b: Annotated[int | None, Field(description='Page identifier in source_b. Omission selects its first stored page.')] = None) -> str:
    return _render(DOC_DIFF_SOURCES, {"collectionname": collection, "file_hash": file_hash, "source_a": source_a, "source_b": source_b, "page_a": page_a, "page_b": page_b})


@mcp.tool(name="pdf_search", description="Find matching text positions in a PDF source. Use it to locate a query on PDF pages. page_from and page_to limit the hits to a range of PDF pages.")
def pdf_search(collection: Annotated[str, Field(description='Copy the collection name from a result. A document call requires one collection.')], file_hash: Annotated[str, Field(description='Copy the document hash from a result in this collection.')], query: Annotated[str, Field(description='Keyword query to match on PDF pages.')], source: Annotated[str, Field(description='Copy a text source from doc_sources. Omission selects the preferred text source.')] = "", page_from: Annotated[int | None, Field(description='Inclusive first PDF page to search. Omission searches from its first page.')] = None, page_to: Annotated[int | None, Field(description='Inclusive last PDF page to search. Omission searches through its last page.')] = None) -> str:
    return _render(PDF_SEARCH, {"collectionname": collection, "file_hash": file_hash, "query": query, "source": source, "page_from": page_from, "page_to": page_to})


@mcp.tool(name="list_document_entities", description=server.LIST_DOCUMENT_ENTITIES_DESCRIPTION)
def list_document_entities(
    documents: Annotated[list[DocumentReference] | None, Field(description='Explicit document references. Each entry requires collection and file_hash.')] = None,
    collection: Annotated[list[str] | str | None, Field(description='Copy the collection name from a result. A document call requires one collection.')] = None,
    file_hash: Annotated[list[str] | str | None, Field(description='Copy the document hash from a result in this collection.')] = None,
) -> str:
    entries = [{"collectionname": d.collection, "file_hash": d.file_hash} for d in documents] if documents else None
    return _render(LIST_DOCUMENT_ENTITIES, {"documents": entries, "collectionname": collection, "file_hash": file_hash}, resolve=False)
