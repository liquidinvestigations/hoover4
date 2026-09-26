"""Client for the website agent API.

The collection MCP server forwards the caller identity headers. Tool arguments never
carry identity or access data.
"""

from __future__ import annotations

import os
import time
from typing import Annotated, Any, Literal, TypeVar, Union

import requests
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONNECT_TIMEOUT = 30.0
TOTAL_TIMEOUT = 60.0
RETRY_STATUSES = {503, 504}
T = TypeVar("T", bound=BaseModel)


NODE_KEY_FIELDS = {"node_id", "node_key"}
ESCAPED_NODE_KEY_SEPARATORS = ("\\u001f", "\\u001F")


def decode_node_keys(item: Any, key: Any = None) -> Any:
    """Read the six characters `\\u001f` in a node key field as U+001F.

    A model cannot write U+001F, which joins the parts of every folder node key, so it
    writes the JSON escape as text. The backend route reads the escape the same way.
    """
    if isinstance(item, str) and key in NODE_KEY_FIELDS:
        for escaped in ESCAPED_NODE_KEY_SEPARATORS:
            item = item.replace(escaped, "\x1f")
        return item
    if isinstance(item, dict):
        return {name: decode_node_keys(nested, name) for name, nested in item.items()}
    if isinstance(item, list):
        return [decode_node_keys(nested) for nested in item]
    return item


class AgentModel(BaseModel):
    """A JSON shape shared with `common::agent_api`."""

    model_config = ConfigDict(extra="forbid")


class AgentRequest(AgentModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def reject_control_characters(cls, value: Any) -> Any:
        # A folder node key joins its parts with the unit separator, U+001F, so a node
        # key field accepts that one control character and no other. The `value` of a
        # `ValueKey` position is cell text that the route issued and binds as a query
        # parameter, so it accepts every character. Every field a model writes keeps
        # the check.
        def visit(item: Any, key: Any = None) -> None:
            allowed = {0x1F} if key in NODE_KEY_FIELDS else set()
            if isinstance(item, str) and any((ord(char) < 32 or ord(char) == 127) and ord(char) not in allowed for char in item):
                raise ValueError("control characters are not allowed")
            if isinstance(item, dict):
                for name, nested in item.items():
                    visit(name)
                    if name == "value" and is_value_key(item):
                        continue
                    visit(nested, name)
            if isinstance(item, (list, tuple)):
                for nested in item:
                    visit(nested)

        def is_value_key(item: dict) -> bool:
            if item is value and cls is ValueKeyPosition:
                return True
            return item.get("kind") == "ValueKey"

        value = decode_node_keys(value)
        visit(value)
        return value


class PagePosition(AgentRequest):
    """A search result page. The kinds below mirror `common::agent_api::AgentPosition`."""

    kind: Literal["Page"] = "Page"
    page: int = Field(default=0, ge=0)


class TextPagePosition(AgentRequest):
    kind: Literal["TextPage"] = "TextPage"
    source: str
    page_id: int = Field(ge=0)


class RowsPosition(AgentRequest):
    kind: Literal["Rows"] = "Rows"
    row_start: int = Field(ge=0)


class OffsetPosition(AgentRequest):
    kind: Literal["Offset"] = "Offset"
    offset: int = Field(ge=0)


class ValueKeyPosition(AgentRequest):
    kind: Literal["ValueKey"] = "ValueKey"
    count: int = Field(ge=0)
    value: str


class NodeKeyPosition(AgentRequest):
    kind: Literal["NodeKey"] = "NodeKey"
    node_key: str


class HitKeyPosition(AgentRequest):
    kind: Literal["HitKey"] = "HitKey"
    page_id: int = Field(ge=0)
    ordinal: int = Field(ge=0)


#: Where the next backend window of a paged route starts. The broker sends back the
#: `next_position` that the route returned, and computes no position itself.
AgentPosition = Annotated[
    Union[PagePosition, TextPagePosition, RowsPosition, OffsetPosition, ValueKeyPosition, NodeKeyPosition, HitKeyPosition],
    Field(discriminator="kind"),
]


class AgentSort(AgentRequest):
    field: Literal["relevance", "date", "file_size", "name"]
    direction: Literal["asc", "desc"]


class AgentTableSort(AgentRequest):
    column: int = Field(ge=0)
    direction: Literal["asc", "desc"]


class AgentTableFilter(AgentRequest):
    column: int = Field(ge=0)
    contains: str | None = None
    equals: str | None = None
    starts_with: str | None = None
    is_empty: bool | None = None
    number_min: float | None = None
    number_max: float | None = None
    date_min: str | None = None
    date_max: str | None = None

    @model_validator(mode="after")
    def one_filter(self) -> "AgentTableFilter":
        values = (self.contains, self.equals, self.starts_with, self.is_empty,
                  self.number_min, self.number_max, self.date_min, self.date_max)
        if sum(value is not None for value in values) != 1:
            raise ValueError("a table filter needs exactly one value")
        return self


class AgentError(AgentModel):
    success: bool = False
    error: str
    message: str


class CollectionsListRequest(AgentRequest):
    pass


class SearchResultsRequest(AgentRequest):
    expected_source: str | None = None
    collectionname: list[str] = Field(default_factory=list)
    query: str = ""
    sort: AgentSort | None = None
    date_after: int | None = None
    date_before: int | None = None
    date_confirmed_only: bool | None = None
    size_min: int | None = None
    size_max: int | None = None
    folder_term_id: int | None = None
    filename_only: bool | None = None
    facet_filters: dict[str, list[str]] = Field(default_factory=dict)
    date_unknown_only: bool | None = None
    mentioned_date_after: int | None = None
    mentioned_date_before: int | None = None
    position: AgentPosition | None = None


class SearchFacetValuesRequest(AgentRequest):
    collectionname: list[str] = Field(default_factory=list)
    facet: str
    query: str | None = None
    ids: list[int] | None = None


class SearchDateHistogramRequest(SearchResultsRequest):
    date_field: Literal["date", "mentioned_date", "size"]
    position: AgentPosition | None = None


class SearchEntityExplainerRequest(AgentRequest):
    collectionname: str
    entity_type: str
    entity_value: str


class DocumentsReadRequest(AgentRequest):
    expected_source: str | None = None
    collectionname: str
    file_hash: list[str] = Field(min_length=1, max_length=20)
    source: str | None = None
    query: str | None = None
    page: int | None = Field(default=None, ge=0)
    position: AgentPosition | None = None


class DocumentsSearchTextRequest(AgentRequest):
    expected_source: str | None = None
    collectionname: str
    file_hash: str
    source: str | None = None
    query: str
    position: AgentPosition | None = None


class DocumentsSourcesRequest(AgentRequest):
    expected_source: str | None = None
    collectionname: str
    file_hash: str
    query: str | None = None


class DocumentsMetadataRequest(AgentRequest):
    expected_source: str | None = None
    collectionname: str
    file_hash: str


class DocumentsEmailRequest(DocumentsMetadataRequest):
    node: str | None = None
    position: AgentPosition | None = None


class DocumentsDiffSourcesRequest(DocumentsMetadataRequest):
    source_a: str
    source_b: str
    page_a: int | None = Field(default=None, ge=0)
    page_b: int | None = Field(default=None, ge=0)


class DocumentsPdfSearchRequest(DocumentsMetadataRequest):
    query: str
    source: str = ""
    page_from: int | None = Field(default=None, ge=0)
    page_to: int | None = Field(default=None, ge=0)
    position: AgentPosition | None = None


class TablesOverviewRequest(DocumentsMetadataRequest):
    position: AgentPosition | None = None


class TablesPageRequest(DocumentsMetadataRequest):
    sheet: int = Field(ge=0)
    sort: AgentTableSort | None = None
    filters: list[AgentTableFilter] = Field(default_factory=list)
    columns: list[int] = Field(default_factory=list, max_length=300)
    search: str = ""
    row_start: int | None = Field(default=None, ge=0)
    position: AgentPosition | None = None


class TablesCellRequest(DocumentsMetadataRequest):
    sheet: int = Field(ge=0)
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    position: AgentPosition | None = None


class TablesColumnValuesRequest(DocumentsMetadataRequest):
    sheet: int = Field(ge=0)
    column: int = Field(ge=0)
    search: str = ""
    position: AgentPosition | None = None


class TablesSearchCellsRequest(DocumentsMetadataRequest):
    sheet: int = Field(ge=0)
    query: str
    position: AgentPosition | None = None


class FoldersOverviewRequest(AgentRequest):
    collectionname: str
    dataset: str | None = None


class FoldersListRequest(AgentRequest):
    expected_source: str | None = None
    collectionname: str
    dataset: str
    node_id: str | None = None
    position: AgentPosition | None = None


class FoldersSearchRequest(AgentRequest):
    collectionname: str
    dataset: str
    node_id: str | None = None
    query: str
    expected_source: str | None = None
    position: AgentPosition | None = None


class DatasetSummary(AgentModel):
    name: str
    document_count: int


class CollectionSummary(AgentModel):
    collectionname: str
    document_count: int
    datasets: list[DatasetSummary]


class SearchDocument(AgentModel):
    collectionname: str
    file_hash: str
    path: str
    title: str
    snippet: str
    canonical_file_type: str
    size: int | None
    document_date: int | None
    dataset: str
    collection_dataset: str = ""


class FacetCount(AgentModel):
    value: str
    id: int | None = None
    count: int


class FacetTerm(AgentModel):
    id: int
    text: str
    count: int | None


class HistogramBucket(AgentModel):
    start: int
    end: int | None
    count: int
    label: str | None = None


class EntityFact(AgentModel):
    label: str
    value: str


class EntityLink(AgentModel):
    title: str
    url: str
    note: str


class EntityExplanation(AgentModel):
    title: str
    subtitle: str
    body: str
    facts: list[EntityFact]
    references: list[EntityLink]


class EntityDocument(AgentModel):
    file_hash: str
    path: str
    title: str
    snippet: str


class DocumentText(AgentModel):
    collectionname: str
    collection_dataset: str = ""
    file_hash: str
    path: str
    title: str
    source_used: str
    page: int | None
    min_page: int | None
    max_page: int | None
    text: str
    hit_count: int
    hit_pages: list[int]
    count_state: str
    next_position: AgentPosition | None = None


class TextHit(AgentModel):
    page: int
    ordinal: int
    start: int
    end: int
    snippet: str


class DocumentSource(AgentModel):
    kind: str
    source: str
    label: str
    hit_count: int | None
    count_state: str
    min_page: int | None = None
    max_page: int | None = None
    page_count: int | None = None
    sheet_count: int | None = None
    row_count: int | None = None
    column_count: int | None = None


class FileLocation(AgentModel):
    path: str
    container_hash: str
    container_chain: list[str]


class DocumentDate(AgentModel):
    value: int
    kind: str
    provenance: str


class DownloadLinks(AgentModel):
    original: str
    ocr_pdf: str | None


class EmailEnvelope(AgentModel):
    subject: str
    date: int | None
    from_: list[str] = Field(alias="from")
    to: list[str]
    cc: list[str]
    bcc: list[str]


class EmailRelation(AgentModel):
    file_hash: str
    subject: str
    from_: str = Field(alias="from")
    date: int | None
    kind: str
    confidence: float


class EmailAttachment(AgentModel):
    file_hash: str
    name: str
    size: int
    coarse_type: str


class EmailGraphNode(AgentModel):
    file_hash: str
    subject: str
    from_: str = Field(alias="from")
    date: int | None
    truncated: bool
    is_centre: bool


class EmailGraphEdge(AgentModel):
    src_file_hash: str
    dst_file_hash: str
    kind: str
    confidence: float
    evidence: str


class EmailGraph(AgentModel):
    nodes: list[EmailGraphNode]
    edges: list[EmailGraphEdge]
    cluster_size: int
    truncated: bool


class PdfHit(AgentModel):
    page: int
    start: int
    end: int


class TableColumnInfo(AgentModel):
    column_id: int
    name: str
    column_type: str = Field(alias="type")


class TableSheet(AgentModel):
    sheet: int
    name: str
    row_count: int
    column_count: int
    columns: list[TableColumnInfo]


class CutMarker(AgentModel):
    field: str
    returned_bytes: int
    total_bytes: int


class CutText(AgentModel):
    """A cell text over 2,000 characters, cut by the route. `table_cell` reads the rest."""

    text: str
    cut: CutMarker


CellText = str | CutText


class TableRow(AgentModel):
    row_number: int
    row_id: int
    cells: dict[str, CellText]


class TableClamps(AgentModel):
    rows_requested: int
    rows_applied: int
    columns_requested: int
    columns_applied: int


class ColumnValue(AgentModel):
    value: CellText
    count: int


class CellHit(AgentModel):
    row_number: int
    row_id: int
    column: str
    column_id: int
    value: CellText


class BreadcrumbNode(AgentModel):
    node_id: str
    name: str


class FolderChild(AgentModel):
    node_id: str
    name: str
    kind: str
    child_count: int | None
    term_id: int | None


class FolderFile(AgentModel):
    node_id: str
    file_hash: str
    name: str
    size: int
    date: int | None
    canonical_file_type: str | None
    is_container: bool
    term_id: int | None


class FolderMatch(AgentModel):
    node_id: str
    parent_id: str
    name: str
    kind: str
    path: str
    term_id: int | None


# Response models mirror the website route records. Raw metadata and email headers
# remain JSON because those Rust fields use serde_json::Value.
class CollectionsListResponse(AgentModel):
    collections: list[CollectionSummary]
    source: str


class SearchResultsResponse(AgentModel):
    documents: list[SearchDocument]
    total_count: int
    facet_counts: dict[str, list[FacetCount]]
    page: int
    has_more: bool
    query_notes: list[str] = Field(default_factory=list)
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class SearchFacetValuesResponse(AgentModel):
    terms: list[FacetTerm]
    resolved: dict[str, str]
    source: str


class SearchDateHistogramResponse(AgentModel):
    buckets: list[HistogramBucket]
    date_field: str
    source: str


class SearchEntityExplainerResponse(AgentModel):
    explanation: EntityExplanation | None
    documents: list[EntityDocument]
    source: str


class DocumentsReadResponse(AgentModel):
    documents: list[DocumentText]
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class DocumentsSearchTextResponse(AgentModel):
    source_used: str
    hit_count: int
    hits: list[TextHit]
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class DocumentsSourcesResponse(AgentModel):
    sources: list[DocumentSource]
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class DocumentsMetadataResponse(AgentModel):
    raw_metadata: dict[str, list[Any]]
    dates: list[DocumentDate]
    file_locations: list[FileLocation]
    file_locations_total: int
    path: str
    canonical_file_type: str
    download_links: DownloadLinks
    source: str


class DocumentsEmailResponse(AgentModel):
    envelope: EmailEnvelope | None
    parent: EmailRelation | None
    cluster_size: int
    headers: Any
    attachments: list[EmailAttachment]
    graph: EmailGraph
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class DocumentsDiffSourcesResponse(AgentModel):
    source_a: str
    source_b: str
    page_a: int
    page_b: int
    unified_diff: str
    source: str


class DocumentsPdfSearchResponse(AgentModel):
    source_used: str
    pdf_url: str
    hit_positions: list[PdfHit]
    hit_count: int
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class TablesOverviewResponse(AgentModel):
    sheets: list[TableSheet]
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class TablesPageResponse(AgentModel):
    columns: list[TableColumnInfo]
    rows: list[TableRow]
    row_start: int
    total_rows: int
    clamps: TableClamps
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class TablesCellResponse(AgentModel):
    row_number: int
    column: str
    offset: int
    text: str
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class TablesColumnValuesResponse(AgentModel):
    values: list[ColumnValue]
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class TablesSearchCellsResponse(AgentModel):
    hit_count: int
    hits: list[CellHit]
    source: str
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class FoldersOverviewResponse(AgentModel):
    datasets: list[DatasetSummary]
    folder_count: int
    file_count: int
    total_bytes: int
    indexed_count: int | None = None
    error_count: int | None = None
    source: str


class FoldersListResponse(AgentModel):
    breadcrumb: list[BreadcrumbNode]
    container_root: str | None
    children: list[FolderChild]
    files: list[FolderFile]
    source: str
    dataset: str | None = None
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


class FoldersSearchResponse(AgentModel):
    matches: list[FolderMatch]
    source: str
    dataset: str | None = None
    next_position: AgentPosition | None = None
    total: int | None = None
    partial: bool = False


def error_from_status(status: int, message: str) -> AgentError:
    """Map every HTTP failure to the stable tool error vocabulary."""
    names = {
        400: "invalid_argument", 401: "unauthenticated", 403: "permission_denied",
        404: "not_found", 409: "source_changed", 503: "backend_unavailable",
        504: "timed_out",
    }
    return AgentError(error=names.get(status, "backend_unavailable"), message=message)


def _server_deadline_fired(response: requests.Response) -> bool:
    """A 504 whose body is the route's own `timed_out` answer. The route already spent its
    whole deadline, so a retry would run the same read again and fail the same way."""
    if response.status_code != 504:
        return False
    try:
        return response.json().get("error") == "timed_out"
    except (ValueError, AttributeError):
        return False


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

    def post(self, route: str, request: AgentModel, response_model: type[T] | None = None, expected_source: str | None = None) -> T | dict[str, Any] | AgentError:
        url = f"{self.base_url}/api/agent/v1/{route.lstrip('/')}"
        body = request.model_dump(mode="json", exclude_none=True, by_alias=True)
        if expected_source is not None:
            body["expected_source"] = expected_source
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
                    if response.status_code not in RETRY_STATUSES or _server_deadline_fired(response):
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
