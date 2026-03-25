//! State definitions for the document viewer.

use common::document_sources::DocumentSourceItem;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocViewerState {
    pub find_query: String,
    pub selected_source: Option<DocumentSourceItem>,
    pub selected_source_page: Option<u32>,
}

impl DocViewerState {
    pub fn from_find_query(find_query: String) -> Self {
        Self {
            find_query,
            selected_source: None,
            selected_source_page: None,
        }
    }
}

impl Default for DocViewerState {
    fn default() -> Self {
        Self {
            find_query: "".to_string(),
            selected_source: None,
            selected_source_page: None,
        }
    }
}
