"""Document tools backed by the website agent API, and `list_document_entities`, which
this server reads from ClickHouse and pages through the same broker."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server import server
from collection_search_server.backend_client import (
    DocumentsDiffSourcesRequest, DocumentsEmailRequest, DocumentsMetadataRequest,
    DocumentsPdfSearchRequest, DocumentsReadRequest, DocumentsSearchTextRequest, DocumentsSourcesRequest,
)
from collection_search_server.paging import PagedTool
from collection_search_server.server import mcp
from collection_search_server.tools_search import LocalPagedTool


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


def _render(tool: PagedTool | LocalPagedTool, values: dict[str, Any]) -> str:
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="read_documents", description="Read one text page of each of up to 20 documents in one collection. Use it after a search returns document hashes. With a query and no page, it opens the page with the most hits. Give page to read another page id, and use min_page, max_page and hit_pages to choose it.")
def read_documents(collectionname: str, file_hash: list[str], source: str | None = None, query: str | None = None, page: int | None = None) -> str:
    return _render(READ_DOCUMENTS, {"collectionname": collectionname, "file_hash": file_hash, "source": source, "query": query, "page": page})


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
