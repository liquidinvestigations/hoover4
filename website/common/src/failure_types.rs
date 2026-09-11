//! Types shared between the operation-failures admin page and the backend that feeds it.
//!
//! The screen reads the global `operation_failures` table only. Each row is one node of
//! a captured failure tree. The list groups those nodes by the stored `signature`
//! column, which is computed at write and does not include a line number.

/// Filters for the grouped failure list. An empty string means no constraint on that
/// field. Filters combine: a row has to match every non-empty one.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, Default)]
pub struct FailureListFilter {
    pub collectionname: String,
    pub collection_dataset: String,
    pub task_name: String,
    pub error_class: String,
    /// `operations.kind` for the node's `op_id`. Empty means every kind.
    pub operation_kind: String,
    /// Inclusive lower bound on `captured_at`, RFC 3339, or empty.
    pub captured_from: String,
    /// Inclusive upper bound on `captured_at`, RFC 3339, or empty.
    pub captured_to: String,
}

/// Sort for the grouped list. `column` is an allowlisted name; anything else sorts by
/// `last_seen`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FailureListSort {
    pub column: String,
    pub descending: bool,
}

impl Default for FailureListSort {
    fn default() -> Self {
        Self {
            column: "last_seen".to_string(),
            descending: true,
        }
    }
}

/// One grouped row: every stored node that shares a `signature`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FailureGroupRow {
    pub signature: String,
    pub failure_count: u64,
    pub operation_count: u64,
    pub error_class: String,
    pub error_type: String,
    pub task_name: String,
    pub collectionname: String,
    pub collection_dataset: String,
    /// RFC 3339, the newest `captured_at` in the group.
    pub last_seen: String,
    pub sample_message: String,
}

/// One stored node, for the expanded list under a group.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FailureInstanceRow {
    pub op_id: String,
    pub node_index: u32,
    pub message: String,
    pub task_name: String,
    pub collectionname: String,
    pub collection_dataset: String,
    pub captured_at: String,
    pub error_class: String,
    pub error_type: String,
    pub source: String,
    pub stage: String,
}

/// Everything `/admin/failures` renders in one round trip.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FailuresPage {
    pub groups: Vec<FailureGroupRow>,
    pub has_more: bool,
    pub collections: Vec<String>,
    pub datasets: Vec<String>,
    pub task_names: Vec<String>,
    pub error_classes: Vec<String>,
    pub operation_kinds: Vec<String>,
}

/// One node of a captured tree, as the detail page renders it.
///
/// `node_index` is the stored UInt32. A child capture uses a hashed slot, so the value
/// is often near 3e9 and is never assumed to start at 0. `parent_index` of `-1` is a
/// root of that capture; one `op_id` can have several.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FailureNode {
    pub op_id: String,
    pub node_index: u32,
    pub depth: u16,
    pub parent_index: i32,
    pub error_class: String,
    pub error_type: String,
    pub message: String,
    /// May be shorter than the stored stack. See [`stack_trace_original_len`].
    pub stack_trace: String,
    /// Character count of the stored stack before the page cap.
    pub stack_trace_original_len: u32,
    pub signature: String,
    pub task_name: String,
    pub workflow_id: String,
    pub run_id: String,
    pub activity_id: String,
    pub attempt: u16,
    pub collectionname: String,
    pub collection_dataset: String,
    pub stage: String,
    pub details_json: String,
    pub source: String,
    pub nodes_dropped: u32,
    pub captured_at: String,
}

/// The whole captured tree for one `op_id`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct FailureTree {
    pub op_id: String,
    pub nodes: Vec<FailureNode>,
    /// True when any node of this capture recorded a non-zero `nodes_dropped`.
    pub truncated: bool,
    /// True when the operations row exists and this table has no remaining nodes,
    /// which is what a 180-day TTL looks like after the capture has expired.
    pub capture_expired: bool,
    pub temporal_url: String,
    pub operation_kind: String,
    pub operation_state: String,
    pub operation_error: String,
    /// Scrubbed JSON of the stored nodes. Dataset-mount paths are a basename hash,
    /// and any single value over 512 characters is replaced with its length. The
    /// stored rows are not changed.
    pub scrubbed_copy: String,
}
