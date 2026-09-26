//! Request and response types for the agent routes under `/api/agent/v1/`.
//!
//! One struct pair per route. Every `serde` field name equals the field name the agent
//! tool catalogue names for that route. The collection server mirrors these shapes in Python.
//!
//! Every response that a search, document, table or folder read produces carries
//! `source`, the fingerprint a later `read_more` call compares against. A document text
//! route uses the file hash, the source name, and the page count and highest page id of
//! that source. A table route uses the file hash, the reader version and the latest
//! manifest write time. A search
//! or folder route uses the searched collections or requested folder tree.

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

/// Where the next page of a paged route starts. Each route accepts only the kinds it
/// issues and refuses another kind with 400 `invalid_argument`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum AgentPosition {
    /// Names a search result page of `search_const::PAGE_SIZE` results.
    Page { page: u32 },
    /// Names a stored text page of one document source.
    TextPage { source: String, page_id: u32 },
    /// Starts an unsorted, unfiltered table window.
    Rows { row_start: u64 },
    /// Starts a sorted or filtered table window, or a folder search page.
    Offset { offset: u64 },
    /// Continues the table column values after `(count, value)`.
    ValueKey { count: u64, value: String },
    /// Continues the folder children after this node key.
    NodeKey { node_key: String },
    /// Continues the text or PDF hits after `(page_id, ordinal)`.
    HitKey { page_id: u32, ordinal: u32 },
}

impl AgentPosition {
    /// Returns the variant name, as the `kind` field spells it.
    pub fn kind(&self) -> &'static str {
        match self {
            AgentPosition::Page { .. } => "Page",
            AgentPosition::TextPage { .. } => "TextPage",
            AgentPosition::Rows { .. } => "Rows",
            AgentPosition::Offset { .. } => "Offset",
            AgentPosition::ValueKey { .. } => "ValueKey",
            AgentPosition::NodeKey { .. } => "NodeKey",
            AgentPosition::HitKey { .. } => "HitKey",
        }
    }
}

/// The paging fields of a paged route's response, flattened into the response object.
/// The page broker reads these and computes nothing else about paging.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentPageInfo {
    /// Holds the fingerprint of the data this page reads. A later request sends it back as
    /// `expected_source`, and the route answers 409 `source_changed` when it differs.
    pub source: String,
    /// It is absent on the last page.
    #[serde(default)]
    pub next_position: Option<AgentPosition>,
    /// Holds the number of units over all pages, when the route can count them.
    #[serde(default)]
    pub total: Option<u64>,
    /// It is true when a count or a page stopped at a website limit or at the route deadline.
    #[serde(default)]
    pub partial: bool,
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

/// The search filters that `search/results` and `search/histogram` share. Each field has
/// the meaning the search page's filter modal gives it.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentSearchFilters {
    /// Holds epoch seconds. A document matches when its date span overlaps the range.
    #[serde(default)]
    pub date_after: Option<i64>,
    #[serde(default)]
    pub date_before: Option<i64>,
    /// Selects documents with no date. With a date range, it selects the range or no date.
    #[serde(default)]
    pub date_unknown_only: Option<bool>,
    /// The website has no confirmed-date filter, so `true` is refused with 400. A date
    /// range already excludes documents with no date.
    #[serde(default)]
    pub date_confirmed_only: Option<bool>,
    /// Holds epoch seconds. A document matches when any date it mentions is in the range.
    #[serde(default)]
    pub mentioned_date_after: Option<i64>,
    #[serde(default)]
    pub mentioned_date_before: Option<i64>,
    #[serde(default)]
    pub size_min: Option<i64>,
    #[serde(default)]
    pub size_max: Option<i64>,
    #[serde(default)]
    pub folder_term_id: Option<u64>,
    /// Matches the query against the file name only, and not the document text.
    #[serde(default)]
    pub filename_only: Option<bool>,
    /// Maps a facet field to values. `collection_dataset` takes dataset names, short or full.
    /// Every other facet takes the term ids that `facet_counts` and
    /// `search/facet_values` return, as decimal strings.
    #[serde(default)]
    pub facet_filters: BTreeMap<String, Vec<String>>,
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
    #[serde(flatten)]
    pub filters: AgentSearchFilters,
    /// Takes a `Page` position. Pages 0 to 49 exist, because the website shows at most
    /// 1,000 results.
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
    /// Holds the short dataset name that `collections/list` returns.
    pub dataset: String,
    /// Holds the full dataset key that a document card opens the document with.
    #[serde(default)]
    pub collection_dataset: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentFacetCount {
    pub value: String,
    /// Holds the term id that `facet_filters` takes. It is absent for
    /// `collection_dataset`, whose filter value is the dataset name.
    pub id: Option<u64>,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResultsResponse {
    pub documents: Vec<AgentSearchDocument>,
    pub total_count: u64,
    /// Every facet the search page's filter modal lists that has at least one value, each
    /// with at most 21 values, the website's display limit.
    pub facet_counts: BTreeMap<String, Vec<AgentFacetCount>>,
    pub page: u64,
    pub has_more: bool,
    /// What the search changed in the query before it ran, for example `OR` read as `|`.
    #[serde(default)]
    pub query_notes: Vec<String>,
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
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
    /// Counts the documents in the searched collections that carry the term.
    pub count: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchFacetValuesResponse {
    pub terms: Vec<AgentFacetTerm>,
    pub resolved: BTreeMap<String, String>,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// search/histogram
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchDateHistogramRequest {
    #[serde(default)]
    pub collectionname: Vec<String>,
    #[serde(default)]
    pub query: String,
    /// `date`, `mentioned_date` or `size`. The request can spell it `field`.
    #[serde(alias = "field")]
    pub date_field: String,
    #[serde(flatten)]
    pub filters: AgentSearchFilters,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentHistogramBucket {
    /// A date bucket holds epoch seconds. A size bucket holds bytes.
    pub start: i64,
    /// It is absent for the last size bucket, which has no upper bound.
    pub end: Option<i64>,
    pub count: u64,
    /// Holds the website's label of a size bucket. It is absent for a date bucket.
    #[serde(default)]
    pub label: Option<String>,
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

/// The most hashes one `documents/read` request reads.
pub const MAX_READ_DOCUMENTS: usize = 20;

/// The most page ids a document lists in `hit_pages`, one `documents/search_text` page.
pub const MAX_HIT_PAGES: usize = 50;

/// The longest raw metadata value that a route returns whole. A longer value is cut with
/// [`AgentCut`].
pub const MAX_METADATA_VALUE_CHARS: usize = 2_000;

/// The marker on a value that a route cut. The rest of the value stays in the store.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentCut {
    /// Names the cut field, as a JSON pointer inside the unit.
    pub field: String,
    pub returned_bytes: u64,
    pub total_bytes: u64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsReadRequest {
    pub collectionname: String,
    /// At most [`MAX_READ_DOCUMENTS`] hashes.
    pub file_hash: Vec<String>,
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub query: Option<String>,
    /// Holds the page id to read in each document. Page ids can have gaps, and a page id
    /// with no stored page is 404 `not_found`.
    #[serde(default)]
    pub page: Option<u32>,
    /// Holds a `TextPage` position. It selects the source and the page, and it takes
    /// precedence over `source` and `page`.
    #[serde(default)]
    pub position: Option<AgentPosition>,
    #[serde(default)]
    pub expected_source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentDocumentText {
    pub collectionname: String,
    /// Holds the full dataset key that a document card opens the document with.
    #[serde(default)]
    pub collection_dataset: String,
    pub file_hash: String,
    pub path: String,
    pub title: String,
    pub source_used: String,
    /// Holds the page id that `text` holds. It is absent when no page was read.
    pub page: Option<u32>,
    /// Holds the lowest and the highest stored page id of the source.
    pub min_page: Option<u32>,
    pub max_page: Option<u32>,
    pub text: String,
    /// Counts the query hits in the source, over at most 1,000 pages.
    pub hit_count: u64,
    /// Holds the first [`MAX_HIT_PAGES`] page ids with hits, ascending.
    pub hit_pages: Vec<u32>,
    /// `read`, `no_text` when the document has no text source, or `timed_out` when the
    /// route deadline stopped this document.
    pub count_state: String,
    /// Holds the `TextPage` position of the next stored page of this source. It is
    /// absent on the last page.
    pub next_position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsReadResponse {
    pub documents: Vec<AgentDocumentText>,
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}

// ---------------------------------------------------------------------------------
// documents/search_text
// ---------------------------------------------------------------------------------

/// The hits one `documents/search_text` page returns.
pub const TEXT_HITS_PAGE_SIZE: usize = 50;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsSearchTextRequest {
    pub collectionname: String,
    pub file_hash: String,
    /// Holds the text source. It defaults to the first text source.
    #[serde(default)]
    pub source: Option<String>,
    pub query: String,
    /// Holds a `HitKey` position.
    #[serde(default)]
    pub position: Option<AgentPosition>,
    #[serde(default)]
    pub expected_source: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentTextHit {
    pub page: u32,
    /// Counts the hits before this one on the same page.
    pub ordinal: u32,
    /// Holds the character offsets of the hit in the page text.
    pub start: u32,
    pub end: u32,
    pub snippet: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsSearchTextResponse {
    pub source_used: String,
    pub hit_count: u64,
    pub hits: Vec<AgentTextHit>,
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
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
    #[serde(default)]
    pub expected_source: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentDocumentSource {
    /// `text`, `pdf`, `email`, `table`, `image`, `video` or `audio`.
    pub kind: String,
    /// Holds the name that the other document tools take. It is the `extracted_by`
    /// value for a text source, empty or `ocr_<engine>_<languages>` for a PDF, and
    /// `email_parser` for an email.
    pub source: String,
    pub label: String,
    /// Counts the query hits in this source. It is absent with no query, and when the
    /// count did not finish.
    pub hit_count: Option<u64>,
    /// `counted`, `no_query`, `timed_out`, `failed`, or `partial` when the text read
    /// stopped at its 1,000-row limit.
    pub count_state: String,
    #[serde(default)]
    pub min_page: Option<u32>,
    #[serde(default)]
    pub max_page: Option<u32>,
    #[serde(default)]
    pub page_count: Option<u32>,
    #[serde(default)]
    pub sheet_count: Option<u16>,
    #[serde(default)]
    pub row_count: Option<u64>,
    #[serde(default)]
    pub column_count: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsSourcesResponse {
    pub sources: Vec<AgentDocumentSource>,
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}

// ---------------------------------------------------------------------------------
// documents/metadata
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsMetadataRequest {
    pub collectionname: String,
    pub file_hash: String,
    #[serde(default)]
    pub expected_source: Option<String>,
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
pub struct AgentFileLocation {
    pub path: String,
    /// Holds the hash of the container that holds the file. It is empty for a file on
    /// the dataset's own disk.
    pub container_hash: String,
    /// Holds the path of each node from the dataset root to the file, containers
    /// included.
    pub container_chain: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsMetadataResponse {
    /// One entry per raw metadata table that had a row, table name to its rows. A string
    /// value over [`MAX_METADATA_VALUE_CHARS`] characters becomes
    /// `{"text": <first part>, "cut": AgentCut}`.
    pub raw_metadata: BTreeMap<String, Vec<serde_json::Value>>,
    pub dates: Vec<AgentDate>,
    /// Holds at most 25 locations, as the website's File Locations tab.
    pub file_locations: Vec<AgentFileLocation>,
    /// Counts every location of the file.
    pub file_locations_total: u64,
    pub path: String,
    pub canonical_file_type: String,
    pub download_links: AgentDownloadLinks,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/email
// ---------------------------------------------------------------------------------

/// The attachments one `documents/email` page returns.
pub const EMAIL_ATTACHMENTS_PAGE_SIZE: usize = 50;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsEmailRequest {
    pub collectionname: String,
    pub file_hash: String,
    /// Holds the file hash of the message at the graph centre. It defaults to
    /// `file_hash`.
    #[serde(default)]
    pub node: Option<String>,
    /// Holds an `Offset` position into the attachment list.
    #[serde(default)]
    pub position: Option<AgentPosition>,
    #[serde(default)]
    pub expected_source: Option<String>,
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

/// The message that this message answers, forwards or is attached to.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailRelation {
    pub file_hash: String,
    pub subject: String,
    pub from: String,
    pub date: Option<i64>,
    /// `reply`, `forward`, `reference`, `identity` or `attachment`.
    pub kind: String,
    pub confidence: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailAttachment {
    pub file_hash: String,
    pub name: String,
    pub size: u64,
    /// `pdf`, `image`, `email`, `archive`, `text`, or empty.
    pub coarse_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailGraphNode {
    pub file_hash: String,
    pub subject: String,
    pub from: String,
    /// Absent when the `Date:` header did not parse.
    pub date: Option<i64>,
    /// True when the node budget stopped the walk at this node, so it has neighbours the
    /// graph does not show.
    pub truncated: bool,
    pub is_centre: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentEmailGraphEdge {
    pub src_file_hash: String,
    pub dst_file_hash: String,
    pub kind: String,
    pub confidence: f32,
    pub evidence: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct AgentEmailGraph {
    pub nodes: Vec<AgentEmailGraphNode>,
    pub edges: Vec<AgentEmailGraphEdge>,
    /// Counts the messages of the whole connected component.
    pub cluster_size: u32,
    /// True when the node or depth budget stopped the walk.
    pub truncated: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsEmailResponse {
    pub envelope: Option<AgentEmailEnvelope>,
    pub parent: Option<AgentEmailRelation>,
    /// Counts the messages connected to this one, itself included.
    pub cluster_size: u32,
    /// The raw email header JSON (`email_headers.raw_headers_json`), an empty object
    /// when the document is not an email or the row carries none.
    pub headers: serde_json::Value,
    /// Holds one page of at most [`EMAIL_ATTACHMENTS_PAGE_SIZE`] attachments.
    pub attachments: Vec<AgentEmailAttachment>,
    pub graph: AgentEmailGraph,
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
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
    /// Holds the page id to compare in each source. Each defaults to the first stored
    /// page of its source.
    #[serde(default)]
    pub page_a: Option<u32>,
    #[serde(default)]
    pub page_b: Option<u32>,
    #[serde(default)]
    pub expected_source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsDiffSourcesResponse {
    pub source_a: String,
    pub source_b: String,
    pub page_a: u32,
    pub page_b: u32,
    pub unified_diff: String,
    pub source: String,
}

// ---------------------------------------------------------------------------------
// documents/pdf_search
// ---------------------------------------------------------------------------------

/// The hits one `documents/pdf_search` page returns.
pub const PDF_HITS_PAGE_SIZE: usize = 100;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct DocumentsPdfSearchRequest {
    pub collectionname: String,
    pub file_hash: String,
    pub query: String,
    /// The same `extracted_by`-shaped string used everywhere else: empty for the
    /// original PDF, `ocr_<engine>_<languages>` for a derived one.
    #[serde(default)]
    pub source: String,
    /// Holds the lowest and the highest PDF page index to return, as `page` counts them.
    #[serde(default)]
    pub page_from: Option<i32>,
    #[serde(default)]
    pub page_to: Option<i32>,
    /// Holds a `HitKey` position.
    #[serde(default)]
    pub position: Option<AgentPosition>,
    #[serde(default)]
    pub expected_source: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentPdfHit {
    pub page: i32,
    pub start: i32,
    pub end: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentsPdfSearchResponse {
    /// The PDF source that was searched, as the request named it.
    pub source_used: String,
    pub pdf_url: String,
    /// Holds one page of at most [`PDF_HITS_PAGE_SIZE`] hits inside the page range.
    pub hit_positions: Vec<AgentPdfHit>,
    /// Counts the hits in the whole PDF. `total` counts those inside the page range.
    pub hit_count: u64,
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}

// ---------------------------------------------------------------------------------
// tables: the shared fields
// ---------------------------------------------------------------------------------

/// The longest cell text that a table route returns whole. A longer cell is cut with
/// [`AgentCut`], and `tables/cell` reads the rest.
pub const MAX_TABLE_CELL_CHARS: usize = 2_000;

/// The sheets of one `tables/overview` page.
pub const TABLE_OVERVIEW_SHEETS_PAGE_SIZE: usize = 20;

/// The characters of one `tables/cell` page.
pub const TABLE_CELL_PAGE_CHARS: usize = 2_000;

/// The text of one table cell. A cell over [`MAX_TABLE_CELL_CHARS`] characters is an
/// object with the kept text and the cut marker.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum AgentCellText {
    Whole(String),
    Cut { text: String, cut: AgentCut },
}

// ---------------------------------------------------------------------------------
// tables/overview
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesOverviewRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    pub file_hash: String,
    /// Holds an `Offset` position, counted in sheets.
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableColumnInfo {
    /// The value that `columns`, `sort`, `filters` and `tables/cell` take.
    pub column_id: u32,
    pub name: String,
    #[serde(rename = "type")]
    pub column_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableSheet {
    /// The value that the other table routes take as `sheet`.
    pub sheet: u16,
    pub name: String,
    pub row_count: u64,
    pub column_count: u32,
    pub columns: Vec<AgentTableColumnInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesOverviewResponse {
    pub sheets: Vec<AgentTableSheet>,
    /// `total` counts the sheets. `next_position` is an `Offset` in sheets.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
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
    /// Holds the column ids to read, in order. Empty reads the first 60 columns. The
    /// website's column clamp keeps the first 60 of a longer list.
    #[serde(default)]
    pub columns: Vec<u32>,
    #[serde(default)]
    pub search: String,
    /// Holds the 0-based data row where the first window starts. A `position` replaces it.
    #[serde(default)]
    pub row_start: Option<u64>,
    /// Holds a `Rows` position with no sort, filter or search, else an `Offset` position.
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableRow {
    /// Holds the spreadsheet row number, as the website grid shows it.
    pub row_number: u64,
    /// Holds the stored row id, the value that `tables/cell` takes as `row`.
    pub row_id: u64,
    /// Column name to cell text, only the non-empty cells of the requested window.
    pub cells: BTreeMap<String, AgentCellText>,
}

/// The rows and columns a `tables/page` request asked for, and what the website applied.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTableClamps {
    pub rows_requested: u32,
    pub rows_applied: u32,
    pub columns_requested: u32,
    pub columns_applied: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesPageResponse {
    /// The columns of this window, in the order the cells use.
    pub columns: Vec<AgentTableColumnInfo>,
    pub rows: Vec<AgentTableRow>,
    /// The 0-based data row of the first row of this window.
    pub row_start: u64,
    pub total_rows: u64,
    pub clamps: AgentTableClamps,
    /// `total` equals `total_rows`. `next_position` is `Rows` or `Offset`.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}

// ---------------------------------------------------------------------------------
// tables/cell
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesCellRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    pub file_hash: String,
    pub sheet: u16,
    /// Holds the `row_id` of a `tables/page` row.
    pub row: u64,
    /// Holds the `column_id` of the column.
    pub column: u32,
    /// Holds an `Offset` position, counted in characters.
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesCellResponse {
    pub row_number: u64,
    pub column: String,
    /// The character offset of `text` in the cell.
    pub offset: u64,
    /// At most [`TABLE_CELL_PAGE_CHARS`] characters of the cell.
    pub text: String,
    /// `total` counts the characters of the stored cell. A stored cell is at most 64 KiB.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}

// ---------------------------------------------------------------------------------
// tables/column_values
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TablesColumnValuesRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    pub file_hash: String,
    pub sheet: u16,
    pub column: u32,
    /// Keeps the values that contain this text, as the filter popover's search box.
    #[serde(default)]
    pub search: String,
    /// Holds a `ValueKey` position.
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentColumnValue {
    pub value: AgentCellText,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesColumnValuesResponse {
    pub values: Vec<AgentColumnValue>,
    /// `next_position` is a `ValueKey` after the last value of a full page.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
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
    /// Holds an `Offset` position, counted in hits.
    #[serde(default)]
    pub position: Option<AgentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentCellHit {
    pub row_number: u64,
    pub row_id: u64,
    pub column: String,
    pub column_id: u32,
    pub value: AgentCellText,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TablesSearchCellsResponse {
    pub hit_count: u64,
    pub hits: Vec<AgentCellHit>,
    /// `total` equals `hit_count`. `next_position` is an `Offset` in hits.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
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
    /// Counts the documents in the selected datasets that reached the search index.
    pub indexed_count: u64,
    /// Counts the documents in the selected datasets with a processing error.
    pub error_count: u64,
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
    /// The short dataset name that `collections/list` returns, or the full
    /// `<collection>_<dataset>` name.
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
    /// Holds the short dataset name.
    pub dataset: String,
    /// `total` counts the direct children of the node. `next_position` is a `NodeKey`.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}

// ---------------------------------------------------------------------------------
// folders/search
// ---------------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct FoldersSearchRequest {
    #[serde(default)]
    pub expected_source: Option<String>,
    pub collectionname: String,
    /// The short or the full dataset name, as in `folders/list`.
    pub dataset: String,
    #[serde(default)]
    pub node_id: Option<String>,
    pub query: String,
    /// Takes an `Offset` position, a multiple of 500 below 2,000.
    #[serde(default)]
    pub position: Option<AgentPosition>,
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
    /// Holds the short dataset name.
    pub dataset: String,
    /// `total` counts every match under the node. `partial` is true when matches exist
    /// past the website's 2,000-match cap, which no position reaches.
    #[serde(flatten)]
    pub page_info: AgentPageInfo,
}
