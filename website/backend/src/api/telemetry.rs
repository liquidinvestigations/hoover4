//! Usage and API telemetry for the admin metrics page.
//!
//! Two ClickHouse tables, both in the global database, both self-deleting after
//! 24 h (migrations `00014` / `00015`):
//!
//! * `usage_events` — who did roughly what, when. **PRIVACY RULE, do not
//!   "improve" away:** record only the username, the broad route *class*
//!   ([`EVENT_*`] constants), and the timestamp. Never a URL, never a query
//!   string, never a document hash, never a result count — a metrics table
//!   that accumulates search queries is a surveillance log.
//! * `api_events` — per-call timings and sizes: the Rust handler /
//!   server-function name (a bounded, low-cardinality set, never derived from
//!   the request path), error flag, duration, bytes in/out. Still no URLs and
//!   no query text.
//!
//! **Writes are fire-and-forget and must never be able to fail a request.**
//! Events are buffered in-process and batch-inserted on a timer (ClickHouse
//! hates single-row inserts); on overflow the buffer drops and logs at debug.
//! An instrumentation path that can 500 a search is worse than no
//! instrumentation, so nothing here returns a `Result`.

use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use crate::db_utils::clickhouse_utils::get_global_client;

pub const EVENT_USER_LOGIN: &str = "user_login";
pub const EVENT_USER_SEARCH: &str = "user_search";
pub const EVENT_USER_GET_DOCUMENT: &str = "user_get_document";
pub const EVENT_USER_OTHER_REQUEST: &str = "user_other_request";
pub const EVENT_LLM_CHAT_MESSAGE: &str = "llm_chat_message";
pub const EVENT_LLM_MCP_TOOL_CALL: &str = "llm_mcp_tool_call";

/// Insert batch size; the buffer flushes early once it holds this many events.
const BATCH_SIZE: usize = 64;
/// Buffer cap. Beyond it events are dropped (and counted in the debug log) —
/// telemetry must never apply backpressure to the site.
const MAX_BUFFERED: usize = 4096;
/// Longest an event may sit in the buffer before a flush is triggered by the
/// next recorded event.
const FLUSH_INTERVAL: Duration = Duration::from_secs(10);
/// Metadata is a small JSON blob with the broad route class only; keep it small.
const MAX_METADATA_LEN: usize = 256;

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize)]
struct UsageEventRow {
    username: String,
    event_type: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    event_ts: time::OffsetDateTime,
    metadata: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize)]
struct ApiEventRow {
    username: String,
    event_type: String,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    event_ts: time::OffsetDateTime,
    function_name: String,
    is_error: u8,
    duration_ms: u32,
    bytes_in: u32,
    bytes_out: u32,
}

#[derive(Default)]
struct EventBuffer {
    usage: Vec<UsageEventRow>,
    api: Vec<ApiEventRow>,
    last_flush: Option<Instant>,
    flushing: bool,
    dropped: u64,
}

static BUFFER: LazyLock<Mutex<EventBuffer>> = LazyLock::new(|| Mutex::new(EventBuffer::default()));

fn now_utc() -> time::OffsetDateTime {
    time::OffsetDateTime::now_utc()
}

/// Record a usage event (`usage_events`). Fire-and-forget: never fails, never blocks.
///
/// This is the entry point other modules (and the chat API, for
/// `llm_chat_message` / `llm_mcp_tool_call`) instrument with.
pub fn record_event(username: &str, event_type: &str, metadata: &str) {
    let metadata = metadata.chars().take(MAX_METADATA_LEN).collect::<String>();
    let row = UsageEventRow {
        username: username.to_string(),
        event_type: event_type.to_string(),
        event_ts: now_utc(),
        metadata,
    };
    push(|buf| {
        if buf.usage.len() >= MAX_BUFFERED {
            buf.dropped += 1;
            return;
        }
        buf.usage.push(row);
    });
}

/// Record an API call event (`api_events`). `function_name` is the Rust handler
/// or server-function name from a fixed allowlist — never the request path.
#[allow(clippy::too_many_arguments)]
pub fn record_api_event(
    username: &str,
    event_type: &str,
    function_name: &str,
    is_error: bool,
    duration_ms: u32,
    bytes_in: u32,
    bytes_out: u32,
) {
    let row = ApiEventRow {
        username: username.to_string(),
        event_type: event_type.to_string(),
        event_ts: now_utc(),
        function_name: function_name.to_string(),
        is_error: u8::from(is_error),
        duration_ms,
        bytes_in,
        bytes_out,
    };
    push(|buf| {
        if buf.api.len() >= MAX_BUFFERED {
            buf.dropped += 1;
            return;
        }
        buf.api.push(row);
    });
}

fn push(add: impl FnOnce(&mut EventBuffer)) {
    let should_flush = {
        // A poisoned mutex means a panic while holding the lock; recover the
        // buffer rather than refusing to instrument.
        let mut buf = BUFFER.lock().unwrap_or_else(|e| e.into_inner());
        add(&mut buf);
        let full = buf.usage.len() + buf.api.len() >= BATCH_SIZE;
        let stale = buf
            .last_flush
            .is_none_or(|t| t.elapsed() >= FLUSH_INTERVAL);
        (full || stale) && !buf.flushing && {
            buf.flushing = true;
            true
        }
    };
    if should_flush {
        // Outside a tokio runtime (unit tests) there is nothing to spawn on;
        // the events stay buffered and the next record inside a runtime flushes.
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            handle.spawn(flush());
        } else {
            let mut buf = BUFFER.lock().unwrap_or_else(|e| e.into_inner());
            buf.flushing = false;
        }
    }
}

/// Move the buffered rows out and batch-insert them. Any failure is logged at
/// debug and the rows are dropped — telemetry loss is acceptable, request
/// failure is not.
async fn flush() {
    let (usage, api, dropped) = {
        let mut buf = BUFFER.lock().unwrap_or_else(|e| e.into_inner());
        buf.last_flush = Some(Instant::now());
        buf.flushing = false;
        (
            std::mem::take(&mut buf.usage),
            std::mem::take(&mut buf.api),
            buf.dropped,
        )
    };
    if dropped > 0 {
        tracing::debug!("telemetry buffer dropped {dropped} events (overflow)");
    }

    let client = get_global_client();
    if !usage.is_empty() {
        let result: clickhouse::error::Result<()> = async {
            let mut insert = client.insert::<UsageEventRow>("usage_events").await?;
            for row in &usage {
                insert.write(row).await?;
            }
            insert.end().await
        }
        .await;
        if let Err(e) = result {
            tracing::debug!("usage_events insert failed ({} rows dropped): {e}", usage.len());
        }
    }
    if !api.is_empty() {
        let result: clickhouse::error::Result<()> = async {
            let mut insert = client.insert::<ApiEventRow>("api_events").await?;
            for row in &api {
                insert.write(row).await?;
            }
            insert.end().await
        }
        .await;
        if let Err(e) = result {
            tracing::debug!("api_events insert failed ({} rows dropped): {e}", api.len());
        }
    }
}

// ---------------------------------------------------------------------------
// Path classification
// ---------------------------------------------------------------------------

/// Server-function names that count as `user_search`.
const SEARCH_FUNCTIONS: &[&str] = &[
    "search_date_histogram",
    "search_for_results",
    "search_for_results_hit_count",
    "search_numeric_facet",
    "search_string_facet",
];

/// Server-function names (and the one real download route) that count as
/// `user_get_document`.
const DOCUMENT_FUNCTIONS: &[&str] = &[
    "download_document",
    "get_document_entities",
    "get_document_sources",
    "get_document_first_vfs_path",
    "get_document_text_by_id_and_source",
    "get_file_locations",
    "get_file_path",
    "get_raw_metadata",
    "search_document_item_hit_counts",
    "search_document_pdf",
    "search_document_text_for_hit_count",
    "search_document_text_for_hits",
];

/// Every other server-function name we know. Anything under `/api/` that is not
/// in this list or the two classes above still records an `api_events` row,
/// bucketed under the constant `other_server_fn` — never under its path.
/// The list is the whole classification: a server function missing from it is not a
/// missing row, it is a row bucketed under `other_server_fn`, which is invisible unless
/// somebody counts. Every `#[server]` function in the frontend belongs in exactly one of
/// these three lists — the two above only if its own handler records the event.
const KNOWN_FUNCTIONS: &[&str] = &[
    "admin_add_member",
    "admin_cancel_operation",
    "admin_collection_processing",
    "admin_create_collection",
    "admin_create_group",
    "admin_dashboard_counts",
    "admin_delete_collection",
    "admin_delete_dataset",
    "admin_delete_group",
    "admin_delete_user",
    "admin_get_collection",
    "admin_get_dataset",
    "admin_get_group",
    "admin_get_user",
    "admin_grant_permission",
    "admin_list_collections",
    "admin_list_document_failures",
    "admin_list_groups",
    "admin_list_operations",
    "admin_list_settings",
    "admin_list_task_failures",
    "admin_list_users",
    "admin_list_workflows",
    "admin_remove_member",
    "admin_rerun_operation",
    "admin_retry_document",
    "admin_retry_failed_task",
    "admin_revoke_permission",
    "admin_set_collection_public",
    "admin_set_group_admin",
    "admin_set_setting",
    "admin_task_time_breakdown",
    "admin_task_time_live",
    "admin_trigger_workflow",
    "admin_update_collection",
    "admin_update_dataset",
    "admin_update_group",
    "admin_update_user",
    "chat_admin_cancel_run",
    "chat_admin_live_runs",
    "chat_artifact_detail",
    "chat_create_session",
    "chat_delete_session",
    "chat_dismiss_interrupted",
    "chat_get_session",
    "chat_list_models",
    "chat_list_sessions",
    "chat_llm_configured",
    "chat_poll",
    "chat_send_message",
    "chat_set_collections",
    "chat_start_research",
    "chat_stop",
    "collection_overview",
    "fetch_db_terms_for_ints",
    "get_document_dates",
    "get_document_email",
    "get_email_envelope",
    "get_email_graph",
    "get_raw_metadata_tables",
    "list_folder_children",
    "list_storage_tree",
    "vfs_node_term_id",
    "vfs_node_term_ids",
    "vfs_search_in_folder",
    "vfs_tree_children",
    "vfs_tree_path_to",
    "whoami",
];

/// What an HTTP path maps to, telemetry-wise.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RouteClass {
    /// `/api/<fn>` where fn is a search server function.
    Search,
    /// `/api/<fn>` or `/_download_document/...` for document retrieval.
    Document,
    /// Any other server function or authenticated page route.
    Other,
    /// Static assets and anything unauthenticated-looking: not instrumented.
    Uninstrumented,
}

/// Match a `/api/` path segment against an allowlist of server-function names.
///
/// Dioxus server functions mount at `/api/<name><hash>`, where the hash is a
/// decimal content hash appended to the function name — so a match is exact
/// equality or `name` followed by digits only. The returned name is always the
/// allowlist constant, never a slice of the URL.
fn match_function<'a>(segment: &str, allowlist: &[&'a str]) -> Option<&'a str> {
    // Longest first, so `search_for_results_hit_count` wins over
    // `search_for_results` when the hashless prefix could match both.
    let mut candidates: Vec<&'a str> = allowlist.to_vec();
    candidates.sort_by_key(|name| std::cmp::Reverse(name.len()));
    candidates.into_iter().find(|name| {
        segment == *name
            || segment
                .strip_prefix(name)
                .is_some_and(|rest| !rest.is_empty() && rest.bytes().all(|b| b.is_ascii_digit()))
    })
}

/// Classify a request path into a broad route class and, for `/api/` calls, the
/// server-function name.
///
/// The function name comes from matching the path's single server-function
/// segment against the fixed allowlists above — a bounded, low-cardinality set.
/// It is never a free-form slice of the URL: an unmatched path yields the
/// constant `other_server_fn`, so this cannot become a URL log by another
/// route.
pub fn classify_path(path: &str) -> (RouteClass, Option<&'static str>) {
    if let Some(rest) = path.strip_prefix("/api/") {
        let name = rest.split(['/', '?']).next().unwrap_or("");
        if let Some(known) = match_function(name, SEARCH_FUNCTIONS) {
            return (RouteClass::Search, Some(known));
        }
        if let Some(known) = match_function(name, DOCUMENT_FUNCTIONS) {
            return (RouteClass::Document, Some(known));
        }
        if let Some(known) = match_function(name, KNOWN_FUNCTIONS) {
            return (RouteClass::Other, Some(known));
        }
        return (RouteClass::Other, Some("other_server_fn"));
    }
    if path.starts_with("/_download_document/") {
        return (RouteClass::Document, Some("download_document"));
    }
    (RouteClass::Uninstrumented, None)
}

/// Extract the server-function name for rate-limiting/telemetry of an API path,
/// or `None` when the path is not an instrumented API call.
pub fn api_function_name(path: &str) -> Option<&'static str> {
    match classify_path(path) {
        (_, name @ Some(_)) => name,
        _ => None,
    }
}

/// Server-function names instrumented in their backend handlers (search and
/// document retrieval record `user_search` / `user_get_document` where they
/// know the user); everything else authenticated is the catch-all
/// `user_other_request`.
pub fn is_search_or_document(path: &str) -> bool {
    matches!(
        classify_path(path).0,
        RouteClass::Search | RouteClass::Document
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn classifies_search_document_other() {
        assert_eq!(classify_path("/api/search_for_results").0, RouteClass::Search);
        assert_eq!(
            classify_path("/api/search_document_pdf").0,
            RouteClass::Document
        );
        assert_eq!(
            classify_path("/_download_document/ds/hash").0,
            RouteClass::Document
        );
        assert_eq!(classify_path("/api/whoami").0, RouteClass::Other);
        assert_eq!(classify_path("/assets/app.wasm").0, RouteClass::Uninstrumented);
    }

    #[test]
    fn function_names_come_from_the_allowlist_only() {
        assert_eq!(api_function_name("/api/whoami"), Some("whoami"));
        // Dioxus mounts server functions at /api/<name><decimal hash>.
        assert_eq!(api_function_name("/api/whoami933738303362312952"), Some("whoami"));
        assert_eq!(
            api_function_name("/api/search_for_results_hit_count16667617515180422573"),
            Some("search_for_results_hit_count")
        );
        // A path that is not a known function collapses to a constant bucket;
        // the URL never leaks into a function name.
        assert_eq!(
            api_function_name("/api/evil?query=secret"),
            Some("other_server_fn")
        );
        // A known name followed by non-digits is not the function.
        assert_eq!(
            api_function_name("/api/whoami_evil"),
            Some("other_server_fn")
        );
        assert_eq!(api_function_name("/some/page"), None);
    }

    #[test]
    fn metadata_is_truncated_not_rejected() {
        // record_event must never fail; long metadata is cut, not errored.
        let long = "x".repeat(MAX_METADATA_LEN * 2);
        record_event("u", EVENT_USER_OTHER_REQUEST, &long);
        let buf = BUFFER.lock().unwrap_or_else(|e| e.into_inner());
        let last = buf.usage.last().expect("event recorded");
        assert_eq!(last.metadata.chars().count(), MAX_METADATA_LEN);
    }
}
