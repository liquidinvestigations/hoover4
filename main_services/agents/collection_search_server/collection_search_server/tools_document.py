"""Document tools backed by the website agent API."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent_common.result_pages import canonical_json
from collection_search_server.backend_client import (
    DocumentsDiffSourcesRequest, DocumentsEmailRequest, DocumentsMetadataRequest,
    DocumentsPdfSearchRequest, DocumentsReadRequest, DocumentsSourcesRequest,
)
from collection_search_server.paging import PagedTool
from collection_search_server.server import mcp


READ_DOCUMENTS = PagedTool(DocumentsReadRequest, "documents/read", "read_documents", "rows", "documents")
DOC_SOURCES = PagedTool(DocumentsSourcesRequest, "documents/sources", "doc_sources", "rows", "sources")
DOC_METADATA = PagedTool(DocumentsMetadataRequest, "documents/metadata", "doc_metadata", "rows", "__metadata_entries")
DOC_EMAIL = PagedTool(DocumentsEmailRequest, "documents/email", "doc_email", "rows", "attachments")
DOC_DIFF_SOURCES = PagedTool(DocumentsDiffSourcesRequest, "documents/diff_sources", "doc_diff_sources", "blob", "unified_diff")
PDF_SEARCH = PagedTool(DocumentsPdfSearchRequest, "documents/pdf_search", "pdf_search", "rows", "hit_positions")
PAGED_TOOLS = {"read_documents": READ_DOCUMENTS, "doc_sources": DOC_SOURCES, "doc_metadata": DOC_METADATA, "doc_email": DOC_EMAIL, "doc_diff_sources": DOC_DIFF_SOURCES, "pdf_search": PDF_SEARCH}


def _render(tool: PagedTool, values: dict[str, Any]) -> str:
    try:
        return tool.render(tool.model.model_validate(values), {}, "")
    except ValidationError as exc:
        return canonical_json({"success": False, "error": "invalid_argument", "message": str(exc)})


@mcp.tool(name="read_documents", description="Read extracted text from documents in one collection. Use it after a search returns document hashes.")
def read_documents(collectionname: str, file_hash: list[str], source: str | None = None, query: str | None = None) -> str:
    return _render(READ_DOCUMENTS, {"collectionname": collectionname, "file_hash": file_hash, "source": source, "query": query})


@mcp.tool(name="doc_sources", description="List extracted text sources for one document. Use it to select a source before reading or comparing text.")
def doc_sources(collectionname: str, file_hash: str, query: str | None = None) -> str:
    return _render(DOC_SOURCES, {"collectionname": collectionname, "file_hash": file_hash, "query": query})


@mcp.tool(name="doc_metadata", description="Return metadata, dates, locations, and download links for one document. Use it for document properties outside extracted text.")
def doc_metadata(collectionname: str, file_hash: str) -> str:
    return _render(DOC_METADATA, {"collectionname": collectionname, "file_hash": file_hash})


@mcp.tool(name="doc_email", description="Return email fields, attachments, and graph links for one document. Use it when the document is an email.")
def doc_email(collectionname: str, file_hash: str) -> str:
    return _render(DOC_EMAIL, {"collectionname": collectionname, "file_hash": file_hash})


@mcp.tool(name="doc_diff_sources", description="Return a unified diff between two extracted document sources. Use it to compare parser or OCR output.")
def doc_diff_sources(collectionname: str, file_hash: str, source_a: str, source_b: str) -> str:
    return _render(DOC_DIFF_SOURCES, {"collectionname": collectionname, "file_hash": file_hash, "source_a": source_a, "source_b": source_b})


@mcp.tool(name="pdf_search", description="Find matching text positions in a PDF source. Use it to locate a query on PDF pages.")
def pdf_search(collectionname: str, file_hash: str, query: str, source: str = "") -> str:
    return _render(PDF_SEARCH, {"collectionname": collectionname, "file_hash": file_hash, "query": query, "source": source})
