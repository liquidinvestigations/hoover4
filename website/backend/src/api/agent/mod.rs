//! The agent's stable read routes, under [`crate::auth::route_policy::AGENT_ROUTE_PREFIX`].
//!
//! A handler composes an existing backend read where one exists. A handler reads a
//! collection table directly only for a value that no browser read returns, because a
//! browser page never needs it: the dataset that holds a file hash, a route's `source`
//! fingerprint, and the per-row counts, dates and types that the folder and table pages
//! add. Such a read runs through [`Deadline::collection_client`] where the route has a
//! deadline.
//!
//! `session_middleware`'s agent branch has already resolved and inserted the caller's
//! [`CurrentUser`] by the time a handler runs. Every handler still resolves its own
//! collection and dataset permission, because the middleware does not know which
//! collection a request body names.

mod diff;
mod documents;
mod folders;
mod search;
mod tables;

use documents::*;
use folders::*;
use search::*;
use tables::*;

use std::collections::{BTreeMap, HashMap};

use axum::{
    Extension, Json,
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
};
use common::agent_api::*;
use common::current_user::CurrentUser;
use common::document_metadata::DocumentMetadataTableInfo;
use common::document_sources::{DocumentPdfSourceItem, DocumentSourceItem, TextSource};
use common::pdf_search_results::PdfSearchResults;
use common::text_highlight::HighlightTextSpan;
use common::document_tables::{TableColumnFilter, TableFilterKind, TableSort as CoreTableSort, TableViewQuery};
use common::email_graph::{MAX_GRAPH_DEPTH, MAX_GRAPH_NODES};
use common::search_query::{RangeFilter, SearchQuery, SortKey, SortSpec};
use common::search_result::{DocumentIdentifier, FacetOriginalValue};
use common::vfs::dataset_root_key;

use crate::api::documents::{
    get_document_provenance, get_document_sources, get_email_graph, get_file_path,
    get_raw_metadata, search_document_itemcount, search_document_pdf, search_document_text, table_browse,
};
use crate::api::search::search_sql::FILENAME_INDEX_EXTRACTED_BY;
use crate::api::search::{
    date_histogram, explain_entity, fanout, fetch_db_terms_for_ints, search_entity_terms,
    search_for_results, search_for_results_hit_count, search_mentioned_date_histogram,
    search_numeric_facet, search_string_facet, size_bucket_range, term_field_for_column,
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

    /// The route deadline fired, or a datastore stopped the query at its own time limit.
    /// The collection server does not retry this answer.
    fn timed_out(message: impl Into<String>) -> Self {
        Self::new(StatusCode::GATEWAY_TIMEOUT, "timed_out", message)
    }

    /// Maps a backend read's failure by its cause. A typed permission, absence or
    /// bad-request cause becomes its matching status. A statement that Manticore or
    /// ClickHouse refused is 400 with the datastore's message, because it fails the same
    /// way on a retry. A datastore time limit is 504. Anything else is the datastore
    /// being unreachable, 503, which the collection server retries once.
    fn from_anyhow(err: anyhow::Error) -> Self {
        if crate::auth::guard::is_forbidden(&err) {
            Self::permission_denied(err.to_string())
        } else if crate::auth::guard::is_not_found(&err) {
            Self::not_found(err.to_string())
        } else if crate::auth::guard::is_bad_request(&err) {
            Self::invalid_argument(err.to_string())
        } else if crate::db_utils::manticore_utils::is_search_timeout(&err) {
            Self::timed_out(format!("{err:#}"))
        } else if err
            .chain()
            .any(|cause| cause.downcast_ref::<reqwest::Error>().is_some_and(reqwest::Error::is_timeout))
        {
            Self::timed_out(format!("{err:#}"))
        } else if crate::db_utils::manticore_utils::is_manticore_refusal(&err) {
            Self::invalid_argument(err.to_string())
        } else if let Some(error) = err.chain().find_map(|cause| cause.downcast_ref::<clickhouse::error::Error>()) {
            Self::from_clickhouse_ref(error)
        } else {
            Self::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", err.to_string())
        }
    }

    fn from_clickhouse(err: clickhouse::error::Error) -> Self {
        Self::from_clickhouse_ref(&err)
    }

    /// ClickHouse answers a refused statement with `BadResponse`. Error code 159,
    /// `TIMEOUT_EXCEEDED`, is the `max_execution_time` that the route deadline sets.
    fn from_clickhouse_ref(err: &clickhouse::error::Error) -> Self {
        match err {
            clickhouse::error::Error::BadResponse(message)
                if message.contains("TIMEOUT_EXCEEDED") || message.contains("Code: 159") =>
            {
                Self::timed_out(message.clone())
            }
            clickhouse::error::Error::BadResponse(message) => Self::invalid_argument(message.clone()),
            clickhouse::error::Error::TimedOut => Self::timed_out(err.to_string()),
            other => Self::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", other.to_string()),
        }
    }
}

/// The time one agent route request may spend on its backend reads. It equals the 30 s
/// ClickHouse limit of the table reads.
const AGENT_ROUTE_DEADLINE_SECONDS: u64 = 30;

/// One deadline for the whole request. A route that makes more than one read gives each
/// read the time that remains. The 30 s is under the collection server's 60 s client
/// total, so the client never retries a read that is still running.
#[derive(Debug, Clone, Copy)]
struct Deadline(tokio::time::Instant);

impl Deadline {
    fn start() -> Self {
        Self(tokio::time::Instant::now() + std::time::Duration::from_secs(AGENT_ROUTE_DEADLINE_SECONDS))
    }

    /// Whole seconds left, at least 1, for a datastore limit such as `max_execution_time`.
    fn remaining_seconds(&self) -> u64 {
        let left = self.0.saturating_duration_since(tokio::time::Instant::now());
        left.as_secs().clamp(1, AGENT_ROUTE_DEADLINE_SECONDS)
    }

    /// The time left before the deadline.
    fn remaining(&self) -> std::time::Duration {
        self.0.saturating_duration_since(tokio::time::Instant::now())
    }

    /// A collection client whose queries stop when the deadline does.
    fn collection_client(&self, collectionname: &str) -> clickhouse::Client {
        get_collection_client(collectionname)
            .with_option("max_execution_time", self.remaining_seconds().to_string())
    }

    /// Runs a route body, and answers 504 `timed_out` when the deadline fires first.
    async fn run<T>(self, body: impl std::future::Future<Output = Result<T, AgentError>>) -> Result<T, AgentError> {
        match tokio::time::timeout_at(self.0, body).await {
            Ok(result) => result,
            Err(_) => Err(AgentError::timed_out(format!(
                "the server deadline of {AGENT_ROUTE_DEADLINE_SECONDS} s fired before the route had an answer"
            ))),
        }
    }
}

/// A JSON body whose parse failure answers 400 `invalid_argument` in the agent error
/// shape. `axum::Json` answers a body of the wrong shape with a plain-text 422.
pub struct AgentJson<T>(pub T);

impl<T, S> axum::extract::FromRequest<S> for AgentJson<T>
where
    T: serde::de::DeserializeOwned,
    S: Send + Sync,
{
    type Rejection = AgentError;

    async fn from_request(req: axum::extract::Request, state: &S) -> Result<Self, Self::Rejection> {
        match Json::<T>::from_request(req, state).await {
            Ok(Json(value)) => Ok(Self(value)),
            Err(rejection) => Err(AgentError::invalid_argument(rejection.body_text())),
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

/// A folder node key joins its parts with the unit separator, U+001F, so it accepts
/// that one control character and no other.
fn validate_node_key(value: &str) -> Result<(), AgentError> {
    if value.chars().any(|c| c.is_control() && c != '\u{1f}') {
        return Err(AgentError::invalid_argument("control characters other than the node key separator are not allowed"));
    }
    Ok(())
}

/// A model cannot write U+001F, so it writes the six characters `\u001f` for it. This
/// reads that escape, in either letter case, as the separator, and then checks the key.
fn node_key_argument(value: &str) -> Result<String, AgentError> {
    let decoded = value.replace("\\u001f", "\u{1f}").replace("\\u001F", "\u{1f}");
    validate_node_key(&decoded)?;
    Ok(decoded)
}

#[cfg(test)]
mod node_key_tests {
    use super::node_key_argument;

    #[test]
    fn the_escaped_separator_is_the_separator() {
        let key = node_key_argument("textfiles_extra\\u001f\\u001F/").ok();
        assert_eq!(key.as_deref(), Some("textfiles_extra\u{1f}\u{1f}/"));
        let key = node_key_argument("textfiles_extra\u{1f}\u{1f}/").ok();
        assert_eq!(key.as_deref(), Some("textfiles_extra\u{1f}\u{1f}/"));
        assert!(node_key_argument("a\u{7}b").is_err());
    }
}

/// Refuses a position whose kind this route does not issue.
fn wrong_position_kind(route: &str, position: &AgentPosition, accepted: &str) -> AgentError {
    AgentError::invalid_argument(format!(
        "{route} takes a {accepted} position, not {}",
        position.kind()
    ))
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

/// A dataset of one collection, by both of its names.
struct ResolvedDataset {
    /// Holds the full `<collection>_<dataset>` name that every read is keyed by.
    collection_dataset: String,
    /// Holds the short name that `collections/list` returns and every response carries.
    short_name: String,
}

/// Accepts the short dataset name that `collections/list` returns, or the full
/// `<collection>_<dataset>` name, when the dataset belongs to the named collection and the
/// caller may read it. A dataset of another collection, or no dataset, is 403.
async fn require_collection_dataset(
    user: &CurrentUser,
    permitted: &PermissionSet,
    collectionname: &str,
    dataset: &str,
) -> Result<ResolvedDataset, AgentError> {
    require_collection(permitted, collectionname)?;
    let tree = list_datasets::list_permitted_collection_tree(user).await.map_err(AgentError::from_anyhow)?;
    let found = tree
        .into_iter()
        .filter(|node| node.collectionname == collectionname)
        .flat_map(|node| node.datasets)
        .find(|summary| summary.collection_dataset == dataset || summary.dataset_name == dataset);
    let Some(summary) = found else {
        return Err(AgentError::permission_denied(format!(
            "the dataset {dataset:?} is outside the selected collection {collectionname:?}; collections/list names its datasets"
        )));
    };
    permissions::assert_can_read(user, &summary.collection_dataset).await.map_err(AgentError::from_anyhow)?;
    Ok(ResolvedDataset { collection_dataset: summary.collection_dataset, short_name: summary.dataset_name })
}

/// The folder routes' `source`: the node count and the latest `updated_at` of the
/// dataset's structure rows. A node that is added, removed or rewritten changes it.
async fn folder_source_fingerprint(
    deadline: &Deadline,
    collectionname: &str,
    collection_dataset: &str,
) -> Result<String, AgentError> {
    collection_db_name(collectionname).map_err(|error| AgentError::invalid_argument(error.to_string()))?;
    let (count, updated): (u64, String) = deadline
        .collection_client(collectionname)
        .query("SELECT count(), toString(max(updated_at)) FROM vfs_nodes FINAL WHERE collection_dataset = ?")
        .bind(collection_dataset)
        .fetch_one()
        .await
        .map_err(AgentError::from_clickhouse)?;
    Ok(format!("{collection_dataset}:{count}:{updated}"))
}

/// The row that a document route reads, which decides the dataset it resolves to when
/// one blob is in more than one dataset. Each dataset parses a blob on its own, so a
/// blob can have an email row or a table row in one dataset and none in another.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum DatasetRow {
    /// Any dataset that holds the blob.
    Any,
    /// A dataset with an `email_headers` row for the blob.
    Email,
    /// A dataset with an `ok` `table_documents` row for the blob.
    Table,
}

impl DatasetRow {
    /// The query that lists the datasets with the row, or `None` for [`DatasetRow::Any`].
    fn holder_query(self) -> Option<&'static str> {
        match self {
            Self::Any => None,
            Self::Email => Some("SELECT DISTINCT collection_dataset FROM email_headers WHERE email_hash = ?"),
            Self::Table => Some(
                "SELECT DISTINCT collection_dataset FROM table_documents FINAL WHERE hash = ? AND status = 'ok'",
            ),
        }
    }
}

/// Chooses one dataset from the readable datasets that hold a blob. A dataset that
/// holds the row the route reads comes first. Name order decides between equals, so the
/// same request always reads the same dataset.
fn choose_document_dataset(readable: &[String], holders: &[String]) -> Option<String> {
    let mut ordered: Vec<&String> = readable.iter().collect();
    ordered.sort_by_key(|dataset| (!holders.contains(dataset), dataset.as_str()));
    ordered.first().map(|dataset| (*dataset).clone())
}

/// Resolve `collectionname` and `file_hash` to the `collection_dataset` that holds it,
/// restricted to datasets the caller may read.
///
/// No existing backend read performs this lookup: every browser document route already
/// carries its `collection_dataset` from the page's own state (the URL or the search
/// result it came from). The agent names a document by collection and hash alone, so
/// this one query is new: `SELECT DISTINCT collection_dataset FROM blobs WHERE
/// blob_hash = ?`, scoped to the collection's own database exactly as every other read
/// in this module is. `row` names the row the route reads, and
/// [`choose_document_dataset`] prefers a dataset that holds it.
async fn resolve_document_dataset(
    user: &CurrentUser,
    permitted: &PermissionSet,
    collectionname: &str,
    file_hash: &str,
    row: DatasetRow,
) -> Result<String, AgentError> {
    require_collection(permitted, collectionname)?;
    collection_db_name(collectionname).map_err(|e| AgentError::invalid_argument(e.to_string()))?;
    let client = get_collection_client(collectionname);
    let unavailable = |e: clickhouse::error::Error| {
        AgentError::new(StatusCode::SERVICE_UNAVAILABLE, "backend_unavailable", e.to_string())
    };
    let candidates: Vec<String> = client
        .query("SELECT DISTINCT collection_dataset FROM blobs WHERE blob_hash = ? ORDER BY collection_dataset LIMIT 20")
        .bind(file_hash)
        .fetch_all()
        .await
        .map_err(unavailable)?;
    let mut readable = Vec::with_capacity(candidates.len());
    for candidate in candidates {
        if permissions::assert_can_read(user, &candidate).await.is_ok() {
            readable.push(candidate);
        }
    }
    let holders: Vec<String> = match row.holder_query() {
        Some(query) if readable.len() > 1 => {
            client.query(query).bind(file_hash).fetch_all().await.map_err(unavailable)?
        }
        _ => Vec::new(),
    };
    choose_document_dataset(&readable, &holders)
        .ok_or_else(|| AgentError::not_found(format!("no readable dataset in {collectionname:?} holds {file_hash:?}")))
}

#[cfg(test)]
mod dataset_choice_tests {
    use super::choose_document_dataset;

    fn names(items: &[&str]) -> Vec<String> {
        items.iter().map(|item| item.to_string()).collect()
    }

    #[test]
    fn the_dataset_that_holds_the_row_wins() {
        // One blob in two datasets. Only the second one parsed it into an email row.
        let readable = names(&["enron_dasovich_j", "enron_maildir"]);
        let holders = names(&["enron_maildir"]);
        assert_eq!(choose_document_dataset(&readable, &holders).as_deref(), Some("enron_maildir"));
        let readable = names(&["enron_maildir", "enron_dasovich_j"]);
        let holders = names(&["enron_dasovich_j"]);
        assert_eq!(choose_document_dataset(&readable, &holders).as_deref(), Some("enron_dasovich_j"));
    }

    #[test]
    fn name_order_decides_between_equals() {
        let readable = names(&["b_set", "a_set"]);
        assert_eq!(choose_document_dataset(&readable, &[]).as_deref(), Some("a_set"));
        let holders = names(&["a_set", "b_set"]);
        assert_eq!(choose_document_dataset(&readable, &holders).as_deref(), Some("a_set"));
    }

    #[test]
    fn a_holder_the_caller_cannot_read_is_never_chosen() {
        let readable = names(&["b_set"]);
        let holders = names(&["a_set"]);
        assert_eq!(choose_document_dataset(&readable, &holders).as_deref(), Some("b_set"));
        assert_eq!(choose_document_dataset(&[], &holders), None);
    }
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
// Router
// ===================================================================================

/// The agent routes, under [`crate::auth::route_policy::AGENT_ROUTE_PREFIX`].
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
        .route("/api/agent/v1/search/histogram", axum::routing::post(search_date_histogram_handler))
        .route(
            "/api/agent/v1/search/entity_explainer",
            axum::routing::post(search_entity_explainer),
        )
        .route("/api/agent/v1/documents/read", axum::routing::post(documents_read))
        .route("/api/agent/v1/documents/search_text", axum::routing::post(documents_search_text))
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
        .route("/api/agent/v1/tables/cell", axum::routing::post(tables_cell))
        .route("/api/agent/v1/tables/column_values", axum::routing::post(tables_column_values))
        .route("/api/agent/v1/tables/search_cells", axum::routing::post(tables_search_cells))
        .route("/api/agent/v1/folders/overview", axum::routing::post(folders_overview))
        .route("/api/agent/v1/folders/list", axum::routing::post(folders_list))
        .route("/api/agent/v1/folders/search", axum::routing::post(folders_search))
}
