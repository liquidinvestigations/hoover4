//! Request and response types for the agent routes under `/api/agent/v1/`.
//!
//! One struct pair per route. Every `serde` field name equals the field name the agent
//! tool catalogue names for that route. The collection server mirrors these shapes in Python.
//!
//! Every response that a search, document, table or folder read produces carries
//! `source`, the fingerprint a later `read_more` call compares against. A document or
//! table route uses the file hash plus the source name it read; a search or folder route
//! uses the searched collections or requested folder tree.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// The JSON body of a non-2xx agent response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentErrorBody {
    /// One of `unauthenticated`, `permission_denied`, `not_found`, `invalid_argument`,
    /// `source_changed`, `backend_unavailable`, `timed_out`.
    pub error: String,
    pub message: String,
}

/// A page number, the only thing a search, folder or table route reads out of the
/// optional `position` object. A text read ignores `position`, because the broker pages text
/// inside the broker.
#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
pub struct AgentPosition {
    #[serde(default)]
    pub page: u64,
}

// ---------------------------------------------------------------------------------
// collections/list
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct CollectionsListRequest {}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentDatasetSummary {
    pub name: String,
    pub document_count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentCollectionSummary {
    pub collectionname: String,
    pub document_count: u64,
    pub datasets: Vec<AgentDatasetSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CollectionsListResponse {
    pub collections: Vec<AgentCollectionSummary>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// search/results
// ---------------------------------------------------------------------------------

/// `field` is `relevance`, `date`, `file_size` or `name`. `direction` is `asc` or `desc`.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentSort {
    pub field: String,
    pub direction: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchResultsRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    #[serde(default)]
    pub collectionname: Vec<String>,
    #[serde(default)]
    pub query: String,
    #[serde(default)]
    pub sort: Option<AgentSort>,
    #[serde(default)]
    pub date_after: Option<i64>,
    #[serde(default)]
    pub date_before: Option<i64>,
    #[serde(default)]
    pub date_confirmed_only: Option<bool>,
    #[serde(default)]
    pub size_min: Option<i64>,
    #[serde(default)]
    pub size_max: Option<i64>,
    #[serde(default)]
    pub folder_term_id: Option<u64>,
    #[serde(default)]
    pub filename_only: Option<bool>,
    #[serde(default)]
    pub facet_filters: BTreeMap<String, Vec<String>>,
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentSearchDocument {
    pub collectionname: String,
    pub file_hash: String,
    /// The first storage location the structure index has for this file, or empty when
    /// none was found. Absent from the source `search_for_results` struct; composed with
    /// one `get_first_vfs_path` lookup per result.
    pub path: String,
    pub title: String,
    pub snippet: String,
    pub canonical_file_type: String,
    /// Absent when the search result has no size.
    pub size: Option<i64>,
    /// Absent when the search result has no date.
    pub document_date: Option<i64>,
    pub dataset: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFacetCount {
    pub value: String,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResultsResponse {
    pub documents: Vec<AgentSearchDocument>,
    pub total_count: u64,
    /// A map of facet fields to counts. Empty when no facet was read.
    pub facet_counts: BTreeMap<String, Vec<AgentFacetCount>>,
    pub page: u64,
    pub has_more: bool,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// search/facet_values
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchFacetValuesRequest {
    #[serde(default)]
    pub collectionname: Vec<String>,
    pub facet: String,
    #[serde(default)]
    pub query: Option<String>,
    #[serde(default)]
    pub ids: Option<Vec<u64>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFacetTerm {
    pub id: u64,
    pub text: String,
    /// No source: the corpus-wide term search (`search_entity_terms`) reports matched
    /// terms and not their document counts. Absent for a needle search.
    pub count: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchFacetValuesResponse {
    pub terms: Vec<AgentFacetTerm>,
    pub resolved: BTreeMap<String, String>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// search/date_histogram
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchDateHistogramRequest {
    #[serde(default)]
    pub collectionname: Vec<String>,
    #[serde(default)]
    pub query: String,
    /// `date` or `mentioned_date`.
    pub date_field: String,
    #[serde(default)]
    pub date_after: Option<i64>,
    #[serde(default)]
    pub date_before: Option<i64>,
    #[serde(default)]
    pub date_confirmed_only: Option<bool>,
    #[serde(default)]
    pub size_min: Option<i64>,
    #[serde(default)]
    pub size_max: Option<i64>,
    #[serde(default)]
    pub folder_term_id: Option<u64>,
    #[serde(default)]
    pub filename_only: Option<bool>,
    #[serde(default)]
    pub facet_filters: BTreeMap<String, Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentHistogramBucket {
    pub start: i64,
    pub end: i64,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchDateHistogramResponse {
    pub buckets: Vec<AgentHistogramBucket>,
    pub date_field: String,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// search/entity_explainer
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchEntityExplainerRequest {
    pub collectionname: String,
    /// The scanner's `rule_id`, e.g. `bank.iban`. Named `entity_type` to match the tool
    /// catalogue.
    pub entity_type: String,
    /// The stored value JSON exactly as the scan stage wrote it. Named `entity_value` to
    /// match the tool catalogue.
    pub entity_value: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentEntityFact {
    pub label: String,
    pub value: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentEntityLink {
    pub title: String,
    pub url: String,
    pub note: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentEntityExplanation {
    pub title: String,
    pub subtitle: String,
    pub body: String,
    pub facts: Vec<AgentEntityFact>,
    pub references: Vec<AgentEntityLink>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEntityDocument {
    pub file_hash: String,
    pub path: String,
    pub title: String,
    pub snippet: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchEntityExplainerResponse {
    pub explanation: Option<AgentEntityExplanation>,
    /// Documents that match this entity value, when the search read supplies them.
    pub documents: Vec<AgentEntityDocument>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/read
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsReadRequest {
    pub collectionname: String,
    pub file_hash: Vec<String>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentDocumentText {
    pub collectionname: String,
    pub file_hash: String,
    pub path: String,
    pub title: String,
    pub source_used: String,
    pub text: String,
    pub hit_count: u64,
    /// Page numbers a `query` matched on, ascending, deduplicated.
    pub hit_positions: Vec<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsReadResponse {
    pub documents: Vec<AgentDocumentText>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/sources
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsSourcesRequest {
    pub collectionname: String,
    pub file_hash: String,
    #[serde(default)]
    pub query: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentSourceHitCount {
    pub source: String,
    pub hit_count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsSourcesResponse {
    pub sources: Vec<AgentSourceHitCount>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/metadata
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsMetadataRequest {
    pub collectionname: String,
    pub file_hash: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentDate {
    pub value: i64,
    /// The part of the source before its first colon, e.g. `tika`, `email`, `archive`.
    pub kind: String,
    /// The complete source string, e.g. `tika:dcterms:created`.
    pub provenance: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentDownloadLinks {
    pub original: String,
    /// Absent when the document has no OCR'd PDF variant.
    pub ocr_pdf: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsMetadataResponse {
    /// One entry per raw metadata table that had a row, table name to its rows.
    pub raw_metadata: BTreeMap<String, Vec<serde_json::Value>>,
    pub dates: Vec<AgentDate>,
    pub file_locations: Vec<String>,
    pub path: String,
    pub canonical_file_type: String,
    pub download_links: AgentDownloadLinks,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/email
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsEmailRequest {
    pub collectionname: String,
    pub file_hash: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentEmailEnvelope {
    pub subject: String,
    pub date: Option<i64>,
    pub from: Vec<String>,
    pub to: Vec<String>,
    pub cc: Vec<String>,
    pub bcc: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailAttachment {
    pub file_hash: String,
    pub name: String,
    pub size: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailGraphNode {
    pub file_hash: String,
    pub subject: String,
    pub is_centre: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailGraphEdge {
    pub src_file_hash: String,
    pub dst_file_hash: String,
    pub kind: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentEmailGraph {
    pub nodes: Vec<AgentEmailGraphNode>,
    pub edges: Vec<AgentEmailGraphEdge>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsEmailResponse {
    pub envelope: Option<AgentEmailEnvelope>,
    /// The raw email header JSON (`email_headers.raw_headers_json`), an empty object
    /// when the document is not an email or the row carries none.
    pub headers: serde_json::Value,
    pub attachments: Vec<AgentEmailAttachment>,
    pub graph: AgentEmailGraph,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/diff_sources
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsDiffSourcesRequest {
    pub collectionname: String,
    pub file_hash: String,
    pub source_a: String,
    pub source_b: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsDiffSourcesResponse {
    pub source_a: String,
    pub source_b: String,
    pub unified_diff: String,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/pdf_search
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsPdfSearchRequest {
    pub collectionname: String,
    pub file_hash: String,
    pub query: String,
    /// The same `extracted_by`-shaped string used everywhere else: empty for the
    /// original PDF, `ocr_<engine>_<languages>` for a derived one.
    #[serde(default)]
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentPdfHit {
    pub page: i32,
    pub start: i32,
    pub end: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsPdfSearchResponse {
    pub source: String,
    pub pdf_url: String,
    pub hit_positions: Vec<AgentPdfHit>,
    pub hit_count: u64,
}

// ---------------------------------------------------------------------------------
// tables/overview
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesOverviewRequest {
    pub collectionname: String,
    pub file_hash: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableColumnInfo {
    pub name: String,
    #[serde(rename = "type")]
    pub column_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableSheet {
    pub name: String,
    pub row_count: u64,
    pub column_count: u32,
    pub columns: Vec<AgentTableColumnInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesOverviewResponse {
    pub sheets: Vec<AgentTableSheet>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// tables/page
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentTableSort {
    pub column: u32,
    /// `asc` or `desc`.
    pub direction: String,
}

/// One column filter. Exactly one of the optional fields is set; the rest are ignored.
/// This mirrors `common::document_tables::TableFilterKind` without exposing its Rust
/// enum shape over JSON.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentTableFilter {
    pub column: u32,
    #[serde(default)]
    pub contains: Option<String>,
    #[serde(default)]
    pub equals: Option<String>,
    #[serde(default)]
    pub starts_with: Option<String>,
    #[serde(default)]
    pub is_empty: Option<bool>,
    #[serde(default)]
    pub number_min: Option<f64>,
    #[serde(default)]
    pub number_max: Option<f64>,
    #[serde(default)]
    pub date_min: Option<String>,
    #[serde(default)]
    pub date_max: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesPageRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    pub file_hash: String,
    pub sheet: u16,
    #[serde(default)]
    pub sort: Option<AgentTableSort>,
    #[serde(default)]
    pub filters: Vec<AgentTableFilter>,
    #[serde(default)]
    pub hidden_columns: Vec<u32>,
    #[serde(default)]
    pub search: String,
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTablePageColumn {
    pub name: String,
    #[serde(rename = "type")]
    pub column_type: String,
    pub hidden: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableRow {
    pub row_number: u64,
    /// Column name to cell text, only the non-empty cells of the requested window.
    pub cells: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesPageResponse {
    pub columns: Vec<AgentTablePageColumn>,
    pub rows: Vec<AgentTableRow>,
    pub page: u64,
    pub total_rows: u64,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// tables/column_values
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesColumnValuesRequest {
    pub collectionname: String,
    pub file_hash: String,
    pub sheet: u16,
    pub column: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentColumnValue {
    pub value: String,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesColumnValuesResponse {
    pub values: Vec<AgentColumnValue>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// tables/search_cells
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesSearchCellsRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    pub file_hash: String,
    pub sheet: u16,
    pub query: String,
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentCellHit {
    pub row_number: u64,
    pub column: String,
    pub value: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesSearchCellsResponse {
    pub hit_count: u64,
    pub hits: Vec<AgentCellHit>,
    pub has_more: bool,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// folders/overview
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FoldersOverviewRequest {
    pub collectionname: String,
    #[serde(default)]
    pub dataset: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FoldersOverviewResponse {
    pub datasets: Vec<AgentDatasetSummary>,
    /// Number of folder nodes in the selected datasets.
    pub folder_count: u64,
    pub file_count: u64,
    pub total_bytes: u64,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// folders/list
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FoldersListRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    pub dataset: String,
    #[serde(default)]
    pub node_id: Option<String>,
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentBreadcrumbNode {
    pub node_id: String,
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFolderChild {
    pub node_id: String,
    pub name: String,
    /// `dir`, `file` or `container`.
    pub kind: String,
    /// Number of direct child nodes, when available.
    pub child_count: Option<u64>,
    pub term_id: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFolderFile {
    pub node_id: String,
    pub file_hash: String,
    pub name: String,
    pub size: i64,
    /// File date, when available.
    pub date: Option<i64>,
    /// Canonical file type, when available.
    pub canonical_file_type: Option<String>,
    pub is_container: bool,
    pub term_id: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FoldersListResponse {
    pub breadcrumb: Vec<AgentBreadcrumbNode>,
    pub container_root: Option<String>,
    pub children: Vec<AgentFolderChild>,
    pub files: Vec<AgentFolderFile>,
    pub page: u64,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// folders/search
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FoldersSearchRequest {
    pub collectionname: String,
    pub dataset: String,
    #[serde(default)]
    pub node_id: Option<String>,
    pub query: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFolderMatch {
    pub node_id: String,
    pub parent_id: String,
    pub name: String,
    pub kind: String,
    pub path: String,
    pub term_id: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FoldersSearchResponse {
    pub matches: Vec<AgentFolderMatch>,
    pub source: String,
}
