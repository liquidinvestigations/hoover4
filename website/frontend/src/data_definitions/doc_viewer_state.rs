//! State definitions for the document viewer.

use common::document_sources::DocumentSourceItem;
use dioxus::prelude::*;
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

/// Shared control so search, file-browser, and AI-chat pages can drive the document
/// preview pane through URL state. Each page provides a setter that pushes its own route.
#[derive(Debug, Clone, PartialEq, Copy)]
pub struct DocViewerStateControl {
    pub doc_viewer_state: ReadSignal<Option<DocViewerState>>,
    pub set_doc_viewer_state: Callback<DocViewerState>,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub enum ViewerRightTabSelection {
    Entities,
    Metadata,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ViewerRightTabState {
    pub selected_tab: ViewerRightTabSelection,
}

impl Default for ViewerRightTabState {
    fn default() -> Self {
        Self {
            selected_tab: ViewerRightTabSelection::Entities,
        }
    }
}
