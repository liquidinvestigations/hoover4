//! Admin API module.

pub mod ai_status;
pub mod collections;
pub mod dataset_ocr;
pub mod datasets;
pub mod failures;
pub mod groups;
pub mod llm;
pub mod metrics;
pub mod operations;
pub mod processing;
pub mod settings;
pub mod users;

/// Base URL of the Temporal UI, used only to build deep links shown to admins.
/// Distinct from `TEMPORAL_HTTP_URL`, which is the API the backend calls: the UI
/// runs on a different port and is reached from the admin's browser rather than
/// from this container, so it must be a host-reachable address.
pub(crate) fn temporal_ui_base() -> String {
    std::env::var("TEMPORAL_UI_URL").unwrap_or_else(|_| "http://localhost:21909".to_string())
}

/// Deep link to one operation in the Temporal UI. `op_id` is the workflow id.
pub(crate) fn operation_temporal_url(op_id: &str) -> String {
    format!(
        "{}/namespaces/default/workflows/{op_id}",
        temporal_ui_base()
    )
}
