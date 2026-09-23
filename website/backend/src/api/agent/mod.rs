//! The agent's stable read routes, under [`crate::auth::route_policy::AGENT_ROUTE_PREFIX`].
//!
//! Every handler here composes an existing backend read. None of them queries a
//! collection database directly, except the two lookups named below that have no
//! existing counterpart because a browser page never needs them: the browser always
//! already knows a document's `collection_dataset` from the page it is on, while an
//! agent names a document by collection and file hash alone.
//!
//! `session_middleware`'s agent branch has already resolved and inserted the caller's
//! [`CurrentUser`] by the time a handler runs. Every handler still resolves its own
//! collection and dataset permission, because the middleware does not know which
//! collection a request body names.

mod diff;

use std::collections::{BTreeMap, HashMap};

use axum::{
    Extension, Json,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use common::agent_api::*;
use common::current_user::CurrentUser;
use common::document_metadata::DocumentMetadataTableInfo;
use common::document_sources::{DocumentPdfSourceItem, TextSource};
use common::document_tables::{TableColumnFilter, TableFilterKind, TableSort as CoreTableSort, TableViewQuery};
use common::email_graph::{MAX_GRAPH_DEPTH, MAX_GRAPH_NODES};
use common::search_query::{RangeFilter, SearchQuery, SortKey, SortSpec};
use common::search_result::{DocumentIdentifier, FacetOriginalValue};
use common::vfs::dataset_root_key;

use crate::api::documents::{
    get_document_provenance, get_document_sources, get_email_graph, get_file_path,
    get_raw_metadata, search_document_pdf, search_document_text, table_browse,
};
use crate::api::search::{
    date_histogram, explain_entity, fanout, fetch_db_terms_for_ints, search_entity_terms,
    search_for_results, search_for_results_hit_count, search_mentioned_date_histogram,
    search_string_facet,
    term_field_for_column,
};
use crate::api::{list_datasets, vfs as vfs_api};
use crate::auth::permissions::{self, PermissionSet};
use crate::db_utils::clickhouse_utils::{collection_db_name, get_collection_client, list_permitted_collections};

// ===================================================================================
// Errors and the permission gate shared by every handler
// ===================================================================================

/// A typed agent refusal. Constructed directly for a case a handler recognises itself,
/// or produced by [`AgentError::from_anyhow`] from a backend read's `anyhow::Error`.
pub struct AgentError {
    status: StatusCode,
    error: &'static str,
    message: String,
}

impl AgentError {
    fn new(status: StatusCode, error: &'static str, message: impl Into<String>) -> Self {
        Self { status, error, message: message.into() }
    }

    fn permission_denied(message: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, "permission_denied", message)
    }

    fn not_found(message: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, "not_found", message)
    }

    fn invalid_argument(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "invalid_argument", message)
    }

    /// Maps a backend read's failure the same way the rest of the backend already
    /// classifies one (`auth::guard::is_forbidden`, `is_not_found`, `is_bad_request`): a
    /// typed cause becomes its matching status, and anything else is the backend
    /// dependency failing rather than the caller's request being wrong.
    fn from_anyhow(err: anyhow::Error) -> Self {
        if crate::auth::guard::is_forbidden(&err) {
            Self::permission_denied(err.to_string())
        } else if crate::auth::guard::is_not_found(&err) {
            Self::not_found(err.to_string())
        } else if crate::auth::guard::is_bad_request(&err) {
            Self::invalid_argument(err.to_string())
        } else {
            Self::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", err.to_string())
        }
    }
}

impl IntoResponse for AgentError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(AgentErrorBody { error: self.error.to_string(), message: self.message }),
        )
            .into_response()
    }
}

type AgentResult<T> = Result<Json<T>, AgentError>;

/// The collection names the caller's chat session selected, from `X-Hoover4-Collections`.
/// Empty means "no restriction beyond the caller's own permissions".
fn requested_collections_header(headers: &HeaderMap) -> Vec<String> {
    headers
        .get("x-hoover4-collections")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.split(',').map(str::trim).filter(|s| !s.is_empty()).map(str::to_string).collect())
        .unwrap_or_default()
}

/// The collection names this caller may use on this request: the intersection of what
/// the backend's own ACL grants ([`permissions::resolve_permitted_collections`]) and
/// what the chat session selected. An empty header means the whole permitted set.
async fn permitted_collectionnames(
    user: &CurrentUser,
    header: &[String],
) -> Result<PermissionSet, AgentError> {
    let granted = permissions::resolve_permitted_collections(user).await.map_err(AgentError::from_anyhow)?;
    if header.is_empty() {
        return Ok(granted);
    }
    let requested: std::collections::HashSet<String> = header.iter().cloned().collect();
    Ok(match granted {
        PermissionSet::All => PermissionSet::Some(requested),
        PermissionSet::Some(set) => PermissionSet::Some(set.intersection(&requested).cloned().collect()),
    })
}

/// Every collection name a caller may use, materialised to a concrete list (never `All`),
/// for a route that has to enumerate the set rather than only test membership in it.
async fn permitted_collectionnames_list(
    user: &CurrentUser,
    header: &[String],
) -> Result<Vec<String>, AgentError> {
    match permitted_collectionnames(user, header).await? {
        PermissionSet::All => list_permitted_collections(user).await.map_err(AgentError::from_anyhow),
        PermissionSet::Some(set) => {
            let mut list: Vec<String> = set.into_iter().collect();
            list.sort();
            Ok(list)
        }
    }
}

/// Validate one requested collection name against the permitted set. A name outside it
/// is a 403, never a 404: the caller asked for something that exists and was refused,
/// which is a different fact from asking for something absent.
fn require_collection(permitted: &PermissionSet, collectionname: &str) -> Result<(), AgentError> {
    if permitted.allows(collectionname) {
        Ok(())
    } else {
        Err(AgentError::permission_denied(format!(
            "{collectionname:?} is outside the permitted collection set"
        )))
    }
}

fn verify_expected_source(expected: Option<&str>, current: &str) -> Result<(), AgentError> {
    if expected.is_some_and(|value| value != current) {
        return Err(AgentError::new(StatusCode::CONFLICT, "source_changed", "the source changed after the prior page"));
    }
    Ok(())
}

fn validate_plain_text(value: &str) -> Result<(), AgentError> {
    if value.chars().any(char::is_control) {
        return Err(AgentError::invalid_argument("control characters are not allowed"));
    }
    Ok(())
}

fn validate_position(position: Option<AgentPosition>) -> Result<(), AgentError> {
    if position.is_some_and(|value| value.page > 1_000_000) {
        return Err(AgentError::invalid_argument("position is too large"));
    }
    Ok(())
}

fn validate_calendar_date(value: &str) -> Result<(), AgentError> {
    let pieces: Vec<&str> = value.split('-').collect();
    if pieces.len() != 3 || pieces[0].len() != 4 || pieces[1].len() != 2 || pieces[2].len() != 2
        || !value.bytes().all(|byte| byte.is_ascii_digit() || byte == b'-')
    {
        return Err(AgentError::invalid_argument("date must use YYYY-MM-DD"));
    }
    let year: i32 = pieces[0].parse().map_err(|_| AgentError::invalid_argument("date is invalid"))?;
    let month: u8 = pieces[1].parse().map_err(|_| AgentError::invalid_argument("date is invalid"))?;
    let day: u8 = pieces[2].parse().map_err(|_| AgentError::invalid_argument("date is invalid"))?;
    let month = time::Month::try_from(month).map_err(|_| AgentError::invalid_argument("date is invalid"))?;
    time::Date::from_calendar_date(year, month, day)
        .map_err(|_| AgentError::invalid_argument("date is invalid"))?;
    Ok(())
}

async fn require_collection_dataset(
    user: &CurrentUser,
    permitted: &PermissionSet,
    collectionname: &str,
    dataset: &str,
) -> Result<(), AgentError> {
    require_collection(permitted, collectionname)?;
    let datasets = datasets_of_collection(user, collectionname).await.map_err(AgentError::from_anyhow)?;
    if !datasets.iter().any(|name| name == dataset) {
        return Err(AgentError::permission_denied("the dataset is outside the selected collection"));
    }
    permissions::assert_can_read(user, dataset).await.map_err(AgentError::from_anyhow)
}

async fn folder_source_fingerprint(collectionname: &str, dataset: &str) -> Result<String, AgentError> {
    collection_db_name(collectionname).map_err(|error| AgentError::invalid_argument(error.to_string()))?;
    let tree: (u64, u64) = get_collection_client(collectionname)
        .query("SELECT count(), sum(cityHash64(node_key, parent_key, path, kind, file_hash, file_size_bytes, updated_at)) FROM vfs_nodes FINAL WHERE collection_dataset = ?")
        .bind(dataset)
        .fetch_one()
        .await
        .map_err(|error| AgentError::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", error.to_string()))?;
    Ok(format!("{collectionname}:{dataset}:{}:{}", tree.0, tree.1))
}

/// Resolve `collectionname` and `file_hash` to the `collection_dataset` that holds it,
/// restricted to datasets the caller may read.
///
/// No existing backend read performs this lookup: every browser document route already
/// carries its `collection_dataset` from the page's own state (the URL or the search
/// result it came from). The agent names a document by collection and hash alone, so
/// this one query is new: `SELECT DISTINCT collection_dataset FROM blobs WHERE
/// blob_hash = ?`, scoped to the collection's own database exactly as every other read
/// in this module is.
async fn resolve_document_dataset(
    user: &CurrentUser,
    permitted: &PermissionSet,
    collectionname: &str,
    file_hash: &str,
) -> Result<String, AgentError> {
    require_collection(permitted, collectionname)?;
    collection_db_name(collectionname).map_err(|e| AgentError::invalid_argument(e.to_string()))?;
    let client = get_collection_client(collectionname);
    let candidates: Vec<String> = client
        .query("SELECT DISTINCT collection_dataset FROM blobs WHERE blob_hash = ? LIMIT 20")
        .bind(file_hash)
        .fetch_all()
        .await
        .map_err(|e| AgentError::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", e.to_string()))?;
    for candidate in candidates {
        if permissions::assert_can_read(user, &candidate).await.is_ok() {
            return Ok(candidate);
        }
    }
    Err(AgentError::not_found(format!("no readable dataset in {collectionname:?} holds {file_hash:?}")))
}

/// Every `collection_dataset` under one collection name, restricted to what the caller
/// may read. Backs the search routes' `collectionname[]`, which fans out over every
/// dataset of each named collection, the same way ticking a collection row in the
/// filter modal ticks every dataset beneath it.
async fn datasets_of_collection(user: &CurrentUser, collectionname: &str) -> anyhow::Result<Vec<String>> {
    let tree = list_datasets::list_permitted_collection_tree(user).await?;
    Ok(tree
        .into_iter()
        .find(|node| node.collectionname == collectionname)
        .map(|node| node.dataset_ids())
        .unwrap_or_default())
}

/// Include every searched collection in the continuation fingerprint.
async fn collection_source_fingerprint(collections: &[String]) -> Result<String, AgentError> {
    let mut names = collections.to_vec();
    names.sort();
    let mut parts = Vec::with_capacity(names.len());
    for name in names {
        let generation = crate::db_utils::clickhouse_utils::shard_generation(&name)
            .await
            .map_err(AgentError::from_anyhow)?;
        parts.push(format!("{name}@{generation}"));
    }
    Ok(parts.join("|"))
}

// ===================================================================================
// collections/list
// ===================================================================================

pub async fn collections_list(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
) -> AgentResult<CollectionsListResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames_list(&user, &header).await?;
    let tree = list_datasets::list_permitted_collection_tree(&user).await.map_err(AgentError::from_anyhow)?;

    let mut collections = Vec::new();
    for node in tree.into_iter().filter(|node| permitted.contains(&node.collectionname)) {
        let overview = list_datasets::collection_overview(&user, node.collectionname.clone())
            .await
            .map_err(AgentError::from_anyhow)?;
        let datasets = node
            .datasets
            .iter()
            .map(|dataset| AgentDatasetSummary {
                name: dataset.dataset_name.clone(),
                document_count: overview
                    .aggregates_for(&dataset.collection_dataset)
                    .map(|a| a.document_count)
                    .unwrap_or(0),
            })
            .collect::<Vec<_>>();
        let document_count = datasets.iter().map(|d| d.document_count).sum();
        collections.push(AgentCollectionSummary { collectionname: node.collectionname, document_count, datasets });
    }

    Ok(Json(CollectionsListResponse { collections, source: String::new() }))
}

// ===================================================================================
// search/results
// ===================================================================================

fn sort_spec_from_agent(sort: Option<&AgentSort>) -> Result<SortSpec, AgentError> {
    let Some(sort) = sort else { return Ok(SortSpec::default()) };
    let key = match sort.field.as_str() {
        "relevance" => SortKey::Relevance,
        "date" => SortKey::Date,
        "file_size" => SortKey::FileSize,
        "name" => SortKey::Name,
        _ => return Err(AgentError::invalid_argument("invalid sort field")),
    };
    let desc = match sort.direction.as_str() {
        "asc" => false,
        "desc" => true,
        _ => return Err(AgentError::invalid_argument("invalid sort direction")),
    };
    Ok(SortSpec { key, desc })
}

/// Build the shared `SearchQuery` the search routes compose, from the agent's request
/// shape.
#[allow(clippy::too_many_arguments)]
async fn build_search_query(
    user: &CurrentUser,
    permitted: &PermissionSet,
    collectionnames: &[String],
    query_string: &str,
    date_after: Option<i64>,
    date_before: Option<i64>,
    date_confirmed_only: Option<bool>,
    size_min: Option<i64>,
    size_max: Option<i64>,
    folder_term_id: Option<u64>,
    filename_only: Option<bool>,
    facet_filters: &BTreeMap<String, Vec<String>>,
    sort: SortSpec,
) -> Result<SearchQuery, AgentError> {
    validate_plain_text(query_string)?;
    if let (Some(after), Some(before)) = (date_after, date_before) {
        if after > before {
            return Err(AgentError::invalid_argument("date range is invalid"));
        }
    }
    for (name, values) in facet_filters {
        validate_plain_text(name)?;
        for value in values { validate_plain_text(value)?; }
    }
    let selected: Vec<String> = if collectionnames.is_empty() {
        match permitted {
            PermissionSet::All => list_permitted_collections(user).await.map_err(AgentError::from_anyhow)?,
            PermissionSet::Some(names) => names.iter().cloned().collect(),
        }
    } else {
        collectionnames.to_vec()
    };
    let mut collection_datasets: Vec<String> = Vec::new();
    for name in &selected {
        require_collection(permitted, name)?;
        collection_datasets.extend(datasets_of_collection(user, name).await.map_err(AgentError::from_anyhow)?);
    }
    if collection_datasets.is_empty() {
        return Err(AgentError::permission_denied("no selected dataset is readable"));
    }
    collection_datasets.sort();
    collection_datasets.dedup();
    if let Some(wanted) = facet_filters.get("collection_dataset") {
        collection_datasets.retain(|dataset| wanted.contains(dataset));
        if collection_datasets.is_empty() {
            return Err(AgentError::permission_denied("the dataset facet is outside the selected collections"));
        }
    }
    let mut query = SearchQuery { query_string: query_string.to_string(), sort, ..Default::default() };
    query.facet_filters.insert(
        "collection_dataset".to_string(),
        collection_datasets.into_iter().map(FacetOriginalValue::String).collect(),
    );
    for (facet, values) in facet_filters {
        if facet == "collection_dataset" { continue; }
        query.facet_filters.insert(
            facet.clone(),
            values.iter().cloned().map(FacetOriginalValue::String).collect(),
        );
    }
    if filename_only.unwrap_or(false) {
        query.facet_filters.insert(
            "filename_only".to_string(),
            [FacetOriginalValue::String("1".to_string())].into_iter().collect(),
        );
    }
    if let Some(term_id) = folder_term_id {
        query
            .facet_filters
            .entry("file_paths".to_string())
            .or_default()
            .insert(FacetOriginalValue::Int(term_id));
    }
    if date_after.is_some() || date_before.is_some() || date_confirmed_only.unwrap_or(false) {
        query.range_filters.insert(
            "dates".to_string(),
            RangeFilter { min: date_after, max: date_before, include_unknown: false },
        );
    }
    match (size_min, size_max) {
        (None, None) => {}
        (min, max) => {
            query
                .range_filters
                .insert("file_size_bytes".to_string(), RangeFilter { min, max, include_unknown: false });
        }
    }
    Ok(query)
}

/// Flatten decomposed highlight spans into one plain-text snippet, wrapping a matched
/// run in `**…**` so a reader, human or model, can still see what matched without the
/// server's own `<hoover4_strong>` marker leaking into a tool result.
fn spans_to_snippet(spans: &[common::text_highlight::HighlightTextSpan]) -> String {
    let mut out = String::new();
    for span in spans {
        if span.is_highlighted {
            out.push_str("**");
            out.push_str(&span.text);
            out.push_str("**");
        } else {
            out.push_str(&span.text);
        }
    }
    out
}

pub async fn search_results(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<SearchResultsRequest>,
) -> AgentResult<SearchResultsResponse> {
    validate_position(body.position)?;
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let sort = sort_spec_from_agent(body.sort.as_ref())?;
    let query = build_search_query(
        &user,
        &permitted,
        &body.collectionname,
        &body.query,
        body.date_after,
        body.date_before,
        body.date_confirmed_only,
        body.size_min,
        body.size_max,
        body.folder_term_id,
        body.filename_only,
        &body.facet_filters,
        sort,
    )
    .await?;

    let page = body.position.map(|p| p.page).unwrap_or(0);
    let results = search_for_results(&user, query.clone(), page)
        .await
        .map_err(AgentError::from_anyhow)?;
    let hit_count = search_for_results_hit_count(&user, query.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    // collection_dataset -> (collectionname, dataset_name), for the two fields the
    // per-result item wants and `search_for_results` does not carry itself.
    let tree = list_datasets::list_permitted_collection_tree(&user).await.map_err(AgentError::from_anyhow)?;
    let mut lookup: HashMap<String, (String, String)> = HashMap::new();
    for node in &tree {
        for dataset in &node.datasets {
            lookup.insert(dataset.collection_dataset.clone(), (node.collectionname.clone(), dataset.dataset_name.clone()));
        }
    }

    let mut documents = Vec::with_capacity(results.results.len());
    for item in &results.results {
        let (collectionname, dataset) = lookup
            .get(&item.collection_dataset)
            .cloned()
            .unwrap_or_else(|| (item.collection_dataset.clone(), String::new()));
        let path = vfs_api::get_first_vfs_path(&user, item.document_identifier())
            .await
            .map(|d| d.path)
            .unwrap_or_default();
        documents.push(AgentSearchDocument {
            collectionname,
            file_hash: item.file_hash.clone(),
            path,
            title: item.title.clone(),
            snippet: spans_to_snippet(&item.highlight_text_spans),
            canonical_file_type: item.file_type.clone(),
            size: item.file_size_bytes,
            document_date: item.document_date,
            dataset,
        });
    }

    let collections = fanout::permitted_search_collections(&user, &query).await.map_err(AgentError::from_anyhow)?;
    let source = collection_source_fingerprint(&collections).await?;
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let mut facet_counts = BTreeMap::new();
    for (field, term_field) in [("collection_dataset", None), ("file_types", Some("filetype"))] {
        let facets = search_string_facet(
            &user,
            query.clone(),
            field.to_string(),
            term_field.map(str::to_string),
            None,
        ).await.map_err(AgentError::from_anyhow)?;
        let values = facets.facet_values.into_iter().filter_map(|item| {
            if field == "collection_dataset" {
                if let FacetOriginalValue::String(value) = &item.original_value {
                    if !query.facet_filters.get("collection_dataset")
                        .is_some_and(|selected| !selected.contains(&FacetOriginalValue::String(value.clone()))) {
                        return Some(AgentFacetCount { value: item.display_string, count: item.count });
                    }
                }
                None
            } else {
                Some(AgentFacetCount { value: item.display_string, count: item.count })
            }
        }).collect();
        facet_counts.insert(field.to_string(), values);
    }

    Ok(Json(SearchResultsResponse {
        documents,
        total_count: hit_count.total,
        facet_counts,
        page,
        has_more: results.next_hash.is_some(),
        source,
    }))
}

// ===================================================================================
// search/facet_values
// ===================================================================================

pub async fn search_facet_values(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<SearchFacetValuesRequest>,
) -> AgentResult<SearchFacetValuesResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let query = build_search_query(
        &user, &permitted, &body.collectionname, "", None, None, None, None, None, None, None,
        &BTreeMap::new(), SortSpec::default(),
    )
    .await?;

    let mut terms = Vec::new();
    if let Some(needle) = body.query.as_ref().filter(|q| !q.trim().is_empty()) {
        let hits = search_entity_terms(&user, query.clone(), needle.clone(), vec![body.facet.clone()])
            .await
            .map_err(AgentError::from_anyhow)?;
        terms = hits
            .hits
            .into_iter()
            .map(|hit| AgentFacetTerm { id: hit.term_id, text: hit.term_display, count: None })
            .collect();
    }

    let mut resolved = BTreeMap::new();
    if let Some(ids) = body.ids.filter(|ids| !ids.is_empty()) {
        let field = term_field_for_column(&body.facet).map_err(AgentError::from_anyhow)?;
        let collections = fanout::permitted_search_collections(&user, &query).await.map_err(AgentError::from_anyhow)?;
        let values = fetch_db_terms_for_ints(&collections, ids, field.to_string())
            .await
            .map_err(AgentError::from_anyhow)?;
        for (id, text) in values {
            resolved.insert(id.to_string(), text);
        }
    }

    let collections = fanout::permitted_search_collections(&user, &query).await.map_err(AgentError::from_anyhow)?;
    let source = collection_source_fingerprint(&collections).await?;
    Ok(Json(SearchFacetValuesResponse { terms, resolved, source }))
}

// ===================================================================================
// search/date_histogram
// ===================================================================================

pub async fn search_date_histogram_handler(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<SearchDateHistogramRequest>,
) -> AgentResult<SearchDateHistogramResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let mut query = build_search_query(
        &user,
        &permitted,
        &body.collectionname,
        &body.query,
        body.date_after,
        body.date_before,
        body.date_confirmed_only,
        body.size_min,
        body.size_max,
        body.folder_term_id,
        body.filename_only,
        &body.facet_filters,
        SortSpec::default(),
    )
    .await?;

    let mentions = body.date_field == "mentioned_date";
    if mentions {
        if let Some(filter) = query.range_filters.remove("dates") {
            query.range_filters.insert("mentioned_dates".to_string(), filter);
        }
    }

    let histogram = if mentions {
        search_mentioned_date_histogram(&user, query.clone())
            .await
            .map_err(AgentError::from_anyhow)?
    } else {
        date_histogram::search_date_histogram(&user, query.clone()).await.map_err(AgentError::from_anyhow)?
    };

    let collections = fanout::permitted_search_collections(&user, &query).await.map_err(AgentError::from_anyhow)?;
    let source = collection_source_fingerprint(&collections).await?;
    Ok(Json(SearchDateHistogramResponse {
        buckets: histogram
            .buckets
            .into_iter()
            .map(|b| AgentHistogramBucket { start: b.start, end: b.end, count: b.count })
            .collect(),
        date_field: body.date_field,
        source,
    }))
}

// ===================================================================================
// search/entity_explainer
// ===================================================================================

pub async fn search_entity_explainer(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<SearchEntityExplainerRequest>,
) -> AgentResult<SearchEntityExplainerResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    require_collection(&permitted, &body.collectionname)?;

    let explanation = explain_entity(&user, body.entity_type.clone(), body.entity_value.clone(), None)
        .await
        .map_err(AgentError::from_anyhow)?
        .map(|card| AgentEntityExplanation {
            title: card.title,
            subtitle: card.subtitle,
            body: card.body,
            facts: card.facts.into_iter().map(|f| AgentEntityFact { label: f.label, value: f.value }).collect(),
            references: card
                .references
                .into_iter()
                .map(|r| AgentEntityLink { title: r.title, url: r.url, note: r.note })
                .collect(),
        });

    let tree = list_datasets::list_permitted_collection_tree(&user).await.map_err(AgentError::from_anyhow)?;
    let mut documents = Vec::new();
    for dataset in tree.iter().filter(|entry| entry.collectionname == body.collectionname)
        .flat_map(|entry| entry.datasets.iter()) {
        let rows: Vec<(String, String)> = get_collection_client(&body.collectionname)
            .query("SELECT file_hash, any(surface_text) FROM (SELECT file_hash, entity_rule_ids, entity_value_json, entity_texts FROM regex_entity_hit FINAL WHERE collection_dataset = ? AND (file_hash, rule_set_version) IN (SELECT file_hash, max(rule_set_version) FROM regex_entity_hit FINAL WHERE collection_dataset = ? GROUP BY file_hash)) ARRAY JOIN entity_rule_ids AS rule_id, entity_value_json AS value_json, entity_texts AS surface_text WHERE rule_id = ? AND value_json = ? GROUP BY file_hash ORDER BY file_hash LIMIT 20")
            .bind(&dataset.collection_dataset)
            .bind(&dataset.collection_dataset)
            .bind(&body.entity_type)
            .bind(&body.entity_value)
            .fetch_all()
            .await
            .map_err(|err| AgentError::from_anyhow(err.into()))?;
        for (file_hash, snippet) in rows {
            let identifier = DocumentIdentifier { collection_dataset: dataset.collection_dataset.clone(), file_hash: file_hash.clone() };
            let path = vfs_api::get_first_vfs_path(&user, identifier).await
                .map(|p| p.path)
                .unwrap_or_default();
            let title = path.rsplit('/').next().unwrap_or(&path).to_string();
            documents.push(AgentEntityDocument { file_hash, path, title, snippet });
        }
    }
    Ok(Json(SearchEntityExplainerResponse { explanation, documents, source: String::new() }))
}

// ===================================================================================
// documents/read
// ===================================================================================

pub async fn documents_read(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<DocumentsReadRequest>,
) -> AgentResult<DocumentsReadResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;

    let mut documents = Vec::with_capacity(body.file_hash.len());
    let mut last_source = String::new();
    for file_hash in &body.file_hash {
        let collection_dataset =
            resolve_document_dataset(&user, &permitted, &body.collectionname, file_hash).await?;
        let identifier = DocumentIdentifier { collection_dataset: collection_dataset.clone(), file_hash: file_hash.clone() };

        let sources = get_document_sources::get_document_sources(&user, identifier.clone())
            .await
            .map_err(AgentError::from_anyhow)?;
        let text_sources: Vec<common::document_sources::DocumentTextSourceItem> = sources
            .into_iter()
            .filter_map(|s| match s {
                common::document_sources::DocumentSourceItem::Text(t) => Some(t),
                _ => None,
            })
            .collect();
        let Some(chosen) = body
            .source
            .as_ref()
            .and_then(|wanted| text_sources.iter().find(|t| &t.extracted_by == wanted))
            .or_else(|| text_sources.first())
        else {
            continue;
        };

        let text = search_document_text::get_document_text_by_id_and_source(
            &user,
            identifier.clone(),
            chosen.extracted_by.clone(),
            chosen.min_page,
        )
        .await
        .map_err(AgentError::from_anyhow)?;

        let (hit_count, hit_positions) = if let Some(q) = body.query.as_ref().filter(|q| !q.is_empty()) {
            let hits = search_document_text::search_document_text_for_hit_count(&user, identifier.clone(), q.clone())
                .await
                .map_err(AgentError::from_anyhow)?;
            let mine: Vec<_> = hits.into_iter().filter(|h| h.extracted_by == chosen.extracted_by).collect();
            let total: u64 = mine.iter().map(|h| h.hit_count).sum();
            let mut pages: Vec<u32> = mine.iter().map(|h| h.page_id).collect();
            pages.sort_unstable();
            pages.dedup();
            (total, pages)
        } else {
            (0, Vec::new())
        };

        let path = get_file_path::get_file_path(&user, identifier.clone())
            .await
            .map_err(AgentError::from_anyhow)?
            .unwrap_or_default();

        last_source = format!("{file_hash}:{}", chosen.extracted_by);
        let title = path.rsplit('/').next().unwrap_or(&path).to_string();
        documents.push(AgentDocumentText {
            collectionname: body.collectionname.clone(),
            file_hash: file_hash.clone(),
            path,
            title,
            source_used: chosen.extracted_by.clone(),
            text,
            hit_count,
            hit_positions,
        });
    }

    Ok(Json(DocumentsReadResponse { documents, source: last_source }))
}

// ===================================================================================
// documents/sources
// ===================================================================================

pub async fn documents_sources(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<DocumentsSourcesRequest>,
) -> AgentResult<DocumentsSourcesResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let text_sources = get_document_sources::get_text_sources(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    let counts_by_source: HashMap<String, u64> = if let Some(q) = body.query.as_ref().filter(|q| !q.is_empty()) {
        let hits = search_document_text::search_document_text_for_hit_count(&user, identifier.clone(), q.clone())
            .await
            .map_err(AgentError::from_anyhow)?;
        let mut totals: HashMap<String, u64> = HashMap::new();
        for hit in hits {
            *totals.entry(hit.extracted_by).or_insert(0) += hit.hit_count;
        }
        totals
    } else {
        HashMap::new()
    };

    let sources = text_sources
        .into_iter()
        .map(|s| AgentSourceHitCount {
            hit_count: counts_by_source.get(&s.extracted_by).copied().unwrap_or(0),
            source: s.extracted_by,
        })
        .collect();

    Ok(Json(DocumentsSourcesResponse { sources, source: body.file_hash }))
}

// ===================================================================================
// documents/metadata
// ===================================================================================

/// The exact table list `RawMetadataCollector` asks for, copied here because the
/// metadata route composes the same reads the metadata tab renders.
fn raw_metadata_table_list() -> Vec<DocumentMetadataTableInfo> {
    vec![
        DocumentMetadataTableInfo::new("blobs", "blob_hash"),
        DocumentMetadataTableInfo::new("file_types", "hash"),
        DocumentMetadataTableInfo::new("file_type_canonical", "hash"),
        DocumentMetadataTableInfo::new3("tika_metadata", "hash", vec!["tika_metadata_json"]),
        DocumentMetadataTableInfo::new("archives", "archive_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "container_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "hash"),
        DocumentMetadataTableInfo::new3("audio_metadata", "hash", vec!["audio_metadata_json"]),
        DocumentMetadataTableInfo::new3("email_headers", "email_hash", vec!["raw_headers_json"]),
        DocumentMetadataTableInfo::new3("image", "image_hash", vec!["image_metadata"]),
        DocumentMetadataTableInfo::new3("pdf_metadata", "hash", vec!["pdf_metadata_json"]),
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
        DocumentMetadataTableInfo::new3("video_metadata", "hash", vec!["video_metadata_json"]),
        DocumentMetadataTableInfo::new3("raw_ocr_results", "image_hash", vec!["raw_json"]),
        DocumentMetadataTableInfo::new("table_documents", "hash"),
        DocumentMetadataTableInfo::new("table_sheets", "hash"),
        DocumentMetadataTableInfo::new("table_columns", "hash"),
        DocumentMetadataTableInfo::new("processing_errors", "hash"),
    ]
}

pub async fn documents_metadata(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<DocumentsMetadataRequest>,
) -> AgentResult<DocumentsMetadataResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let table_list = raw_metadata_table_list();
    let rows = get_raw_metadata::get_raw_metadata_tables(&user, identifier.clone(), table_list.clone())
        .await
        .map_err(AgentError::from_anyhow)?;
    let mut raw_metadata = BTreeMap::new();
    for (info, values) in table_list.into_iter().zip(rows) {
        if !values.is_empty() {
            raw_metadata.entry(info.table_name).or_insert_with(Vec::new).extend(values);
        }
    }

    let dates = get_document_provenance::get_document_dates(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .dates
        .into_iter()
        .map(|d| AgentDate { value: d.epoch_seconds, kind: d.source_provider().to_string(), provenance: d.source })
        .collect();

    let locations = get_file_path::get_file_locations(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .locations
        .into_iter()
        .map(|l| l.path)
        .collect();

    let path = get_file_path::get_file_path(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .unwrap_or_default();
    let canonical_file_type = get_file_path::get_canonical_file_type(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    let pdf_sources = get_document_sources::get_pdf_sources(&user, identifier.clone()).await.unwrap_or_default();
    let ocr_pdf = pdf_sources
        .iter()
        .find(|s| s.is_ocr())
        .map(|s| s.url(&identifier.collection_dataset, &identifier.file_hash));
    let download_links = AgentDownloadLinks { original: identifier.get_absolute_url_path(), ocr_pdf };

    Ok(Json(DocumentsMetadataResponse {
        raw_metadata,
        dates,
        file_locations: locations,
        path,
        canonical_file_type,
        download_links,
        source: format!("{}:metadata", body.file_hash),
    }))
}

// ===================================================================================
// documents/email
// ===================================================================================

pub async fn documents_email(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<DocumentsEmailRequest>,
) -> AgentResult<DocumentsEmailResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let envelope = get_email_graph::get_email_envelope(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    let headers_rows = get_raw_metadata::get_raw_metadata(
        &user,
        identifier.clone(),
        DocumentMetadataTableInfo::new3("email_headers", "email_hash", vec!["raw_headers_json"]),
    )
    .await
    .unwrap_or_default();
    let headers = headers_rows
        .into_iter()
        .next()
        .and_then(|row| row.get("raw_headers_json").cloned())
        .unwrap_or(serde_json::Value::Object(Default::default()));

    let graph = get_email_graph::get_email_graph(&user, identifier.clone(), MAX_GRAPH_NODES, MAX_GRAPH_DEPTH)
        .await
        .map_err(AgentError::from_anyhow)?;
    let graph = AgentEmailGraph {
        nodes: graph
            .nodes
            .iter()
            .map(|n| AgentEmailGraphNode {
                file_hash: n.document_identifier.file_hash.clone(),
                subject: n.subject.clone(),
                is_centre: n.is_centre,
            })
            .collect(),
        edges: graph
            .edges
            .iter()
            .map(|e| AgentEmailGraphEdge {
                src_file_hash: e.src.file_hash.clone(),
                dst_file_hash: e.dst.file_hash.clone(),
                kind: e.kind.clone(),
                confidence: e.confidence,
            })
            .collect(),
    };

    let response = match envelope {
        Some(envelope) => DocumentsEmailResponse {
            attachments: envelope
                .attachments
                .iter()
                .map(|a| AgentEmailAttachment {
                    file_hash: a.document_identifier.file_hash.clone(),
                    name: a.file_name.clone(),
                    size: a.size_bytes,
                })
                .collect(),
            envelope: Some(AgentEmailEnvelope {
                subject: envelope.subject,
                date: envelope.date_sent,
                from: envelope.from.iter().map(|p| p.full()).collect(),
                to: envelope.to.iter().map(|p| p.full()).collect(),
                cc: envelope.cc.iter().map(|p| p.full()).collect(),
                bcc: envelope.bcc.iter().map(|p| p.full()).collect(),
            }),
            headers,
            graph,
            source: format!("{}:email", body.file_hash),
        },
        None => DocumentsEmailResponse {
            envelope: None,
            headers,
            attachments: Vec::new(),
            graph,
            source: format!("{}:email", body.file_hash),
        },
    };

    Ok(Json(response))
}

// ===================================================================================
// documents/diff_sources
// ===================================================================================

async fn read_named_text_source(
    user: &CurrentUser,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
) -> Result<String, AgentError> {
    let sources = get_document_sources::get_document_sources(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;
    let Some(text) = sources.into_iter().find_map(|s| match s {
        common::document_sources::DocumentSourceItem::Text(t) if t.extracted_by == extracted_by => Some(t),
        _ => None,
    }) else {
        return Err(AgentError::not_found(format!("no text source {extracted_by:?}")));
    };
    search_document_text::get_document_text_by_id_and_source(user, identifier.clone(), text.extracted_by, text.min_page)
        .await
        .map_err(AgentError::from_anyhow)
}

pub async fn documents_diff_sources(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<DocumentsDiffSourcesRequest>,
) -> AgentResult<DocumentsDiffSourcesResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let text_a = read_named_text_source(&user, &identifier, &body.source_a).await?;
    let text_b = read_named_text_source(&user, &identifier, &body.source_b).await?;
    let unified_diff = diff::unified_diff(&text_a, &text_b, &body.source_a, &body.source_b);

    Ok(Json(DocumentsDiffSourcesResponse {
        source_a: body.source_a,
        source_b: body.source_b,
        unified_diff,
        source: format!("{}:diff", body.file_hash),
    }))
}

// ===================================================================================
// documents/pdf_search
// ===================================================================================

pub async fn documents_pdf_search(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<DocumentsPdfSearchRequest>,
) -> AgentResult<DocumentsPdfSearchResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let parsed = TextSource::parse(&body.source);
    let source_item = match parsed {
        TextSource::Ocr { engine, languages } => Some(DocumentPdfSourceItem { page_count: 0, engine, languages }),
        TextSource::Native { .. } => None,
    };
    let pdf_url = source_item
        .as_ref()
        .map(|s| s.url(&identifier.collection_dataset, &identifier.file_hash))
        .unwrap_or_else(|| identifier.get_absolute_url_path());

    let results = search_document_pdf::search_document_pdf(&user, identifier, body.query, source_item)
        .await
        .map_err(AgentError::from_anyhow)?;

    Ok(Json(DocumentsPdfSearchResponse {
        source: body.source,
        pdf_url,
        hit_count: results.total.max(0) as u64,
        hit_positions: results
            .results
            .into_iter()
            .map(|r| AgentPdfHit { page: r.page_index, start: r.char_index, end: r.char_index + r.char_count })
            .collect(),
    }))
}

// ===================================================================================
// tables/overview
// ===================================================================================

pub async fn tables_overview(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<TablesOverviewRequest>,
) -> AgentResult<TablesOverviewResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let overview = table_browse::get_table_overview(&user, identifier).await.map_err(AgentError::from_anyhow)?;
    let Some(overview) = overview else {
        return Err(AgentError::not_found("this document has no browsable table"));
    };

    let sheets = overview
        .sheets
        .iter()
        .map(|sheet| AgentTableSheet {
            name: sheet.label(),
            row_count: sheet.row_count,
            column_count: sheet.column_count,
            columns: overview
                .columns_of(sheet.sheet_id)
                .into_iter()
                .map(|c| AgentTableColumnInfo { name: c.label(), column_type: c.column_type.clone() })
                .collect(),
        })
        .collect();

    Ok(Json(TablesOverviewResponse { sheets, source: format!("{}:table", body.file_hash) }))
}

// ===================================================================================
// tables/page
// ===================================================================================

fn table_filter_kind(filter: &AgentTableFilter) -> Option<TableFilterKind> {
    if let Some(v) = &filter.contains {
        return Some(TableFilterKind::Contains(v.clone()));
    }
    if let Some(v) = &filter.equals {
        return Some(TableFilterKind::Equals(v.clone()));
    }
    if let Some(v) = &filter.starts_with {
        return Some(TableFilterKind::StartsWith(v.clone()));
    }
    if filter.is_empty == Some(true) {
        return Some(TableFilterKind::IsEmpty);
    }
    if filter.number_min.is_some() || filter.number_max.is_some() {
        return Some(TableFilterKind::NumberRange { min: filter.number_min, max: filter.number_max });
    }
    if filter.date_min.is_some() || filter.date_max.is_some() {
        return Some(TableFilterKind::DateRange { min: filter.date_min.clone(), max: filter.date_max.clone() });
    }
    None
}

pub async fn tables_page(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<TablesPageRequest>,
) -> AgentResult<TablesPageResponse> {
    validate_position(body.position)?;
    validate_plain_text(&body.search)?;
    if body.sort.as_ref().is_some_and(|sort| sort.direction != "asc" && sort.direction != "desc") {
        return Err(AgentError::invalid_argument("sort direction is invalid"));
    }
    for filter in &body.filters {
        for value in [&filter.contains, &filter.equals, &filter.starts_with] {
            if let Some(value) = value { validate_plain_text(value)?; }
        }
        for date in [&filter.date_min, &filter.date_max] {
            if let Some(date) = date { validate_calendar_date(date)?; }
        }
        if filter.number_min.is_some_and(|value| !value.is_finite())
            || filter.number_max.is_some_and(|value| !value.is_finite())
            || filter.number_min.zip(filter.number_max).is_some_and(|(min, max)| min > max)
            || filter.date_min.as_ref().zip(filter.date_max.as_ref()).is_some_and(|(min, max)| min > max)
        {
            return Err(AgentError::invalid_argument("table filter range is invalid"));
        }
        if table_filter_kind(filter).is_none() {
            return Err(AgentError::invalid_argument("table filter is invalid"));
        }
    }
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let page_number = body.position.map(|p| p.page).unwrap_or(0);
    let limit = common::document_tables::DEFAULT_TABLE_PAGE_ROWS;
    let view_query = TableViewQuery {
        sheet_id: body.sheet,
        visible_columns: Vec::new(),
        sort: body.sort.as_ref().map(|s| CoreTableSort { column_id: s.column, desc: s.direction == "desc" }),
        filters: body
            .filters
            .iter()
            .filter_map(|f| table_filter_kind(f).map(|kind| TableColumnFilter { column_id: f.column, kind }))
            .collect(),
        search: body.search.clone(),
        offset: page_number.checked_mul(limit as u64)
            .ok_or_else(|| AgentError::invalid_argument("position is too large"))?,
        limit,
    };

    let overview = table_browse::get_table_overview(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .ok_or_else(|| AgentError::not_found("this document has no browsable table"))?;
    let sheet_columns = overview.columns_of(body.sheet);
    let (cell_count, cell_sum): (u64, u64) = get_collection_client(&body.collectionname)
        .query("SELECT count(), sum(cityHash64(row_id, column_id, cell_text, parsed_at)) FROM table_cells FINAL WHERE file_hash = ? AND sheet_id = ?")
        .bind(&body.file_hash)
        .bind(body.sheet)
        .fetch_one()
        .await
        .map_err(|err| AgentError::from_anyhow(err.into()))?;
    let source = sha256::digest(format!("{}:{}:{}:{}:{}", body.file_hash, body.sheet, cell_count, cell_sum, serde_json::to_string(&overview).map_err(|err| AgentError::from_anyhow(err.into()))?));
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let page = table_browse::get_table_page(&user, identifier, view_query).await.map_err(AgentError::from_anyhow)?;

    let columns = sheet_columns
        .iter()
        .map(|c| AgentTablePageColumn {
            name: c.label(),
            column_type: c.column_type.clone(),
            hidden: body.hidden_columns.contains(&c.column_id),
        })
        .collect();
    let column_names: HashMap<u32, String> = sheet_columns.iter().map(|c| (c.column_id, c.label())).collect();
    let rows = page
        .rows
        .into_iter()
        .map(|row| AgentTableRow {
            row_number: row.source_row,
            cells: row
                .cells
                .into_iter()
                .filter(|c| !body.hidden_columns.contains(&c.column_id))
                .map(|c| (column_names.get(&c.column_id).cloned().unwrap_or_default(), c.text))
                .collect(),
        })
        .collect();

    Ok(Json(TablesPageResponse {
        columns,
        rows,
        page: page_number,
        total_rows: page.total_rows,
        source,
    }))
}

// ===================================================================================
// tables/column_values
// ===================================================================================

pub async fn tables_column_values(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<TablesColumnValuesRequest>,
) -> AgentResult<TablesColumnValuesResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let values = table_browse::get_table_column_values(&user, identifier, body.sheet, body.column, String::new())
        .await
        .map_err(AgentError::from_anyhow)?
        .into_iter()
        .map(|v| AgentColumnValue { value: v.value, count: v.count })
        .collect();

    Ok(Json(TablesColumnValuesResponse { values, source: format!("{}:table:{}", body.file_hash, body.sheet) }))
}

// ===================================================================================
// tables/search_cells
// ===================================================================================

pub async fn tables_search_cells(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<TablesSearchCellsRequest>,
) -> AgentResult<TablesSearchCellsResponse> {
    validate_position(body.position)?;
    validate_plain_text(&body.query)?;
    if body.query.is_empty() {
        return Err(AgentError::invalid_argument("query is required"));
    }
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    let collection_dataset =
        resolve_document_dataset(&user, &permitted, &body.collectionname, &body.file_hash).await?;
    let identifier = DocumentIdentifier { collection_dataset, file_hash: body.file_hash.clone() };

    let overview = table_browse::get_table_overview(&user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .ok_or_else(|| AgentError::not_found("this document has no browsable table"))?;
    let column_names: HashMap<u32, String> =
        overview.columns_of(body.sheet).into_iter().map(|c| (c.column_id, c.label())).collect();

    let client = get_collection_client(&body.collectionname);
    let (hit_count, source_sum): (u64, u64) = client
        .query("SELECT count(), sum(cityHash64(column_id, row_id, cell_text, parsed_at)) FROM table_cells FINAL WHERE file_hash = ? AND sheet_id = ? AND positionCaseInsensitiveUTF8(cell_text, ?) > 0 AND row_id NOT IN (SELECT header_row FROM table_sheets FINAL WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? AND header_row > 0)")
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(&body.query)
        .bind(&identifier.collection_dataset)
        .bind(&body.file_hash)
        .bind(body.sheet)
        .fetch_one()
        .await
        .map_err(|err| AgentError::from_anyhow(err.into()))?;
    let source = format!("{}:table:{}:{hit_count}:{source_sum}", body.file_hash, body.sheet);
    verify_expected_source(body.expected_source.as_deref(), &source)?;
    let page_number = body.position.map(|p| p.page).unwrap_or(0);
    let offset = page_number.checked_mul(u64::from(common::document_tables::MAX_TABLE_PAGE_ROWS))
        .ok_or_else(|| AgentError::invalid_argument("position is too large"))?;
    let rows: Vec<(u64, u32, String)> = client
        .query("SELECT source_row, column_id, cell_text FROM table_cells FINAL WHERE file_hash = ? AND sheet_id = ? AND positionCaseInsensitiveUTF8(cell_text, ?) > 0 AND row_id NOT IN (SELECT header_row FROM table_sheets FINAL WHERE collection_dataset = ? AND hash = ? AND sheet_id = ? AND header_row > 0) ORDER BY row_id, column_id LIMIT ? OFFSET ?")
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(&body.query)
        .bind(&identifier.collection_dataset)
        .bind(&body.file_hash)
        .bind(body.sheet)
        .bind(common::document_tables::MAX_TABLE_PAGE_ROWS)
        .bind(offset)
        .fetch_all()
        .await
        .map_err(|err| AgentError::from_anyhow(err.into()))?;
    let hits: Vec<AgentCellHit> = rows.into_iter().map(|(row_number, column_id, value)| AgentCellHit {
        row_number,
        column: column_names.get(&column_id).cloned().unwrap_or_default(),
        value,
    }).collect();
    let has_more = offset.saturating_add(hits.len() as u64) < hit_count;

    Ok(Json(TablesSearchCellsResponse {
        hit_count,
        hits,
        has_more,
        source,
    }))
}

// ===================================================================================
// folders/overview
// ===================================================================================

pub async fn folders_overview(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<FoldersOverviewRequest>,
) -> AgentResult<FoldersOverviewResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    require_collection(&permitted, &body.collectionname)?;

    let overview = list_datasets::collection_overview(&user, body.collectionname.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    let matches_dataset = |name: &str, collection_dataset: &str| {
        body.dataset.as_ref().is_none_or(|wanted| wanted == name || wanted == collection_dataset)
    };
    let datasets: Vec<AgentDatasetSummary> = overview
        .datasets
        .iter()
        .filter(|d| matches_dataset(&d.dataset_name, &d.collection_dataset))
        .map(|d| AgentDatasetSummary {
            name: d.dataset_name.clone(),
            document_count: overview.aggregates_for(&d.collection_dataset).map(|a| a.document_count).unwrap_or(0),
        })
        .collect();
    let total_bytes = overview
        .datasets
        .iter()
        .filter(|d| matches_dataset(&d.dataset_name, &d.collection_dataset))
        .filter_map(|d| overview.aggregates_for(&d.collection_dataset))
        .map(|a| a.total_size_bytes)
        .sum();
    let file_count = datasets.iter().map(|d| d.document_count).sum();

    let mut folder_count = 0;
    for dataset in overview.datasets.iter().filter(|d| matches_dataset(&d.dataset_name, &d.collection_dataset)) {
        let count: u64 = get_collection_client(&body.collectionname)
            .query("SELECT countIf(kind != 'file') FROM vfs_nodes FINAL WHERE collection_dataset = ?")
            .bind(&dataset.collection_dataset)
            .fetch_one()
            .await
            .map_err(|error| AgentError::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", error.to_string()))?;
        folder_count += count;
    }
    Ok(Json(FoldersOverviewResponse { datasets, folder_count, file_count, total_bytes, source: String::new() }))
}

// ===================================================================================
// folders/list
// ===================================================================================

const FOLDER_PAGE_SIZE: u64 = 200;

fn node_kind_str(kind: common::vfs::VfsNodeKind) -> &'static str {
    match kind {
        common::vfs::VfsNodeKind::Dir => "dir",
        common::vfs::VfsNodeKind::File => "file",
        common::vfs::VfsNodeKind::Container => "container",
    }
}

pub async fn folders_list(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<FoldersListRequest>,
) -> AgentResult<FoldersListResponse> {
    validate_position(body.position)?;
    if let Some(node_id) = &body.node_id { validate_plain_text(node_id)?; }
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    require_collection_dataset(&user, &permitted, &body.collectionname, &body.dataset).await?;

    let source = folder_source_fingerprint(&body.collectionname, &body.dataset).await?;
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let node_key = body.node_id.clone().unwrap_or_else(|| dataset_root_key(&body.dataset));
    let page = body.position.map(|p| p.page).unwrap_or(0);

    let breadcrumb = vfs_api::vfs_tree_path_to(&user, body.dataset.clone(), node_key.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .into_iter()
        .map(|n| {
            let name = n.display_name().to_string();
            AgentBreadcrumbNode { node_id: n.node_key, name }
        })
        .collect();

    let children_page = vfs_api::vfs_tree_children(
        &user,
        body.dataset.clone(),
        node_key.clone(),
        FOLDER_PAGE_SIZE,
        page * FOLDER_PAGE_SIZE,
        false,
    )
    .await
    .map_err(AgentError::from_anyhow)?;

    let node_keys: Vec<String> = children_page.nodes.iter().map(|n| n.node_key.clone()).collect();
    let term_ids = vfs_api::tree::node_term_ids(&body.dataset, &node_keys).await.unwrap_or_default();
    let child_counts: HashMap<String, u64> = get_collection_client(&body.collectionname)
        .query("SELECT parent_key, count() FROM vfs_nodes FINAL WHERE collection_dataset = ? AND parent_key IN (?) GROUP BY parent_key")
        .bind(&body.dataset)
        .bind(&node_keys)
        .fetch_all::<(String, u64)>()
        .await
        .map_err(|err| AgentError::from_anyhow(err.into()))?
        .into_iter()
        .collect();
    let file_hashes: Vec<String> = children_page.nodes.iter()
        .filter(|n| n.kind != common::vfs::VfsNodeKind::Dir)
        .map(|n| n.file_hash.clone())
        .collect();
    let file_types: HashMap<String, String> = get_collection_client(&body.collectionname)
        .query("SELECT hash, file_type FROM file_type_canonical FINAL WHERE collection_dataset = ? AND hash IN (?)")
        .bind(&body.dataset)
        .bind(&file_hashes)
        .fetch_all::<(String, String)>()
        .await
        .map_err(|err| AgentError::from_anyhow(err.into()))?
        .into_iter()
        .collect();
    let file_dates: HashMap<String, i64> = get_collection_client(&body.collectionname)
        .query("SELECT hash, min(date) FROM document_dates FINAL WHERE collection_dataset = ? AND hash IN (?) GROUP BY hash")
        .bind(&body.dataset)
        .bind(&file_hashes)
        .fetch_all::<(String, i64)>()
        .await
        .map_err(|err| AgentError::from_anyhow(err.into()))?
        .into_iter()
        .collect();

    let mut children = Vec::new();
    let mut files = Vec::new();
    for node in children_page.nodes {
        let term_id = term_ids.get(&node.node_key).copied();
        match node.kind {
            common::vfs::VfsNodeKind::File => {
                files.push(AgentFolderFile {
                    node_id: node.node_key.clone(),
                    file_hash: node.file_hash.clone(),
                    name: node.display_name().to_string(),
                    size: node.file_size_bytes,
                    date: file_dates.get(&node.file_hash).copied(),
                    canonical_file_type: file_types.get(&node.file_hash).cloned(),
                    is_container: false,
                    term_id,
                });
            }
            common::vfs::VfsNodeKind::Container => {
                files.push(AgentFolderFile {
                    node_id: node.node_key.clone(),
                    file_hash: node.file_hash.clone(),
                    name: node.display_name().to_string(),
                    size: node.file_size_bytes,
                    date: file_dates.get(&node.file_hash).copied(),
                    canonical_file_type: file_types.get(&node.file_hash).cloned(),
                    is_container: true,
                    term_id,
                });
                children.push(AgentFolderChild {
                    node_id: node.node_key.clone(),
                    name: node.display_name().to_string(),
                    kind: node_kind_str(node.kind).to_string(),
                    child_count: Some(*child_counts.get(&node.node_key).unwrap_or(&0)),
                    term_id,
                });
            }
            common::vfs::VfsNodeKind::Dir => {
                children.push(AgentFolderChild {
                    node_id: node.node_key.clone(),
                    name: node.display_name().to_string(),
                    kind: node_kind_str(node.kind).to_string(),
                    child_count: Some(*child_counts.get(&node.node_key).unwrap_or(&0)),
                    term_id,
                });
            }
        }
    }

    let container_root = if node_key.contains('\u{1f}') && !node_key.ends_with('\u{1f}') {
        let parts: Vec<&str> = node_key.split('\u{1f}').collect();
        let container_hash = parts.get(1).copied().unwrap_or("");
        if !container_hash.is_empty() {
            vfs_api::vfs_tree_container_node(&user, body.dataset.clone(), container_hash.to_string())
                .await
                .ok()
                .flatten()
                .map(|n| n.node_key)
        } else {
            None
        }
    } else {
        None
    };

    Ok(Json(FoldersListResponse { breadcrumb, container_root, children, files, page, source }))
}

// ===================================================================================
// folders/search
// ===================================================================================

pub async fn folders_search(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    Json(body): Json<FoldersSearchRequest>,
) -> AgentResult<FoldersSearchResponse> {
    let header = requested_collections_header(&headers);
    let permitted = permitted_collectionnames(&user, &header).await?;
    require_collection_dataset(&user, &permitted, &body.collectionname, &body.dataset).await?;

    let node_key = body.node_id.clone().unwrap_or_else(|| dataset_root_key(&body.dataset));
    let results = vfs_api::vfs_search_in_folder(&user, body.dataset.clone(), node_key, body.query, 200)
        .await
        .map_err(AgentError::from_anyhow)?;

    let node_keys: Vec<String> = results.nodes.iter().map(|n| n.node_key.clone()).collect();
    let term_ids = vfs_api::tree::node_term_ids(&body.dataset, &node_keys).await.unwrap_or_default();

    let matches = results
        .nodes
        .into_iter()
        .map(|n| AgentFolderMatch {
            node_id: n.node_key.clone(),
            parent_id: n.parent_key.clone(),
            name: n.display_name().to_string(),
            kind: node_kind_str(n.kind).to_string(),
            path: n.path.clone(),
            term_id: term_ids.get(&n.node_key).copied(),
        })
        .collect();

    Ok(Json(FoldersSearchResponse { matches, source: String::new() }))
}

// ===================================================================================
// Router
// ===================================================================================

/// The eighteen agent routes, under [`crate::auth::route_policy::AGENT_ROUTE_PREFIX`].
///
/// `main.rs` merges this into the site's router before the session-middleware layer, so
/// that layer's agent branch resolves the caller for every route named here before a
/// handler runs. Every route is `POST`, matching the request/response pair in
/// `common::agent_api`.
pub fn router() -> axum::Router {
    axum::Router::new()
        .route("/api/agent/v1/collections/list", axum::routing::post(collections_list))
        .route("/api/agent/v1/search/results", axum::routing::post(search_results))
        .route("/api/agent/v1/search/facet_values", axum::routing::post(search_facet_values))
        .route(
            "/api/agent/v1/search/date_histogram",
            axum::routing::post(search_date_histogram_handler),
        )
        .route(
            "/api/agent/v1/search/entity_explainer",
            axum::routing::post(search_entity_explainer),
        )
        .route("/api/agent/v1/documents/read", axum::routing::post(documents_read))
        .route("/api/agent/v1/documents/sources", axum::routing::post(documents_sources))
        .route("/api/agent/v1/documents/metadata", axum::routing::post(documents_metadata))
        .route("/api/agent/v1/documents/email", axum::routing::post(documents_email))
        .route(
            "/api/agent/v1/documents/diff_sources",
            axum::routing::post(documents_diff_sources),
        )
        .route("/api/agent/v1/documents/pdf_search", axum::routing::post(documents_pdf_search))
        .route("/api/agent/v1/tables/overview", axum::routing::post(tables_overview))
        .route("/api/agent/v1/tables/page", axum::routing::post(tables_page))
        .route("/api/agent/v1/tables/column_values", axum::routing::post(tables_column_values))
        .route("/api/agent/v1/tables/search_cells", axum::routing::post(tables_search_cells))
        .route("/api/agent/v1/folders/overview", axum::routing::post(folders_overview))
        .route("/api/agent/v1/folders/list", axum::routing::post(folders_list))
        .route("/api/agent/v1/folders/search", axum::routing::post(folders_search))
}
