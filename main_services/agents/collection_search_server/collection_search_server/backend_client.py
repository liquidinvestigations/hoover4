"""Client for the website agent API.

The collection MCP server forwards the caller identity headers. Tool arguments never
carry identity or access data.
"""

from __future__ import annotations

import os
import time
from typing import Any, TypeVar

import requests
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONNECT_TIMEOUT = 30.0
TOTAL_TIMEOUT = 60.0
RETRY_STATUSES = {503, 504}
T = TypeVar("T", bound=BaseModel)


class AgentModel(BaseModel):
    """A JSON shape shared with `common::agent_api`."""

    model_config = ConfigDict(extra="forbid")


class AgentPosition(AgentModel):
    page: int = 0


class AgentError(AgentModel):
    success: bool = False
    error: str
    message: str


class CollectionsListRequest(AgentModel):
    pass


class SearchResultsRequest(AgentModel):
    collectionname: list[str] = Field(default_factory=list)
    query: str = ""
    sort: dict[str, str] | None = None
    date_after: int | None = None
    date_before: int | None = None
    date_confirmed_only: bool | None = None
    size_min: int | None = None
    size_max: int | None = None
    folder_term_id: int | None = None
    filename_only: bool | None = None
    facet_filters: dict[str, list[str]] = Field(default_factory=dict)
    position: AgentPosition | None = None


class SearchFacetValuesRequest(AgentModel):
    collectionname: list[str] = Field(default_factory=list)
    facet: str
    query: str | None = None
    ids: list[int] | None = None


class SearchDateHistogramRequest(SearchResultsRequest):
    date_field: str
    position: AgentPosition | None = None


class SearchEntityExplainerRequest(AgentModel):
    collectionname: str
    entity_type: str
    entity_value: str


class DocumentsReadRequest(AgentModel):
    collectionname: str
    file_hash: list[str]
    source: str | None = None
    query: str | None = None


class DocumentsSourcesRequest(AgentModel):
    collectionname: str
    file_hash: str
    query: str | None = None


class DocumentsMetadataRequest(AgentModel):
    collectionname: str
    file_hash: str


class DocumentsEmailRequest(DocumentsMetadataRequest):
    pass


class DocumentsDiffSourcesRequest(DocumentsMetadataRequest):
    source_a: str
    source_b: str


class DocumentsPdfSearchRequest(DocumentsMetadataRequest):
    query: str
    source: str = ""


class TablesOverviewRequest(DocumentsMetadataRequest):
    pass


class TablesPageRequest(DocumentsMetadataRequest):
    sheet: int
    sort: dict[str, Any] | None = None
    filters: list[dict[str, Any]] = Field(default_factory=list)
    hidden_columns: list[int] = Field(default_factory=list)
    search: str = ""
    position: AgentPosition | None = None


class TablesColumnValuesRequest(TablesOverviewRequest):
    sheet: int
    column: int


class TablesSearchCellsRequest(TablesOverviewRequest):
    sheet: int
    query: str


class FoldersOverviewRequest(AgentModel):
    collectionname: str
    dataset: str | None = None


class FoldersListRequest(AgentModel):
    collectionname: str
    dataset: str
    node_id: str | None = None
    position: AgentPosition | None = None


class FoldersSearchRequest(AgentModel):
    collectionname: str
    dataset: str
    node_id: str | None = None
    query: str


# Response models keep the website route contract visible in the broker. Nested route
# items stay JSON objects because Rust uses maps and arbitrary metadata JSON in several
# of these fields.
class CollectionsListResponse(AgentModel):
    collections: list[dict[str, Any]]
    source: str


class SearchResultsResponse(AgentModel):
    documents: list[dict[str, Any]]
    total_count: int
    facet_counts: dict[str, list[dict[str, Any]]]
    page: int
    has_more: bool
    source: str


class SearchFacetValuesResponse(AgentModel):
    terms: list[dict[str, Any]]
    resolved: dict[str, str]
    source: str


class SearchDateHistogramResponse(AgentModel):
    buckets: list[dict[str, Any]]
    date_field: str
    source: str


class SearchEntityExplainerResponse(AgentModel):
    explanation: dict[str, Any] | None
    documents: list[dict[str, Any]]
    source: str


class DocumentsReadResponse(AgentModel):
    documents: list[dict[str, Any]]
    source: str


class DocumentsSourcesResponse(AgentModel):
    sources: list[dict[str, Any]]
    source: str


class DocumentsMetadataResponse(AgentModel):
    raw_metadata: dict[str, list[Any]]
    dates: list[dict[str, Any]]
    file_locations: list[str]
    path: str
    canonical_file_type: str
    download_links: dict[str, Any]
    source: str


class DocumentsEmailResponse(AgentModel):
    envelope: dict[str, Any] | None
    headers: Any
    attachments: list[dict[str, Any]]
    graph: dict[str, Any]
    source: str


class DocumentsDiffSourcesResponse(AgentModel):
    source_a: str
    source_b: str
    unified_diff: str
    source: str


class DocumentsPdfSearchResponse(AgentModel):
    source: str
    pdf_url: str
    hit_positions: list[dict[str, Any]]
    hit_count: int


class TablesOverviewResponse(AgentModel):
    sheets: list[dict[str, Any]]
    source: str


class TablesPageResponse(AgentModel):
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    page: int
    total_rows: int
    source: str


class TablesColumnValuesResponse(AgentModel):
    values: list[dict[str, Any]]
    source: str


class TablesSearchCellsResponse(AgentModel):
    hit_count: int
    hits: list[dict[str, Any]]
    source: str


class FoldersOverviewResponse(AgentModel):
    datasets: list[dict[str, Any]]
    folder_count: int
    file_count: int
    total_bytes: int
    source: str


class FoldersListResponse(AgentModel):
    breadcrumb: list[dict[str, Any]]
    container_root: str | None
    children: list[dict[str, Any]]
    files: list[dict[str, Any]]
    page: int
    source: str


class FoldersSearchResponse(AgentModel):
    matches: list[dict[str, Any]]
    source: str


def error_from_status(status: int, message: str) -> AgentError:
    """Map every HTTP failure to the stable tool error vocabulary."""
    names = {
        400: "invalid_argument", 401: "unauthenticated", 403: "permission_denied",
        404: "not_found", 409: "source_changed", 503: "backend_unavailable",
        504: "timed_out",
    }
    return AgentError(error=names.get(status, "backend_unavailable"), message=message)


class BackendClient:
    """POST-only client with one retry for transport and dependency failures."""

    def __init__(self, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or os.getenv("AGENT_API_BASE_URL", "http://hoover4-website:8080")).rstrip("/")
        self.session = session or requests.Session()

    @staticmethod
    def caller_headers() -> dict[str, str]:
        headers = {key.lower(): value for key, value in get_http_headers().items()}
        return {
            "x-hoover4-user": headers.get("x-hoover4-user", ""),
            "X-Hoover4-Collections": headers.get("x-hoover4-collections", ""),
        }

    def post(self, route: str, request: AgentModel, response_model: type[T] | None = None, source: str | None = None) -> T | dict[str, Any] | AgentError:
        url = f"{self.base_url}/api/agent/v1/{route.lstrip('/')}"
        body = request.model_dump(mode="json", exclude_none=True)
        if source is not None:
            body["source"] = source
        started = time.monotonic()
        for attempt in range(2):
            remaining = TOTAL_TIMEOUT - (time.monotonic() - started)
            if remaining <= 0:
                return AgentError(error="timed_out", message="the agent API deadline expired")
            try:
                response = self.session.post(url, json=body, headers=self.caller_headers(), timeout=(CONNECT_TIMEOUT, remaining))
            except requests.Timeout:
                failure = AgentError(error="timed_out", message="the agent API deadline expired")
            except requests.RequestException as exc:
                failure = AgentError(error="backend_unavailable", message=f"agent API transport failure: {exc}")
            else:
                if response.status_code >= 400:
                    message = response.text[:1000]
                    try:
                        message = response.json().get("message", message)
                    except ValueError:
                        pass
                    failure = error_from_status(response.status_code, message)
                    if response.status_code not in RETRY_STATUSES:
                        return failure
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        return AgentError(error="backend_unavailable", message="agent API returned invalid JSON")
                    if response_model is None:
                        return data
                    try:
                        return response_model.model_validate(data)
                    except ValidationError as exc:
                        return AgentError(error="backend_unavailable", message=f"agent API returned an invalid response: {exc}")
            if attempt == 1:
                return failure
        raise AssertionError("unreachable")
