"""Document tools backed by the website agent API, and `list_document_entities`, which
this server reads from ClickHouse and pages through the same broker."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server import server
from collection_search_server.acl import AccessDenied
from collection_search_server.backend_client import (
    DocumentsDiffSourcesRequest, DocumentsEmailRequest, DocumentsMetadataRequest,
    DocumentsPdfSearchRequest, DocumentsReadRequest, DocumentsSearchTextRequest, DocumentsSourcesRequest,
)
from collection_search_server.paging import PagedTool
from collection_search_server.server import mcp
from collection_search_server.tools_search import LocalPagedTool, collections_for


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


READ_DOCUMENTS = PagedTool(DocumentsReadRequest, "documents/read", "read_documents", "rows", "documents")
DOC_SEARCH_TEXT = PagedTool(DocumentsSearchTextRequest, "documents/search_text", "doc_search_text", "rows", "hits")
DOC_SOURCES = PagedTool(DocumentsSourcesRequest, "documents/sources", "doc_sources", "rows", "sources")
DOC_METADATA = PagedTool(DocumentsMetadataRequest, "documents/metadata", "doc_metadata", "rows", "__metadata_entries")
DOC_EMAIL = PagedTool(DocumentsEmailRequest, "documents/email", "doc_email", "rows", "attachments")
DOC_DIFF_SOURCES = PagedTool(DocumentsDiffSourcesRequest, "documents/diff_sources", "doc_diff_sources", "blob", "unified_diff")
PDF_SEARCH = PagedTool(DocumentsPdfSearchRequest, "documents/pdf_search", "pdf_search", "rows", "hit_positions")
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


def _with_notes(text: str, notes: list[str]) -> str:
    """The result `text` with `collection_notes` added, when it is a JSON object."""
    if not notes:
        return text
    try:
        body = json.loads(text)
    except ValueError:
        return text
    if not isinstance(body, dict):
        return text
    body["collection_notes"] = notes
    return canonical_json(body)


def _render(tool: PagedTool | LocalPagedTool, values: dict[str, Any]) -> str:
    """The first page of `tool` for `values`. A dataset name in `collectionname` becomes its
    collection first. A name that is already readable costs nothing."""
    notes = _map_collections(values)
    try:
        return _with_notes(tool.render(tool.model.model_validate(values), {}, ""), notes)
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="read_documents", description="Read one text page of each of up to 20 documents in one collection. Use it after a search returns document hashes. With a query and no page, it opens the page with the most hits. Give page to read another page id, and use min_page, max_page and hit_pages to choose it.")
def read_documents(collectionname: str, file_hash: list[str], source: str | None = None, query: str | None = None, page: int | None = None) -> str:
    values: dict[str, Any] = {"collectionname": collectionname, "file_hash": file_hash, "source": source, "query": query, "page": page}
    notes = _map_collections(values)
    try:
        values["file_hash"] = server.full_hashes(values["collectionname"], file_hash)
    except server.HashPrefixError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})
    except Exception:  # noqa: BLE001, a failed lookup leaves the hashes to the route
        server.log.warning("the file_hash starts of read_documents were not looked up", exc_info=True)
    return _with_notes(_render(READ_DOCUMENTS, values), notes)


@mcp.tool(name="doc_search_text", description="List the hits of a query in one document text source, in page order, with the page, the offsets and a snippet of each hit. Use it to find the pages of a long document to read.")
def doc_search_text(collectionname: str, file_hash: str, query: str, source: str | None = None) -> str:
    return _render(DOC_SEARCH_TEXT, {"collectionname": collectionname, "file_hash": file_hash, "query": query, "source": source})


@mcp.tool(name="doc_sources", description="List every source of one document: text, PDF, email, table, image, audio and video, with the page range of each text source. With a query, give the hit count of each source. Use it to select a source before reading or comparing text.")
def doc_sources(collectionname: str, file_hash: str, query: str | None = None) -> str:
    return _render(DOC_SOURCES, {"collectionname": collectionname, "file_hash": file_hash, "query": query})


@mcp.tool(name="doc_metadata", description="Return metadata, dates, locations, and download links for one document. Use it for document properties outside extracted text. A value longer than 2,000 characters comes back cut, with a cut marker.")
def doc_metadata(collectionname: str, file_hash: str) -> str:
    return _render(DOC_METADATA, {"collectionname": collectionname, "file_hash": file_hash})


@mcp.tool(name="doc_email", description="Return email fields, the parent message, attachments, and the message graph for one document. Use it when the document is an email. Give node, a file hash in the graph, to centre the graph on another message.")
def doc_email(collectionname: str, file_hash: str, node: str | None = None) -> str:
    return _render(DOC_EMAIL, {"collectionname": collectionname, "file_hash": file_hash, "node": node})


@mcp.tool(name="doc_diff_sources", description="Return a unified diff between one page of two extracted document sources. Use it to compare parser or OCR output. page_a and page_b default to the first page of each source.")
def doc_diff_sources(collectionname: str, file_hash: str, source_a: str, source_b: str, page_a: int | None = None, page_b: int | None = None) -> str:
    return _render(DOC_DIFF_SOURCES, {"collectionname": collectionname, "file_hash": file_hash, "source_a": source_a, "source_b": source_b, "page_a": page_a, "page_b": page_b})


@mcp.tool(name="pdf_search", description="Find matching text positions in a PDF source. Use it to locate a query on PDF pages. page_from and page_to limit the hits to a range of PDF pages.")
def pdf_search(collectionname: str, file_hash: str, query: str, source: str = "", page_from: int | None = None, page_to: int | None = None) -> str:
    return _render(PDF_SEARCH, {"collectionname": collectionname, "file_hash": file_hash, "query": query, "source": source, "page_from": page_from, "page_to": page_to})


@mcp.tool(name="list_document_entities", description=server.LIST_DOCUMENT_ENTITIES_DESCRIPTION)
def list_document_entities(
    documents: list[dict] | str | None = None,
    collectionname: list[str] | str | None = None,
    file_hash: list[str] | str | None = None,
) -> str:
    return _render(LIST_DOCUMENT_ENTITIES, {"documents": documents, "collectionname": collectionname, "file_hash": file_hash})
